"""One document per public creative/product/rule; deterministic stdlib retrieval."""

import hashlib
import json
import math
import re
from array import array
from dataclasses import dataclass

TOP_K = 10
MAX_DOC_CHARS = 1500
_CREATIVE_FIELDS = (
    "brand",
    "category",
    "content_type",
    "hook_type",
    "hook_description",
    "angle",
    "format",
    "talent",
    "cta_type",
    "claims",
    "ingredients",
    "structure",
    "platform_fit",
)
_PRODUCT_FIELDS = (
    "brand",
    "name_ko",
    "name_en",
    "category",
    "ingredients",
    "certifications",
)
_RULE_FIELDS = ("rule_id", "rule_type", "group", "applies_to", "terms_ko")
CORPUS_FIELDS = tuple(
    dict.fromkeys((*_CREATIVE_FIELDS, *_PRODUCT_FIELDS, *_RULE_FIELDS))
)


@dataclass(frozen=True)
class CorpusDoc:
    id: str
    text: str

    @property
    def embedding_text(self):
        return self.embedding_text_for(None)

    def embedding_text_for(self, max_chars=None):
        return self.text[: MAX_DOC_CHARS if max_chars is None else max_chars]


def cosine(a, b):
    if len(a) != len(b) or not all(math.isfinite(x) for x in (*a, *b)):
        raise ValueError("VECTOR_INVALID")
    norm = math.sqrt(math.sumprod(a, a)) * math.sqrt(math.sumprod(b, b))
    return math.sumprod(a, b) / norm if norm else 0.0


def top_k(query_vec, doc_vecs, ids, k=TOP_K):
    if (
        len(doc_vecs) != len(ids)
        or len(set(ids)) != len(ids)
        or type(k) is not int
        or k < 0
    ):
        raise ValueError("VECTOR_INVALID")
    scored = [
        (cosine(query_vec, vec), id_) for vec, id_ in zip(doc_vecs, ids, strict=True)
    ]
    return [id_ for _, id_ in sorted(scored, key=lambda item: (-item[0], item[1]))[:k]]


def _document(id_, values, fields):
    return CorpusDoc(
        id_,
        "\n".join(
            f"{key}: {json.dumps(values.get(key), ensure_ascii=False, default=str)}"
            for key in fields
            if values.get(key) is not None
        ),
    )


def build_corpus(creative_source, product_source, *, run_tag="v1", rules=()):
    """Reuse the graph's PostgreSQL readers, without brand/split filtering."""
    docs = []
    for row in creative_source.read_changed(since=None, limit=None, run_tag=run_tag):
        values = {"brand": row.properties.get("brand")}
        for label in creative_source.read_labels(row.key, run_tag=run_tag):
            if label.status == "done" and label.kind in {
                f"{kind}@{run_tag}" for kind in ("content_type", "hook", "full")
            }:
                values.update(
                    {
                        key: value
                        for key, value in (label.labels or {}).items()
                        if key in _CREATIVE_FIELDS and key != "brand"
                    }
                )
        docs.append(
            _document(
                f"{row.key.source.value}:{row.key.source_id}", values, _CREATIVE_FIELDS
            )
        )
    for entry in product_source.read_changed(since=None, limit=None):
        p = entry.product
        values = {
            key: getattr(p, key, None)
            for key in _PRODUCT_FIELDS
            if key not in {"ingredients", "certifications"}
        }
        values["ingredients"] = [
            i.standard_name
            for i in entry.ingredients
            if i.status == "resolved" and i.standard_name
        ]
        values["certifications"] = [
            c.kind for c in entry.certs if c.status == "certified"
        ]
        docs.append(
            _document(f"product:{p.brand}:{p.source_url}", values, _PRODUCT_FIELDS)
        )
    for rule in rules:
        docs.append(
            _document(
                rule.rule_id,
                {
                    "rule_id": rule.rule_id,
                    "rule_type": rule.rule_type.value,
                    "group": rule.group,
                    "applies_to": [
                        f"{scope.kind}:{scope.value}"
                        for scope in rule.applies_to
                        if scope.status in {"advisor_approved", "confirmed"}
                    ],
                    "terms_ko": rule.terms_ko,
                },
                _RULE_FIELDS,
            )
        )
    docs.sort(key=lambda d: d.id)
    if len({d.id for d in docs}) != len(docs):
        raise ValueError("CORPUS_ID_DUPLICATE")
    return docs


def _paths(root, model, max_chars=None):
    # Include the original name digest so path-safe names never collide.
    stem = (
        re.sub(r"[^A-Za-z0-9_-]", "_", model)
        + "-"
        + hashlib.sha256(model.encode()).hexdigest()[:16]
    )
    if max_chars is not None and max_chars != MAX_DOC_CHARS:
        stem += f"-chars-{max_chars}"
    return root / (stem + ".json"), root / (stem + ".bin")


def _fingerprint(docs, max_chars=None):
    payload = [(d.id, d.embedding_text_for(max_chars)) for d in docs]
    if max_chars is not None and max_chars != MAX_DOC_CHARS:
        payload = {"max_chars": max_chars, "documents": payload}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def save_cache(root, model, docs, vectors, max_chars=None):
    if (
        len(docs) != len(vectors)
        or not vectors
        or not vectors[0]
        or any(
            len(v) != len(vectors[0]) or any(not math.isfinite(x) for x in v)
            for v in vectors
        )
    ):
        raise ValueError("VECTOR_CACHE_INVALID")
    root.mkdir(parents=True, exist_ok=True)
    meta, binary = _paths(root, model, max_chars)
    values = array("f", (x for vec in vectors for x in vec))
    binary.write_bytes(values.tobytes())
    meta.write_text(
        json.dumps(
            {
                "model": model,
                "ids": [d.id for d in docs],
                "dimension": len(vectors[0]),
                "fingerprint": _fingerprint(docs, max_chars),
                "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            }
        ),
        encoding="utf-8",
    )


def load_cache(root, model, docs, max_chars=None):
    meta, binary = _paths(root, model, max_chars)
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        if (
            data.get("model") != model
            or data.get("fingerprint") != _fingerprint(docs, max_chars)
            or data.get("ids") != [d.id for d in docs]
        ):
            return None
        raw = binary.read_bytes()
        dimension = data.get("dimension")
        if (
            type(dimension) is not int
            or dimension <= 0
            or hashlib.sha256(raw).hexdigest() != data.get("binary_sha256")
        ):
            return None
        values = array("f")
        values.frombytes(raw)
        if len(values) != len(docs) * dimension or not all(
            math.isfinite(x) for x in values
        ):
            return None
        return data.get("ids"), [
            list(values[i : i + dimension]) for i in range(0, len(values), dimension)
        ]
    except (OSError, ValueError, TypeError, AttributeError):
        return None
