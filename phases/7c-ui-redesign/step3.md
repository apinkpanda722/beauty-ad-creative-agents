# Step 3: plan-main

## 설계 검토 기록

**목적**: 메인 화면(광고 기획)을 전면 교체한다: 입력 폼, 진행창(애니메이션), 확인 질문 정리, 예시 칩 제거. 결과 렌더는 step 4가 바꾸므로 이 step은 기존 `CommandSlot` 출력을 그대로 아래에 연결한다.

**코드를 열어 확인한 사실(문제의 원인)**
1. **"완료 완료"**: `web/components/StepBar.tsx`가 모든 단계에 `<span>{stage.label}</span> <small>{labels[stage.status]}</small>`를 그리고, 마지막 단계 `complete`의 label이 `"완료"`라 완료 상태에서 "완료 완료"가 된다(`web/lib/stages.ts`의 `complete` 단계).
2. **해결된 확인 질문**: `reducer.ts`의 `append`가 `needs_choice` 턴을 `done`으로 바꾸고, `TurnView.tsx`는 `turn.clarification`이 있으면 `ClarifyCard`를 계속 그린다(버튼 `disabled`만 바뀜).
3. **예시 칩**: `Chat.tsx`의 `.examples` 블록과 `web/lib/examples.ts`.

**설계 결정**
- 새 `web/components/plan/`: `PlanPage`(입력 + 턴 목록), `Composer`, `ProgressTracker`, `TurnCard`, `ClarifySummary`.
- **ProgressTracker**: 가로 스테퍼(원 + 연결선 + 라벨). 상태 표시는 색과 아이콘·글자 병행(대기 회색 윤곽 / 진행 틸 채움 + 펄스 링 / 완료 틸 체크 / 실패 적색 ✕). 마지막 단계 `완료`는 상태가 `done`이면 **라벨 하나만** 표시(상태 글자를 반복하지 않음). 경과 시간 표시는 `Date.now` 대신 주입 가능한 시계(테스트용)로, 진행 중일 때만 갱신. 기획 N회·되돌림 M회 보조 줄은 유지.
- **애니메이션**: 순수 CSS(`@keyframes` 펄스 링, 연결선 채움 전환). `@media (prefers-reduced-motion: reduce)`에서 `animation: none; transition: none`, 상태는 색·아이콘으로만 구분. JS 타이머 애니메이션 금지.
- **확인 질문**: 대기 중(`status === "needs_choice"`)에는 지금처럼 선택 카드. **선택이 끝난 턴(`choiceLabel` 있거나 `status !== "needs_choice"`)은 `ClarifySummary` 한 줄**(예: `효능 선택 · 보습`)로 접고 버튼을 그리지 않는다. `ClarifyCard`의 버튼은 `needs_choice` 턴에서만 렌더.
- **예시 칩 삭제**: `web/lib/examples.ts` 삭제, `Chat.tsx`의 `.examples` 제거. 칩 3개를 되살리지 않는다.
- 옛 `Chat.tsx`·`StepBar.tsx`·`TurnView.tsx`·`ClarifyCard.tsx`는 새 `plan/` 컴포넌트로 **대체하고 삭제**한다(`WorkspacePicker`는 step 1 상단 바로 이동했다면 삭제, 아니면 유지 — step 1 결과 확인). `CommandSlot`·결과 컴포넌트는 이 step에서 수정하지 않는다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `ProgressTracker` | `web/components/plan/ProgressTracker.tsx` | `TurnCard.tsx`, `stages.test.ts`, 실행 기록(step 9의 단계 요약) |
| `ClarifySummary` | `web/components/plan/ClarifySummary.tsx` | `TurnCard.tsx` |
| 새 `Stage.display` 필드(완료 단계의 표시 방식) | `web/lib/stages.ts` | `ProgressTracker.tsx` |

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/{Chat,StepBar,TurnView,ClarifyCard,WorkspacePicker,CommandSlot,Notice}.tsx`, `/web/lib/{reducer,stages,examples,claim,session}.ts*`, `/web/components/ui/*`, `/web/components/shell/*`
- `/web/tests/{chat,stages,reducer,claim}.test.ts*`, `/tests/test_demo_docs.py`(`chip_messages`·`test_confirmed_prompts_match_workspace_chips`·`test_chip_check_rejects_empty_synthetic_input`가 `web/lib/examples.ts`를 읽는다), `/DEMO.md`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/components/plan/*`, `web/app/plan.css`, `web/lib/stages.ts`, `web/lib/examples.ts`(삭제), `web/components/{Chat,StepBar,TurnView,ClarifyCard}.tsx`(삭제), `web/components/shell/AppShell.tsx`(본문 연결), `web/tests/{plan,stages,chat}.test.tsx` (chat은 plan으로 교체), `tests/test_demo_docs.py`(칩 결합 단언 교체만), `web/app/page.tsx`(`Chat` 렌더를 `PlanPage`로 교체만), `web/app/globals.css`(`.examples` 규칙 제거만: `.options, .examples, .composer-actions` 선택자에서 `.examples`를 빼고 `.examples`·`.examples button` 두 규칙 삭제), `web/tests/evidence-plan.test.tsx`(삭제되는 `Chat`·`TurnView`·`StepBar` 참조와 진행창 완료 표시 기대값만 새 구조에 맞춘다. 행동 단언 유지·약화 금지. step 4가 이 파일을 `results.test.tsx`로 교체한다)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/components/plan/*`, `web/app/plan.css`, `web/lib/stages.ts`, `web/lib/examples.ts`(삭제), `web/components/{Chat,StepBar,TurnView,ClarifyCard}.tsx`(삭제), `web/components/shell/AppShell.tsx`(본문 연결), `web/tests/{plan,stages,chat}.test.tsx` (chat은 plan으로 교체), `tests/test_demo_docs.py`(칩 결합 단언 교체만), `web/app/page.tsx`(`Chat` 렌더를 `PlanPage`로 교체만), `web/app/globals.css`(`.examples` 규칙 제거만: `.options, .examples, .composer-actions` 선택자에서 `.examples`를 빼고 `.examples`·`.examples button` 두 규칙 삭제), `web/tests/evidence-plan.test.tsx`(삭제되는 `Chat`·`TurnView`·`StepBar` 참조와 진행창 완료 표시 기대값만 새 구조에 맞춘다. 행동 단언 유지·약화 금지. step 4가 이 파일을 `results.test.tsx`로 교체한다)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/stages.ts`: `Stage`에 완료 단계의 표시 규칙을 추가한다(기존 필드와 `deriveStages` 결과의 `id/label/status/count/reworks`는 바꾸지 않는다. "완료 완료" 문제는 렌더 쪽에서 `id === "complete"`일 때 상태 글자를 생략해 해결한다).
**2.** `web/components/plan/*`와 `web/app/plan.css`(`gs-` 접두). `PlanPage`가 `useSession()`으로 상태를 읽고 새 컴포넌트를 조립한다. 결과 영역은 기존 `CommandSlot`을 그대로 사용한다.
**3.** 옛 `Chat`·`StepBar`·`TurnView`·`ClarifyCard`와 `examples.ts`를 삭제하고 `AppShell`의 광고 기획 본문을 `PlanPage`로 교체한다.
**3-1.** 삭제되는 컴포넌트의 소비자도 함께 옮긴다(앞선 실행이 blocked로 찾아낸 누락): `web/app/page.tsx`가 `Chat`을 import해 렌더하므로 `PlanPage`로 바꾸고, `web/tests/evidence-plan.test.tsx`가 `Chat`·`TurnView`·`StepBar`를 import하므로 새 컴포넌트 참조로 바꾸되 **기존 행동 단언은 그대로 유지**하고(완료 표시 기대값만 새 규칙 "완료 한 번"에 맞춤), `web/app/globals.css`의 `.examples` 규칙 3줄은 소스 금지 가드(`.examples` 없음)와 충돌하므로 제거한다.
**4.** **`tests/test_demo_docs.py` 갱신(예시 칩 삭제의 직접 영향)**: 이 파일의 `test_confirmed_prompts_match_workspace_chips`는 `web/lib/examples.ts`의 칩 문장이 `PROMPTS`와 같은지와 `DEMO.md`에 그 문장이 있는지를 함께 단언한다. 칩이 사라지므로 **칩 문장 일치 단언과 `chip_messages`·`test_chip_check_rejects_empty_synthetic_input`만** 제거하고, **`DEMO.md`에 `PROMPTS`의 모든 확인 문장이 있다는 단언은 그대로 유지**(`PROMPTS`를 직접 순회, 0건이면 실패)한다. 대체 가드로 `web/` 소스에 `examples`·`.examples`·`예시 요청`이 없다는 단언(소스 파일을 읽어 검사, 파일 0개면 실패)을 **추가**한다. 이 교체는 사용자 승인 사항이다(설계 제안서 §8 확인 요청 2).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/stages.test.ts`: 기존 단언 유지 + (1) 완료 단계는 `deriveStages` 결과가 그대로이고(기존), 렌더 규칙은 `plan.test.tsx`가 검사.
- `web/tests/plan.test.tsx`(`chat.test.tsx` 대체: **기존 `chat.test.tsx`의 모든 행동 단언을 새 구조에서 같은 엄격도로 옮긴다**: 요청 전송, Enter/Shift+Enter, IME 조합 중 전송 금지, 중단·재시도, 작업 공간 변경 시 중단, 이미지 포함 체크, 오류 표시): (2) `complete` 단계는 완료 상태에서 "완료"가 **정확히 한 번** 표시(`getAllByText("완료")` 길이 1), (3) 진행 중 단계는 `data-status="running"`이고 `aria-live` 영역에 있다, (4) `ProgressTracker`의 CSS에 `@keyframes`가 있고 `prefers-reduced-motion` 안에서 `animation: none`(CSS 파일 읽기), (5) **예시 버튼이 없다**(`queryByLabelText("예시 요청")` 없음, `examples.ts` 파일 없음), (6) 확인 질문 대기 턴은 선택 버튼이 있고, 선택해 해결된 턴은 `효능 선택 · …` 요약 한 줄만 있고 **`role="button"` 선택지가 없다**, (7) 해결된 질문 뒤의 새 요청 턴은 일반 턴으로 표시.
- `web/tests/reducer.test.ts`: 기존 단언 유지(리듀서 동작 불변).
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
- `pnpm add`·`uv add`·그 밖의 패키지 설치와 `package.json`·`pnpm-lock.yaml` 수정을 하지 마라. 이유: 이번 phase의 새 패키지는 승인된 `pretendard@1.3.9` 하나뿐이다.
- 모델·유료 API를 호출하거나 `make live-slice`, `make live-collect`, `make live-pilot`, `make live-analyze`, `make live-tiktok`, `make live-tiktok-analyze`, `make live-graph`, `make live-products`, `make live-ingredient-catalog`, `make live-cert-recheck`, `make live-cq`, `make live-product-identify`, `make live-agent`, `make live-agents`, `make live-evidence`, `make live-compare`, `make live-evalset`, `make live-e2e5`, `make live-e3`, `make live-isolation`, `make serve`, `make demo-up`, `make db-up`, `make obs-up`을 실행하지 마라. `.env`를 열거나 출력하지 마라. 테스트는 합성 데이터와 가짜 환경만 쓴다. 이유: 실제 호출과 사람이 보는 확인은 사용자가 한다(AGENTS.md CRITICAL).
- 제품 이름 문자열(`Gyeol Studio`, `결 스튜디오`)을 `web/lib/brand.ts` 밖에 리터럴로 쓰지 마라(테스트 파일 제외 불가: 가드 테스트가 `web/` 소스 전체를 검사한다). 이유: 이름은 한 곳에서만 바꾼다(확정 설계 조건 1).
- `web/lib/reducer.ts`·`web/lib/sse.ts`·`web/lib/api.ts`의 동작을 바꾸지 마라. 이유: 이 step은 표현 교체이고 상태·통신 계약은 불변이다(SSE 이벤트 종류, `claim_choice` 계약).
- 예시 칩(`examples`)·`web/lib/examples.ts`를 어떤 형태로든 되살리지 마라. 이유: 사용자가 이미 없앴다고 지시했다.
- JS `setInterval`로 애니메이션을 구동하지 마라. 이유: 애니메이션은 CSS이고 `prefers-reduced-motion`에서 꺼져야 한다(경과 시간 숫자만 상태 갱신 허용).
