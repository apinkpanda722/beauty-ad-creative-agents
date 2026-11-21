# Step 1: tokens-shell

## 설계 검토 기록

**목적**: 7c의 바탕을 만든다. 제품 이름 상수, 디자인 토큰, Pretendard, 앱 셸(좌측 내비 5개)과 화면 전환, 그리고 `Chat`이 갖고 있던 요청 세션 상태를 위로 올린다. 이 step이 끝나도 기존 화면(대화·전체 스키마)은 **광고 기획·지식 그래프 화면의 임시 본문**으로 그대로 보인다(교체는 다음 step들).

**코드를 열어 확인한 사실**: `web/app/page.tsx`가 탭 2개와 `Chat`·`SchemaView`를 그린다. `Chat.tsx`가 `useReducer(reducer, initialState)`·`run()`(SSE)·`start()`를 갖는다. `reducer.ts`의 `State/Action/Turn` 타입과 `initialState`는 그대로 쓴다. `web/app/layout.tsx`의 `metadata.title`은 `"Beauty Ad Creative Agents"` 문자열이다.

**설계 결정**
- `web/lib/brand.ts`: `export const BRAND = { name: "Gyeol Studio", nameKo: "결 스튜디오" } as const;`. `layout.tsx`의 title과 셸 로고는 이 상수를 import한다.
- `web/app/tokens.css`(CSS 변수만): 색 `--gs-accent #0F766E`, `--gs-accent-weak #F0FDFA`, `--gs-bg #FFFFFF`, `--gs-surface #F8FAFC`, `--gs-border #E2E8F0`, `--gs-text #0F172A`, `--gs-text-muted #475569`, `--gs-danger #B91C1C`, `--gs-warn`, 간격(4px 배수), 반경, 그림자, 글자 크기 단계. 라이트 전용(`color-scheme: light`, 다크 미디어 쿼리 없음).
- Pretendard: `pnpm add pretendard@1.3.9 --save-exact`로 설치(이 step만 허용). `package.json`에는 `"pretendard": "1.3.9"`(범위 기호 `^`·`~` 없음, `tests/test_web_contract.py::test_web_dependencies_are_pinned`가 이를 단언한다)로 들어가야 한다. 가변 woff2 한 파일(`dist/web/variable/woff2/PretendardVariable.woff2` 예상, **설치 후 실제 경로를 확인**하고 없으면 `blocked`)을 `next/font/local`로 읽어 `--font-pretendard`에 연결하고 `font-family: var(--font-pretendard), system-ui, sans-serif`. 설치된 버전을 summary에 적는다.
- 앱 셸(`web/components/shell/AppShell.tsx`, `Sidebar.tsx`, `TopBar.tsx`): 좌측 240px 내비 5개(`광고 기획`·`근거 소재`·`지식 그래프`·`실행 기록`·`저장한 기획`), 상단 바에 로고와 작업 공간 선택(`WorkspacePicker` 자리), 활성 항목은 좌측 3px 틸 막대 + 틸 글자. 880px 미만에서 내비는 상단 가로 스크롤. 화면 전환은 **URL 라우트가 아닌 클라이언트 상태**(`view: "plan" | "evidence" | "graph" | "history" | "saved"`)이고 접근성은 `nav` + `aria-current="page"`.
- 세션 상태: `web/lib/session.tsx`에 `SessionProvider`(reducer 상태, `start`, `send`, `cancel`, `retry`, SSE 실행 `run`)와 `useSession()`. 로직은 `Chat.tsx`의 `run`·`start`를 **그대로 옮긴다**(동작 변경 금지). `Chat.tsx`는 `useSession()`을 쓰도록 최소 수정한다. 화면 전환 중에도 진행 중 요청·결과가 유지되어야 한다.
- 이 step에서 아직 없는 화면(근거 소재·실행 기록·저장한 기획)의 내비 항목은 **숨기지 않고 "준비 중" 본문**을 보여 준다(마지막 step이 컷 결과에 따라 정리). 광고 기획 = 기존 `Chat`, 지식 그래프 = 기존 `SchemaView`.
- 대비 가드: 토큰 쌍(본문/배경, 보조 글자/배경, 틸/흰색, 위험/흰색)의 WCAG 대비 비율을 계산해 4.5 이상을 단언하는 테스트(`contrast.test.ts`, 계산식은 테스트 안에 둔다). 확인된 값: 틸/흰색 5.47, 본문/흰색 17.85, 보조/흰색 7.58, 위험/흰색 6.47.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `BRAND` | `web/lib/brand.ts` | `layout.tsx`, `TopBar.tsx`, `brand.test.ts` |
| 디자인 토큰 | `web/app/tokens.css` | `shell.css`, 이후 모든 step의 CSS, `contrast.test.ts` |
| `SessionProvider`/`useSession` | `web/lib/session.tsx` | `Chat.tsx`(이후 step 3이 교체), 이후 `history`·`evidence` 화면 |
| 활성 화면 `view` | `AppShell.tsx` | `page.tsx`, `Sidebar.tsx` |

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/app/page.tsx`, `/web/app/layout.tsx`, `/web/app/globals.css`, `/web/components/Chat.tsx`, `/web/lib/reducer.ts`, `/web/lib/api.ts`, `/web/components/WorkspacePicker.tsx`, `/web/components/SchemaView.tsx`
- `/web/tests/chat.test.tsx`, `/web/tests/smoke.test.tsx`(옛 구조 단언 확인), `/web/package.json`, `/web/eslint.config.mjs`, `/tests/test_web_contract.py`, `/tests/test_ci_workflow.py`(둘 다 수정 없이 통과해야 한다)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/brand.ts`, `web/lib/session.tsx`, `web/app/layout.tsx`, `web/app/page.tsx`, `web/app/tokens.css`, `web/app/shell.css`, `web/components/shell/*`, `web/components/Chat.tsx`(세션 이동만), `web/package.json`, `web/pnpm-lock.yaml`(pretendard만), `web/tests/brand.test.ts`, `web/tests/contrast.test.ts`, `web/tests/shell.test.tsx`, `web/tests/chat.test.tsx`·`web/tests/smoke.test.tsx`(렌더 헬퍼 추가만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/brand.ts`, `web/lib/session.tsx`, `web/app/layout.tsx`, `web/app/page.tsx`, `web/app/tokens.css`, `web/app/shell.css`, `web/components/shell/*`, `web/components/Chat.tsx`(세션 이동만), `web/package.json`, `web/pnpm-lock.yaml`(pretendard만), `web/tests/brand.test.ts`, `web/tests/contrast.test.ts`, `web/tests/shell.test.tsx`, `web/tests/chat.test.tsx`·`web/tests/smoke.test.tsx`(렌더 헬퍼 추가만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/brand.ts`, `web/app/tokens.css`, `web/app/shell.css`, `web/app/layout.tsx`(title은 `BRAND`, 글꼴 연결), `web/app/page.tsx`(`SessionProvider` + `AppShell`).
**2.** `web/components/shell/` 3개와 `web/lib/session.tsx`. `Chat.tsx`는 reducer·`run`을 `useSession()`으로 옮기는 최소 수정만 한다(JSX 구조는 이 step에서 바꾸지 않는다).
**3.** `pretendard@1.3.9` 설치와 폰트 연결. `globals.css`는 건드리지 않는다(옛 규칙은 step 9에서 제거).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/brand.test.ts`: (1) `BRAND` 값이 정확히 `Gyeol Studio`·`결 스튜디오`, (2) `web/app`·`web/components`·`web/lib` 소스 파일에서 이 두 문자열 리터럴이 `web/lib/brand.ts` 밖에 없다(소스 파일을 읽어 검사, 파일 0개면 실패).
- `web/tests/contrast.test.ts`: 위 토큰 쌍의 비율이 4.5 이상이고 `tokens.css`에 정의된 값과 테스트 상수가 같다(CSS를 읽어 파싱, 쌍 0개면 실패).
- `web/tests/shell.test.tsx`: (3) 내비 항목이 정확히 5개이고 순서가 `광고 기획·근거 소재·지식 그래프·실행 기록·저장한 기획`, (4) 항목 클릭 시 `aria-current="page"`가 바뀌고 본문이 바뀐다, (5) **광고 기획에서 요청을 보내 진행 중인 상태로 다른 화면으로 이동했다가 돌아와도 같은 턴이 유지된다**(가짜 `postChatAsk`), (6) 라이트 전용: `tokens.css`에 `prefers-color-scheme: dark`가 없다.
- 기존 `chat.test.tsx`·`smoke.test.tsx`의 행동 단언은 그대로 통과해야 한다(`Chat`이 `SessionProvider` 안에서 렌더되도록 테스트 헬퍼만 추가 가능, 단언 변경 금지).
- 해시 시드·집합·딕셔너리 순회 순서에 기대는 새 단언을 만들지 마라(리스트와 명시적 순서로 단언).

## Acceptance Criteria

```bash
make verify   # lint + pytest + pnpm lint·typecheck·test 통과
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

- `docs/EVAL.md`의 동결 기준·`docs/results/`·사전 등록과 동결 가드 테스트(`tests/test_prereg.py`·`tests/test_freeze_guard.py`)·`src/beautyads/agents/`·`llm/`·`analysis/`·`checks/`의 프롬프트와 상수를 수정하지 마라. 이유: 동결 값은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL).
- 기존 단언을 약화·삭제하지 마라. 컴포넌트 구조가 바뀌어 교체해야 하는 웹 테스트는 **같은 행동을 같은 엄격도로** 새 구조에서 단언하고, 완료 보고(summary)에 "교체한 단언 → 새 단언" 대응을 적어라. 이유: 가드를 약화하면 회귀를 못 잡는다.
- `pnpm add`·`uv add`·그 밖의 패키지 설치와 `package.json`·`pnpm-lock.yaml` 수정을 하지 마라 (단, 이 step에서 `pnpm add pretendard@1.3.9 --save-exact` 한 가지만 허용). 이유: 이번 phase의 새 패키지는 승인된 `pretendard@1.3.9` 하나뿐이다.
- 모델·유료 API를 호출하거나 `make live-slice`, `make live-collect`, `make live-pilot`, `make live-analyze`, `make live-tiktok`, `make live-tiktok-analyze`, `make live-graph`, `make live-products`, `make live-ingredient-catalog`, `make live-cert-recheck`, `make live-cq`, `make live-product-identify`, `make live-agent`, `make live-agents`, `make live-evidence`, `make live-compare`, `make live-evalset`, `make live-e2e5`, `make live-e3`, `make live-isolation`, `make serve`, `make demo-up`, `make db-up`, `make obs-up`을 실행하지 마라. `.env`를 열거나 출력하지 마라. 테스트는 합성 데이터와 가짜 환경만 쓴다. 이유: 실제 호출과 사람이 보는 확인은 사용자가 한다(AGENTS.md CRITICAL).
- 제품 이름 문자열(`Gyeol Studio`, `결 스튜디오`)을 `web/lib/brand.ts` 밖에 리터럴로 쓰지 마라(테스트 파일 제외 불가: 가드 테스트가 `web/` 소스 전체를 검사한다). 이유: 이름은 한 곳에서만 바꾼다(확정 설계 조건 1).
- `web/components/Chat.tsx`·`web/lib/reducer.ts`의 **동작**(요청 실행, 중단, 재시도, 확인 질문 제출)을 바꾸지 마라. 옮기기만 한다. 이유: 이 step의 목적은 구조 이동이고 행동 변경은 step 3이 정리한다.
- `web/app/globals.css`의 옛 규칙을 지우거나 수정하지 마라. 이유: 옛 화면이 아직 쓴다(step 9에서 정리).
