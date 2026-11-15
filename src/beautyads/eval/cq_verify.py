"""Read-only frozen-v1 competency-question verification; no model calls."""

import json
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO
from urllib.parse import urlsplit

from beautyads.graph.connection import GraphConnection, GraphError, connect_graph
from beautyads.graph.queries import QUESTIONS, months_before, question_parameters
from beautyads.pipeline.preflight import docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    neo4j_password,
    neo4j_uri,
)
from beautyads.sources.advertiser_classes import (
    AdvertiserClassesError,
    advertiser_class,
    load_advertiser_classes,
)

# Verbatim frozen-v1 limitations, including historical counts (not thresholds).
_LIMIT_TEXT = (
    '**CQ-01·02·04·05·10·14의 답은 성분→효능 연결(`HAS_EFFICACY`)이 있는 범위에서만 나온다.** 이 연결의 출처는 (a) 식약처 기능성 고시 성분(미백·주름 개선·자외선 차단), (b) 진정·보습 등 그 밖의 효능은 출처(문헌·성분 데이터베이스 등)를 붙인 소규모 수기 표로 한정한다(ADR-012 후속 결정). 출처 없는 연결은 만들지 않으므로 범위가 제한적이고, 연결이 없는 성분·효능은 "답 없음"이 아니라 "근거 연결 없음"으로 보고한다.',
    '**성분→효능 표(2026-11-15, `config/ingredient_efficacy.yaml`)의 범위와 한계**: CQ-01·02·04·05·10·14의 답은 **이 표에 연결된 성분 범위에서만** 나온다. 연결은 (a) 식약처 기능성 고시 성분(미백·주름 개선·자외선 차단, `basis: regulatory_notice`, 출처 「기능성화장품 심사에 관한 규정」 별표)과 (b) 문헌 리뷰 근거 성분(보습·장벽·진정, `basis: literature_review`, 각 연결에 PMID 출처)뿐이다. 표에 없는 성분은 "효능 없음"이 아니라 "근거 연결 없음"이다. `Allantoin`·`Betaine`·`Tocopherol`·`Arginine`·`Beta-Glucan`은 출처 미확인으로 연결하지 않았다(한계). **진정은 병풀추출물만 근거 성분이다.** `Titanium Dioxide`·`Zinc Oxide`는 카탈로그 영문명이 `Titanium Dioxide,CI 77891`·`Zinc Oxide,CI 77947`이라 정확 일치하지 않아 연결하지 않았다(추측으로 연결하지 않는다).',
    '**식약처 고시 연결(`conditional: true`)은 조건부다.** 고시 성분이 들었다고 그 효능이 인정되는 것이 아니다. 고시 함량 조건과 기능성 심사(보고)가 따르므로, CQ-03·10의 답은 "성분이 고시 목록에 있다"까지만 말하고 인증 여부는 `CERTIFIED_AS`(식약처 보고 품목 연결)로 따로 판단한다.',
    "**`ADDRESSES`(효능→피부 고민)는 분류 체계 정의이며 효능 주장이 아니다.** 실증 근거가 아니라 이 프로젝트의 분류 약속이고 `basis: taxonomy_definition`으로 적재한다.",
    '**CQ-03·10·11은 식약처 품목과 제품의 연결 규칙(제품명 일치)이 정해져야 답할 수 있다.** 규칙은 `mfds-source`·`product-records` step에서 정하고, 답과 함께 **커버리지**(식약처 품목과 연결된 제품 수 ÷ 대상 제품 수)를 보고한다. 연결되지 않은 제품은 "인증 없음"이 아니라 `unknown`이다(`docs/CONTRACTS.md` 식약처 절).',
    '**CQ-03·10·11의 인증 연결 규칙과 커버리지(2026-11-15 `live-cert-recheck`, 저장된 제품 71개)**: 몰 제품명에서 SPF·PA·용량·기호를 빼고 공백을 제거한 값이 식약처 보고 품목명에서 앞의 브랜드 한글명(`config/brand_korean_names.yaml`)을 뺀 공백 제거형과 **정확히 같을 때만** 연결한다(정밀도 우선). 일치 품목명이 둘 이상이거나, 브랜드 접두어가 없거나 다른 품목이거나, 품목이 나오지 않으면 `unknown`이다. 업체명으로 브랜드를 판정하지 않는다. **답은 연결(일치)된 제품에 한정되고, 연결되지 않은 제품은 "인증 없음"이 아니라 `unknown`이다.** 커버리지(연결된 제품 수 ÷ 대상 71개): 미백 13개(18.3%), 주름 개선 11개(15.5%), 자외선 차단 16개(22.5%), 어느 한 종류라도 연결된 제품 30개(42.3%)이고 나머지는 `unknown`이다. 이 값은 식약처 보고 품목명이 제품명과 다르게 등록된 경우를 놓치므로(예: 라운드랩은 품목명에 브랜드 접두어가 없다) 실제 인증 제품 수의 하한에 가깝다. CQ-03은 이 연결된 제품만 답하며 커버리지를 함께 보고한다.',
    '**CQ-06**의 "상위·하위"는 `docs/EVAL.md`의 지표 정규화(채널 내 조회수 백분위, 게시 14일 이상)를 따르며, 조회수 값이 있는 소재에서만 나눈다. Instagram 소재에는 조회수 필드가 있으나 값이 비어 있는 소재가 섞여 있다(2026-11-15 읽기 전용 확인, 있음·없음만 확인). 출처 간 조회수는 직접 비교하지 않으며, TikTok은 조회수가 아니라 도달 구간이다(`docs/ARCHITECTURE.md`).',
    '**CQ-09는 TikTok 한정이다.** TikTok 분석분은 시드 표본이라 소규모다(2026-11-15 실측: `content_type@v1` 완료 221건, 제품 소재 분석(`hook@v1`) 92건). 집행 주체 분류는 `config/retailers.yaml`(사용자 확인 대기)에 의존한다. **사용자가 광고주를 분류한 뒤 `brand_direct`·`retailer` 중 한쪽의 소재 수가 30건 미만이면 CQ-09는 "표본 부족으로 방향만 제시"로 표시하고, 결론으로 쓰지 않는다.** **2026-11-15 분류 결과(훅·full 분석 결과가 있는 TikTok 소재 92건, 광고주 44곳): `brand_direct` 29건, `retailer` 26건, `unknown` 37건이다. 두 쪽 모두 30건 미만이므로 CQ-09는 "표본 부족으로 방향만 제시"이며 결론으로 쓰지 않는다.** 분류는 사용자가 확인 대상 16곳을 채팅으로 답한 값과, 이름에 브랜드명·판매처 시드가 들어 있거나 이름이 숫자 ID·공백인 광고주에 대한 규칙 값이다.',
    "**2층 질문(CQ-04·05·06·08·13·14·15·16 중 `PROMOTES`를 거치는 것)은 YouTube·Instagram 소재에서만 제품에 연결된다.** TikTok 소재는 제목·캡션 필드가 비어 있어 `PROMOTES` 규칙(`docs/ARCHITECTURE.md`)으로 연결되지 않는다. **TikTok은 CQ-09와 분포 용도로만 쓰고, 제품 연결(`PROMOTES`)을 거치는 질문의 답은 YouTube·Instagram에서만 나온다.** `layer2-links`에서 YouTube·Instagram의 test 커버리지가 부족하면 그때 영상에서 제품을 식별하는 별도 추출을 사용자에게 제안한다. 토리든·넘버즈인은 제품 정보를 받지 못해 `PROMOTES` 커버리지에서 빠진다. `PROMOTES` 규칙은 dev 브랜드에서 다듬고 test 브랜드에서 커버리지를 보고한다. CQ-09는 `PROMOTES`를 거치지 않으므로 영향이 없다.",
    "**대표 단품 선정(2026-11-15 사용자 확정, 71개)의 근거는 약하다.** 광고 텍스트(YouTube·Instagram 제목·캡션)에서 이름이 확인되는 것은 31개뿐이고 나머지 40개는 공식몰 목록 순서로 채웠다. 선정은 브랜드×카테고리별 최대 2개이며 목록을 끝까지 보지 못한 몰이 있다. 이 때문에 제품 소재 중 `PROMOTES`가 이어지는 비율이 낮을 수 있고 2층 질문의 답이 작아질 수 있다.",
    "**CQ-12는 P4에서는 합성 데이터로만 검증하고, P5 피드백 메모리 이후 실데이터로 검증한다.**",
    'CQ-13·14는 "우리 제품"이 작업 공간(테넌트)의 브랜드 프로필에서 정해진다. CQ-15의 "최근"은 서버가 정한 기준일에서 계산한다.',
    '**`cq-verify`는 질문마다 "연결된 소재 수(`PROMOTES` 커버리지)"를 답과 함께 보고한다.** 소재가 제품에 연결되지 못하면(`PROMOTES`를 만들지 않음) 2층 질문의 답이 작아지므로, 답의 크기를 해석하려면 이 수가 필요하다.',
    "이번 검토에서 나온 약점: CQ-06·09는 관계형 조인 한두 번으로도 답이 나온다. 그래프가 확실히 나은 질문은 별칭 경유(CQ-05·15), 3~4홉 경로(CQ-02는 3홉, CQ-05·13·14·16은 4홉), 규칙 상속(CQ-11), 차집합 비교(CQ-14)다.",
)
_LIMIT_QUESTIONS = (
    (1, 2, 4, 5, 10, 14),
    (1, 2, 4, 5, 10, 14),
    (3, 10),
    (2,),
    (3, 10, 11),
    (3, 10, 11),
    (6,),
    (9,),
    (4, 5, 6, 8, 13, 14, 15, 16),
    (4, 5, 6, 8, 13, 14, 15, 16),
    (12,),
    (13, 14, 15),
    (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16),
    (2, 5, 6, 9, 11, 13, 14, 16),
)
LIMITATIONS = {
    qid: tuple(
        text
        for text, numbers in zip(_LIMIT_TEXT, _LIMIT_QUESTIONS, strict=True)
        if int(qid[3:]) in numbers
    )
    for qid in QUESTIONS
}

GRAPH_COUNT = "MATCH (n) WHERE n:Creative OR n:Product RETURN count(n) AS count"
FEEDBACK_COUNT = "MATCH (f:Feedback) RETURN count(f) AS count"
CREATIVE_SCOPE = """
    MATCH (c:Creative)
    WHERE c.content_type = $content_type AND c.source IN $sources
      AND ($category IS NULL OR c.category = $category)
    RETURN c.source + ':' + c.source_id AS creative_id,
           EXISTS { MATCH (c)-[:PROMOTES]->(:Product) } AS linked,
           c.latest_view_count AS views, c.source AS source,
           c.brand AS channel_brand, c.published_at AS published_at
"""
CERT_COVERAGE = """
    MATCH (p:Product)
    WHERE ($category IS NULL OR p.category = $category)
    WITH p, EXISTS {
        MATCH (p)-[:CERTIFIED_AS]->(f:FunctionalCert)
        WHERE $cert IS NULL OR f.value = $cert
    } AS linked
    RETURN count(p) AS products,
           count(CASE WHEN linked THEN p END) AS certified,
           count(CASE WHEN NOT linked THEN p END) AS unknown
"""


def error_code(error: Exception) -> str:
    code = getattr(error, "code", None)
    if code == "Neo.ClientError.Statement.SyntaxError":
        return "CQ_SYNTAX_ERROR"
    if code == "NEO4J_UNREACHABLE" or isinstance(
        error, (ConnectionError, TimeoutError)
    ):
        return "NEO4J_UNREACHABLE"
    if isinstance(error, GraphError):
        return error.code
    return "CQ_EXECUTION_ERROR"


def sample_warning(counts: Mapping[str, int]) -> str | None:
    if min(counts.get("brand_direct", 0), counts.get("retailer", 0)) < 30:
        return "표본 부족으로 방향만 제시"
    return None


def _ids(answers: list[dict]) -> set[str]:
    result = set()
    for row in answers:
        if row.get("creative_id") is not None:
            result.add(row.get("creative_id"))
        result.update(row.get("creative_ids") or [])
    return result


def _datetime(value):
    native = getattr(value, "to_native", None)
    if callable(native):
        value = native()
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return (
                parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            )
        except ValueError:
            pass
    return None


def _percentiles(scope, answers, as_of):
    # Rank ALL in-scope creatives with views, including ones without PROMOTES.
    # The graph currently retains brand/source, not original channel identifiers.
    groups = defaultdict(dict)
    mature = datetime.fromisoformat(
        question_parameters(QUESTIONS["CQ-06"], as_of=as_of)["mature_before"]
    )
    excluded = 0
    for row in scope:
        if row.get("views") is None:
            excluded += 1
            continue
        published = _datetime(row.get("published_at"))
        if published is not None and published <= mature:
            groups[(row.get("source"), row.get("channel_brand"))][
                row.get("creative_id")
            ] = row.get("views")
    bands = {}
    for group in groups.values():
        values = sorted(group.values())
        low_index = (len(values) - 1) * 0.25
        high_index = (len(values) - 1) * 0.75

        def threshold(index, values=values):
            lo = int(index)
            hi = min(lo + 1, len(values) - 1)
            return values[lo] + (values[hi] - values[lo]) * (index - lo)

        low, high = threshold(low_index), threshold(high_index)
        for key, value in group.items():
            bands[key] = (
                "top" if value >= high else "bottom" if value <= low else "middle"
            )
    counts = Counter()
    hooks = defaultdict(set)
    for row in answers:
        band = bands.get(row.get("creative_id"))
        if band in {"top", "bottom"}:
            key = (
                row.get("category"),
                row.get("source"),
                row.get("channel_brand"),
                band,
                row.get("hook"),
            )
            counts[key] += 1
            hooks[row.get("hook")].add(row.get("category"))
    return {
        "excluded_missing_views": excluded,
        "normalization": "source/brand proxy; original channel identity unavailable",
        "hook_distribution": [
            {
                "category": k[0],
                "source": k[1],
                "channel_brand": k[2],
                "band": k[3],
                "hook": k[4],
                "creatives": v,
            }
            for k, v in sorted(counts.items(), key=lambda item: str(item[0]))
        ],
        "cross_category_hooks": {h: sorted(cats) for h, cats in hooks.items()},
    }


def run_verification(
    graph: GraphConnection,
    *,
    as_of: date,
    out: TextIO,
    advertiser_path: Path = Path("config/advertiser_classes.yaml"),
    context: Mapping[str, str] | None = None,
) -> dict:
    """Context is trusted session data, never a CLI argument or tool input.

    CQ-13/14/16 enumerate public reference-product pairs in this offline runner.
    A workspace-specific interpretation requires the P5 brand profile.
    """
    summary = {
        "event": "summary",
        "as_of": as_of.isoformat(),
        "hop_compliant": 0,
        "zero_rows": 0,
        "failed": 0,
        "skipped": 0,
        "cost_usd": 0,
        "advertiser_classes": None,
    }
    try:
        classes = load_advertiser_classes(advertiser_path)
        classes_error = None
    except AdvertiserClassesError as error:
        classes, classes_error = {}, error.code
    for qid, spec in QUESTIONS.items():
        report = {
            "id": qid,
            "hops": spec.hops,
            "success": False,
            "code": "OK",
            "rows": 0,
            "connected_creatives": None,
            "scope_product_creatives": None,
            "promotes_coverage": None,
            "limitations": LIMITATIONS[qid],
        }
        try:
            if qid == "CQ-09" and classes_error:
                raise GraphError(classes_error)
            if qid == "CQ-12":
                records = graph.run(FEEDBACK_COUNT).records
                if not records or not records[0].get("count"):
                    report["code"] = "SKIPPED_SYNTHETIC_ONLY"
                    summary["skipped"] += 1
                    # Coverage remains independently reported for skipped questions.
                elif not context or not context.get("tenant_id"):
                    raise GraphError("CQ_CONTEXT_MISSING")
            params = question_parameters(spec, as_of=as_of, context=context)
            sources = ["tiktok"] if qid == "CQ-09" else ["youtube", "instagram"]
            category = (
                params.get("category") if qid in {"CQ-01", "CQ-02", "CQ-04"} else None
            )
            scope = graph.run(
                CREATIVE_SCOPE,
                {
                    "content_type": "product_creative",
                    "sources": sources,
                    "category": category,
                },
            ).records
            scope_ids = {r.get("creative_id") for r in scope}
            linked = {r.get("creative_id") for r in scope if r.get("linked")}
            report["scope_product_creatives"] = len(scope_ids)
            answers = (
                [] if report["code"] != "OK" else graph.run(spec.cypher, params).records
            )
            report["rows"] = len(answers)
            numerator = len(_ids(answers) & linked)
            report["connected_creatives"] = numerator
            report["promotes_coverage"] = numerator / len(scope_ids) if scope_ids else 0
            report["answers"] = answers
            report["scope"] = {"sources": sources, "category": category}
            if not answers and qid in {
                "CQ-01",
                "CQ-02",
                "CQ-04",
                "CQ-05",
                "CQ-10",
                "CQ-14",
            }:
                report["evidence_note"] = (
                    "근거 연결 없음일 수 있으며 효능 없음으로 해석하지 않음"
                )
            if qid in {"CQ-03", "CQ-10", "CQ-11"}:
                records = graph.run(
                    CERT_COVERAGE, {"category": category, "cert": params.get("cert")}
                ).records
                report["certification"] = (
                    records[0]
                    if records
                    else {"products": 0, "certified": 0, "unknown": 0}
                )
            if qid == "CQ-06":
                report.update(_percentiles(scope, answers, as_of))
            if qid == "CQ-09":
                ids = {name: set() for name in ("brand_direct", "retailer", "unknown")}
                distribution = defaultdict(set)
                for row in answers:
                    group = advertiser_class(classes, row.get("advertiser_name"))
                    ids[group].add(row.get("creative_id"))
                    distribution[(group, row.get("hook"))].add(row.get("creative_id"))
                counts = {name: len(values) for name, values in ids.items()}
                summary["advertiser_classes"] = counts
                report["advertiser_classes"] = counts
                report["hook_distribution"] = [
                    {"advertiser_class": k[0], "hook": k[1], "creatives": len(v)}
                    for k, v in distribution.items()
                ]
                warning = sample_warning(counts)
                if warning:
                    report["sample_warning"] = summary["sample_warning"] = warning
            if qid == "CQ-15":
                boundary = datetime.combine(
                    months_before(as_of, 3), datetime.min.time(), UTC
                )
                recent, previous = set(), set()
                for row in answers:
                    published = _datetime(row.get("published_at"))
                    if published is not None:
                        (recent if published >= boundary else previous).add(
                            row.get("creative_id")
                        )
                report["trend"] = {
                    "recent_3_months": len(recent),
                    "previous_3_months": len(previous),
                    "change": len(recent) - len(previous),
                }
            if qid == "CQ-16":
                report["price_pairs"] = answers
                report["price_note"] = (
                    "단위당 정가 기준; 컨텍스트 가격 범위가 없으면 기준 제품과 정확히 같은 가격만 조회"
                )
            if qid in {"CQ-13", "CQ-14", "CQ-16"}:
                report["reference_scope"] = (
                    "public_product_pairs; workspace brand profile required in P5"
                )
            if qid == "CQ-13":
                report["key_ingredient_note"] = (
                    "is_key가 unknown인 성분은 핵심 성분으로 추정하지 않음"
                )
            if report["code"] == "OK":
                report["success"] = True
                summary["hop_compliant"] += int(1 <= spec.hops <= 4)
                summary["zero_rows"] += int(not answers)
        except Exception as error:  # noqa: BLE001 -- isolate questions, never print diagnostics
            report["code"] = error_code(error)
            summary["failed"] += 1
        print(json.dumps(report, ensure_ascii=False, default=str), file=out)
    print(json.dumps(summary, ensure_ascii=False), file=out)
    return summary


def cq_preflight(*, environ, env_file, docker_check, tcp_check):
    if get_setting("NEO4J_PASSWORD", environ=environ, env_file=env_file) is None:
        return "ENV_MISSING:NEO4J_PASSWORD"
    try:
        neo4j_password(environ=environ, env_file=env_file)
    except SettingError as error:
        return f"INVALID_SETTING:{error.name}"
    if not docker_check():
        return "DOCKER_DOWN"
    try:
        uri = urlsplit(neo4j_uri(environ=environ, env_file=env_file))
        port = uri.port or 7687
        if (
            uri.scheme
            not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}
            or not uri.hostname
            or not 1 <= port <= 65535
            or not tcp_check(uri.hostname, port, 1.0)
        ):
            return "NEO4J_UNREACHABLE"
    except (TypeError, ValueError, OSError):
        return "NEO4J_UNREACHABLE"
    return None


def main(
    *,
    environ=None,
    out=None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    graph_factory=None,
) -> int:
    out = sys.stdout if out is None else out
    env_file = DEFAULT_ENV_FILE if environ is None else None
    problem = cq_preflight(
        environ=environ,
        env_file=env_file,
        docker_check=docker_check,
        tcp_check=tcp_check,
    )
    if problem:
        print(f"PREFLIGHT_FAILED {problem}", file=out)
        return 2
    graph = None
    try:
        graph = (
            graph_factory()
            if graph_factory
            else connect_graph(environ=environ, env_file=env_file)
        )
        records = graph.run(GRAPH_COUNT).records
        if not records or not records[0].get("count"):
            print("PREFLIGHT_FAILED GRAPH_EMPTY — 먼저 make sync", file=out)
            return 2
        summary = run_verification(graph, as_of=datetime.now(UTC).date(), out=out)
        return 3 if summary["failed"] else 0
    except Exception as error:  # noqa: BLE001 -- credential-free CLI errors
        print(f"PREFLIGHT_FAILED {error_code(error)}", file=out)
        return 2
    finally:
        if graph is not None:
            try:
                graph.close()
            except Exception:  # noqa: BLE001, S110 -- do not expose close diagnostics
                pass


if __name__ == "__main__":
    raise SystemExit(main())
