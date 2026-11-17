"""Synthetic claim dictionaries exercise format and matching, not model accuracy."""

import re
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from beautyads.domain.claims import (
    CLAIM_CHECK_DISCLAIMER,
    ClaimRule,
    ClaimRulesError,
    RuleType,
    check_plan_fields,
    find_claim_terms,
    parse_claim_rules,
)
from beautyads.sources.claim_rules import load_claim_rules
from beautyads.sources.config import ConfigError

ROOT = Path(__file__).resolve().parents[1]


def rule(**changes):
    return {
        "rule_id": "S-001",
        "rule_type": "prohibited",
        "source_page": 1,
        "law_basis": "합성 근거",
        "group": None,
        "source_items": ["합성 원문 항목"],
        "terms_ko": ["합성 표현"],
        "terms_en": [],
        "terms_en_added": [],
        "en_pending": True,
        "en_waived": False,
        "matchable": True,
        "exception_note": None,
        "exceptions": [],
        "exception_refs": [],
        "applies_to": [],
        **changes,
    }


def document(*rules):
    return {
        "source": {
            "title": "합성 출처",
            "registration_no": "synthetic-001",
            "page_url": "https://example.invalid/guide",
            "file_url": "https://example.invalid/guide.pdf",
            "file_sha256": "a" * 64,
            "pages": 3,
            "legal_effect": "참고용 합성 문서",
        },
        "status": "synthetic",
        "verification": {"method": "synthetic"},
        "transcription_rules": ["합성 전사 원칙"],
        "general_principles": [{"page": 1, "ref": "S.1", "text": "합성 원칙"}],
        "excluded_scope": [],
        "rules": list(rules),
    }


def test_parse_preserves_all_rule_types_provenance_and_scope():
    source = document(
        rule(
            source_page_end=2,
            terms_en=["synthetic"],
            terms_en_added=["made up"],
            en_origin="advisor_added_en",
            en_pending=False,
            en_note="합성 영어 근거",
            exceptions=["합성 표현 예외"],
            exception_refs=["S-002"],
            exception_note="합성 비고",
            applies_to=[
                {"kind": "efficacy", "value": "hydration", "status": "draft"},
                {
                    "kind": "skin_concern",
                    "value": "건조",
                    "status": "advisor_approved",
                },
                {"kind": "category", "value": "sun_care", "status": "confirmed"},
            ],
        ),
        rule(rule_id="S-002", rule_type="requires_functional_cert"),
        rule(rule_id="S-003", rule_type="requires_substantiation"),
    )
    before = deepcopy(source)
    parsed = parse_claim_rules(source)
    assert all(isinstance(item, ClaimRule) for item in parsed)
    assert {item.rule_type for item in parsed} == set(RuleType)
    for raw, parsed_rule in zip(source["rules"], parsed, strict=True):
        result = parsed_rule.model_dump(mode="json")
        assert all(result[key] == value for key, value in raw.items())
    assert source == before


@pytest.mark.parametrize(
    "changes,missing,location",
    [
        ({}, "source_page", ("source_page",)),
        ({"source_page": 0}, None, ("source_page",)),
        ({"source_page": -1}, None, ("source_page",)),
        ({"source_page": True}, None, ("source_page",)),
        ({"source_page_end": 0}, None, ("source_page_end",)),
        ({"source_page": 2, "source_page_end": 1}, None, ("source_page_end",)),
        ({"source_items": []}, None, ("source_items",)),
        ({"source_items": [" "]}, None, ("source_items", 0)),
        ({"terms_ko": []}, None, ("terms_ko",)),
        ({"terms_ko": [" \t"]}, None, ("terms_ko", 0)),
        ({"matchable": False}, None, ("terms_ko",)),
        ({"en_pending": False}, None, ("en_waived",)),
        (
            {"terms_en_added": ["synthetic"], "en_origin": "source"},
            None,
            ("terms_en_added",),
        ),
        ({"exception_refs": ["missing"]}, None, ("exception_refs", 0)),
        ({"exception_refs": ["S-001"]}, None, ("exception_refs", 0)),
        ({"rule_type": "unknown"}, None, ("rule_type",)),
        ({"rule_id": ""}, None, ("rule_id",)),
        (
            {"applies_to": [{"kind": "unknown", "value": "건조", "status": "draft"}]},
            None,
            ("applies_to", 0, "kind"),
        ),
        *[
            (
                {"applies_to": [{"kind": kind, "value": value, "status": "draft"}]},
                None,
                ("applies_to", 0, "value"),
            )
            for kind, value in [
                ("efficacy", "unknown"),
                ("skin_concern", "unknown"),
                ("category", "unknown"),
                ("category", "hydration"),
            ]
        ],
        (
            {
                "applies_to": [
                    {"kind": "efficacy", "value": "hydration", "status": "unknown"}
                ]
            },
            None,
            ("applies_to", 0, "status"),
        ),
    ],
)
def test_invalid_rules_report_code_and_precise_location(changes, missing, location):
    raw = rule(**changes)
    if missing:
        raw.pop(missing)
    with pytest.raises(ClaimRulesError) as caught:
        parse_claim_rules(document(raw))
    assert caught.value.code == "CLAIM_RULES_INVALID"
    assert caught.value.location == ("rules", 0, *location)
    assert "CLAIM_RULES_INVALID" in str(caught.value)
    assert str(location[0]) in str(caught.value)


@pytest.mark.parametrize("key", list(document(rule())))
def test_every_top_level_section_is_required(key):
    raw = document(rule())
    raw.pop(key)
    with pytest.raises(ClaimRulesError) as caught:
        parse_claim_rules(raw)
    assert caught.value.location == (key,)


@pytest.mark.parametrize("key", list(document(rule())["source"]))
def test_source_metadata_is_required(key):
    raw = document(rule())
    raw["source"].pop(key)
    with pytest.raises(ClaimRulesError) as caught:
        parse_claim_rules(raw)
    assert caught.value.location == ("source", key)


@pytest.mark.parametrize(
    "raw,location",
    [
        (document(), ("rules",)),
        (document(rule(), rule()), ("rules", 1, "rule_id")),
        ([], ()),
        (None, ()),
        (document("not a mapping"), ("rules", 0)),
    ],
)
def test_invalid_documents_and_duplicate_ids(raw, location):
    with pytest.raises(ClaimRulesError) as caught:
        parse_claim_rules(raw)
    assert caught.value.code == "CLAIM_RULES_INVALID"
    assert caught.value.location == location


@pytest.mark.parametrize(
    "english",
    [
        {"terms_en": ["synthetic"], "en_pending": False},
        {
            "terms_en_added": ["synthetic"],
            "en_origin": "advisor_added_en",
            "en_pending": False,
        },
        {"en_pending": True},
        {"en_pending": False, "en_waived": True},
        {"matchable": False, "terms_ko": [], "en_pending": False},
    ],
)
def test_english_or_explicit_pending_and_waiver_are_accepted(english):
    assert parse_claim_rules(document(rule(**english)))


@pytest.mark.parametrize(
    "text,expected",
    [
        ("앞 합성 표현 뒤", True),
        ("합 성\t표 현", True),
        ("다른 표현", False),
        ("", False),
        ("합성 표현이 두 번 합성표현", True),
    ],
)
def test_korean_normalization_and_deterministic_rule_identity(text, expected):
    rules = parse_claim_rules(document(rule()))
    matches = find_claim_terms(text, rules)
    assert bool(matches) is expected
    assert matches == find_claim_terms(text, rules)
    assert all(match.rule_id == rules[0].rule_id for match in matches)
    assert all(match.rule_type is RuleType.prohibited for match in matches)
    assert all(match.term == "합성 표현" for match in matches)


def test_nfkc_casefold_and_sentence_rules():
    rules = parse_claim_rules(
        document(
            rule(terms_ko=["합성 ABC"]),
            rule(rule_id="S-002", matchable=False, terms_ko=[], terms_en=["sentence"]),
        )
    )
    assert find_claim_terms("합 성 ａｂｃ", rules)[0].term == "합성 ABC"
    assert find_claim_terms("합성 원문 항목 sentence", rules) == []


@pytest.mark.parametrize(
    "term,text,expected",
    [
        ("drug", "drug", True),
        ("drug", "a drug test", True),
        ("drug", "DRUG.", True),
        ("drug", "ＤＲＵＧ.", True),
        ("drug", "drugstore", False),
        ("drug", "undrugged", False),
        ("drug", "drug2", False),
        ("drug", "2drug", False),
        ("drug", "d r u g", False),
        ("UV", "UV차단", True),
        ("UV", "UVA", False),
        ("UV", "guv", False),
        ("anti-aging", "anti-aging", True),
        ("anti-aging", "anti-aging   care", True),
        ("stem cell", "stem cell", True),
        ("stem cell", "STEM  \t CELL", True),
        ("stem cell", "stemcell", False),
        ("stem cell", "stem cells", False),
    ],
)
@pytest.mark.parametrize("field", ["terms_en", "terms_en_added"])
def test_english_uses_ascii_boundaries_and_preserves_word_spaces(
    term, text, expected, field
):
    # The confirmed format can repeat English in terms_ko: it must not bypass boundaries.
    rules = parse_claim_rules(
        document(
            rule(
                terms_ko=[term],
                **{field: [term]},
                en_origin="advisor_added_en" if field == "terms_en_added" else None,
                en_pending=False,
            )
        )
    )
    assert bool(find_claim_terms(text, rules)) is expected


@pytest.mark.parametrize("referenced", [False, True])
def test_exceptions_suppress_only_overlapping_occurrences(referenced):
    first = rule(
        exceptions=[] if referenced else ["합성 표현 허용"],
        exception_refs=["S-002"] if referenced else [],
    )
    second = rule(
        rule_id="S-002",
        rule_type="requires_substantiation",
        terms_ko=["합성 표현 허용"],
    )
    rules = parse_claim_rules(document(first, second))

    def matches(text):
        return [
            match for match in find_claim_terms(text, rules) if match.rule_id == "S-001"
        ]

    assert matches("합 성 표 현 허 용") == []
    assert matches("합성표현허용, 합 성 표현")
    assert matches("합성 표현, 합성표현 허용")


def test_english_exception_overlap_uses_shared_normalized_positions():
    rules = parse_claim_rules(
        document(
            rule(
                terms_ko=["합성"], terms_en=["stem cell"], exceptions=["허용 stem cell"]
            ),
        )
    )
    assert find_claim_terms("허 용 ＳＴＥＭ  \t ＣＥＬＬ", rules) == []
    assert find_claim_terms("허용 stem cell, stem cell", rules)


def test_plan_checks_title_and_separates_all_fields_with_disclaimer():
    rules = parse_claim_rules(
        document(
            rule(),
            rule(
                rule_id="S-002",
                terms_ko=["합성 실증"],
                rule_type="requires_substantiation",
            ),
        )
    )
    result = check_plan_fields(
        {"title": "합성 표현", "copy": "합성 실증", "subtitles": "다른 문구"}, rules
    )
    assert set(result.fields) == {"title", "copy", "subtitles"}
    assert result.fields["title"][0].rule_id == "S-001"
    assert result.fields["copy"][0].rule_type is RuleType.requires_substantiation
    assert result.fields["subtitles"] == []
    assert (
        result.disclaimer
        == CLAIM_CHECK_DISCLAIMER
        == "식약처 안내서 기준 점검이며 법적 판단이 아님"
    )
    assert check_plan_fields({}, rules).disclaimer == CLAIM_CHECK_DISCLAIMER


@pytest.mark.parametrize(
    "content,code",
    [
        (None, "CLAIM_RULES_UNREADABLE"),
        ("rules: [", "CLAIM_RULES_UNREADABLE"),
        (b"\xff", "CLAIM_RULES_UNREADABLE"),
        ("[]", "CLAIM_RULES_INVALID"),
        ("", "CLAIM_RULES_INVALID"),
        ("rules: []", "CLAIM_RULES_INVALID"),
    ],
)
def test_loader_classifies_unreadable_and_invalid_files(tmp_path, content, code):
    path = tmp_path / "synthetic.yaml"
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif content is not None:
        path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=code):
        load_claim_rules(path)


def test_loader_reports_io_errors(tmp_path):
    with pytest.raises(ConfigError, match="CLAIM_RULES_UNREADABLE"):
        load_claim_rules(tmp_path)


def test_loader_uses_domain_parser_and_retains_error_location(tmp_path):
    path = tmp_path / "synthetic.yaml"
    path.write_text(yaml.safe_dump(document(rule())), encoding="utf-8")
    assert load_claim_rules(path) == parse_claim_rules(document(rule()))
    path.write_text(yaml.safe_dump(document(rule(source_page=0))), encoding="utf-8")
    with pytest.raises(
        ConfigError, match=r"CLAIM_RULES_INVALID.*rules.*0.*source_page"
    ):
        load_claim_rules(path)


def test_confirmed_config_has_valid_provenance_and_rule_format():
    path = ROOT / "config" / "claim_rules.yaml"
    rules = load_claim_rules(path)
    assert rules
    assert all(
        item.source_page >= 1 and item.rule_type in set(RuleType) for item in rules
    )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    contracts = (ROOT / "docs" / "CONTRACTS.md").read_text(encoding="utf-8")
    section = contracts.split("식약처 안내서 PDF 내려받기", 1)[1].split("\n## ", 1)[0]
    assert raw["source"]["file_sha256"] == re.search(
        r"`([a-f0-9]{64})`", section
    ).group(1)
