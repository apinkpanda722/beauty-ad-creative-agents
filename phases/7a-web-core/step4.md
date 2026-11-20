# Step 4: web-scaffold

## 설계 검토 기록

**배경(P7 설계 승인)**: `web/`은 아직 없다(`pyproject.toml`의 ruff `extend-exclude`와 `.gitignore`의 `node_modules/`·`.next/`만 미리 준비돼 있다). 이 step은 **Next.js 골격, SSE 파서, 서버 이벤트 타입, API 호출 함수, `make verify`의 pnpm 단계**만 만든다. 화면 컴포넌트는 step 5~7이다.

**로컬 환경(2026-11-20 확인)**: node v26.4.0, pnpm 12.8.1. 설치 도구는 더 필요 없다.

**`pnpm install`의 네트워크(확인함)**: `scripts/execute.py`가 `codex exec --sandbox workspace-write`에 `-c sandbox_workspace_write.network_access=true`를 넘긴다(393행 부근). 그래서 step 안에서 레지스트리 접속이 막히지 않는다고 보고 **이 step이 직접 `make web-install`을 실행하는 설계를 유지한다**. 그래도 `blocked`(네트워크 차단·레지스트리 오류)가 나면 설계를 바꾼다: 사용자가 승인한 고정 버전으로 `pnpm install`을 **저장소 작업자 셸에서 직접** 실행해 `web/package.json`·`pnpm-lock.yaml`·`node_modules`를 만들어 두고, 이 step은 그 상태를 입력으로 삼아 나머지(설정·타입·SSE·테스트·Makefile)만 한다(고정 버전 외 패키지는 추가하지 않는다). 그 경우 이 기록에 바꾼 내용을 적는다.

**승인된 패키지와 고정 버전** (정확한 버전을 고정하고 `^`·`~`를 쓰지 않는다. 설치 가능한 최신값은 `npm view`로 2026-11-20에 조회했다):

| 패키지 | 버전 | 이유 |
|---|---|---|
| `next` | 16.4.6 | 화면 프레임워크(App Router) |
| `react`, `react-dom` | 19.3.1 | 렌더링 |
| `typescript` | 7.0.2 (조정 허용) | 타입 검사 |
| `eslint` | 10.15.0 (조정 허용) | 린트 |
| `eslint-config-next` | 16.4.6 (Next와 같은 버전) | Next 규칙(평면 설정) |
| `vitest` | 5.1.1 | 테스트 실행기 |
| `@testing-library/react` | 16.3.3 | 컴포넌트 테스트 |
| `jsdom` | 31.0.1 이하 호환 최신 | 테스트 DOM(요구 node `^22.22.2 \|\| ^24.15.0 \|\| >=26`) |
| `cytoscape` | 3.35.0 | 그래프 화면(step 7에서 사용, 자체 타입 `index.d.ts` 포함). 이 step에서는 설치만 한다 |

**동반 패키지(승인 목록의 peer·타입이 요구하는 것. **2026-11-20 사용자·조언 세션이 승인함**, 추가 확인 없이 설치한다)**: `vite`(`vitest@5.1.1`의 필수 peer: `^6.4.0 || ^7.0.0 || ^8.0.0`), `@testing-library/dom`(`@testing-library/react@16.3.3`의 peer `^10.0.0`), `@types/node`(`>=24`), `@types/react`·`@types/react-dom`(`^19`). **이 다섯 개 외에는 설치하지 않는다**(필요하면 `blocked`로 보고한다). `typescript 7.0.2`·`eslint 10.15.0`과 Next 16.4.6의 호환은 확인되지 않았다: 설치나 `tsc`·`eslint`가 호환 문제로 실패하면 **호환되는 가장 높은 버전으로 낮추고** 무엇을 왜 바꿨는지 `summary`에 적는다. `pnpm`의 빌드 스크립트 승인이 필요한 패키지가 나오면 그 이름만 `onlyBuiltDependencies`로 허용하고 `summary`에 적는다.

**서버 계약(읽어서 맞춘다)**: step 1~3 이후의 SSE 이벤트와 화면 명령은 `api/sse.py`(`EventName`), `api/ask.py`, `api/ask_view.py`, `domain/supervisor.py`(`ClaimChoice`)에 있다. TypeScript 타입은 이 코드와 `docs/ARCHITECTURE.md`의 이벤트 절에서 읽어 만든다(추측 금지). 이벤트: `step{agent,phase,status}`, `tool_start{name,kind}`, `token{text,display_text?}`, `ui_command{kind,data}`, `error{code,detail?,error_code?}`, `needs_clarification{reason,requested_claim,requested_label,available[{claim,label}],text,options[{id,label}]}`, `efficacy_unavailable{reason,text}`. 화면 명령 `kind`: `show_evidence_cards`, `show_plan`, `show_distribution`, `show_graph_fragment`, `show_aggregates`, `show_cost`.

**연결 방식**: 브라우저는 같은 출처의 `/api/*`만 부르고 Next `rewrites`가 `http://127.0.0.1:8000/*`(서버 기본 포트)로 보낸다. CORS가 필요 없고 `X-Thread-Id` 응답 헤더가 그대로 보인다. SSE가 프록시에서 버퍼링되지 않게 `compress: false`로 둔다(실측은 사용자가 서버를 띄운 뒤에 한다, 이 step에서는 못 한다).

**`make verify`에 넣는 줄**: `uv run pytest -q` 뒤에 아래 두 줄을 더한다. `pnpm install`은 레지스트리 네트워크가 필요하므로 verify에 넣지 않는다(AGENTS.md: verify는 키·네트워크·실제 서비스 없이 통과). 설치는 별도 타깃 `make web-install`이다.
```
	@test -d web/node_modules || { echo "WEB_DEPS_MISSING: make web-install"; exit 1; }
	cd web && pnpm lint && pnpm typecheck && pnpm test
```
**기존 단언과의 충돌 점검(`rg -n "verify:" tests/`·`step_file_checks` 소비자 경고로 확인)**: `tests/test_pilot.py::test_makefile_adds_live_pilot_without_changing_verify`가 `verify` 본문을 **세 줄 정확 일치**로 단언한다 → 위 두 줄을 더한 **다섯 줄 정확 일치로 갱신**한다(`==` 유지, 부분 문자열·길이 비교로 바꾸지 않음). 그 밖의 `tests/test_compose.py::test_verify_remains_offline`(줄에 `db-`·`graph-`·`live-` 포함 금지), `test_clarify_demo.py`(`demo-`), `test_fetch_design_font.py`(`fetch-`), `test_collect.py`·`test_collect_tiktok.py`·`test_evidence_check.py`(`live-`), `test_cost_recalc.py`(`cost-recalc`), `test_e1_scorer.py`(`e1-score`)는 **verify 본문에 그 부분 문자열이 없으면** 통과한다: 새 줄에 `db-`·`graph-`·`live-`·`demo-`·`fetch-`·`cost-recalc`·`e1-score`가 들어가지 않게 쓴다(`web-install`이라는 타깃 이름도 verify 본문에는 쓰지 않는다, 메시지 안의 `make web-install`은 `db-`·`graph-`와 겹치지 않는다). 새 타깃은 별도 `.PHONY: web-install` 블록으로 더하고 맨 윗줄 `.PHONY:` 목록·기존 줄은 바꾸지 않는다. `Makefile` 주석 "web/ 골격과 pnpm 단계는 M3 phase의 step 0에서 추가한다."는 사실과 달라지므로 그 한 줄만 고친다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 서버 이벤트·화면 명령 타입 | `web/lib/types.ts` | `web/lib/sse.ts`·`api.ts`·step 5~7 컴포넌트, `tests/test_web_contract.py`(드리프트 검사) |
| SSE 프레임 해석 | `web/lib/sse.ts` | `web/lib/api.ts`, step 5 reducer |
| API 호출 | `web/lib/api.ts` | step 5~7 |
| `verify` pnpm 줄 | `Makefile` | `tests/test_pilot.py`(갱신), 하네스(`execute.py`·Stop hook) |

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(기술 스택·명령어 절을 이 step에서 고친다), `/docs/ARCHITECTURE.md`(스트리밍 이벤트와 화면 명령, 실행 환경), `/docs/PRD.md`(시연과 포트폴리오 산출물)
- `/src/beautyads/api/sse.py`, `/src/beautyads/api/ask.py`, `/src/beautyads/api/ask_view.py`, `/src/beautyads/api/graph_routes.py`, `/src/beautyads/domain/supervisor.py`(`ClaimChoice`, `ClarifyOption`), `/src/beautyads/api/chat_client.py`(`parse_sse`: 파이썬 쪽 SSE 해석, 같은 규칙을 따른다)
- `/Makefile`, `/pyproject.toml`(ruff `extend-exclude`), `/.gitignore`
- `/tests/test_pilot.py`(`test_makefile_adds_live_pilot_without_changing_verify`), `/tests/test_compose.py`(`test_verify_remains_offline`), `/tests/test_api_chat_client.py`(SSE 파싱 케이스: CRLF·여러 줄 data)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/`, `Makefile`, `AGENTS.md`, `tests/test_pilot.py`, `tests/test_web_contract.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `web/`, `Makefile`, `AGENTS.md`, `tests/test_pilot.py`, `tests/test_web_contract.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `web/` 골격** (`pnpm`, App Router, TypeScript, 소스는 `web/` 바로 아래에 `app/`·`components/`·`lib/`·`tests/`):
- `web/package.json`: `"private": true`, `"packageManager": "pnpm@12.8.1"`, 스크립트 `dev`(`next dev`), `build`(`next build`), `start`(`next start`), `lint`(`eslint .`; **`next lint`는 쓰지 않는다**), `typecheck`(`tsc --noEmit`), `test`(`vitest run`). 의존성은 위 표의 정확한 버전.
- `web/pnpm-lock.yaml`(커밋 대상), `web/tsconfig.json`(strict), `web/next.config.ts`(`compress: false`, `rewrites()`가 `/api/:path*` → `${BEAUTYADS_API_ORIGIN ?? "http://127.0.0.1:8000"}/:path*`), `web/eslint.config.mjs`(평면 설정, `eslint-config-next`), `web/vitest.config.ts`(`environment: "jsdom"`, `include: ["tests/**/*.test.{ts,tsx}"]`, TSX는 `esbuild: { jsx: "automatic" }`로 처리하고 `@vitejs/plugin-react`는 쓰지 않는다).
- `web/app/layout.tsx`·`web/app/page.tsx`(제목만 있는 자리 표시 화면, step 5가 교체)·`web/app/globals.css`(최소 스타일, 외부 폰트·CDN 없음).
- `web/lib/types.ts`: 위 이벤트·화면 명령·`ClaimChoice`(`mode: "selected" | "keep_requested" | "none"`, `claims: string[]`, `requested_claim: string | null`)·`ApiErrorBody`의 **판별 유니언 타입**. 서버 코드에서 읽은 키만 쓴다(예: `show_plan`의 키는 `ask_view.py`의 `data = {...}`에서 읽는다).
- `web/lib/sse.ts`: `export async function* parseSseStream(body: ReadableStream<Uint8Array>): AsyncGenerator<{ event: string; data: Record<string, unknown> }>`. `TextDecoder(stream: true)`로 **청크 경계가 멀티바이트 문자 가운데여도** 깨지지 않게 하고, `\n`·`\r\n` 줄 끝, 한 프레임의 여러 `data:` 줄(`\n`으로 이음), `event:`와 `data:` 사이 공백, 마지막 빈 줄 없이 끝난 프레임을 처리한다. `data`가 JSON 객체가 아니면 그 프레임을 건너뛴다(`api/chat_client.py` `parse_sse`와 같은 규칙).
- `web/lib/api.ts`: `export class ApiError extends Error { status: number; code: string | null }`, `export async function postAsk(args: { tenantId: string; message: string; threadId?: string; claimChoice?: ClaimChoice; withImage?: boolean; signal?: AbortSignal }): Promise<{ threadId: string | null; events: AsyncGenerator<SseFrame> }>`. `POST /api/ask`, 헤더 `Content-Type: application/json`·`X-Tenant-Id`, 본문 `{ message, with_image, thread_id?, claim_choice? }`(**없는 칸은 키를 빼고 `null`을 보내지 않는다**, 서버 `AskRequest`가 `extra="forbid"`). 응답이 200이 아니면 본문의 `detail`이 문자열일 때만 `code`로 쓰고(`detail`이 목록이거나 JSON이 아니면 `code: null`) `ApiError`를 던진다. 성공이면 `X-Thread-Id` 헤더와 `parseSseStream` 결과를 돌려준다.
- `web/tests/`: `sse.test.ts`(청크 분할·한글 멀티바이트 분할·CRLF·여러 `data:` 줄·객체가 아닌 JSON 건너뜀·끝 프레임), `api.test.ts`(가짜 `fetch`로 URL·헤더·본문 정확 일치, `null` 키 없음, 비-200 `ApiError`의 `status`·`code`, `detail` 목록이면 `code === null`, `X-Thread-Id` 전달), `smoke.test.tsx`(`@testing-library/react`로 `app/page.tsx`가 렌더되는지 하나).

**2. `Makefile`**: 위 "verify에 넣는 줄"을 `verify` 레시피 끝에 더하고, 파일 끝에 `.PHONY: web-install` / `web-install:` / `\tcd web && pnpm install --frozen-lockfile`을 더한다. 주석 한 줄만 고친다.

**3. `AGENTS.md`**: "기술 스택"의 "웹(Next.js)은 M3 phase에서 추가한다. 지금은 `web/`이 없다." 한 줄을 "웹은 `web/`(Next.js 16, pnpm, TypeScript, vitest). 의존성 설치는 `make web-install`"로 바꾸고, "명령어" 절에 `make web-install`·`make serve` 두 줄만 더한다. 다른 줄은 바꾸지 않는다.

**4. 테스트**
- `tests/test_pilot.py`: `test_makefile_adds_live_pilot_without_changing_verify`의 `verify` 정확 일치 기대값을 위 다섯 줄로 **갱신만** 한다(다른 단언 불변).
- `tests/test_web_contract.py`(새): (1) `api/sse.py`의 `EventName`(`typing.get_args`)의 모든 이름이 `web/lib/types.ts`에 있고, 거꾸로 `types.ts`의 이벤트 이름 목록에 서버에 없는 것이 없다. (2) `api/ask_view.py`에서 정규식으로 찾은 `"kind": "show_..."` 값 전부가 `types.ts`에 있고 그 반대도 같다. 검사한 이름 수가 0이면 실패(B-FP-069). (3) `web/package.json`의 `dependencies`·`devDependencies` 버전에 `^`·`~`·`latest`·`*`가 없다. (4) `Makefile`의 `verify` 본문에 `pnpm install`이 없고 `WEB_DEPS_MISSING`과 `pnpm lint`·`pnpm typecheck`·`pnpm test`가 있다. (5) `web/pnpm-lock.yaml`이 있다.

## Acceptance Criteria

```bash
make web-install   # 승인된 패키지만 설치(네트워크 필요, 이 step에서만 허용)
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함, 승인 목록에서 조정한 것은 이유까지)"`
   - 해결할 수 없는 실패 → `"status": "error"`, `"reason": "구체적 에러 내용"`
   - 사용자 개입 필요 (API 키, 외부 인증, 수동 설정 등) → `"status": "blocked"`, `"reason": "구체적 사유"` 후 즉시 중단


## 공통 금지사항

<!-- common-block:start -->
- **선점검**: 코드를 쓰기 전에 이 파일의 작업 지시·금지사항·"수정할 파일" 목록을 서로 대조한다. 충돌(하나가 요구한 것을 다른 것이 금지함, 수정할 파일 목록 밖 파일의 수정이 필요함, 계층 경계 위반)이 있으면 코드를 쓰지 않고 즉시 `blocked`로 보고한다. reason에는 충돌하는 두 문장을 그대로 인용한다. 충돌이 없으면 진행한다.
- **실제 서비스**: 실제 서비스(YouTube·Instagram·TikTok·식약처 공공 API·브랜드 공식몰·Gemini·OpenAI·Anthropic·LiteLLM·Langfuse·Neo4j·PostgreSQL·외부 API)에 접속하는 코드는 작성할 수 있다. step 안에서 그 코드를 실행하거나 그 코드에 접속하는 테스트를 만들지 않는다. 테스트는 가짜 환경(가짜 실행기·로컬 루프백·`tests/fixtures/contracts/`의 응답 원본에서 만든 픽스처)으로만 한다.
- **계층 경계**: `AGENTS.md`의 계층 경계 표와 `tests/test_architecture.py`를 따른다. 가드 테스트를 약화하지 않는다.
- **읽기 전용**: `.claude/`, `docs/EVAL.md`의 동결된 판정 기준, `docs/results/`의 사전 등록 파일, `scripts/`, `phases/`, `tests/fixtures/contracts/`의 응답 원본은 읽기만 한다(이 step의 "수정할 파일"에 있는 것만 예외). 기존 테스트의 단언을 약화하지 않는다.
- **비밀 값**: `.env`를 열거나 출력하지 않는다. 토큰·키·Authorization 헤더를 코드·테스트·문서·로그·trace에 남기지 않는다.
<!-- common-block:end -->

## 이 step의 금지사항

- 승인 목록과 동반 패키지 다섯 개 외의 패키지를 설치하지 마라. `^`·`~`·`latest`로 버전을 두지 마라. 이유: 패키지 설치는 승인한 것만 허용하고 설치된 버전은 완료 보고에 적는다(AGENTS.md CRITICAL). 조정한 버전은 이유까지 `summary`에 적는다.
- `pnpm install`을 `make verify`에 넣지 마라. `next lint`·`next telemetry`·외부 CDN·구글 폰트를 쓰지 마라. 이유: verify는 네트워크 없이 통과해야 한다(AGENTS.md CRITICAL). 린트는 `eslint .`다.
- 서버 응답의 키를 추측해 타입을 만들지 마라(`ask_view.py`·`ask.py`·`sse.py`에서 읽은 것만). 이유: 외부 응답은 실측된 형태만 전제한다(AGENTS.md CRITICAL, FP-C01). 서버와의 드리프트는 `tests/test_web_contract.py`가 막는다.
- 요청 본문에 `null` 키를 넣지 마라(`thread_id: null` 등). 이유: 서버 `AskRequest`는 `extra="forbid"`이고 `thread_id`는 문자열이 아니면 422다(`api/ask.py`).
- `tests/test_pilot.py`의 다른 단언·`Makefile`의 기존 줄·`src/`를 수정하지 마라. 서버(`make serve`)·`pnpm dev`·`pnpm build`를 서버 연결이 필요한 방식으로 실행하지 마라. 이유: 이 step은 골격이고, 서버 실행은 사용자가 한다(A-FP-040). 테스트는 가짜 `fetch`와 가짜 스트림만 쓴다.
