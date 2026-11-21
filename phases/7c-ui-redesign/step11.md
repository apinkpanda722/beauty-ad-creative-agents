# Step 11: cost-restore

## 설계 검토 기록

**배경**: step 10(visual-align) 검토에서 `ResultsView`가 `CostLine`을 더 이상 그리지 않아 결과 화면에서 서버 라벨 `텍스트 모델 비용(이미지 제외)`과 소수 4자리 비용이 사라진 것이 확인됐다. 진행 줄의 비용(소수 3자리, 접근 이름은 서버 라벨)만 남았다. 이 step은 그 항목을 `전체 보기` 영역 안에 복원한다. 새 패키지·서버 변경·live 호출은 없다.

**코드를 열어 확인한 사실**
- `web/components/results/CostLine.tsx`는 `data`가 있으면 `<p className="gs-cost-line muted">이 요청의 {data.label} ${data.text_spent_usd.toFixed(4)}</p>`, 없으면 `null`이다. **상한(`max_text_cost_usd`)은 이 컴포넌트가 원래부터 표시하지 않는다**(이전 보고에서 상한이 "표시되지 않는다"고 쓴 것은 진행 줄에 대한 말이었고, 상한은 어느 화면에도 표시된 적이 없다). 단위 테스트(`tests/results.test.tsx`의 `shows cost only when supplied with verbatim label and four decimals`)가 `container.textContent`가 정확히 `이 요청의 합성 비용 레이블(이미지 제외) $0.0123`이고 `이미지 제외`가 한 번뿐임을 단언한다. 따라서 `CostLine`의 출력을 바꾸면 이 테스트가 깨진다.
- `show_cost` 명령의 데이터는 `{label, text_spent_usd, max_text_cost_usd}`이고 서버(`api/ask_view.py`)가 `result["limits"]`의 `text_spent_usd`·`max_text_cost_usd`가 모두 유한한 수일 때만 만든다. 라벨은 `텍스트 모델 비용(이미지 제외)`이다.
- `web/components/results/ResultsView.tsx`는 현재 `show_plan` 명령마다 `PlanResult`를 그리고, `show_cost`는 그리지 않는다. `PlanResult.tsx`의 `전체 보기`는 `aria-expanded`/`aria-controls`로 `div.gs-plan-expanded`(`hidden={!expanded}`, 접혀도 DOM에 유지)를 여닫는다.

**설계 결정**
- 새 `web/components/results/CostDetail.tsx`: `{data}`(show_cost 데이터)를 받아 `<CostLine data={data} />`를 **그대로 쓰고**(출력 불변) 그 아래에 상한 줄을 별도 요소로 그린다: `텍스트 비용 상한 ${data.max_text_cost_usd.toFixed(4)}`(소수 4자리, `<p className="gs-cost-line muted">`). `data`가 없으면 `null`. (상한 문구의 대상 범위는 `api/` 쪽 `limits` 정의를 열어 확인하고, 확인되지 않는 `요청당` 같은 수식어를 붙이지 않는다.)
- `ResultsView.tsx`: `show_cost` 명령의 데이터(첫 번째)를 찾아 **첫 번째 `PlanResult`에만** `cost` prop으로 넘긴다(비용은 요청 단위이므로 기획안이 여러 개여도 중복 표시하지 않는다). `show_plan`이 하나도 없는데 `show_cost`가 있으면 `ResultsView`가 `CostDetail`을 직접 그린다(예전 위치: 마지막). `show_cost`가 없으면 아무것도 그리지 않는다.
- `PlanResult.tsx`: `cost?: ...` prop을 추가하고 `div.gs-plan-expanded` **안**(맨 아래, 면책 문구 다음)에서 `<CostDetail data={cost} />`를 그린다. 그 외 구조·표시 항목·`전체 보기` 동작은 바꾸지 않는다. 진행 줄(`ProgressTracker`)의 비용 표시는 유지한다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `CostDetail`(라벨·4자리·상한) | `web/components/results/CostDetail.tsx` | `PlanResult.tsx`, `ResultsView.tsx`, `results.test.tsx` |
| `PlanResult`의 `cost` prop | `PlanResult.tsx` | `ResultsView.tsx` |

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/results/{CostLine,PlanResult,ResultsView}.tsx`, `/web/components/plan/{TurnCard,ProgressTracker}.tsx`, `/web/lib/types.ts`(`show_cost` 형태), `/src/beautyads/api/ask_view.py`(읽기 전용, `limits` 출처 확인), `/web/tests/results.test.tsx`, `/web/tests/plan.test.tsx`(진행 줄 비용 단언, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/components/results/CostDetail.tsx`, `web/components/results/PlanResult.tsx`, `web/components/results/ResultsView.tsx`, `web/app/results.css`, `web/tests/results.test.tsx`(추가만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/components/results/CostDetail.tsx`, `web/components/results/PlanResult.tsx`, `web/components/results/ResultsView.tsx`, `web/app/results.css`, `web/tests/results.test.tsx`(추가만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/components/results/CostDetail.tsx` 새로 만들기(`CostLine` 재사용, 상한 줄 별도).
**2.** `PlanResult.tsx`에 `cost` prop과 `전체 보기` 영역 안 렌더, `ResultsView.tsx`에서 `show_cost`를 찾아 첫 `PlanResult`에 전달(기획안이 없으면 직접 렌더), 필요한 CSS는 `results.css`에 `gs-` 접두와 `tokens.css` 변수만으로 추가.
**3.** `web/tests/results.test.tsx`에 단언 추가(기존 단언은 수정하지 않는다).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/results.test.tsx`(추가만, **기존 `CostLine` 단위 테스트를 포함한 모든 기존 단언은 수정 없이 통과**): (1) `show_plan` + `show_cost`(`label: "텍스트 모델 비용(이미지 제외)"`, `text_spent_usd: 0.012345`, `max_text_cost_usd: 1`)를 `ResultsView`로 렌더한다. **`전체 보기`를 누르기 전**에는 펼침 영역이 `hidden`이지만 그 안에 비용 요소가 DOM에 있다. **`전체 보기`를 펼친 뒤** 펼침 영역(`aria-controls`가 가리키는 요소) 안에서 `이 요청의 텍스트 모델 비용(이미지 제외) $0.0123`(서버 라벨 그대로, 4자리 값)과 `텍스트 비용 상한 $1.0000`(4자리)이 모두 보인다(`within(영역).getByText`), (2) 서버 라벨 `이미지 제외`가 비용 줄에서 정확히 한 번이다, (3) 기획안이 둘이면 비용·상한은 **첫 번째 기획안의 펼침 영역에만** 있고 전체에서 정확히 한 번이다, (4) `show_plan` 없이 `show_cost`만 있으면 비용·상한이 펼침 없이 보인다, (5) `show_cost`가 없으면 비용·상한 문구가 어디에도 없다, (6) 진행 줄의 비용(`$0.062`, 서버 라벨 접근 이름)은 그대로다(`tests/plan.test.tsx`의 기존 단언이 수정 없이 통과), (7) 서버가 보낸 라벨 문자열이 달라도(예: `합성 비용 레이블(이미지 제외)`) 그대로 표시된다(하드코딩 금지).
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
- `web/components/results/CostLine.tsx`를 수정하지 마라(출력 문자열·구조 불변). 이유: 기존 단위 테스트가 `textContent`의 정확 일치를 단언한다. 상한은 별도 요소로 더한다.
- 서버 코드(`src/`)·`web/lib/types.ts`·`web/lib/api.ts`·`web/lib/sse.ts`를 수정하지 마라. `show_cost`의 데이터 형태를 바꾸지 마라. 이유: 서버 계약은 불변이다.
- 진행 줄(`ProgressTracker.tsx`)의 비용 표시와 `web/tests/plan.test.tsx`의 기존 단언을 바꾸지 마라. 이유: 진행 줄 비용(3자리)은 유지가 승인 조건이다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드가 소스에서 이 문자열을 찾는다.
