"""Lifespan-owned full services; connections and model boundaries are injectable."""

import math
import re
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from time import monotonic
from uuid import uuid4

from beautyads.agents.design_compose import FontMissing, compose_design, product_line
from beautyads.agents.design_images import (
    image_prompt,
    save_composed_design,
    save_design_image,
)
from beautyads.agents.evaluation import evaluate_plan
from beautyads.agents.lookups import (
    GraphCertLookup,
    GraphEfficacySupport,
    GraphEvidenceIndex,
)
from beautyads.agents.plan_eval import run_plan_eval
from beautyads.agents.planning import make_plan
from beautyads.agents.research import run_research
from beautyads.agents.skeleton import build_graph
from beautyads.agents.supervisor import decide, run_request
from beautyads.agents.tools import run_tool
from beautyads.api.app import Assembly
from beautyads.api.ask_view import json_copy
from beautyads.api.checkpointer import (
    build_checkpointer,
    close_checkpointer,
    setup_checkpointer,
)
from beautyads.domain.creative import Source
from beautyads.domain.labels import Claim
from beautyads.domain.lookups import SupportStatus
from beautyads.domain.plan import Plan
from beautyads.domain.supervisor import RequestLimits, cost_exceeded
from beautyads.domain.tenant import WorkspaceProfile, price_band
from beautyads.domain.tools import EVIDENCE_ID_PATTERN
from beautyads.graph.connection import connect_graph
from beautyads.graph.evidence_queries import (
    product_name_parameters,
    product_name_query,
    product_unit_price_parameters,
    product_unit_price_query,
)
from beautyads.llm.chat import chat_complete
from beautyads.llm.image import generate_image
from beautyads.llm.structured import make_structured
from beautyads.obs.ledger import CostCapExceeded, ledger_total, read_entries
from beautyads.obs.trace import append_trace, build_trace
from beautyads.settings import DEFAULT_ENV_FILE, get_setting
from beautyads.sources.claim_rules import load_claim_rules
from beautyads.sources.workspaces import load_workspaces
from beautyads.store.connection import connect, postgres_dsn
from beautyads.store.repository import PostgresCreativeStore
from beautyads.store.tenant_repository import PostgresTenantRepository

_DESIGN_DIR = Path("data/design")
_DEFAULT_LIMITS = RequestLimits()
_HYDRATE_COLUMNS = (
    "source",
    "url",
    "brand",
    "title",
    "published_at",
    "latest_view_count",
    "latest_like_count",
)
_HYDRATE_SQL = """SELECT source, url, brand, title, published_at,
                         latest_view_count, latest_like_count
                  FROM creatives WHERE source = %s AND source_id = %s"""


def _close(resource):
    try:
        resource.close()
    except Exception:  # noqa: BLE001 -- driver errors can include credentials
        raise RuntimeError("ASSEMBLY_CLOSE_FAILED") from None


async def _close_saver(saver):
    try:
        await close_checkpointer(saver)
    except Exception:  # noqa: BLE001 -- pool errors can include credentials
        raise RuntimeError("ASSEMBLY_CLOSE_FAILED") from None


class _ConfiguredStructured:
    def __init__(self, inner, options, guard):
        self.inner, self.options, self.guard = inner, options, guard
        self.model = inner.model
        self.last_cost = None

    @property
    def stats(self):
        return self.inner.stats

    def generate(self, spec, **options):
        self.guard()
        try:
            result = self.inner.generate(spec, **{**options, **self.options})
        except CostCapExceeded:
            raise
        except Exception:  # noqa: BLE001 -- model errors never cross assembly with raw diagnostics
            raise RuntimeError("ASSEMBLY_MODEL_FAILED") from None
        self.last_cost = result.cost_usd
        return result


async def assemble_full(
    *,
    settings,
    workspaces_path=Path("config/workspaces.yaml"),
    group="dev",
    models=None,
    connect_fn=connect,
    graph_fn=connect_graph,
    saver_fn=build_checkpointer,
    environ=None,
    env_file=DEFAULT_ENV_FILE,
    limits=_DEFAULT_LIMITS,
    with_image_enabled=False,
    evaluation_model="claude-haiku-5-5",
    trace_path: Path | None = None,
) -> Assembly:
    """Build services without invoking models.

    models optionally overrides the chat, structured (factory), and image callables.
    The caller owns the returned async close; startup failures close locally.
    """
    if evaluation_model not in {"claude-haiku-5-5", "claude-sonnet-5-5"}:
        raise ValueError("EVALUATION_MODEL_INVALID")
    if group not in {"dev", "test"}:
        raise ValueError("WORKSPACE_GROUP_INVALID")
    model_calls = {
        "chat": chat_complete,
        "structured": make_structured,
        "image": generate_image,
        **(models or {}),
    }
    config = {"environ": environ, "env_file": env_file}
    caps = dict(settings.provider_caps_usd)
    purpose_caps = dict(settings.purpose_caps_usd)

    try:
        async with AsyncExitStack() as stack:
            dsn = postgres_dsn(**config)
            conn = connect_fn(dsn)
            stack.callback(_close, conn)
            graph_connection = graph_fn(**config)
            stack.callback(_close, graph_connection)
            saver = await saver_fn(dsn)
            stack.push_async_callback(_close_saver, saver)
            await setup_checkpointer(saver)
            collected = [
                item.last_collected_at
                for item in PostgresCreativeStore(conn).collection_stats()
                if item.last_collected_at is not None
            ]
            tenants = PostgresTenantRepository(conn)
            workspaces, price_bands, product_names = {}, {}, {}
            for workspace in load_workspaces(workspaces_path):
                if workspace.group != group:
                    continue
                profile = WorkspaceProfile.model_validate(
                    workspace.model_dump(exclude={"group"})
                )
                tenants.save_profile(profile.tenant_id, profile)
                workspaces[profile.tenant_id] = profile.model_dump(mode="json")
                rows = graph_connection.run(
                    product_unit_price_query(),
                    product_unit_price_parameters(
                        brand=profile.brand, url=profile.own_product_url
                    ),
                ).records
                price = next(
                    (
                        row.get("unit_list_price")
                        for row in rows
                        if row.get("price_basis") == "list_price"
                        and row.get("unit_list_price") is not None
                    ),
                    None,
                )
                if price is not None:
                    price_bands[profile.tenant_id] = price_band(
                        float(price), profile.price_band_pct
                    ).model_dump(mode="json")
                try:
                    rows = graph_connection.run(
                        product_name_query(),
                        product_name_parameters(
                            brand=profile.brand, url=profile.own_product_url
                        ),
                    ).records
                    name = next(iter(rows), {}).get("product_name")
                    if isinstance(name, str) and name.strip():
                        product_names[profile.tenant_id] = name
                except Exception:  # noqa: BLE001, S110 -- optional identity lookup never exposes diagnostics
                    pass

            rules = load_claim_rules(Path("config/claim_rules.yaml"))
            runner = partial(run_tool, graph=graph_connection)

            def call_options(model):
                return {
                    "ledger_path": settings.ledger_path,
                    "caps": caps,
                    "api_key": get_setting(
                        "ANTHROPIC_API_KEY"
                        if model.startswith("claude-")
                        else "OPENAI_API_KEY",
                        **config,
                    ),
                    "max_tokens": 4096,
                }

            def chat(**options):
                try:
                    return model_calls["chat"](
                        **{
                            "purpose": "agent-skeleton",
                            **options,
                            **call_options(options["model"]),
                        }
                    )
                except CostCapExceeded:
                    raise
                except Exception:  # noqa: BLE001 -- no model/credential diagnostics in public errors
                    raise RuntimeError("ASSEMBLY_MODEL_FAILED") from None

            def hydrate(ids):
                try:
                    cards = []
                    for eid in dict.fromkeys(ids):
                        if not isinstance(eid, str) or not re.fullmatch(
                            EVIDENCE_ID_PATTERN, eid
                        ):
                            continue
                        source, source_id = eid.split(":", 1)
                        if source not in Source:
                            continue
                        rows = conn.execute(
                            _HYDRATE_SQL, (source, source_id)
                        ).fetchall()
                        if not rows:
                            continue
                        row = dict(zip(_HYDRATE_COLUMNS, rows[0], strict=True))
                        cards.append(
                            {
                                "evidence_id": eid,
                                **{
                                    key: value
                                    for key, value in row.items()
                                    if key
                                    not in {"latest_view_count", "latest_like_count"}
                                },
                                "view_count": row.get("latest_view_count"),
                                "like_count": row.get("latest_like_count"),
                            }
                        )
                    return json_copy(cards)
                except Exception:  # noqa: BLE001 -- SQL failures can include DSN or row values
                    raise RuntimeError("ASSEMBLY_HYDRATE_FAILED") from None
                finally:
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001 -- never expose rollback diagnostics
                        raise RuntimeError("ASSEMBLY_HYDRATE_FAILED") from None

            def ask(
                message,
                ctx,
                profile,
                feedback,
                with_image,
                on_event=None,
                *,
                context_mode="on",
            ):
                profile = {**profile, "product_name": product_names.get(ctx.tenant_id)}
                started_at, started = datetime.now(UTC), monotonic()
                generators = []
                result, failure = None, None
                try:
                    before = ledger_total(
                        settings.ledger_path, exclude_purpose_prefix="image"
                    )

                    def spent_fn():
                        return (
                            ledger_total(
                                settings.ledger_path, exclude_purpose_prefix="image"
                            )
                            - before
                        )

                    def guard():
                        if cost_exceeded(spent_fn(), limits):
                            raise RuntimeError("REQUEST_TEXT_CAP_REACHED")

                    def structured(model):
                        generator = _ConfiguredStructured(
                            model_calls["structured"](model), call_options(model), guard
                        )
                        generators.append(generator)
                        return generator

                    def decide_fn(text):
                        result = decide(
                            text,
                            as_of=ctx.as_of,
                            structured=structured("gpt-6-luna"),
                            limits=limits,
                        )
                        if not result.ok:
                            raise RuntimeError("SUPERVISOR_DECISION_FAILED")
                        return result.decision

                    def research_chat(**options):
                        guard()
                        return chat(**options)

                    def research_fn(brief, raw_store, context_mode="on"):
                        return run_research(
                            brief,
                            ctx=ctx,
                            chat=research_chat,
                            tool_runner=runner,
                            structured=structured("gpt-6-luna"),
                            raw_store=raw_store,
                            **(
                                {"context_mode": context_mode}
                                if context_mode != "on"
                                else {}
                            ),
                        )

                    def claims_fn(profile: dict) -> tuple[list[str], str]:
                        product_url = profile.get("own_product_url")
                        if not product_url or not product_url.strip():
                            return [], "skipped"
                        support = GraphEfficacySupport(graph_connection)
                        available, failed = [], False
                        for claim in Claim:
                            if claim == Claim.other:
                                continue
                            status = support.efficacy_support(product_url, claim)
                            if support.last_error is not None:
                                failed = True
                            if status == SupportStatus.supported:
                                available.append(claim.value)
                        return ([], "failed") if failed else (available, "ok")

                    def plan_fn(**options):
                        return make_plan(
                            **options, structured=structured("gpt-6.1-terra")
                        )

                    def evaluate_fn(**options):
                        generator = structured(evaluation_model)
                        report = evaluate_plan(
                            **options,
                            rules=rules,
                            evidence_index=GraphEvidenceIndex(graph_connection),
                            support=GraphEfficacySupport(graph_connection),
                            certs=GraphCertLookup(graph_connection),
                            structured=generator,
                            model=evaluation_model,
                        )
                        return {
                            **report.model_dump(mode="json"),
                            "cost_usd": generator.last_cost,
                        }

                    request_key, image_index = uuid4().hex, 0
                    image_fn = None
                    if with_image_enabled:

                        def image_fn(plan):
                            nonlocal image_index
                            try:
                                outcome = model_calls["image"](
                                    prompt=image_prompt(Plan.model_validate(plan)),
                                    ledger_path=settings.ledger_path,
                                    caps=caps,
                                    purpose_caps=purpose_caps,
                                    api_key=get_setting("GEMINI_API_KEY", **config),
                                )
                            except CostCapExceeded as exc:
                                cap = (
                                    "purpose:image"
                                    if exc.provider == "purpose:image"
                                    else "provider:" + exc.provider
                                    if isinstance(exc.provider, str)
                                    and re.fullmatch(r"[a-z_]{1,32}", exc.provider)
                                    else "provider:unknown"
                                )
                                return {
                                    "ok": False,
                                    "code": "IMAGE_CAP_REACHED",
                                    "cap": cap,
                                }
                            except Exception:  # noqa: BLE001 -- no image diagnostics or signatures
                                return {"ok": False, "code": "IMAGE_FAILED"}
                            if not outcome.ok:
                                return {"ok": False, "code": "IMAGE_FAILED"}
                            index = image_index
                            image_index += 1
                            saved = save_design_image(
                                outcome,
                                request_key=request_key,
                                index=index,
                                base_dir=_DESIGN_DIR,
                            )
                            reference = {
                                "ok": True,
                                "request_key": request_key,
                                "index": index,
                                "mime": saved.mime,
                                "size": saved.size,
                                "sha256": saved.sha256,
                            }
                            try:
                                composed = compose_design(
                                    outcome.image_bytes,
                                    headline=plan["hook_text"],
                                    product_line=product_line(
                                        profile["brand"], profile.get("product_name")
                                    ),
                                )
                                saved_composed = save_composed_design(
                                    composed.png_bytes,
                                    request_key=request_key,
                                    index=index,
                                    base_dir=_DESIGN_DIR,
                                )
                                reference["composed"] = {
                                    "mime": saved_composed.mime,
                                    "size": saved_composed.size,
                                    "sha256": saved_composed.sha256,
                                }
                                adjusted = getattr(composed, "contrast_adjusted", None)
                                contrast = getattr(composed, "min_contrast", None)
                                if type(adjusted) is bool:
                                    reference["composed"]["contrast_adjusted"] = (
                                        adjusted
                                    )
                                if (
                                    type(contrast) in (int, float)
                                    and math.isfinite(contrast)
                                    and contrast >= 0
                                ):
                                    reference["composed"]["min_contrast"] = round(
                                        float(contrast), 3
                                    )
                            except FontMissing:
                                reference["compose_error"] = "FONT_MISSING"
                            except Exception:  # noqa: BLE001 -- composition never invalidates the original
                                reference["compose_error"] = "COMPOSE_FAILED"
                            return reference

                    def plan_eval_fn(brief, handoff, profile, feedback, *, max_reworks):
                        return run_plan_eval(
                            brief=brief,
                            handoff=handoff,
                            profile=profile,
                            feedback=feedback,
                            plan_fn=plan_fn,
                            evaluate_fn=evaluate_fn,
                            image_fn=image_fn,
                            with_image=with_image and with_image_enabled,
                            max_reworks=max_reworks,
                        )

                    result = run_request(
                        message=message,
                        ctx=ctx,
                        profile=profile,
                        feedback=feedback,
                        decide_fn=decide_fn,
                        research_fn=research_fn,
                        plan_eval_fn=plan_eval_fn,
                        spent_fn=spent_fn,
                        limits=limits,
                        on_event=on_event,
                        claims_fn=claims_fn,
                        **(
                            {"context_mode": context_mode}
                            if context_mode != "on"
                            else {}
                        ),
                    )
                    return result
                except BaseException as exc:
                    failure = exc
                    raise
                finally:
                    try:
                        structured_stats = {}
                        for generator in generators:
                            stats = generator.stats
                            totals = structured_stats.setdefault(
                                generator.model,
                                {
                                    "calls": 0,
                                    "failed_after_retry": 0,
                                    "first_attempt_failures": {},
                                    "first_attempt_failure_details": {},
                                },
                            )
                            totals["calls"] += stats.calls
                            totals["failed_after_retry"] += stats.failed_after_retry
                            for kind, count in stats.first_attempt_failures.items():
                                failures = totals["first_attempt_failures"]
                                failures[kind] = failures.get(kind, 0) + count
                            for (
                                key,
                                count,
                            ) in stats.first_attempt_failure_details.items():
                                details = totals["first_attempt_failure_details"]
                                details[key] = details.get(key, 0) + count
                        # Timestamp windows may overlap for concurrent requests.
                        # The demo is single-user; the ledger has no request ID.
                        entries = [
                            entry
                            for entry in read_entries(settings.ledger_path).entries
                            if entry.ts >= started_at
                        ]
                        record = build_trace(
                            tenant_id=ctx.tenant_id,
                            started_at=started_at,
                            duration_ms=max(0, int((monotonic() - started) * 1000)),
                            message=message,
                            result=result,
                            failure={
                                "class": type(failure).__name__,
                                "code": getattr(failure, "code", None),
                            }
                            if failure is not None
                            else None,
                            ledger_entries=entries,
                            structured=structured_stats,
                        )
                        append_trace(
                            trace_path
                            if trace_path is not None
                            else settings.ledger_path.with_name("traces.jsonl"),
                            record,
                        )
                    except Exception:  # noqa: BLE001, S110 -- observation must preserve results without diagnostics
                        pass

            graph = build_graph(chat=chat, tool_runner=runner, checkpointer=saver)
            result = Assembly(
                graph=graph,
                tenants=tenants,
                allowed_tenants=frozenset(workspaces),
                as_of=datetime.now(UTC).date(),
                last_collected_at=max(collected) if collected else None,
                chat=chat,
                tool_runner=runner,
                workspaces=workspaces,
                price_bands=price_bands,
                ask=ask,
                hydrate=hydrate,
                design_dir=_DESIGN_DIR,
                image_enabled=with_image_enabled,
                close=stack.aclose,
            )
            result.close = stack.pop_all().aclose
            return result
    except Exception:  # noqa: BLE001 -- startup and cleanup diagnostics can contain secrets
        raise RuntimeError("ASSEMBLY_FAILED") from None
