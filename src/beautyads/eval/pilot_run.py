"""Run two dev-only thinking comparisons and write blind pilot labeling files."""

import argparse
import json
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from functools import partial
from io import StringIO
from math import isfinite
from pathlib import Path
from typing import NamedTuple, TextIO

from pydantic import BaseModel

from beautyads.domain import JobStatus, Source
from beautyads.eval.pilot import select_pilot
from beautyads.eval.sheets import (
    SheetError,
    _output_paths,
    build_blind_sheet,
    codebook_rows,
    instructions_text,
    read_key_items,
    sha256_of,
    write_key_supplement,
    write_sheet_files,
)
from beautyads.llm import (
    CostCapExceeded,
    InteractionResult,
    delete_file,
    gemini_interact,
    upload_video,
    wait_processed,
)
from beautyads.obs import check_cap, provider_total
from beautyads.pipeline.analyze import AXES, AnalysisDeps, AnalysisReport, run_analysis
from beautyads.pipeline.collect import DEFAULT_INSTAGRAM_BASE_URL, with_retries
from beautyads.pipeline.media_flow import (
    AnalysisRun,
    MediaDeps,
    MediaStore,
    prepare_instagram_plans,
)
from beautyads.pipeline.preflight import Problem, docker_running, tcp_reachable
from beautyads.settings import (
    DEFAULT_ENV_FILE,
    SettingError,
    get_setting,
    load_settings,
    require_setting,
)
from beautyads.sources.config import ConfigError, load_instagram_accounts
from beautyads.sources.instagram import instagram_httpx_get, refresh_media_urls
from beautyads.sources.media import download_media, httpx_media_get
from beautyads.sources.split import (
    BrandSplit,
    SplitError,
    load_brand_split,
    volume_violations,
)
from beautyads.store import (
    PostgresCreativeStore,
    StoreConnectError,
    apply_migrations,
    connect,
    postgres_dsn,
)

RUN_TAGS = ("minimal", "default")
# 재조회가 사용량으로 중단돼 못 찾았거나 범위 안에서 못 찾아 실패한 content_type 작업.
RETRY_CODES = frozenset({"MEDIA_URL_MISSING", "MEDIA_REFRESH_STOPPED"})
DEFAULT_OUT_DIR = Path("data/interim/pilot")
SPLIT_PATH = Path("config/brand_split.yaml")
LABELING_NOTICE = "키 파일(pilot_key.json)은 라벨링을 마치기 전에 열지 마세요"


class PilotDeps(NamedTuple):
    analysis: AnalysisDeps
    store: MediaStore
    now: Callable[[], datetime]


class PilotReport(BaseModel):
    selected: int
    shortfall: int
    runs: dict[str, AnalysisReport]
    by_status: dict[str, dict[str, dict[str, int]]]
    stopped: str | None
    gemini_cost_usd: float
    files: dict[str, Path]
    split_sha256: str
    elapsed_s: float


class RetryReport(BaseModel):
    tag: str
    retried: int
    run: AnalysisReport | None
    stopped: str | None
    gemini_cost_usd: float
    supplement: Path | None


class PilotError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def estimate(
    *,
    n: int,
    runs: int,
    content_type_window_s: float,
    full_window_s: float,
    tokens_per_second: float = 91.0,
) -> dict:
    """One content call, up to three axes, and one schema retry per axis.

    Video-only token bounds assume each window is fully consumed. Short videos,
    prompts/captions, transport retries, output and thought tokens are not modeled.
    """
    count = n * runs
    minimum = count * content_type_window_s * tokens_per_second
    maximum = count * (content_type_window_s + 3.0 + full_window_s) * tokens_per_second
    return {
        "calls_min": count,
        "calls_max": count * 3,
        "calls_max_with_retries": count * 6,
        "input_tokens_min": minimum,
        "input_tokens_max": maximum,
        "input_tokens_max_with_retries": maximum * 2,
    }


def preflight_pilot(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: Path | None = DEFAULT_ENV_FILE,
    ledger_path: Path,
    caps: Mapping[str, float],
    split_path: Path = SPLIT_PATH,
    sources: Sequence[Source] | None = None,
    docker_check: Callable[[], bool] = docker_running,
    tcp_check: Callable[[str, int, float], bool] = tcp_reachable,
) -> list[Problem]:
    """Finish local checks before Docker/TCP probes or live dependency creation."""
    names = ["GEMINI_API_KEY", "POSTGRES_PASSWORD"]
    if sources is None or Source.instagram in sources:
        names.extend(("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"))
    problems = [
        Problem(f"ENV_MISSING:{name}")
        for name in names
        if get_setting(name, environ=environ, env_file=env_file) is None
    ]
    try:
        load_brand_split(split_path)
    except SplitError:
        problems.append(Problem("PILOT_SPLIT_FILE_INVALID"))

    writable = True
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=ledger_path.parent) as probe:
            probe.write(b"probe")
            probe.flush()
        if ledger_path.exists():
            with ledger_path.open("a", encoding="utf-8"):
                pass
    except OSError:
        writable = False
    try:
        check_cap(ledger_path, "gemini", caps)
    except CostCapExceeded:
        problems.append(Problem("COST_CAP:gemini"))
    except (OSError, UnicodeError):
        writable = False
    if not writable:
        problems.append(Problem("LEDGER_NOT_WRITABLE"))
    if problems:
        return problems
    if not docker_check():
        return [Problem("DOCKER_DOWN")]
    value = get_setting(
        "BEAUTYADS_POSTGRES_PORT", "5433", environ=environ, env_file=env_file
    )
    try:
        port = int(value)
        reachable = 1 <= port <= 65535 and tcp_check("127.0.0.1", port, 1.0)
    except (TypeError, ValueError, OSError):
        reachable = False
    return [] if reachable else [Problem("POSTGRES_UNREACHABLE")]


def run_pilot(
    deps: PilotDeps,
    *,
    n: int,
    seed: int,
    content_type_window_s: float,
    full_window_s: float,
    split: BrandSplit,
    split_sha256: str,
    ledger_path: Path,
    caps: Mapping[str, float],
    interact: Callable[..., InteractionResult],
    out_dir: Path,
    out: TextIO,
) -> PilotReport:
    _output_paths(out_dir)
    started = deps.now()
    counts: Counter[tuple[str, str]] = Counter()
    for stat in deps.store.collection_stats():
        if stat.brand is not None:
            counts[stat.source.value, stat.brand] += stat.analyzable_true
    if volume_violations(split, counts):
        raise PilotError("PILOT_SPLIT_NOT_VERIFIED")
    candidates = deps.store.list_creatives(
        brands=split.dev,
        sources=(Source.youtube, Source.instagram),
        analyzable_only=True,
    )
    if not candidates:
        raise PilotError("PILOT_NO_COLLECTION")
    selection = select_pilot(candidates, split, n=n, seed=seed)
    if not selection.items:
        raise PilotError("PILOT_NO_COLLECTION")
    if selection.shortfall:
        print(f"PILOT_SHORTFALL {selection.shortfall}", file=out)
    keys = [item.key for item in selection.items]
    initial_cost = provider_total(ledger_path, "gemini")
    reports = {}
    stopped = None
    for tag in RUN_TAGS:
        deps.store.enqueue_analysis(f"content_type@{tag}", selection.items)
        run = AnalysisRun(
            thinking_level=tag,
            run_tag=tag,
            purpose=f"pilot-{tag}",
            ledger_path=ledger_path,
            caps=caps,
            content_type_window_s=content_type_window_s,
            full_window_s=full_window_s,
            hook_window_max_s=3.0,
            interact=interact,
        )
        # Batch diagnostics contain creative provenance. The pilot prints only
        # aggregate status and artifact paths, keeping labeling output blind.
        report = run_analysis(
            deps.analysis._replace(store=deps.store),
            run=run,
            limit=len(keys),
            only_keys=keys,
            retry_failed=False,
            out=StringIO(),
        )
        reports[tag] = report
        if report.stopped:
            stopped = report.stopped
            break

    results = {}
    by_status = {}
    for tag in RUN_TAGS:
        by_status[tag] = {}
        for axis in AXES:
            kind = f"{axis}@{tag}"
            jobs = deps.store.get_job_results(kind, keys)
            results.update(((kind, job.key), job) for job in jobs)
            statuses = dict.fromkeys((status.value for status in JobStatus), 0)
            statuses.update(Counter(job.status.value for job in jobs))
            by_status[tag][axis] = statuses
    sheet = build_blind_sheet(
        selection.items,
        seed=seed,
        job_results=results,
        run_tags=RUN_TAGS,
        split_sha256=split_sha256,
        selection_seed=seed,
    )
    files = write_sheet_files(out_dir, sheet, codebook_rows(), instructions_text())
    report = PilotReport(
        selected=len(keys),
        shortfall=selection.shortfall,
        runs=reports,
        by_status=by_status,
        stopped=stopped,
        gemini_cost_usd=provider_total(ledger_path, "gemini") - initial_cost,
        files=files,
        split_sha256=split_sha256,
        elapsed_s=(deps.now() - started).total_seconds(),
    )
    if stopped:
        print(f"STOPPED {stopped}", file=out)
    print(report.model_dump_json(), file=out)
    print(LABELING_NOTICE, file=out)
    return report


def retry_pilot(
    deps: PilotDeps,
    *,
    tag: str,
    content_type_window_s: float,
    full_window_s: float,
    ledger_path: Path,
    caps: Mapping[str, float],
    interact: Callable[..., InteractionResult],
    out_dir: Path,
    out: TextIO,
) -> RetryReport:
    """Re-run only this tag's refresh-related content_type failures for the pilot items.

    The sheet and the existing key are never rewritten; the new results go to a
    supplement file next to them. Jobs already done are not touched.
    """
    key_items = read_key_items(out_dir)
    keys = list(key_items.values())
    kind = f"content_type@{tag}"
    failed = [
        job.key
        for job in deps.store.get_job_results(kind, keys)
        if job.status == JobStatus.failed and job.error_code in RETRY_CODES
    ]
    initial_cost = provider_total(ledger_path, "gemini")
    if not failed:
        print("RETRY_NOTHING", file=out)
        return RetryReport(
            tag=tag,
            retried=0,
            run=None,
            stopped=None,
            gemini_cost_usd=0.0,
            supplement=None,
        )
    # 이 종류의 작업은 시범만 쓰므로 종류 단위 되돌림이 시범 밖 소재에 닿지 않는다.
    deps.store.requeue_jobs(kind, RETRY_CODES)
    run = AnalysisRun(
        thinking_level=tag,
        run_tag=tag,
        purpose=f"pilot-{tag}-retry",
        ledger_path=ledger_path,
        caps=caps,
        content_type_window_s=content_type_window_s,
        full_window_s=full_window_s,
        hook_window_max_s=3.0,
        interact=interact,
    )
    report = run_analysis(
        deps.analysis._replace(store=deps.store),
        run=run,
        limit=len(failed),
        only_keys=failed,
        retry_failed=False,
        out=StringIO(),
    )
    retried = set(failed)
    results = {}
    for axis in AXES:
        for job in deps.store.get_job_results(f"{axis}@{tag}", failed):
            results[job.kind, job.key] = job
    items = {}
    for item_id, key in key_items.items():
        if key not in retried:
            continue
        axes = {}
        for axis in AXES:
            job = results.get((f"{axis}@{tag}", key))
            axes[axis] = (
                job.model_dump(
                    mode="json",
                    include={
                        "status",
                        "labels",
                        "error_code",
                        "model",
                        "thinking_level",
                        "prompt_version",
                    },
                )
                if job is not None
                else None
            )
        items[item_id] = {
            "source": key.source.value,
            "source_id": key.source_id,
            "runs": {tag: axes},
        }
    supplement = write_key_supplement(
        out_dir,
        {
            "run_tag": tag,
            "generated_at": deps.now().isoformat(),
            "note": "pilot_key.json은 바뀌지 않았다. 이 파일의 항목이 같은 item_id의 해당 실행 결과를 보충한다.",
            "items": items,
        },
    )
    if report.stopped:
        print(f"STOPPED {report.stopped}", file=out)
    result = RetryReport(
        tag=tag,
        retried=len(failed),
        run=report,
        stopped=report.stopped,
        gemini_cost_usd=provider_total(ledger_path, "gemini") - initial_cost,
        supplement=supplement,
    )
    print(result.model_dump_json(), file=out)
    return result


def _live_deps(*, environ, env_file, stack: ExitStack) -> PilotDeps:
    """Assemble existing SDK boundaries only after the preflight succeeds."""
    accounts = {
        account.username: account
        for account in load_instagram_accounts(Path("config/sources.yaml"))
    }
    gemini_key = require_setting("GEMINI_API_KEY", environ=environ, env_file=env_file)
    refresh = partial(
        refresh_media_urls,
        with_retries(instagram_httpx_get),
        require_setting("INSTAGRAM_ACCESS_TOKEN", environ=environ, env_file=env_file),
        require_setting("INSTAGRAM_USER_ID", environ=environ, env_file=env_file),
        base_url=get_setting(
            "BEAUTYADS_INSTAGRAM_BASE_URL",
            DEFAULT_INSTAGRAM_BASE_URL,
            environ=environ,
            env_file=env_file,
        ),
    )

    def now():
        return datetime.now(UTC)

    def refresh_account(account, wanted_ids):
        return refresh(account, wanted_ids, now=now())

    def rerefresh(creative):
        account = accounts.get(creative.account)
        if account is None:
            return None
        return lambda: refresh_account(account, {creative.source_id}).urls.get(
            creative.source_id
        )

    connection = connect(postgres_dsn(environ=environ, env_file=env_file))
    stack.callback(connection.close)
    apply_migrations(connection)
    store = PostgresCreativeStore(connection)
    analysis = AnalysisDeps(
        store=store,
        media=MediaDeps(
            download=partial(download_media, httpx_media_get),
            upload=partial(upload_video, api_key=gemini_key),
            wait=partial(wait_processed, api_key=gemini_key),
            delete=partial(delete_file, api_key=gemini_key),
        ),
        plans=partial(
            prepare_instagram_plans, accounts=accounts, refresh=refresh_account
        ),
        rerefresh=rerefresh,
        sleep=time.sleep,
        now=now,
    )
    return PilotDeps(analysis, store, now)


def _n(value: str) -> int:
    try:
        number = int(value)
        if 1 <= number <= 40:
            return number
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("n must be 1..40")


def _window(value: str) -> float:
    try:
        seconds = float(value)
        if isfinite(seconds) and seconds > 0:
            return seconds
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("window must be finite and positive")


def main(
    argv: Sequence[str] | None = None,
    *,
    environ=None,
    out: TextIO | None = None,
    docker_check=docker_running,
    tcp_check=tcp_reachable,
    deps_factory: Callable[[], PilotDeps] | None = None,
) -> int:
    out = sys.stdout if out is None else out
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=_n, default=20)
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--content-type-window-s", type=_window, default=60.0)
    parser.add_argument("--full-window-s", type=_window, default=60.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--retry-missing",
        action="store_true",
        help="시트·키를 다시 쓰지 않고 이 실행 태그의 MEDIA_URL_MISSING·MEDIA_REFRESH_STOPPED 실패만 재시도",
    )
    parser.add_argument("--retry-tag", choices=RUN_TAGS, default="default")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    try:
        _output_paths(args.out_dir)
    except SheetError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    if args.dry_run:
        preview = estimate(
            n=args.n,
            runs=len(RUN_TAGS),
            content_type_window_s=args.content_type_window_s,
            full_window_s=args.full_window_s,
        )
        preview["assumptions"] = (
            "콘텐츠 유형만~세 축 전부, 축당 스키마 재요청 1회는 별도 상한; "
            "영상 입력만 91토큰/초, 구간 상한 전체 사용 가정(짧은 영상은 더 적음); "
            "프롬프트·캡션·출력·thought 토큰과 전송 재시도 제외. "
            "비용은 원장에 기록되며 시범 뒤 `cost-recalc`가 계산한다"
        )
        print("ESTIMATE " + json.dumps(preview, ensure_ascii=False), file=out)
        return 0
    env_file = DEFAULT_ENV_FILE if environ is None else None
    try:
        settings = load_settings(environ=environ, env_file=env_file)
        problems = preflight_pilot(
            environ=environ,
            env_file=env_file,
            ledger_path=settings.ledger_path,
            caps=settings.provider_caps_usd,
            docker_check=docker_check,
            tcp_check=tcp_check,
        )
        if problems:
            for problem in problems:
                print(f"PREFLIGHT_FAILED {problem.code}", file=out)
            return 2
        if args.retry_missing:
            with ExitStack() as stack:
                deps = (
                    deps_factory()
                    if deps_factory is not None
                    else _live_deps(environ=environ, env_file=env_file, stack=stack)
                )
                retry = retry_pilot(
                    deps,
                    tag=args.retry_tag,
                    content_type_window_s=args.content_type_window_s,
                    full_window_s=args.full_window_s,
                    ledger_path=settings.ledger_path,
                    caps=settings.provider_caps_usd,
                    interact=partial(
                        gemini_interact,
                        api_key=require_setting(
                            "GEMINI_API_KEY", environ=environ, env_file=env_file
                        ),
                    ),
                    out_dir=args.out_dir,
                    out=out,
                )
            return 3 if retry.stopped else 0
        try:
            split = load_brand_split(SPLIT_PATH)
            split_hash = sha256_of(SPLIT_PATH)
        except (SplitError, OSError):
            raise PilotError("PILOT_SPLIT_FILE_INVALID") from None
        with ExitStack() as stack:
            deps = (
                deps_factory()
                if deps_factory is not None
                else _live_deps(environ=environ, env_file=env_file, stack=stack)
            )
            report = run_pilot(
                deps,
                n=args.n,
                seed=args.seed,
                content_type_window_s=args.content_type_window_s,
                full_window_s=args.full_window_s,
                split=split,
                split_sha256=split_hash,
                ledger_path=settings.ledger_path,
                caps=settings.provider_caps_usd,
                interact=partial(
                    gemini_interact,
                    api_key=require_setting(
                        "GEMINI_API_KEY", environ=environ, env_file=env_file
                    ),
                ),
                out_dir=args.out_dir,
                out=out,
            )
    except SettingError as exc:
        print(f"PREFLIGHT_FAILED {exc.code}:{exc.name}", file=out)
        return 2
    except (StoreConnectError, PilotError, SheetError) as exc:
        print(f"PREFLIGHT_FAILED {exc.code}", file=out)
        return 2
    except ConfigError as exc:
        print(f"PREFLIGHT_FAILED {exc}", file=out)
        return 2
    return 3 if report.stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
