# Step 8: web-polish

## 설계 검토 기록

**배경(7a 화면 확인 결과, 조언 세션 승인)**: 7a의 step 1~7이 끝난 뒤 Playwright로 `/api/*` 응답을 가로채 화면을 확인했다(백엔드·모델 호출 없음). 서버 계약과 무관한 **화면 수정 9건**이 나왔고, 같은 phase 안의 8번째 step으로 처리한다(수정마다 새 phase를 만들지 않는다, B-FP-053). **서버 계약은 이 step에서 바꾸지 않는다**(`src/`·파이썬 모듈 수정 금지. 필요해 보이면 `blocked`로 보고한다).

**처리 항목과 코드로 확인한 현재 상태**:
1. **비용 줄 중복**: `web/components/CostLine.tsx`가 `이 요청의 {data.label} ${금액} (이미지 제외)`를 그린다. 서버 `label`이 이미 "텍스트 모델 비용(이미지 제외)"(`api/ask_view.py`)라 "이미지 제외"가 두 번 나온다 → `이 요청의 {data.label} ${금액}`으로 **한 번만** 쓴다(서버 라벨이 단일 출처).
2. **게시일 형식**: `web/components/EvidenceCards.tsx` 30행 `card.published_at ?? "게시일 정보 없음"`이 ISO 원문(`2026-10-01T00:00:00+00:00`)을 그대로 보인다 → 문자열이 `^\d{4}-\d{2}-\d{2}`로 시작하면 **그 앞 10글자(날짜 부분)만** 쓴다. `Date` 객체·시간대 변환을 쓰지 않는다(변환하면 날짜가 바뀔 수 있다). 형식이 다르면 원문, `null`이면 기존 문구.
3. **분포 막대 라벨의 한국어 이름**: `web/components/DistributionChart.tsx`가 `row.value`(예: `question`·`problem`·`bold_claim`)를 그대로 쓴다. 이름표의 출처는 이미 **서버 분류 체계**다: `web/lib/taxonomy.ts` `taxonomyNames(schema)`가 `/graph/schema` 응답의 `taxonomy`(훅·소구·형식)와 `claims`를 읽는다(웹에 이름표를 복제하지 않는다 → 드리프트 없음). `bold_claim`·`problem` 등 훅·소구·형식·효능 값은 서로 겹치지 않으므로(`analysis/prompts.py` 닫힌 목록 확인) `taxonomyNames`에 `valueName(value)`를 더해 훅 → 소구 → 형식 → 효능 순으로 찾고 **없으면 원 값**을 쓴다(`Talent`·`CtaType`의 `none`은 겹치므로 이 함수에 넣지 않는다). `CommandSlot.tsx`의 `needsSchema`에 `show_distribution`을 더하고 `DistributionChart`에 `names`를 넘긴다. 스키마 조회가 실패해도 원 값으로 동작한다.
4. **"기획안입니다." 문구**: `web/components/TurnView.tsx`가 `turn.displayText`를 **결과 카드 아래**에 그린다. 서버는 `kind == "plan"`일 때 `display_text`에 "기획안입니다."(`api/ask_view.py`)를 넣고 같은 화면에 기획안 카드가 있다 → (a) 메시지를 단계 표시줄 **바로 아래, 카드 위**로 옮기고, (b) `show_plan` 명령이 있는 턴에서는 **그 한 줄("기획안입니다.")만** 뺀다(한도 도달 문구 등 다른 줄은 유지). 줄 문구는 `web/lib/text.ts`의 상수 `PLAN_INTRO_TEXT = "기획안입니다."` 하나에 두고, `tests/test_web_contract.py`가 `api/ask_view.py`의 같은 문자열과 일치함을 대조한다(항목 8의 드리프트 가드와 같은 방식). 리서치 결과(`리서치 결과입니다.` + 결론)·고정 문구 종류(근거 없음·범위 밖·실패·한도)는 지금처럼 보인다.
5. **되묻기 턴의 단계 표시줄**: `StepBar.tsx`가 `deriveStages`의 모든 단계를 그려 되묻기 턴에 "리서치 대기·기획 대기·평가 대기·완료 대기"가 남는다 → `turnStatus`가 `needs_choice`이면 "요청 해석 완료 · 선택을 기다리는 중" 한 줄만, `unavailable`·`stopped`이면 표시줄을 그리지 않는다. `deriveStages`(`lib/stages.ts`)는 바꾸지 않는다.
6. **근거 그래프 가독성**: `GraphCanvas.tsx`의 스타일(`font-size` 11, 관계 이름 8, `text-margin-y` 7, 레이아웃 `cose`)로 노드 라벨과 관계 이름이 겹친다 → 노드 라벨 크기와 간격·관계 이름 크기를 줄이고(예: 노드 9~10, 관계 7), `cose`의 `nodeRepulsion`·`idealEdgeLength`·`nodeOverlap` 옵션 등으로 간격을 넓힌다(옵션은 `cytoscape` 3.35.0 내장 `cose`만, 확장 패키지 설치 금지). 범례 `GRAPH_LEGEND`(`lib/graph.ts`)는 층(1층 제품 지식·2층 광고 관찰·3층 피드백)과 레이블(제품·광고 소재)이 한 목록에 섞여 있다 → **두 묶음(제목 "층", "노드 종류")으로 분리**한다. `tests/graph.test.ts` 39행(`GRAPH_LEGEND.some(item => item.color === node.data.color)`)은 새 구조에서도 같은 의미(노드 색이 범례 어딘가에 있음)로 유지한다.
7. **`web/AGENTS.md` 자동 생성 차단**: `next dev`가 시작할 때 "Generated AGENTS.md for AI agents. Set `agentRules: false` in next.config to disable."을 출력하고 `web/AGENTS.md`를 만든다(2026-11-20 화면 확인 때 확인) → `web/next.config.ts`에 `agentRules: false`를 넣는다. `NextConfig` 타입에 이 키가 없어 `pnpm typecheck`가 실패하면 `node_modules/next/dist/server/config-shared.d.ts`에서 확인한 뒤 `NextConfig & { agentRules?: boolean }`로 확장하고 이유를 주석으로 적는다. `.gitignore`로 가리지 않는다(생성 자체를 설정으로 막는다). 확인은 `grep`(`node_modules/next/dist`에서 `agentRules`)로 하고 `pnpm dev`는 실행하지 않는다.
8. **효능 값 집합 드리프트 가드**: `web/lib/claim.ts`가 `claims = new Set([... 11개 ...])`를 하드코딩한다 → 값 목록을 `export const CLAIM_VALUES = [...] as const`로 꺼내 쓰고, `tests/test_web_contract.py`가 `beautyads.domain.labels.Claim`의 멤버 값 집합과 `claim.ts`의 `CLAIM_VALUES` 집합을 **양방향으로 대조**한다(검사한 값이 0이면 실패, B-FP-069). 같은 파일에 `PLAN_INTRO_TEXT` 대조(항목 4)와 `next.config.ts`의 `agentRules: false` 존재 단언을 더한다.
9. **기획안 카드 정리**(`web/components/PlanCard.tsx`): (a) "평가 시도"(시도별 점수·재검토 항목·시도 비용)는 **기본으로 접은** `<details>`("평가 시도 보기 · 되돌림 N회")로 두고 펼치면 지금 내용이 그대로 나온다. (b) 기본 화면의 순서: 제목·훅·분류 배지 → 장면 구성 → 카피 → 주장 효능 → 검사 결과(근거 연결 없음 배지, 코드 검사, 평가 상태) → 경쟁사 패턴 반영 → 근거 소재 목록 → (접힌) 평가 시도 → 면책 문구 → 시안 이미지 → 피드백 바. (c) **배지 중복 정리**: 배지에는 총 건수("근거 연결 없음 N건"), 그 아래 목록에는 **코드의 한국어 이름만**(건수 없음, 예: "효능 근거 연결 없음")을 보인다. `unknownNames`에 없는 코드는 원 코드.
- **촬영 안내(7b DEMO.md로 이월, 이 step에서는 하지 않는다)**: 촬영은 `pnpm build`·`pnpm start`(운영 모드)로 한다(개발 모드의 N 아이콘이 화면에 나오지 않게).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `taxonomyNames().valueName` | `web/lib/taxonomy.ts` | `DistributionChart.tsx`(`CommandSlot.tsx`가 `names` 전달) |
| `PLAN_INTRO_TEXT` | `web/lib/text.ts` | `TurnView.tsx`, `tests/test_web_contract.py`(서버 문자열과 대조) |
| `CLAIM_VALUES` | `web/lib/claim.ts` | `claim.ts` 내부 검증, `tests/test_web_contract.py`(`Claim`과 대조) |
| 날짜 표시 함수 | `web/lib/format.ts` | `EvidenceCards.tsx` |
| 범례 두 묶음 | `web/lib/graph.ts` | `GraphCanvas.tsx`(`GraphLegend`), `tests/graph.test.ts` |
| `agentRules: false` | `web/next.config.ts` | `tests/test_web_contract.py` |

**기존 단언과의 충돌 점검(웹 테스트를 `rg`로 확인)**: 아래 테스트는 **옛 표시 방식을 단언**하므로 새 방식에 맞게 **기대값만 갱신**한다(같은 의미를 더 정확하게 단언, 부분 비교·삭제로 약화하지 않는다). 그 밖의 단언은 불변이다.
- `web/tests/evidence-plan.test.tsx` 143행 부근 `CostLine` 단언: 테스트 라벨 "합성 비용 레이블"에는 "이미지 제외"가 없고 지금 코드가 literal로 붙여 통과한다 → 서버처럼 라벨에 "(이미지 제외)"를 넣은 합성 데이터로 바꾸고 **"이미지 제외"가 정확히 한 번**임을 단언한다.
- 같은 파일 47행 `getByText(/효능 근거 연결 없음.*1건/)`: 목록은 이름만 나오므로 이름 텍스트 단언으로 갱신하고, 배지 "근거 연결 없음 N건"(34·45행)은 그대로다. 평가 시도를 다루는 단언은 `<details>`가 **접혀 있음**(`open` 속성 없음)과 펼치면 내용이 나옴 두 가지로 나눈다. 165행 Chat 순서 테스트는 메시지가 카드 위로 올라오는 새 순서에 맞게 갱신한다(`display_text`만 쓰고 `text` 원문이 없음은 유지).
- `web/tests/chat.test.tsx`·`reducer.test.ts`·`stages.test.ts`: `displayText`·`deriveStages` 계약은 불변이다(표시 쪽만 바뀐다). 깨지면 약화하지 말고 `blocked`로 보고한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/PRD.md`(시연과 포트폴리오 산출물), `/docs/ARCHITECTURE.md`(스트리밍 이벤트와 화면 명령)
- `/src/beautyads/api/ask_view.py`(`display_text`·`show_cost` 라벨·"기획안입니다." 문구, 읽기 전용), `/src/beautyads/domain/labels.py`(`Claim`), `/src/beautyads/analysis/prompts.py`(분류 값 목록, 읽기 전용)
- `/web/components/CostLine.tsx`, `/web/components/EvidenceCards.tsx`, `/web/components/DistributionChart.tsx`, `/web/components/CommandSlot.tsx`, `/web/components/TurnView.tsx`, `/web/components/StepBar.tsx`, `/web/components/PlanCard.tsx`, `/web/components/GraphCanvas.tsx`
- `/web/lib/taxonomy.ts`, `/web/lib/graph.ts`, `/web/lib/claim.ts`, `/web/lib/stages.ts`, `/web/lib/reducer.ts`, `/web/next.config.ts`
- `/web/tests/`(모든 테스트), `/tests/test_web_contract.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/`, `tests/test_web_contract.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `web/`, `tests/test_web_contract.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

위 "처리 항목" 1~9를 구현한다. 새 파일은 `web/lib/text.ts`·`web/lib/format.ts`뿐이다(각각 상수 하나·함수 하나). 새 패키지는 설치하지 않는다.

**테스트(`web/tests/`와 `tests/test_web_contract.py`, 합성 데이터, 서버 문장을 기대값으로 굳히지 않는다)**
- (1) 비용 줄: 서버 형식 라벨에서 "이미지 제외"가 한 번, 금액 소수 4자리.
- (2) 게시일: `2026-10-01T00:00:00+00:00`·`2026-10-01T23:30:00-05:00`가 둘 다 `2026-10-01`(시간대로 날짜가 바뀌지 않음), 날짜 형식이 아닌 값은 원문, `null`은 기존 문구.
- (3) 분포 라벨: 스키마가 있으면 훅·소구·형식·효능 값이 한국어 이름, 스키마가 없거나 이름이 없는 값(`other`·알 수 없는 값)은 원 값.
- (4) 메시지: 결과 카드 위에 나오고, `show_plan`이 있는 턴에서는 `PLAN_INTRO_TEXT` 한 줄만 빠지고 다른 줄(한도 도달 문구 등)은 남는다. `show_plan`이 없으면 그대로.
- (5) 단계 표시줄: `needs_choice`는 "선택을 기다리는 중"만(대기 문구 없음), `unavailable`·`stopped`는 표시줄 없음, `running`·`done`은 지금과 같다.
- (6) 그래프: 범례가 두 묶음이고 노드 색이 범례에 있음(기존 의미 유지), `GraphCanvas`의 스타일 값이 위 항목의 숫자 범위에 있음(`vi.mock("cytoscape")`로 받은 설정 검사).
- (7) 기획안 카드: 평가 시도가 기본으로 접혀 있고(`open` 없음) 펼치면 시도별 점수·재검토 항목이 보임, 기본 화면에 위 (b) 순서의 섹션이 있음, 배지에는 총 건수·목록에는 이름만(건수 숫자 없음), 모르는 코드는 원 코드.
- (8) `tests/test_web_contract.py`: `Claim` 멤버 값 집합 ↔ `CLAIM_VALUES` 양방향, `PLAN_INTRO_TEXT` ↔ `ask_view.py`의 같은 문자열, `next.config.ts`에 `agentRules: false`.

## Acceptance Criteria

```bash
make verify   # ruff + pytest + pnpm lint·typecheck·test 통과
NEXT_TELEMETRY_DISABLED=1 pnpm --dir web build   # 프로덕션 빌드 통과, 서버 연결 불필요
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

- `src/`·파이썬 모듈·`Makefile`·`web/package.json`의 의존성을 수정하지 마라. 서버가 주는 문구를 바꾸기 위해 서버를 고치지 마라(웹에서 한 줄을 거르는 방식만). 이유: 이 step은 화면 수정이고 서버 계약은 7a step 2·3에서 끝났다. 필요해 보이면 `blocked`로 보고한다.
- 분포·카드·그래프에 분류 값의 한국어 이름을 웹에 새로 복제하지 마라(스키마의 `taxonomy`·`claims`와 기존 `TALENT_NAMES`·`CTA_NAMES`만 쓴다). 이유: 서버 분류 체계가 단일 출처이고 복제하면 드리프트한다(P5 결정 50의 "분리 표시" 원칙과 같다: 출처는 하나).
- 게시일을 `new Date(...)`로 변환하거나 `toLocale*`로 만들지 마라. 이유: 시간대 변환으로 날짜가 하루 바뀔 수 있다(승인 요구 2).
- 기존 테스트 단언을 약화·삭제하지 마라(위 "기존 단언과의 충돌 점검"의 기대값 갱신만 허용). 화면에 우열·성능을 말하는 문구(좋음·효과적·인기 등)를 만들지 마라. 이유: 가드를 약화하면 회귀를 못 잡고, 사용자 원칙은 사실과 다른 문구를 만들지 않는 것이다.
- `pnpm dev`·`pnpm start`를 실행하지 마라(`pnpm --dir web build`는 AC에서 허용). 이유: 서버 실행과 화면 확인은 사용자가 한다(A-FP-040). `agentRules`는 `node_modules`의 `grep`으로만 확인한다.
