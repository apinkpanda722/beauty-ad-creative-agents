"""Deterministic plan checks use only synthetic rules, text, and lookups."""

from collections import Counter
from copy import deepcopy

import pytest
from pydantic import ValidationError

from beautyads.checks.plan_checks import run_checks, run_checks_on_dict
from beautyads.domain.claims import CLAIM_CHECK_DISCLAIMER, ClaimRule, RuleType
from beautyads.domain.labels import Angle, Category, Claim, CtaType, Format, HookType
from beautyads.domain.lookups import (
    CertLookup,
    CertStatus,
    EfficacySupportLookup,
    EvidenceIndex,
    SupportStatus,
)
from beautyads.domain.plan import (
    CheckCode,
    CheckIssue,
    CheckSeverity,
    Plan,
    PlanCheckReport,
)

IDS = ["youtube:synthetic_A", "instagram:synthetic-B"]
PRODUCT_URL = "https://example.invalid/synthetic-product"
TERM = "합성검사용문구"
EFFICACY = next(iter(Claim))


class FakeEvidence(EvidenceIndex):
    def __init__(self, ids=IDS):
        self.ids = set(ids)
        self.calls = []

    def existing(self, ids):
        self.calls.append(tuple(ids))
        return self.ids.intersection(ids)


class FakeSupport(EfficacySupportLookup):
    def __init__(self, status=SupportStatus.supported):
        self.status = status
        self.calls = []

    def efficacy_support(self, product_url, efficacy):
        self.calls.append((product_url, efficacy))
        return self.status


class FakeCerts(CertLookup):
    def __init__(self, status=CertStatus.certified):
        self.status = status
        self.calls = []

    def cert_status(self, product_url, efficacy):
        self.calls.append((product_url, efficacy))
        return self.status


def synthetic_rule(rule_type=RuleType.prohibited, **changes):
    return ClaimRule(
        **{
            "rule_id": "SYN-001",
            "rule_type": rule_type,
            "source_page": 1,
            "law_basis": "합성 규칙 출처",
            "group": None,
            "source_items": ["합성 원문"],
            "matchable": True,
            "terms_ko": [TERM],
            "terms_en": [],
            "terms_en_added": [],
            "en_pending": True,
            "en_waived": False,
            "exception_note": None,
            "exceptions": [],
            "exception_refs": [],
            "applies_to": [],
            **changes,
        }
    )


def efficacy_scope(efficacy=EFFICACY):
    return {"kind": "efficacy", "value": efficacy.value, "status": "confirmed"}


def plan_data(**changes):
    return {
        "title": "합성 제목",
        "hook_type": next(iter(HookType)),
        "hook_text": "합성 훅",
        "scenes": ["합성 장면", "두 번째 합성 장면"],
        "copy_lines": ["합성 카피", "두 번째 합성 카피"],
        "image_brief": "합성 이미지 설명",
        "cta_type": next(iter(CtaType)),
        "angle": next(iter(Angle)),
        "format": next(iter(Format)),
        "category": next(iter(Category)),
        "product_url": PRODUCT_URL,
        "claimed_efficacy": [EFFICACY],
        "evidence_ids": list(IDS),
        **changes,
    }


def check(plan=None, **changes):
    args = {
        "handoff_evidence_ids": IDS,
        "rules": [synthetic_rule()],
        "evidence_index": FakeEvidence(),
        "support": FakeSupport(),
        "certs": FakeCerts(),
        **changes,
    }
    plan = Plan(**plan_data()) if plan is None else plan
    entrypoint = run_checks_on_dict if isinstance(plan, dict) else run_checks
    report = entrypoint(plan, **args)
    assert report.disclaimer == CLAIM_CHECK_DISCLAIMER
    return report


def test_existing_handoff_evidence_has_no_issues():
    assert check().issues == []


def test_empty_evidence_is_a_failure_and_skips_lookup():
    index = FakeEvidence()
    report = check(Plan(**plan_data(evidence_ids=[])), evidence_index=index)
    assert [issue.code for issue in report.issues] == [CheckCode.EVIDENCE_MISSING]
    assert report.issues[0].severity == CheckSeverity.fail
    assert not report.passed
    assert index.calls == []


@pytest.mark.parametrize("evidence_ids", [(), tuple(IDS)])
def test_schema_coercion_does_not_skip_evidence_checks(evidence_ids):
    converted = check(plan_data(evidence_ids=evidence_ids))
    explicit_list = check(plan_data(evidence_ids=list(evidence_ids)))
    assert converted.issues == explicit_list.issues


def test_handoff_and_graph_membership_are_independent():
    report = check(handoff_evidence_ids=IDS[:1], evidence_index=FakeEvidence(IDS[:1]))
    assert [issue.code for issue in report.issues] == [
        CheckCode.EVIDENCE_NOT_IN_HANDOFF,
        CheckCode.EVIDENCE_NOT_FOUND,
    ]
    assert all(IDS[1] in issue.detail for issue in report.issues)
    assert all(issue.severity == CheckSeverity.fail for issue in report.issues)


def test_outside_handoff_fails_even_when_graph_contains_id():
    report = check(handoff_evidence_ids=IDS[:1])
    assert [issue.code for issue in report.issues] == [
        CheckCode.EVIDENCE_NOT_IN_HANDOFF
    ]


def test_missing_graph_id_fails_even_when_in_handoff():
    report = check(evidence_index=FakeEvidence(IDS[:1]))
    assert [issue.code for issue in report.issues] == [CheckCode.EVIDENCE_NOT_FOUND]


@pytest.mark.parametrize(
    "evidence_id",
    [
        "",
        "no-prefix",
        "Youtube:synthetic",
        "youtube:",
        "youtube:a/b",
        "yt:" + "a" * 65,
        "yt:a\n",
    ],
)
def test_malformed_id_is_not_found_even_if_lookup_would_accept_it(evidence_id):
    index = FakeEvidence([evidence_id])
    report = check(
        Plan(**plan_data(evidence_ids=[evidence_id])),
        handoff_evidence_ids=[evidence_id],
        evidence_index=index,
    )
    assert [issue.code for issue in report.issues] == [CheckCode.EVIDENCE_NOT_FOUND]
    assert report.issues[0].field == "evidence_ids[0]"
    assert index.calls == []


@pytest.mark.parametrize("evidence_id", ["x:A_-0", "synthetic:" + "a" * 64])
def test_step_two_evidence_pattern_accepts_all_allowed_prefixes(evidence_id):
    assert (
        check(
            Plan(**plan_data(evidence_ids=[evidence_id])),
            handoff_evidence_ids=[evidence_id],
            evidence_index=FakeEvidence([evidence_id]),
        ).issues
        == []
    )


TAXONOMY_FIELDS = {
    "hook_type": HookType,
    "cta_type": CtaType,
    "angle": Angle,
    "format": Format,
    "category": Category,
    "claimed_efficacy": Claim,
}


@pytest.mark.parametrize("field", TAXONOMY_FIELDS)
def test_invalid_taxonomy_dict_returns_report(field):
    value = (
        ["synthetic-outside-list"]
        if field == "claimed_efficacy"
        else "synthetic-outside-list"
    )
    report = check(plan_data(**{field: value}))
    assert [issue.code for issue in report.issues] == [CheckCode.TAXONOMY_INVALID]
    assert report.issues[0].field.startswith(field)
    assert not report.passed


@pytest.mark.parametrize(
    ("field", "value"),
    [(field, value) for field, enum in TAXONOMY_FIELDS.items() for value in enum],
)
def test_every_closed_value_is_accepted(field, value):
    value = [value] if field == "claimed_efficacy" else value
    data = plan_data(**{field: value})
    assert check(data).issues == check(Plan(**data)).issues == []


@pytest.mark.parametrize("field", TAXONOMY_FIELDS)
def test_unvalidated_constructed_plan_cannot_bypass_taxonomy_check(field):
    value = (
        ["synthetic-invalid"] if field == "claimed_efficacy" else "synthetic-invalid"
    )
    report = check(Plan.model_construct(**plan_data(**{field: value})))
    assert report.issues[0].code == CheckCode.TAXONOMY_INVALID


@pytest.mark.parametrize(
    "changes", [{"unexpected": True}, {"title": None}, {"scenes": 123}]
)
def test_dict_schema_failure_is_a_report_not_an_exception(changes):
    report = check(plan_data(**changes))
    assert all(issue.code == CheckCode.TAXONOMY_INVALID for issue in report.issues)
    assert not report.passed


def test_dict_missing_required_field_is_a_report():
    data = plan_data()
    del data["title"]
    assert check(data).issues[0].code == CheckCode.TAXONOMY_INVALID


def test_invalid_dict_reports_evidence_before_taxonomy_and_skips_text_checks():
    report = check(
        plan_data(evidence_ids=[], hook_type="synthetic-invalid", title=TERM)
    )
    assert [issue.code for issue in report.issues] == [
        CheckCode.EVIDENCE_MISSING,
        CheckCode.TAXONOMY_INVALID,
    ]


def test_invalid_taxonomy_does_not_hide_handoff_or_graph_failures():
    report = check(
        plan_data(category="synthetic-invalid"),
        handoff_evidence_ids=IDS[:1],
        evidence_index=FakeEvidence(IDS[:1]),
    )
    assert [issue.code for issue in report.issues] == [
        CheckCode.EVIDENCE_NOT_IN_HANDOFF,
        CheckCode.EVIDENCE_NOT_FOUND,
        CheckCode.TAXONOMY_INVALID,
    ]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"title": TERM}, "title"),
        ({"hook_text": TERM}, "hook_text"),
        ({"scenes": ["합성 장면", TERM]}, "scene[1]"),
        ({"copy_lines": [TERM]}, "copy_lines[0]"),
        ({"image_brief": TERM}, "image_brief"),
    ],
)
def test_prohibited_expression_is_found_in_each_displayed_field(changes, field):
    report = check(Plan(**plan_data(**changes)))
    assert len(report.issues) == 1
    issue = report.issues[0]
    assert issue.code == CheckCode.PROHIBITED_EXPRESSION
    assert issue.severity == CheckSeverity.fail
    assert issue.field == field
    assert all(part in issue.detail for part in (field, "SYN-001", TERM))


def test_no_matching_terms_and_optional_image_produce_no_issues():
    assert check(Plan(**plan_data(image_brief=None))).issues == []


def test_no_rules_remains_visible_in_serialized_report():
    report = check(rules=[])
    assert report.rule_count == report.model_dump()["rule_count"] == 0
    assert not any(
        issue.code == CheckCode.PROHIBITED_EXPRESSION for issue in report.issues
    )
    assert check().rule_count == 1


@pytest.mark.parametrize(
    ("status", "severity"),
    [
        (CertStatus.certified, None),
        (CertStatus.not_certified, CheckSeverity.fail),
        (CertStatus.unknown, CheckSeverity.unknown),
    ],
)
def test_functional_cert_disposition_uses_rule_efficacy_even_if_not_declared(
    status, severity
):
    certs = FakeCerts(status)
    report = check(
        Plan(**plan_data(title=TERM, claimed_efficacy=[])),
        rules=[
            synthetic_rule(
                RuleType.requires_functional_cert, applies_to=[efficacy_scope()]
            )
        ],
        certs=certs,
    )
    assert certs.calls == [(PRODUCT_URL, EFFICACY)]
    if severity is None:
        assert report.issues == []
    else:
        assert [
            (issue.code, issue.severity, issue.field) for issue in report.issues
        ] == [(CheckCode.CERT_REQUIRED_UNVERIFIED, severity, "title")]
        assert all(
            part in report.issues[0].detail
            for part in ("SYN-001", TERM, EFFICACY.value)
        )
    assert report.passed is (severity != CheckSeverity.fail)


@pytest.mark.parametrize("product_url", [None, "", "  "])
def test_missing_product_cannot_be_certified_or_supported(product_url):
    certs, support = FakeCerts(), FakeSupport()
    report = check(
        Plan(**plan_data(title=TERM, product_url=product_url)),
        rules=[
            synthetic_rule(
                RuleType.requires_functional_cert, applies_to=[efficacy_scope()]
            )
        ],
        certs=certs,
        support=support,
    )
    assert [(issue.code, issue.severity) for issue in report.issues] == [
        (CheckCode.CERT_REQUIRED_UNVERIFIED, CheckSeverity.unknown),
        (CheckCode.EFFICACY_UNKNOWN, CheckSeverity.unknown),
    ]
    assert certs.calls == support.calls == []
    assert report.passed
    assert report.unknown_count == 2


def test_cert_rule_without_efficacy_scope_is_unresolved_not_certified():
    certs = FakeCerts()
    report = check(
        Plan(**plan_data(title=TERM)),
        rules=[synthetic_rule(RuleType.requires_functional_cert)],
        certs=certs,
    )
    assert [(issue.code, issue.severity) for issue in report.issues] == [
        (CheckCode.CERT_REQUIRED_UNVERIFIED, CheckSeverity.unknown)
    ]
    assert certs.calls == []


def test_missing_product_is_visible_even_without_declared_efficacies():
    support = FakeSupport()
    report = check(
        Plan(**plan_data(product_url=None, claimed_efficacy=[])), support=support
    )
    assert [(issue.code, issue.severity, issue.field) for issue in report.issues] == [
        (CheckCode.EFFICACY_UNKNOWN, CheckSeverity.unknown, "product_url")
    ]
    assert report.unknown_count == 1
    assert support.calls == []


def test_cert_checks_all_rule_scopes_not_unrelated_declared_claim():
    scopes = list(Claim)[:2]
    declared = list(Claim)[-1]
    certs = FakeCerts(CertStatus.not_certified)
    report = check(
        Plan(**plan_data(title=TERM, claimed_efficacy=[declared])),
        rules=[
            synthetic_rule(
                RuleType.requires_functional_cert,
                applies_to=[efficacy_scope(value) for value in scopes],
            )
        ],
        certs=certs,
    )
    assert certs.calls == [(PRODUCT_URL, value) for value in scopes]
    assert [issue.code for issue in report.issues] == [
        CheckCode.CERT_REQUIRED_UNVERIFIED,
        CheckCode.CERT_REQUIRED_UNVERIFIED,
    ]
    assert not report.passed


@pytest.mark.parametrize(
    ("status", "code", "severity"),
    [
        (SupportStatus.supported, None, None),
        (SupportStatus.unsupported, CheckCode.EFFICACY_UNSUPPORTED, CheckSeverity.fail),
        (SupportStatus.unknown, CheckCode.EFFICACY_UNKNOWN, CheckSeverity.unknown),
    ],
)
def test_efficacy_support_dispositions(status, code, severity):
    support = FakeSupport(status)
    report = check(support=support)
    assert support.calls == [(PRODUCT_URL, EFFICACY)]
    if code is None:
        assert report.issues == []
    else:
        assert [(issue.code, issue.severity) for issue in report.issues] == [
            (code, severity)
        ]
        assert EFFICACY.value in report.issues[0].detail
        if severity == CheckSeverity.unknown:
            assert "근거 연결 없음" in report.issues[0].detail
    assert report.passed is (severity != CheckSeverity.fail)


def test_substantiation_is_observed_and_delegated_to_efficacy_check():
    rules = [synthetic_rule(RuleType.requires_substantiation)]
    report = check(Plan(**plan_data(title=TERM)), rules=rules)
    assert report.issues == []
    assert len(report.substantiation_observations) == 1
    assert all(
        part in report.substantiation_observations[0]
        for part in ("title", "SYN-001", TERM)
    )
    unknown = check(
        Plan(**plan_data(title=TERM)),
        rules=rules,
        support=FakeSupport(SupportStatus.unknown),
    )
    assert [issue.code for issue in unknown.issues] == [CheckCode.EFFICACY_UNKNOWN]
    undeclared = check(Plan(**plan_data(title=TERM, claimed_efficacy=[])), rules=rules)
    assert undeclared.substantiation_observations == report.substantiation_observations


def test_unknown_counters_are_visible_even_when_passed():
    report = check(
        Plan(**plan_data(title=TERM, scenes=[TERM], claimed_efficacy=list(Claim)[:2])),
        rules=[
            synthetic_rule(
                RuleType.requires_functional_cert, applies_to=[efficacy_scope()]
            )
        ],
        certs=FakeCerts(CertStatus.unknown),
        support=FakeSupport(SupportStatus.unknown),
    )
    assert report.passed
    assert report.unknown_count == 4
    assert report.unknown_codes == {
        CheckCode.CERT_REQUIRED_UNVERIFIED.value: 2,
        CheckCode.EFFICACY_UNKNOWN.value: 2,
    }
    assert report.unknown_codes == dict(
        Counter(issue.code.value for issue in report.issues)
    )
    serialized = report.model_dump(mode="json")
    assert serialized["unknown_count"] == 4
    assert serialized["unknown_codes"] == report.unknown_codes
    assert serialized["passed"] is True


def test_fail_issues_do_not_count_toward_unknown_totals():
    report = check(
        Plan(**plan_data(title=TERM)), support=FakeSupport(SupportStatus.unknown)
    )
    assert not report.passed
    assert report.unknown_count == 1
    assert report.unknown_codes == {CheckCode.EFFICACY_UNKNOWN.value: 1}


def test_issue_order_is_fixed_and_inputs_are_not_mutated():
    plan = Plan(**plan_data(title=TERM, hook_text=TERM, image_brief=TERM))
    rules = [
        synthetic_rule(),
        synthetic_rule(
            RuleType.requires_functional_cert,
            rule_id="SYN-002",
            applies_to=[efficacy_scope()],
        ),
    ]
    before = deepcopy((plan, rules))
    kwargs = {
        "handoff_evidence_ids": set(IDS[:1]),
        "evidence_index": FakeEvidence(IDS[:1]),
        "certs": FakeCerts(CertStatus.unknown),
        "support": FakeSupport(SupportStatus.unsupported),
        "rules": rules,
    }
    first = check(plan, **kwargs)
    assert check(plan, **kwargs).issues == first.issues
    assert (plan, rules) == before
    assert [issue.code for issue in first.issues] == [
        CheckCode.EVIDENCE_NOT_IN_HANDOFF,
        CheckCode.EVIDENCE_NOT_FOUND,
        CheckCode.PROHIBITED_EXPRESSION,
        CheckCode.CERT_REQUIRED_UNVERIFIED,
        CheckCode.PROHIBITED_EXPRESSION,
        CheckCode.CERT_REQUIRED_UNVERIFIED,
        CheckCode.PROHIBITED_EXPRESSION,
        CheckCode.CERT_REQUIRED_UNVERIFIED,
        CheckCode.EFFICACY_UNSUPPORTED,
    ]


def test_reports_default_to_the_single_domain_disclaimer():
    report = PlanCheckReport(issues=[])
    assert report.disclaimer == CLAIM_CHECK_DISCLAIMER
    assert report.passed and report.unknown_count == 0 and report.unknown_codes == {}


@pytest.mark.parametrize("model", [Plan, CheckIssue, PlanCheckReport])
def test_models_forbid_extra_fields(model):
    data = {
        Plan: plan_data(),
        CheckIssue: {
            "code": CheckCode.EVIDENCE_MISSING,
            "severity": CheckSeverity.fail,
            "field": None,
            "detail": "합성",
        },
        PlanCheckReport: {"issues": []},
    }[model]
    with pytest.raises(ValidationError):
        model(**data, synthetic_extra=True)
