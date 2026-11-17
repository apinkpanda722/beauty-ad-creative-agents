import inspect
import json
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from test_links_domain import product

from beautyads.analysis import product_identify
from beautyads.analysis.models import ANALYSIS_MODEL_ID, VideoInput
from beautyads.domain import Creative, JobStatus
from beautyads.domain.product_id import candidates_for_brand
from beautyads.llm import CostCapExceeded, InteractionResult, UsageInfo
from beautyads.obs.ledger import LedgerEntry, append_entry


def material(source="youtube", id="1", **changes):
    return Creative(
        source=source,
        source_id=id,
        url=f"https://example.test/{id}",
        brand="dev",
        duration_s=120,
        collected_at=datetime.now(UTC),
        analyzable=True,
        **changes,
    )


def response(body):
    return InteractionResult(
        json.dumps(body), UsageInfo(ANALYSIS_MODEL_ID, 10, 2, 0, 0, 0.001), {}
    )


def sel(candidate, evidence="spoken_name"):
    return {"candidate": candidate, "evidence": evidence}


def identify(tmp_path, interact, **kwargs):
    return product_identify.identify_product(
        material(),
        candidates=candidates_for_brand("dev", [product()]),
        thinking_level="minimal",
        ledger_path=tmp_path / "ledger.jsonl",
        caps={"gemini": 12},
        interact=interact,
        **kwargs,
    )


@pytest.mark.parametrize(
    "values",
    [
        [sel("C999")],
        [sel("C1"), sel("C1")],
        [[], sel("C1")],
        [None],
        [sel("합성 푸른 세럼")],
        [{"candidate": "C1"}],
    ],
)
def test_invalid_output_retries_once_and_holds(tmp_path, values):
    interact = Mock(return_value=response({"selections": values}))
    attempts = []
    outcome = identify(tmp_path, interact, on_attempt=attempts.append)
    assert outcome.status == JobStatus.held and outcome.attempts == 2
    assert interact.call_count == 2
    assert [a.status for a in attempts] == [JobStatus.pending, JobStatus.held]
    assert all(a.raw_output for a in attempts)


def test_empty_is_done_and_request_has_bounded_video_and_candidate_schema(tmp_path):
    interact = Mock(return_value=response({"selections": []}))
    result = identify(tmp_path, interact)
    assert result.status == JobStatus.done and result.labels == {
        "products": [],
        "selections": [],
        "dropped": 0,
    }
    request = interact.call_args.kwargs
    assert request["model"] == ANALYSIS_MODEL_ID
    assert request["purpose"] == "product-identify"
    assert "temperature" not in request
    video = next(p for p in request["input_parts"] if p["type"] == "video")
    assert video["uri"] == material().url
    assert video["processing"] == {
        "type": "static",
        "start_offset": "0s",
        "end_offset": "60s",
        "fps": 1,
    }
    item = request["response_format"]["schema"]["properties"]["selections"]["items"]
    assert item["properties"]["candidate"]["enum"] == ["C1"]
    prompt = request["input_parts"][0]["text"]
    assert "같은 라인의 다른 제품" in prompt and "[]" in prompt
    assert request["purpose"] == "product-identify"
    assert ANALYSIS_MODEL_ID not in inspect.getsource(product_identify)


def test_decode_all_candidate_ids_and_short_video(tmp_path):
    candidates = candidates_for_brand("dev", [product(url="a"), product(url="b")])
    interact = Mock(return_value=response({"selections": [sel(c) for c in candidates]}))
    outcome = product_identify.identify_product(
        material().model_copy(update={"duration_s": 5}),
        candidates=candidates,
        thinking_level="minimal",
        ledger_path=tmp_path / "costs",
        caps={"gemini": 12},
        interact=interact,
        video=VideoInput("files/synthetic", "video/mp4"),
    )
    assert outcome.labels["products"] == [
        p.key.model_dump() for p in candidates.values()
    ]
    assert [r["evidence"] for r in outcome.labels["selections"]] == ["spoken_name"] * 2
    assert outcome.labels["dropped"] == 0
    assert (
        interact.call_args.kwargs["input_parts"][1]["processing"]["end_offset"] == "5s"
    )


def test_cap_is_checked_before_injected_call(tmp_path):
    append_entry(
        tmp_path / "ledger.jsonl",
        LedgerEntry(
            ts=datetime.now(UTC),
            provider="gemini",
            model=ANALYSIS_MODEL_ID,
            purpose="synthetic",
            cost_usd=12,
            cost_source="response_cost",
        ),
    )
    interact = Mock()
    with pytest.raises(CostCapExceeded):
        identify(tmp_path, interact)
    interact.assert_not_called()


@pytest.mark.parametrize("weak", ["resembles_only", "package_label"])
def test_weak_evidence_selection_is_stored_as_empty_with_dropped_count(tmp_path, weak):
    interact = Mock(return_value=response({"selections": [sel("C1", weak)]}))
    outcome = identify(tmp_path, interact)
    assert outcome.status == JobStatus.done
    assert outcome.labels == {"products": [], "selections": [], "dropped": 1}
    assert outcome.prompt_version == "product-id-v2"
