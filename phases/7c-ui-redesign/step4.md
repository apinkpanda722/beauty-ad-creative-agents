# Step 4: results

## 설계 검토 기록

**목적**: 결과 영역(기획안·근거·평가·피드백)과 근거 소재 화면을 교체한다. 근거 소재는 플랫폼별 묶음, 자사 배지, 썸네일 없는 플랫폼의 대체 표현을 갖는다.

**코드를 열어 확인한 사실**: `PlanCard.tsx`(기획안, 평가 시도 `<details>`, `FeedbackBar`, `DesignImage`), `EvidenceCards.tsx`(YouTube만 썸네일 `https://i.ytimg.com/vi/{id}/hqdefault.jpg`, 정규식 `^youtube:([A-Za-z0-9_-]{1,64})$`; 실패 시 `div.source-icon`), `CommandSlot.tsx`(결과 명령 렌더, 근거 앵커 `anchors`), 카드 필드에 자사 여부 없음, `Workspace.brand`는 `/workspaces`에서 온다.

**설계 결정**
- `web/components/results/`: `PlanResult`(기획안 카드를 `ui` 부품으로 다시 구성: 제목·훅·축 배지·장면·카피·주장 효능·검사·평가 시도·시안·피드백), `ResultsView`(명령 종류별 배치). **`PlanCard`의 모든 표시 항목(근거 연결 없음 건수, 코드 검사, 평가 상태, 패턴 정렬, 평가 시도, 면책 문구, 시안 이미지 오류 표시, 피드백 저장)을 유지**한다. 위치·스타일만 바뀐다.
- 근거 앵커 링크(기획안 → 근거 카드)는 유지한다(`#anchor`). 근거 카드가 근거 소재 화면으로 옮겨져도 결과 안의 "근거 요약"에서 앵커가 동작해야 한다.
- `web/lib/evidence.ts`: `groupByPlatform(cards)`(순서: 카드가 많은 플랫폼 먼저, 동률이면 이름순), `dedupeCards`(`evidence_id` 기준, 없는 id는 유지), `isOwnBrand(cardBrand, workspaceBrand)`(trim·소문자화·공백과 하이픈을 `_`로 바꾼 뒤 동일, 둘 중 하나가 없으면 `false`). 작업 공간 `brand`는 `config/workspaces.yaml`의 슬러그(`mixsoon`, `cosrx`, `isntree`, `beauty_of_joseon`)이고 근거 카드의 `brand`는 그래프 `Creative.brand`(`evidence_queries.py`의 `c.brand AS brand`)다. 두 값이 같은 슬러그 형태인지는 **실제 데이터로 확인할 수 없으므로**(live 없음) 단위 테스트는 위 슬러그를 입력으로 쓰고, 한글 표기 등 다른 표기는 일치로 보지 않는다는 한계를 완료 보고에 적는다, `platformLabel(source)`(알 수 없는 값은 원문 표시).
- 근거 소재 화면(`web/components/evidence/EvidencePage.tsx`): 세션의 모든 턴의 `show_evidence_cards`를 모아 플랫폼별 묶음 헤더 + 카드 격자. 상단 필터(전체·플랫폼별·자사만). **빈 상태**는 `EmptyState`(행동 버튼 "광고 기획으로"). 카드에는 `자사` 배지.
- **썸네일 없는 플랫폼의 대체 표현**: 플랫폼 중립 틴트 타일 + 플랫폼 이름 + 모노그램 글자(상표 로고·이미지 없음) + 첫 분석 배지(훅 유형) 하나. YouTube 썸네일이 로드에 실패하면 같은 타일로 복귀(기존 `onError` 동작 유지).
- `CommandSlot.tsx`는 `ResultsView`로 대체하고 삭제(스키마 이름 조회 로직 `getSchema`·`taxonomyNames`는 `ResultsView`로 옮김).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `isOwnBrand`, `groupByPlatform`, `dedupeCards` | `web/lib/evidence.ts` | `EvidencePage.tsx`, `evidence.test.ts` |
| 자사 배지 | `EvidenceCardView.tsx` | `EvidencePage.tsx`, 결과의 근거 요약 |
| 세션 근거 카드 수집 | `web/lib/evidence.ts`의 `collectSessionCards(turns)` | `EvidencePage.tsx` |

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/{PlanCard,EvidenceCards,CommandSlot,PatternAlignment,DistributionChart,AggregatesPanel,CostLine,DesignImage,FeedbackBar,Notice}.tsx`, `/web/lib/{types,taxonomy,format,api,session}.ts*`, `/web/components/ui/*`, `/web/components/plan/*`
- `/web/tests/evidence-plan.test.tsx`(전체: 이 파일의 행동 단언이 교체 대상), `/web/tests/api.test.ts`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/evidence.ts`, `web/components/results/*`, `web/components/evidence/*`, `web/app/{results,evidence}.css`, `web/components/plan/PlanPage.tsx`(결과 연결), `web/components/shell/AppShell.tsx`(본문 연결), 옛 `web/components/{PlanCard,EvidenceCards,CommandSlot,PatternAlignment,DistributionChart,AggregatesPanel,CostLine,DesignImage,FeedbackBar}.tsx`(삭제), `web/tests/{evidence,results}.test.ts*`, `web/tests/evidence-plan.test.tsx`(results로 교체)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/evidence.ts`, `web/components/results/*`, `web/components/evidence/*`, `web/app/{results,evidence}.css`, `web/components/plan/PlanPage.tsx`(결과 연결), `web/components/shell/AppShell.tsx`(본문 연결), 옛 `web/components/{PlanCard,EvidenceCards,CommandSlot,PatternAlignment,DistributionChart,AggregatesPanel,CostLine,DesignImage,FeedbackBar}.tsx`(삭제), `web/tests/{evidence,results}.test.ts*`, `web/tests/evidence-plan.test.tsx`(results로 교체)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/evidence.ts`(+ 테스트). **2.** `web/components/results/*`: `PlanCard`·`DistributionChart`·`AggregatesPanel`·`CostLine`·`PatternAlignment`·`DesignImage`·`FeedbackBar`를 새 구조로 재작성하고 옛 파일은 삭제(동작 이름은 유지). **3.** `web/components/evidence/*`와 `AppShell`의 근거 소재 본문 연결. **4.** `PlanPage`가 `ResultsView`를 쓰도록 연결(턴 결과 영역).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/evidence.test.ts`: (1) `isOwnBrand`는 **`config/workspaces.yaml`의 슬러그를 입력으로 하는 케이스를 포함**한다: `isOwnBrand("isntree","isntree")`·`isOwnBrand("beauty_of_joseon","beauty_of_joseon")`는 `true`, `isOwnBrand("Beauty-of-Joseon","beauty_of_joseon")`처럼 대소문자·하이픈 차이도 `true`, `isOwnBrand("cosrx","isntree")`·빈 값·`null`은 `false`, (2) `groupByPlatform`은 플랫폼별로 묶고 정렬 규칙이 결정적이다(리스트 기대값), (3) `dedupeCards`는 같은 `evidence_id`를 한 번만 남기고 id 없는 카드는 유지, (4) 알 수 없는 플랫폼 문자열도 묶음으로 남는다.
- `web/tests/results.test.tsx`(`evidence-plan.test.tsx` 대체: **기존의 모든 행동 단언을 새 구조에서 같은 엄격도로 옮긴다**: 기획안 모든 표시 항목, 근거 앵커 링크 이동, YouTube 썸네일 `onError` 복귀, 이미지 `DESIGN_NOT_FOUND` 표시, 승인·반려 저장과 `저장했습니다` 표시, 분포·집계·비용 줄 표시): (5) 근거 소재 화면에서 YouTube 카드는 썸네일이 있고 인스타그램·틱톡 카드는 타일(플랫폼 이름 + 모노그램)이며 `img`가 없다, (6) 작업 공간 브랜드와 같은 카드만 `자사` 배지가 붙는다, (7) 필터 `자사만`이 카드를 거른다, (8) 세션에 카드가 없으면 빈 상태와 행동 버튼, (9) 같은 카드를 가진 두 턴은 한 번만 보인다.
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
- `web/lib/reducer.ts`·`web/lib/api.ts`·`web/lib/types.ts`의 계약(SSE 이벤트, `UiCommand` 종류, `_CARD_FIELDS`)을 바꾸지 마라. 이유: 서버 계약은 불변이다. 자사 여부 필드가 필요하면 완료 보고에 적고 중단하라(blocked).
- 외부 이미지를 저장·프록시하거나 플랫폼 로고 이미지를 추가하지 마라. 이유: 썸네일은 직접 로드만 하고(상표·저작권), 대체 표현은 글자 모노그램이다.
