# Step 19: insight-polish-3

## 설계 검토 기록

**목적**: 사용자가 시각 확인 뒤 승인한 3차 수정 4건(항목 22~25)을 한 step으로 처리한다. 새 패키지·live 호출·비용 발생 작업 없음. 6b-clarify 되묻기 동작은 바꾸지 않는다. **서버(`src/`) 변경은 항목 24(b)의 `src/beautyads/agents/tools.py` 한 곳(상위·하위 도구 경로의 `operation == "rows"` 분기 몇 줄)에 한정**한다. 기존 단언은 그대로 두고, 아래 "교체 단언" 표는 선점검에서 확정 충돌이 없었으므로 **비어 있다**. 실제로 깨지는 기존 단언이 나오면 구현하지 말고 `blocked`로 멈춰 최소 교체안(같은 사실·같은 엄격도)을 `reason`에 적어라(임의로 단언을 고치지 않는다). 새 테스트는 추가만 한다.

**코드를 열어 확인한 사실**
- `web/components/results/InsightPanel.tsx`(step 18): `InsightCard`가 `<section class="gs-result-section gs-distribution gs-insight-card" aria-labelledby>` 안에 `<h3 id>` 제목, 상위·하위 카드의 설명 `<p class="gs-insight-note">`(`insightDescription("top_vs_bottom_axis")`), `ui/Tabs`(축 탭), 검증 variant의 `표로 보기` 토글·`DataTable`을 둔다. `grouped`는 분포마다 `{ data, axis }`이고 `active`가 현재 탭이다. 막대는 `DistributionChart embedded`가 그린다(`bars` = `value` 문자열·`creatives` 정수 행, 나머지 행은 표). 모델 작성값 차트는 `ModelChart.rows`(`parseModelBreakdown` 결과)를 입력 순서대로 그린다. 기존 테스트는 `getAllByRole("heading")`이 카드 제목만 반환함을 단언한다(`insight-panel.test.tsx`) — 새 `총 N건`은 heading이 아니어야 한다.
- `web/lib/insight.ts`: `insightColumnName("top_vs_bottom_axis", …)`(`분류`·`상위 25% 광고 수`·`하위 25% 광고 수`), `insightDescription`(설명 문장 정확 일치 단언이 있다), `insightValue`(= `displayValue`), `parseModelBreakdown`. `taxonomy.ts`의 `names.valueName("other")`는 스키마의 `기타 훅`·`기타 각도`·`기타 포맷` 같은 이름을 돌려줄 수 있고 스키마가 없으면 `other`다(`DistributionChart`는 이 경우 `gs-sr-only` `other`를 덧붙인다).
- 분포 행 모양(서버): 경쟁사 분포(`compare_axis_by_category`)는 `{ value, creatives, total? }`(`total` = 전체 분모, 서버가 이미 보냄), 상위·하위(`top_vs_bottom_axis`)는 `{ value, n_top, n_bottom }`이고 표본 수는 싣지 않는다. 웹 테스트의 기존 분포 입력은 거의 모두 행이 1개이거나 이미 건수 내림차순이다(`history-page.test.tsx`의 `distribution` 행: `question` 7/2, `how_to` 3/1).
- 서버: `src/beautyads/agents/tools.py`의 `_run_evidence_tool`은 `operation == "rows"`(도구 `top_vs_bottom_axis`)에서 `bands = split_top_bottom(rows, mature_before=…)`, `rows = [row.model_dump() for row in bands.rows]`를 만들고 맨 끝에서 `top_rows=rows[:5]`·`row_count=len(rows)`로 돌려준다. `domain/evidence.py`의 `split_top_bottom`이 만드는 행은 분류 값 알파벳순(`sorted(by_value.items())`)이라 5행 자르기에서 알파벳 뒤쪽 분류(`question`·`result_first`·`ugc_style`·`problem_solution`·`social_proof` 등)가 통째로 누락된다. 웹의 `show_distribution` 행은 `tool_outputs`의 `rows`(없으면 `top_rows`)에서 오고 현재 도구는 `top_rows`만 준다(`agents/supervisor.py` `_tool_outputs`).
- **동결 확인(선점검에서 `rg`로 확인한 결과, 코드 전에 같은 명령으로 재확인하라)**: `docs/EVAL.md`·`docs/results/`·`tests/test_prereg.py`·`tests/test_freeze_guard.py`·`tests/test_e3_live.py`에는 이 도구의 행 정렬·`top_rows` 구성을 평가 기준·사전 등록으로 고정한 곳이 없다(`docs/results/2026-11-20-p6-final.md:99`가 "도구는 `top_rows` 5행…"이라는 한계만 기록하고 이 변경은 그 한계를 바꾸지 않는다; `tests/test_research_agent.py`·`tests/test_domain_supervisor.py`는 도구 이름 `top_vs_bottom_axis`만 쓰고 행 순서를 단언하지 않는다; `src/beautyads/eval`·`docs/EVAL.md`에 `agents/tools.py` 파일 고정 참조가 없다). **재확인에서 고정이 발견되거나 동결 가드 테스트가 이 변경으로 실패하면 서버 변경만 보류**(항목 24(b)를 구현하지 않고 웹 항목 22·23·24(a)·25는 계속)하고 `summary`에 원인과 최소안을 적어라.

**설계 결정**

**항목 22. 분포 카드 총 건수(`InsightPanel.tsx`, `results.css`)**
- `InsightCard`의 제목 줄을 `<div class="gs-insight-head"><h3 id>제목</h3>{총 건수}</div>`로 바꾼다(`flex; justify-content: space-between; align-items: baseline; gap: var(--gs-space-3)`). 총 건수는 `<span class="gs-insight-total">총 {N}건</span>`(heading 아님, `color: var(--gs-text-muted); font-size: var(--gs-text-sm)`, 숫자는 `toLocaleString("ko-KR")`)이다. **`경쟁사 광고 분포` 카드에만** 표시하고 `조회수 상위·하위 25% 광고 비교` 카드(`comparison`)에는 총 건수를 만들지 않는다(서버가 표본 수를 행에 싣지 않는다).
- 값: **현재 선택된 탭**(`active`)의 분포들(`grouped`에서 `axis === active.value`인 것)의 **모든 행**을 모아, 모든 행에 `total`이 유한한 음이 아닌 정수로 있고 그 값이 **하나로 모두 같을 때만** 표시한다. 값이 여러 개이거나 하나라도 `total`이 없거나 유효하지 않으면 표시하지 않는다(요소 자체를 그리지 않는다). 탭을 바꾸면 그 탭의 값으로 바뀐다. 헬퍼 `insightTotal(rows)`를 `insight.ts`에 새 export로 둔다(`number | null`). 검증 variant의 같은 `InsightPanel`에도 같은 규칙이 적용된다(`variant` 무관). 입력 객체는 변형하지 않는다.

**항목 23. `기타`를 맨 마지막으로(`insight.ts` 새 헬퍼, `InsightPanel.tsx`; 표시 단계에서만 정렬)**
- `web/lib/insight.ts`에 새 export 3개: `isOtherCategory(label: string, names: TaxonomyNames): boolean`(`label === "other"`이거나 `insightValue(label, names)`가 `기타`로 시작 — 곧 `기타`·`기타 훅`·`기타 각도`·`기타 포맷` 계열), `sortInsightRows(tool, rows, names)`(새 배열을 돌려준다: ① 문자열 `value`가 기타 계열이면 항상 마지막, ② 나머지는 건수 내림차순, ③ 동률은 기존 상대 순서 유지(안정 정렬; 인덱스 타이브레이커를 명시)). 건수는 `tool === "top_vs_bottom_axis"`이면 `n_top` 내림차순 다음 `n_bottom` 내림차순, 그 밖의 도구는 `creatives`(없으면 `count`) 내림차순이며 숫자가 아닌 값은 0으로 본다, `sortModelRows(rows, names)`(모델 작성값 차트 행 `{ label, count, total }`: 기타 계열(`label` 기준) 마지막, 나머지 `count` 내림차순, 안정).
- 적용 위치: `InsightPanel`이 분포를 `{ ...data, rows: sortInsightRows(data.tool, data.rows, names) }`로 **복사해서** 막대 차트(`DistributionChart embedded`)와 검증 variant의 원천 표(`DataTable`)에 모두 넘긴다(같은 정렬 함수 → 차트와 원천 표의 행 값·순서가 같다). 모델 작성값 차트는 `sortModelRows`로 정렬해 그린다(`parseModelBreakdown`의 반환 순서는 바꾸지 않는다). **원본 분포·`model_written`·서버 순서 객체는 변형하지 않는다**(JSON 스냅샷 불변). 단독 렌더되는 `DistributionChart`(`InsightPanel` 밖)의 출력은 바꾸지 않는다.

**항목 24(a). 상위·하위 25% 표(`InsightPanel.tsx`, `DistributionChart.tsx`, `insight.ts`, `results.css`)**
- 열 순서: 상위·하위 도구의 표 열은 `value`, `n_top`, `n_bottom`, 그 밖의 열 순(`분류`·`상위 25% 광고 수`·`하위 25% 광고 수`·…)으로 둔다(열 제목 문구·`insightColumnName`·카드 제목·설명 문장은 step 16·17 그대로). 이 도구의 `n_top` 칸은 헤더와 셀 **내용을** `<span class="gs-col-primary">`(`font-weight: 700`)로, `n_bottom` 칸은 `<span class="gs-col-muted">`(`color: var(--gs-text-muted)`, 토큰만, 새 색 금지)로 감싼다 — `DistributionChart`의 표(결과 화면, 일반 `th`·`td` 안)와 `InsightPanel` 검증 variant의 `DataTable`(`columns[].header`(ReactNode)와 `render` 반환값 안) 둘 다. **`web/components/ui/DataTable.tsx`(`ui/*`)는 수정하지 않는다**(`th`·`td` 자체에는 클래스를 달지 않는다). 텍스트는 그대로여서 `columnheader`·`cell`의 `textContent`는 변하지 않는다. 행 정렬은 `sortInsightRows`(`n_top` 내림차순 → `n_bottom` 내림차순 → 기타 마지막 → 안정).
- 설명 아래 한 줄: 설명 문장(`insightDescription`, 정확 일치 단언이 있으므로 **수정하지 않는다**) 바로 다음에 `<p class="gs-insight-note">상위 25% 광고 수가 많은 분류부터 5개까지 표시합니다.</p>`를 더한다. 문구는 `insight.ts`의 새 export `insightLimitNote(tool): string | null`(`top_vs_bottom_axis`만 문장, 나머지 `null`)로 두고 `InsightPanel`의 상위·하위 카드와 단독 `DistributionChart`(비임베디드)가 같은 위치에서 쓴다. `h3` 바로 뒤 형제는 기존처럼 설명 문장이어야 한다(한 줄은 그 다음 형제).

**항목 24(b). 서버: 상위·하위 행을 5행 자르기 전에 정렬(`src/beautyads/agents/tools.py`만)**
- `_run_evidence_tool`의 `operation == "rows"` 분기에서 `rows = [row.model_dump() for row in bands.rows]` 직후, **새 리스트**로 정렬한다: `rows = sorted(rows, key=…)` 정렬 키 `(값이 "other"이면 1 아니면 0, -n_top, -n_bottom, str(값))`(`n_top`·`n_bottom`이 정수가 아니면 0으로 본다; 값은 `row.get("value")`). 5행 한계(`top_rows=rows[:5]`), `row_count`(자르기 전 전체 행 수 = `len(rows)`), `summary` 문자열, 다른 operation 분기(`count`·`examples`), `domain/evidence.py`(`split_top_bottom` 자체), 상수·프롬프트는 바꾸지 않는다(변경은 정렬 한 줄과 키 함수 몇 줄). 입력(`bands.rows`)과 그래프 레코드 리스트는 변형하지 않는다.

**항목 25. 결과 카드 시안 이미지 칸 다듬기 ①(`results.css`만)**
- 구조는 step 17 그대로(칸 높이 채움, 메인 이미지 `object-fit: contain`, `.gs-design-backdrop`에 `cover`+`blur`). 바꾸는 것: (a) `.gs-design-image img.gs-design-backdrop`의 필터를 `blur(32px) brightness(0.78)`로, `transform: scale(1.2)`로(가장자리 투명 방지; `object-fit: cover`는 이 규칙에만, 규칙 전체 `object-fit: cover` 출현은 정확히 1번 유지). (b) **페이드 방식은 문구가 가려지지 않는 쪽을 골랐다 — 이미지 위아래의 전환 띠**: 메인 이미지에는 `mask-image`를 **걸지 않고**(시안 문구가 이미지 가장자리에 걸려도 가려지지 않는다), `.gs-design-image::before`·`::after`(칸의 위·아래 각 `14%` 높이, `position: absolute`, `inset-inline: 0`, `pointer-events: none`, `z-index`는 배경 이미지 위·메인 이미지 아래, `linear-gradient(to bottom|top, var(--gs-surface), transparent)`)로 흐린 배경이 칸 가장자리로 부드럽게 이어지게 한다. 메인 이미지 규칙은 `position: relative`로 띠 위에 오게 하고 `z-index`를 준다. 구현 중 위 방식이 시각적으로 어색하면 그대로 두고 완료 보고에 적어라(방식 변경은 하지 않는다).

**교체 단언**: 확정 충돌 없음(선점검). `tests/results.test.tsx` `fills the media slot with a contained image over a blurred backdrop and falls back on failure`의 `backdropRule`(`cover`·`blur(` 포함)·`object-fit: cover` 출현 1번·`mainRule` `contain` 단언은 **수정하지 않고 통과**해야 한다(수치 `24px`·`0.85`는 단언에 없다). 새 단언은 추가만 한다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `insightTotal`·`isOtherCategory`·`sortInsightRows`·`sortModelRows`·`insightLimitNote` | `web/lib/insight.ts` | `InsightPanel.tsx`, `DistributionChart.tsx`, `insight.test.ts`(기존 단언 불변) |
| `.gs-insight-head`·`.gs-insight-total`·`.gs-col-primary`·`.gs-col-muted` | `web/app/results.css` | `InsightPanel.tsx`, `DistributionChart.tsx`, 새 CSS 구조 단언 |
| 서버 행 정렬 | `src/beautyads/agents/tools.py` | `tests/test_agent_tools.py`(새 테스트), `agents/supervisor.py`·`api/ask_view.py`(읽기 전용) |
| 이미지 칸 띠·필터 | `web/app/results.css` | `results.test.tsx`(기존 단언 불변) |

**문서 동기화(DEMO.md, 이 step의 수정 허용 경로)**: `DEMO.md`의 리허설 확인 ㉑·㉒만 **같은 형식**(`뜻 —`·`판정 —`(칸마다 `(n) 이름: … O … X`, 번호 연속, 판정 안 괄호 문자 `(`·`)` 금지)·`예시 —`(하나)·`기록 방법 —`(`칸 번호별 O/X와 한 줄 메모`)·`결과 기록: ______.`)으로 갱신한다. 번호·개수(`⑰~㉗` 11개)·`tests/test_demo_docs.py`는 바꾸지 않는다. ㉑ (1)의 판정을 `시안 이미지: 이미지 칸이 카드 높이 전체를 채우고 시안 문구가 잘리지 않으며 남는 영역의 흐린 배경이 칸 위아래 가장자리로 부드럽게 이어지면 O, 아래 빈 여백이 생기거나 문구가 잘리거나 흐린 배경이 띠처럼 끊겨 보이면 X`로 바꾼다. ㉒는 기존 (5) 조회수 비교 뒤에 `(6) 총 건수: 경쟁사 광고 분포 카드 오른쪽 위에 현재 탭의 총 건수가 총 N건으로 보이고 탭을 바꾸면 값이 바뀌면 O, 없거나 다른 탭의 값이 남거나 상위·하위 카드에 총 건수가 보이면 X`, `(7) 기타 순서: 모든 차트와 표에서 기타 계열 행이 항상 맨 아래이고 나머지는 건수가 많은 순서이면 O, 기타가 중간에 섞이면 X`, `(8) 상위·하위 표: 상위 25% 광고 수 열이 굵게 앞에 있고 하위 25% 광고 수 열이 옅은 회색이며 행이 상위 광고 수 순서이고 설명 아래에 상위 25% 광고 수가 많은 분류부터 5개까지 표시한다는 한 줄이 있으면 O, 열 강조나 순서나 한 줄이 빠지면 X`를 추가한다(칸 번호 연속). `README.md`·`docs/PHASES.md`·`docs/portfolio/DETAIL_PAGE.md`는 위 변경으로 틀려지는 문구가 `rg`로 확인될 때만 맞추고 `docs/PHASES.md`의 `| 58 |` 행·`DETAIL_PAGE.md`의 수치 표 행·`docs/TROUBLESHOOTING_LOG.md`는 수정하지 않는다.

**시각 확인 필요(사용자 화면, 완료 보고에 항목별로 적는다)**: 경쟁사 광고 분포 카드 오른쪽 위 `총 N건`의 정렬과 탭 전환 값, `기타` 행이 모든 차트·표에서 맨 아래인지, 상위·하위 표의 굵은 열·옅은 회색 열·설명 아래 한 줄, 시안 이미지 칸의 흐린 배경(`blur(32px)`)과 위아래 전환 띠가 이미지 문구를 가리지 않고 부드럽게 이어지는지(1열 레이아웃 포함).

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/results/{InsightPanel,DistributionChart,PlanResult,DesignImage}.tsx`, `/web/lib/{insight,taxonomy,localize,types}.ts`, `/web/app/{results,tokens}.css`, `/DEMO.md`(리허설 확인 ㉑·㉒)
- `/src/beautyads/agents/tools.py`(`_run_evidence_tool`), `/src/beautyads/domain/evidence.py`(`split_top_bottom`, 읽기 전용·수정 금지), `/src/beautyads/agents/supervisor.py`(`_tool_outputs`, 읽기 전용), `/docs/EVAL.md`·`/docs/results/2026-11-20-p6-final.md`·`/tests/test_prereg.py`·`/tests/test_freeze_guard.py`(동결 확인, 읽기 전용)
- `/tests/test_agent_tools.py`(740~775행 부근 `top_vs_bottom_axis` 기존 단언, FakeGraph·`run_tool` 사용법), `/web/tests/{insight-panel,insight,results,history-page,taxonomy,contrast}.test.ts*`, `/tests/test_demo_docs.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/tools.py`(`operation == "rows"` 분기 정렬만), `tests/test_agent_tools.py`(새 테스트만), `web/lib/insight.ts`, `web/components/results/{InsightPanel,DistributionChart}.tsx`, `web/app/results.css`, `DEMO.md`(㉑·㉒만), `README.md`·`docs/PHASES.md`·`docs/portfolio/DETAIL_PAGE.md`(문구가 틀려지는 곳만), `web/tests/{insight-panel,insight,results}.test.ts*`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `src/beautyads/agents/tools.py`(`operation == "rows"` 분기 정렬만), `tests/test_agent_tools.py`(새 테스트만), `web/lib/insight.ts`, `web/components/results/{InsightPanel,DistributionChart}.tsx`, `web/app/results.css`, `DEMO.md`(㉑·㉒만), `README.md`·`docs/PHASES.md`·`docs/portfolio/DETAIL_PAGE.md`(문구가 틀려지는 곳만), `web/tests/{insight-panel,insight,results}.test.ts*`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** 동결 확인(위 `rg`를 코드 전에 재실행해 결과를 `summary`에 적는다). **2.** 서버(항목 24(b)): `tools.py` 정렬 몇 줄과 `tests/test_agent_tools.py` 새 테스트. **3.** 웹: `lib/insight.ts` 새 헬퍼, `InsightPanel.tsx`(제목 줄·총 건수·정렬·열 강조·설명 아래 한 줄), `DistributionChart.tsx`(열 강조·설명 아래 한 줄), `results.css`(머리 줄·강조 클래스·이미지 칸). **4.** 새 테스트 작성, `DEMO.md` 갱신. 모든 간격·색·반경·글자 크기는 `tokens.css` 변수만 쓴다. 마케터 화면에 영문 코드·내부 도구명·스키마 키를 표시하지 않는다(`data-tool` 속성은 원문 유지).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_agent_tools.py`(기존 단언 변경 없음, 새 테스트 추가, 합성 데이터만; `split_top_bottom`을 `tools` 모듈에서 가짜로 바꿔 `model_dump()`를 가진 행 객체를 돌려주게 하거나 FakeGraph 레코드로 만들되 더 단순한 쪽): (1) 분류 7개(알파벳 뒤쪽 `question`·`ugc_style` 포함)에서 `top_rows`가 5행이고 `n_top` 내림차순으로 잘려 알파벳 뒤쪽 분류가 누락되지 않는다, (2) `other`가 `n_top`이 가장 커도 5행 안에 들어갈 때 마지막 위치, (3) 동률은 `n_bottom` 내림차순 다음 값 오름차순, (4) `row_count`가 자르기 전 전체 행 수(예: 7)이고 `summary` 문자열과 5행 한계가 변하지 않는다, (5) 입력 레코드·`split_top_bottom`이 돌려준 객체의 순서가 변하지 않는다(새 리스트로 정렬), (6) `compare_axis_by_category`(`count`) 결과는 정렬 변경 없이 기존 순서 그대로, (7) 기존 `top_vs_bottom_axis` 단언(`output.top_rows[0]["n_top"] == 1`)은 수정 없이 통과.
- `web/tests/insight.test.ts`(기존 단언 변경 없음, 새 `it` 추가): (8) `isOtherCategory`(`other`·`기타`·`기타 훅`·`기타 각도`·`기타 포맷`·스키마 이름이 `기타 …`인 값은 true, `question`·`기타` 아닌 이름 false), (9) `sortInsightRows`: 건수 내림차순·동률은 입력 순서 유지(안정)·`other` 항상 마지막(건수가 가장 커도)·입력 배열 불변(JSON 스냅샷), (10) 상위·하위 도구는 `n_top` 내림차순→`n_bottom` 내림차순→기타 마지막, `creatives`가 없는 표 행은 `count`로, 숫자 아닌 값은 0으로, (11) `sortModelRows`(count 내림차순·기타 마지막·안정), (12) `insightTotal`: 모든 행의 `total`이 같은 정수이면 그 값, 값이 둘 이상·하나라도 없음·정수가 아님·빈 배열이면 `null`, (13) `insightLimitNote`(`top_vs_bottom_axis`만 정확한 문장, 나머지 `null`).
- `web/tests/insight-panel.test.tsx`(기존 단언 변경 없음, 새 `it` 추가): (14) `경쟁사 광고 분포` 카드에서 현재 탭 행의 `total`이 모두 같으면 제목 줄에 `총 N건`이 오른쪽 요소(`.gs-insight-head > .gs-insight-total`, heading 아님)로 보이고 탭을 바꾸면 그 탭의 값으로 바뀐다(탭마다 다른 값이 되는 입력), 값이 여러 개이거나 `total`이 없으면 요소가 없다, (15) `조회수 상위·하위 25% 광고 비교` 카드에는 `total`이 있어도 `총 N건`이 없다, (16) `variant="verification"`에서도 같은 규칙, (17) 행이 `other`·`question`·`problem`(건수 `1`·`3`·`3`) 순으로 들어오면 막대 `meter` 이름 순서가 `[question의 표시 이름, problem의 표시 이름, 기타 표시]`(동률 입력 순서, 기타 마지막)이고 검증 variant 원천 표 첫 열 값 순서가 같다(차트·원천 표 행 값·순서 일치), (18) 모델 작성값 차트 행이 기타 마지막·`count` 내림차순, (19) 상위·하위 표: 입력 `[{value:"a",n_top:1,n_bottom:5},{value:"other",n_top:9,n_bottom:9},{value:"b",n_top:3,n_bottom:1},{value:"c",n_top:3,n_bottom:4}]`이 `c`(3/4)→`b`(3/1)→`a`(1/5)→`other` 순이고 `n_top` 칸 `th`·`td` 안에 `span.gs-col-primary`(그 `textContent`는 헤더 문구·숫자 그대로), `n_bottom` 칸 `th`·`td` 안에 `span.gs-col-muted`, 열 제목 배열은 `["분류","상위 25% 광고 수","하위 25% 광고 수"]`, (20) 설명 문장 다음 형제 `<p class="gs-insight-note">`가 `상위 25% 광고 수가 많은 분류부터 5개까지 표시합니다.`이고 `h3`의 바로 다음 형제는 여전히 설명 문장이다, (21) 모든 입력 분포·`modelCharts`는 변하지 않는다(JSON 스냅샷).
- `web/tests/results.test.tsx`(기존 단언 변경 없음, 새 `it` 추가): (22) CSS 구조: `results.css`에서 `.gs-design-image img.gs-design-backdrop` 규칙에 `blur(32px)`·`brightness(0.78)`·`scale(1.2)`, 메인 이미지 규칙(`.gs-design-image img`)에 `mask-image`가 없고(문구 보호), `.gs-design-image::before`·`::after` 규칙이 `14%`·`linear-gradient(`·`pointer-events: none`을 갖고 `var(--gs-surface)`를 쓴다(새 색 하드코딩 금지: 정규식으로 `#` 색 문자열이 이 규칙에 없다), 규칙 전체의 `object-fit: cover` 출현은 여전히 1번, (23) `.gs-insight-head`가 `justify-content: space-between`, `.gs-insight-total`이 `var(--gs-text-muted)`, `.gs-col-primary`가 `font-weight: 700`, `.gs-col-muted`가 `var(--gs-text-muted)`를 쓴다.
- `web/tests/history-page.test.tsx`·`taxonomy.test.tsx`·`contrast.test.ts`: 기존 단언 변경 없음. `contrast.test.ts`의 기존 `--gs-text-muted`/`--gs-bg` 쌍 단언이 `.gs-col-muted`·`.gs-insight-total` 색의 대비 근거이므로 새 색 토큰을 만들지 않는다.
- 해시 시드·집합·객체 순회 순서에 기대는 새 단언을 만들지 마라(리스트·명시적 순서로 단언). 합성 데이터만 쓴다.
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
- 기존 단언을 수정·삭제·약화하지 마라(이 step의 교체 단언 표는 비어 있다). 새 테스트만 추가하라. 실제로 깨지는 기존 단언이 나오면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체가 없다.
- 서버 변경은 `src/beautyads/agents/tools.py`의 `operation == "rows"` 분기 정렬 몇 줄뿐이다. `5행 자르기`(`top_rows=rows[:5]`)·`row_count`·`summary` 문자열·다른 operation 분기·`src/beautyads/domain/evidence.py`(`split_top_bottom`)·상수·프롬프트·`src/beautyads/api/`·`config/`·`docs/EVAL.md`·`docs/results/`·`tests/test_prereg.py`·`tests/test_freeze_guard.py`·`tests/test_e3_live.py`·`tests/test_research_agent.py`·`tests/test_domain_supervisor.py`를 수정하지 마라(뒤 세 테스트와 `tests/test_agent_tools.py`의 기존 단언은 수정 없이 통과해야 한다). 동결 확인에서 고정이 발견되면 서버 변경만 보류하라. 이유: 동결 값·사전 등록은 결과를 본 뒤 바꾸지 않는다.
- `insightDescription`(설명 문장)·`insightColumnName`·카드 제목·열 제목 문구를 바꾸지 마라(설명 아래 한 줄은 별도 `insightLimitNote`). 단독 `DistributionChart`(`InsightPanel` 밖)의 정렬·막대·표 출력을 바꾸지 마라(열 강조 클래스·설명 아래 한 줄만 추가). 서버가 보낸 분포·`model_written` 원본 객체를 변형하지 마라(복사본만 정렬). `조회수 상위·하위 25% 광고 비교` 카드에 총 건수를 만들지 마라. 이유: 기존 단언과 데이터 불변.
- 시안 이미지의 메인 `<img>`에 `mask-image`를 걸지 마라(문구가 가려질 수 있다). `results.css`의 `object-fit: cover`를 `.gs-design-backdrop` 규칙 밖에 쓰지 마라. 새 색을 하드코딩하지 마라(토큰만). 이유: 시안 문구 보호와 시각 기준.
- `web/components/ui/*`(`DataTable` 포함)를 수정하지 마라(열 강조는 `header`·`render` 안 `span`으로). 이유: ui 키트 테스트와 범위.
- 6b-clarify 동작·`web/lib/reducer.ts`·`web/components/plan/*`·`web/components/shell/*`를 수정하지 마라. 새 패키지를 설치하지 마라. 이유: 범위 분리.
- `docs/PHASES.md`의 `| 58 |` 행, `docs/portfolio/DETAIL_PAGE.md`의 수치 표 행, `docs/TROUBLESHOOTING_LOG.md`, `DEMO.md`의 ⑰~㉗ 번호·개수·형식 규칙(`뜻 —`·`판정 —`·`예시 —`·`기록 방법 —`, 칸 번호 연속, 판정 안 괄호 문자 금지, `결과 기록: ______.`)을 깨지 마라. 사용자 live 결과를 지어내지 마라. 이유: 문서 가드 테스트.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
