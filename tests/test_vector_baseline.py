"""Deterministic vector retrieval and the existing-store corpus boundary."""

import ast
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from beautyads.domain.claims import ClaimRule
from beautyads.domain.sync import SyncCreative, SyncLabel
from beautyads.eval.vector_baseline import (
    CORPUS_FIELDS,
    MAX_DOC_CHARS,
    CorpusDoc,
    build_corpus,
    cosine,
    load_cache,
    save_cache,
    top_k,
)


@pytest.mark.parametrize(
    "a,b,expected", [([1, 0], [0, 1], 0), ([1, 2], [1, 2], 1), ([0, 0], [1, 2], 0)]
)
def test_cosine(a, b, expected):
    assert cosine(a, b) == pytest.approx(expected)


def test_sorting_validation_and_clipping():
    assert top_k([1, 0], [[1, 0], [1, 0], [0, 1]], ["b", "a", "c"], k=2) == ["a", "b"]
    assert (
        len(CorpusDoc("a", "x" * (MAX_DOC_CHARS + 1)).embedding_text) == MAX_DOC_CHARS
    )
    with pytest.raises(ValueError):
        cosine([1], [1, 2])
    with pytest.raises(ValueError):
        top_k([1], [[1]], [])


def test_cache_roundtrip_and_model_corpus_isolation(tmp_path):
    docs = [CorpusDoc("a", "first"), CorpusDoc("b", "second")]
    save_cache(tmp_path, "model/a", docs, [[1, 2], [3, 4]])
    assert load_cache(tmp_path, "model/a", docs) == (["a", "b"], [[1, 2], [3, 4]])
    assert load_cache(tmp_path, "model/b", docs) is None
    assert load_cache(tmp_path, "model_a", docs) is None
    assert load_cache(tmp_path, "model/a", [CorpusDoc("a", "changed")]) is None
    assert any(p.suffix == ".bin" for p in tmp_path.iterdir())


def test_existing_read_methods_only_and_reported_fields():
    class Source:
        def read_changed(self, **kw):
            assert kw == {"since": None, "limit": None, "run_tag": "v1"}
            return [
                SyncCreative(
                    {
                        "source": "youtube",
                        "source_id": "a",
                        "brand": "test-brand",
                        "ignored": "secret",
                    },
                    datetime.now(UTC),
                )
            ]

        def read_labels(self, key, **kw):
            return [
                SyncLabel(
                    "full@v1", "done", {"angle": "comparison", "ignored": "secret"}
                )
            ]

    product = SimpleNamespace(
        brand="brand",
        source_url="https://example.invalid/p",
        name_ko="name",
        name_en=None,
        category="sun_care",
    )
    products = SimpleNamespace(
        read_changed=lambda **kw: [
            SimpleNamespace(
                product=product,
                ingredients=[
                    SimpleNamespace(status="resolved", standard_name="ingredient")
                ],
                certs=[SimpleNamespace(status="certified", kind="brightening")],
            )
        ]
    )
    docs = build_corpus(Source(), products)
    assert docs == build_corpus(Source(), products, rules=())
    assert {d.id for d in docs} == {
        "youtube:a",
        "product:brand:https://example.invalid/p",
    }
    assert "test-brand" in docs[-1].text
    fields = {line.partition(": ")[0] for d in docs for line in d.text.splitlines()}
    assert fields <= set(CORPUS_FIELDS)
    assert {"brand", "angle", "name_ko", "ingredients", "certifications"} <= fields
    assert all("secret" not in d.text for d in docs)


def test_no_new_queries_or_forbidden_imports():
    import beautyads.eval.vector_baseline as module

    tree = ast.parse(Path(module.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [n.name for n in node.names]
                if isinstance(node, ast.Import)
                else [node.module]
            )
            assert all(n.split(".")[0] not in {"numpy", "litellm"} for n in names)
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(
                word in node.value.upper() for word in ("SELECT ", "MATCH (", "MERGE (")
            )


def test_length_specific_text_and_cache_preserve_legacy_format(tmp_path):
    from beautyads.eval.vector_baseline import _fingerprint, _paths

    docs = [CorpusDoc("a", "abcdef")]
    assert docs[0].embedding_text_for(3) == "abc"
    assert docs[0].embedding_text_for(None) == docs[0].embedding_text
    expected_stem = "model_a-" + hashlib.sha256(b"model/a").hexdigest()[:16]
    assert _paths(tmp_path, "model/a")[0].name == expected_stem + ".json"
    assert _paths(tmp_path, "model/a", MAX_DOC_CHARS) == _paths(tmp_path, "model/a")
    expected_hash = hashlib.sha256(json.dumps([("a", "abcdef")]).encode()).hexdigest()
    assert _fingerprint(docs) == expected_hash
    assert _fingerprint(docs, MAX_DOC_CHARS) == expected_hash
    save_cache(tmp_path, "model/a", docs, [[1.0]])
    meta = json.loads(_paths(tmp_path, "model/a")[0].read_text())
    assert set(meta) == {"model", "ids", "dimension", "fingerprint", "binary_sha256"}
    for length in (2, 3):
        assert load_cache(tmp_path, "model/a", docs, length) is None
        save_cache(tmp_path, "model/a", docs, [[float(length)]], length)
    for length in (2, 3):
        assert load_cache(tmp_path, "model/a", docs, length) == (
            ["a"],
            [[float(length)]],
        )
    assert load_cache(tmp_path, "model/a", docs) == (["a"], [[1.0]])
    assert len(list(tmp_path.glob("*.json"))) == 3
    # Even identical truncated text must have distinct non-default fingerprints.
    assert _fingerprint([CorpusDoc("a", "x")], 2) != _fingerprint(
        [CorpusDoc("a", "x")], 3
    )


def synthetic_rule(rule_id="CR-011", scopes=()):
    return ClaimRule(
        rule_id=rule_id,
        rule_type="prohibited",
        source_page=1,
        law_basis="SENTINEL_BASIS",
        group="synthetic group",
        source_items=["SENTINEL_SOURCE"],
        matchable=True,
        terms_ko=["합성" * MAX_DOC_CHARS],
        terms_en=["SENTINEL_ENGLISH"],
        terms_en_added=[],
        en_pending=False,
        en_waived=False,
        exception_note="SENTINEL_EXCEPTION",
        exceptions=["SENTINEL_EXCEPTION"],
        exception_refs=[],
        applies_to=list(scopes),
    )


def test_rule_documents_keep_only_direct_approved_scopes_and_ordered_fields():
    from beautyads.eval.vector_baseline import _RULE_FIELDS

    expected_fields = ("rule_id", "rule_type", "group", "applies_to", "terms_ko")
    assert _RULE_FIELDS == expected_fields
    rules = [
        synthetic_rule(
            "CR-012",
            [
                {"kind": "category", "value": "sun_care", "status": "confirmed"},
                {"kind": "efficacy", "value": "soothing", "status": "draft"},
            ],
        ),
        synthetic_rule(
            "CR-011",
            [
                {
                    "kind": "efficacy",
                    "value": "hydration",
                    "status": "advisor_approved",
                },
                {"kind": "skin_concern", "value": "건조", "status": "confirmed"},
            ],
        ),
    ]
    source = SimpleNamespace(read_changed=lambda **kw: [])
    docs = build_corpus(source, source, rules=rules)
    assert [d.id for d in docs] == sorted(r.rule_id for r in rules)
    assert build_corpus(source, source) == build_corpus(source, source, rules=()) == []
    assert set(_RULE_FIELDS) <= set(CORPUS_FIELDS)
    by_id = {r.rule_id: r for r in rules}
    for doc in docs:
        lines = [line.partition(": ") for line in doc.text.splitlines()]
        assert tuple(key for key, _, _ in lines) == expected_fields
        assert {key for key, _, _ in lines} <= set(CORPUS_FIELDS)
        values = {key: json.loads(value) for key, _, value in lines}
        rule = by_id[doc.id]
        assert values == {
            "rule_id": rule.rule_id,
            "rule_type": rule.rule_type.value,
            "group": rule.group,
            "applies_to": [
                f"{scope.kind}:{scope.value}"
                for scope in rule.applies_to
                if scope.status in {"confirmed", "advisor_approved"}
            ],
            "terms_ko": rule.terms_ko,
        }
        assert "SENTINEL" not in doc.text
        assert len(doc.embedding_text) == MAX_DOC_CHARS
        # ID and all direct scopes survive truncation of the final terms field.
        prefix = doc.embedding_text.split("\nterms_ko: ")[0]
        assert prefix == doc.text.split("\nterms_ko: ")[0]


@pytest.mark.parametrize("duplicate", ["creative", "product", "rule"])
def test_rule_id_collisions_use_existing_error(duplicate):
    source = SimpleNamespace(
        read_changed=lambda **kw: [
            SyncCreative({"source": "youtube", "source_id": "a"}, datetime.now(UTC))
        ],
        read_labels=lambda *a, **kw: [],
    )
    product = SimpleNamespace(brand="brand", source_url="https://example.invalid/p")
    products = SimpleNamespace(
        read_changed=lambda **kw: [
            SimpleNamespace(product=product, ingredients=[], certs=[])
        ]
    )
    id_ = {
        "creative": "youtube:a",
        "product": f"product:{product.brand}:{product.source_url}",
        "rule": "CR-011",
    }[duplicate]
    rules = [synthetic_rule(id_)]
    if duplicate == "rule":
        rules *= 2
    with pytest.raises(ValueError, match="^CORPUS_ID_DUPLICATE$"):
        build_corpus(source, products, rules=rules)


def test_corpus_module_imports_only_stdlib_without_tenant_or_api_dependencies():
    import sys

    import beautyads.eval.vector_baseline as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0 and node.module is not None
            roots.add(node.module.split(".")[0])
    assert roots
    assert roots <= sys.stdlib_module_names
    assert roots.isdisjoint({"beautyads"})
