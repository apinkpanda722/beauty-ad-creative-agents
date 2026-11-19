"""Exercise the pinned SDK's real, local pre-dispatch parameter validation."""

import os
from copy import deepcopy
from uuid import uuid4

import pytest

from beautyads.agents.tools import tool_definitions
from beautyads.llm import (
    StructuredSpec,
    chat,
    chat_complete,
    chat_stream,
    make_structured,
)

# llm/__init__.py sets LITELLM_LOCAL_MODEL_COST_MAP=True before importing
# litellm==1.103.3. get_optional_params is local; completion is always injected.
# Add future image (6a) and structured/tool (6b) call shapes to this guard too.
MODELS = ("gpt-6-luna", "gpt-6.1-terra", "claude-haiku-5-5", "claude-sonnet-5-5")
EFFORTS = ("none", "low", "medium", "high")
SCHEMA = {
    "type": "object",
    "properties": {"value": {"type": "integer"}},
    "required": ["value"],
    "additionalProperties": False,
}
SPEC = StructuredSpec("answer", "Synthetic payload", SCHEMA, lambda value: value)
SHAPES = ("plain", "tools", "auto", "none", "required", "schema")


def options(tmp_path, model, effort):
    return {
        "model": model,
        "messages": [{"role": "user", "content": "synthetic request"}],
        "purpose": "param-guard",
        "ledger_path": tmp_path / "costs.jsonl",
        "caps": {"openai": 10.0, "anthropic": 8.0},
        "api_key": uuid4().hex,
        "reasoning_effort": effort,
    }


def capture_completion(calls):
    def complete(**kwargs):
        calls.append(deepcopy(kwargs))
        message = {
            "role": "assistant",
            "content": '{"value":1}',
            "tool_calls": [
                {
                    "id": "synthetic-call",
                    "type": "function",
                    "function": {"name": SPEC.name, "arguments": '{"value":1}'},
                }
            ],
        }
        usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
        if kwargs.get("stream"):
            return iter(
                [
                    chat.litellm.ModelResponse(
                        model=kwargs.get("model"),
                        stream=True,
                        choices=[
                            {
                                "index": 0,
                                "delta": {"role": "assistant", "content": "synthetic"},
                                "finish_reason": "stop",
                            }
                        ],
                        usage=usage,
                    )
                ]
            )
        return {
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": usage,
        }

    return complete


def guard(calls, *, provider=None):
    assert calls, "No captured combinations were validated"
    checked = 0
    for call in calls:
        kwargs = {
            name: value
            for name, value in call.items()
            if name not in {"model", "api_key", "timeout", "messages", "num_retries"}
        }
        if provider is None:
            call_provider, model = call.get("model").split("/", 1)
        else:
            call_provider, model = provider, call.get("model")
        chat.litellm.get_optional_params(
            model=model, custom_llm_provider=call_provider, **kwargs
        )
        checked += 1
    assert checked > 0
    return checked


@pytest.mark.parametrize(
    ("model", "effort"),
    [(model, effort) for model in MODELS[:2] for effort in EFFORTS]
    + [(model, None) for model in MODELS[2:]],
)
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("complete", [chat_complete, chat_stream])
def test_chat_parameter_matrix(tmp_path, model, effort, shape, complete):
    assert os.environ.get("LITELLM_LOCAL_MODEL_COST_MAP") == "True"
    args = options(tmp_path, model, effort)
    if shape in {"tools", "auto", "none", "required"}:
        args["tools"] = [
            {"type": "function", "function": definition}
            for definition in tool_definitions()
        ]
        assert args.get("tools")
    if shape in {"auto", "none", "required"}:
        args["tool_choice"] = shape
    if shape == "schema":
        args["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": SPEC.name, "strict": True, "schema": SCHEMA},
        }
    calls = []
    complete(**args, completion_fn=capture_completion(calls))
    assert len(calls) == 1
    if complete is chat_stream:
        assert calls[0].get("stream") is True
        assert calls[0].get("stream_options") == {"include_usage": True}
    assert guard(calls) == 1


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("style", ["default", "instruction"])
def test_structured_chat_shapes(tmp_path, model, style):
    args = options(tmp_path, model, "none" if model in MODELS[:2] else None)
    args.pop("model")
    calls = []
    result = make_structured(model, style=style).generate(
        SPEC, **args, completion_fn=capture_completion(calls)
    )
    assert result.ok and len(calls) == 1
    if style == "default":
        if model in MODELS[:2]:
            assert (
                calls[0].get("response_format").get("json_schema").get("strict") is True
            )
        else:
            assert calls[0].get("tools") and calls[0].get("tool_choice") == "auto"
    assert guard(calls) == 1


@pytest.mark.parametrize("model", MODELS[2:])
def test_structured_native_shape(tmp_path, model):
    args = options(tmp_path, model, None)
    args.pop("model")
    calls = []

    async def acreate(**kwargs):
        calls.append(deepcopy(kwargs))
        return {
            "content": [{"type": "text", "text": '{"value":1}'}],
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    result = make_structured(model, style="native").generate(
        SPEC, **args, acreate_fn=acreate
    )
    assert result.ok and len(calls) == 1
    assert calls[0].get("output_config") == {
        "format": {"type": "json_schema", "schema": SCHEMA}
    }
    # This local validator covers shared optional params, not the provider's
    # native output_config acceptance (already measured in CONTRACTS.md).
    assert guard(calls, provider="anthropic") == 1


@pytest.mark.parametrize("model", MODELS[:2])
@pytest.mark.parametrize("effort", EFFORTS)
@pytest.mark.parametrize("choice", ["auto", "none", "required"])
def test_guard_rejects_openai_tool_choice_without_allowance(model, effort, choice):
    with pytest.raises(chat.litellm.UnsupportedParamsError):
        chat.litellm.get_optional_params(
            model=model,
            custom_llm_provider="openai",
            reasoning_effort=effort,
            tools=[
                {"type": "function", "function": definition}
                for definition in tool_definitions()
            ],
            tool_choice=choice,
        )


def test_guard_rejects_empty_capture():
    with pytest.raises(AssertionError, match="No captured combinations"):
        guard([])


def test_image_parameter_shape(tmp_path):
    from beautyads.llm import generate_image

    calls = []
    generate_image(
        prompt="synthetic image brief",
        ledger_path=tmp_path / "costs.jsonl",
        caps={"gemini": 12.0},
        purpose_caps={"image": 3.5},
        api_key=uuid4().hex,
        completion_fn=capture_completion(calls),
    )
    assert len(calls) == 1
    assert calls[0].get("model") == "gemini/gemini-3.1-flash-lite-image"
    assert calls[0].get("modalities") == ["image", "text"]
    assert guard(calls) == 1


@pytest.mark.parametrize("effort", EFFORTS)
def test_planning_strict_plan_shape(tmp_path, effort):
    import json

    from test_plan_checks import plan_data

    from beautyads.agents.planning import strict_plan_schema
    from beautyads.domain.plan import Plan

    calls = []
    args = options(tmp_path, "gpt-6.1-terra", effort)
    args.pop("model")
    spec = StructuredSpec(
        "plan", "Synthetic plan", strict_plan_schema(), Plan.model_validate
    )
    capture = capture_completion(calls)

    def complete(**kwargs):
        response = capture(**kwargs)
        response["choices"][0]["message"]["content"] = json.dumps(
            Plan.model_validate(plan_data()).model_dump(mode="json")
        )
        return response

    result = make_structured("gpt-6.1-terra").generate(
        spec, **args, completion_fn=complete
    )
    assert result.ok and len(calls) == 1
    for call in calls:
        assert call["reasoning_effort"] == effort
        assert call["response_format"]["json_schema"]["strict"] is True
        assert call["response_format"]["json_schema"]["schema"] == strict_plan_schema()
        assert "temperature" not in call
    assert guard(calls) == len(calls)


@pytest.mark.parametrize("model", MODELS[2:])
def test_evaluation_single_auto_tool_shape(tmp_path, model):
    import json

    from beautyads.domain.evaluation import EvaluationScores

    calls = []
    args = options(tmp_path, model, None)
    args.pop("model")
    spec = StructuredSpec(
        "evaluation_scores",
        "Synthetic scores",
        EvaluationScores.model_json_schema(),
        EvaluationScores.model_validate,
    )
    capture = capture_completion(calls)

    def complete(**kwargs):
        response = capture(**kwargs)
        function = response["choices"][0]["message"]["tool_calls"][0]["function"]
        function["name"] = spec.name
        function["arguments"] = json.dumps(
            {"differentiation": 3, "fit": 3, "rationale": "synthetic"}
        )
        return response

    result = make_structured(model).generate(spec, **args, completion_fn=complete)
    assert result.ok and len(calls) == 1
    for call in calls:
        assert len(call["tools"]) == 1 and call["tool_choice"] == "auto"
        assert call["tools"][0]["function"]["parameters"] == spec.schema
        assert not {"reasoning_effort", "thinking", "temperature"} & call.keys()
    assert guard(calls) == len(calls)


def test_supervisor_strict_decision_call_shape(tmp_path):
    import json

    from test_domain_supervisor import decision_data

    from beautyads.agents.supervisor import SUPERVISOR_REASONING_EFFORT, decide
    from beautyads.domain.supervisor import RequestLimits

    calls = []
    capture = capture_completion(calls)

    def complete(**kwargs):
        response = capture(**kwargs)
        response["choices"][0]["message"]["content"] = json.dumps(decision_data())
        return response

    args = options(tmp_path, "gpt-6-luna", SUPERVISOR_REASONING_EFFORT)
    args.pop("model")
    args.pop("messages")
    args.pop("reasoning_effort")
    result = decide(
        "synthetic",
        as_of="2026-01-02",
        structured=make_structured("gpt-6-luna"),
        limits=RequestLimits(),
        completion_fn=complete,
        **args,
    )
    assert result.ok and len(calls) == 1
    assert calls[0]["model"] == "openai/gpt-6-luna"
    assert calls[0]["reasoning_effort"] == SUPERVISOR_REASONING_EFFORT == "none"
    assert calls[0]["response_format"]["type"] == "json_schema"
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
    assert "temperature" not in calls[0]
    assert guard(calls) == 1


def test_embedding_candidates_real_local_parameter_guard(tmp_path):
    from beautyads.llm.embed import embed_texts
    from beautyads.llm.prices import EMBEDDING_PRICES

    calls = []

    def capture(**kw):
        calls.append(deepcopy(kw))
        return {
            "data": [{"index": 0, "embedding": [1.0]}],
            "usage": {"prompt_tokens": 1},
        }

    for model in EMBEDDING_PRICES:
        embed_texts(
            ["synthetic"],
            model=model,
            ledger_path=tmp_path / "ledger",
            caps={"openai": 10.0},
            api_key=uuid4().hex,
            embedding_fn=capture,
        )
    checked = set()
    for call in calls:
        provider, model = call["model"].split("/", 1)
        optional = {
            k: v
            for k, v in call.items()
            if k not in {"model", "input", "api_key", "timeout", "num_retries"}
        }
        assert not {"temperature", "dimensions", "reasoning_effort"} & optional.keys()
        chat.litellm.utils.get_optional_params_embeddings(
            model=model, custom_llm_provider=provider, **optional
        )
        checked.add(model)
    assert checked and checked == set(EMBEDDING_PRICES)
