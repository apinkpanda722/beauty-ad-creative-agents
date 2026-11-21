# Step 16: history-verify-polish

## 설계 검토 기록

**목적**: 7c 시각 확인에서 사용자가 지적한 실행 기록·검증·결과 표 정리 4건(항목 6~9)을 한 step으로 처리한다. 새 패키지·서버 변경·live 호출 없음. 아래 "교체 단언" 표에 적힌 것만 기존 단언을 바꾸고 그 밖의 기존 단언은 수정하지 않는다. 목록 밖에서 충돌을 발견하면 구현하지 말고 `blocked`로 멈추고 최소 교체안을 `reason`에 적어라(임의로 단언을 고치지 않는다). `tests/test_taxonomy_freeze.py`와 `src/beautyads/domain/labels.py`는 건드리지 않는다(서버 스키마 이름 `욕구`는 그대로, 화면 표시 이름만 바꾼다).

**코드를 열어 확인한 사실**
- `web/components/history/HistoryDetail.tsx`: `Tabs` 4개(`stages`·`verification`·`evaluation`·`cost`). 단계 탭은 `summary.progress`(`deriveProgress`)의 단계 `<li>`(`data-status`, `stage.id === "plan_eval"`이 `기획·평가` 단계, 재작업 `Badge`)와 `기획 N회 · 평가 N회` 문장. 평가 탭이 시도별 `<section class="gs-history-evaluation">`(제목 `평가 시도 보기 · 되돌림 N회`, 시도 `<li>`: `시도 N`, `시도 코드 검사: … · 최종 판정: …`(`checkLabel`: `미실행`/`통과`/`실패`), 점수 `차별성 (differentiation): N`, `사유: …`(`localizeText`), `재검토 항목: …`, `시도 텍스트 비용 $…`)을 그린다. 비용 탭은 `CostDetail`과 시도별 `시도 N · 시도 텍스트 비용 …` 목록. 검증 탭은 `검사 결과` 카드(`section.gs-plan-checks.gs-detail-card`, `근거 연결 없음 N건` 배지 등), `AggregatesPanel`, 분포 원천 `section.gs-history-source`(`<span class="gs-source-chip">{data.tool}</span>` + `DataTable` caption `시장 인사이트 원천 데이터`, 열은 모든 행의 키 합집합, 값이 `null`·객체면 `—`).
- `web/components/results/AggregatesPanel.tsx`: `Card` 하나에 섹션 3개(`aria-label` `검증된 집계(도구가 센 값)`(`h3` + `Badge` `검증됨` + 항목 `<li><span class="gs-source-chip">{item.tool}</span>: <span>{count_label}</span><p>전체 {row_count}건 · 표시 {shown_count}건</p></li>`), `모델 작성값`(`h4` `{data.label}` + `미검증` + `dl`: `dt` 이름·`dd` 값), `제외된 값`(`h4` + `제외됨` + 설명 문장 + `li`)). 세 블록이 모두 비면 `null`을 돌려준다. `web/app/globals.css` 57~58행에 옛 규칙 `.verified-block { background: #f3f8f5; border-color: #78968c !important }`·`.model-block, .removed-block { background: #f5f5f5 }`(연한 녹색·회색 전체 폭 배경, 제목이 모서리에 걸리는 원인)이 있고, `results.css`의 `.gs-aggregates section + section`은 위 구분선이다.
- `web/components/results/PatternAlignment.tsx`: 표 열 제목 `["축", "기획안", "지배 패턴", "같음/다름", "점유율"]`, 셀 `기획안: {값}`·`경쟁사 지배 패턴: {값}`, 일치 여부 `<span class="pattern-fact">같음|다름|비교 불가</span>`, 점유율 셀(`share`가 없으면 `점유율 비교 불가`, 있으면 `25.0%` 형식), 표 아래 `<small>{label}</small>`(`pattern_alignment_label`, `PlanResult.tsx` 92행이 `label={data.pattern_alignment_label}`로 전달), 문장 `비교한 축 N개 중 같은 축 N개`, region 이름 `경쟁사 패턴 반영`. 축 이름 `{hook_type:"훅", angle:"소구", format:"형식"}`이 이 파일에 있다.
- `web/lib/insight.ts`: `TOOL_TITLES`(키 10개, `tests/insight.test.ts`가 키 목록 정확 일치를 단언), `insightTitle(tool, values)`(`top_vs_bottom_axis`면 `TOOL_TITLES[tool]`), `columnName(key)`(`n_top: "상위 25%"`, `n_bottom: "하위 25%"`; `tests/insight.test.ts`가 `columnName`의 정확 값을 단언), `insightValue`. `DistributionChart.tsx`가 제목 `h3`과 막대·표를 그리고 표 열 이름은 `columnName(key)`다.
- `web/lib/taxonomy.ts`: `taxonomyNames(schema)`의 `axisName(axis, value)`와 `valueName(value)`가 스키마 이름(없으면 원문)을 돌려준다. `web/lib/localize.ts`의 `displayValue`·`localizeText`가 이를 쓴다. `localizeText`는 정확한 식별자 토큰(가장 긴 것 우선)만 바꾸고 `:`가 든 토큰·`other`는 보호한다.
- 서버 닫힌 목록 `src/beautyads/domain/labels.py`의 소구 값: `problem_solution`, `desire`(서버 이름 `욕구`), `social_proof`, `comparison`, `ingredient_science`, `how_to`, `other`.

**설계 결정**

6. **평가 탭 삭제와 시도 줄 이동(`HistoryDetail.tsx`, `history.css`)**: 탭은 `단계`·`검증`·`비용` 3개다(평가 탭·`gs-history-evaluation` 섹션 삭제). 단계 탭의 `plan_eval`(`기획·평가`) 단계 `<li>` 아래에 시도별 한 줄 목록(`<ul class="gs-history-attempts">`, 시도마다 `<li>` 하나, 텍스트는 한 개의 문자열)을 둔다. 형식(정확): `시도 {N} · 검사 {통과|실패|미실행} · 최종 {통과|실패|미실행} · 차별성 {a}/5 · 요청 적합성 {b}/5`이고 `low_items`가 있으면 같은 줄 끝에 ` · 재검토: {한글 점수 이름들을 ", "로 이은 것}`을 붙인다(예: `시도 1 · 검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성`). 점수(`scores.differentiation`·`scores.fit`)가 숫자가 아니면 그 항목만 생략하고, 점수 이름은 `scoreNames`(`차별성`·`요청 적합성`)를 쓰며 `low_items`의 모르는 코드는 `기타`(기존 규칙)다. **영문 코드 병기(`(differentiation)`)와 모델이 쓴 사유 문장(`rationale`)은 어디에도 표시하지 않는다**(`사유:` 문구 없음). 기획안이 둘 이상이면 기획안마다 작은 라벨 줄 `기획안 N`을 앞에 두고 그 아래에 시도 줄을 둔다(시도 줄 형식은 그대로). 시도가 없으면 아무것도 그리지 않는다(`정보 없음` 자리표시를 만들지 마라: 기존 단언이 단계 탭의 `정보 없음` 개수를 센다). 시도별 텍스트 비용은 비용 탭의 기존 표시를 그대로 둔다. `turn`과 그 `commands`·`attempts` 입력 객체는 변형하지 않는다(JSON 스냅샷 검사). `web/lib/localize.ts`의 `localizeText`와 `tests/localize.test.ts`는 삭제하지 않는다(컴포넌트에서 쓰지 않게 되면 완료 보고에 "미사용" 한 줄만 적는다; 아래 7번이 `localizeText`를 집계 표시에 쓰므로 실제로는 쓰인다).
7. **검증 탭 정리(`HistoryDetail.tsx`, `AggregatesPanel.tsx`, `localize.ts`, `insight.ts`, `globals.css`, `history.css`, `results.css`, `tokens.css`)**: 검증 탭의 위에서 아래 구성은 (a) 기획안마다 `검사 결과` 카드, (b) `show_aggregates` 명령마다 집계 카드 1개, (c) 시장 인사이트 원천 영역 1개이고 **서로 형제이며 카드 안에 카드를 만들지 않는다**.
   - **검사 결과 카드**: 지금 문구·요소 그대로(`근거 연결 없음 N건` 배지, `unknown_codes` 한글 목록, `코드 검사: …`, `평가 상태: …`). 서버의 `pattern_alignment_label`(코드 계산, 판정 아님; 값은 서버 문구 그대로)을 이 카드 **안**의 작은 회색 문장(`<small class="gs-pattern-label muted">`)으로 옮긴다(`PatternAlignment`에서는 삭제: 8번).
   - **집계 카드 1개(`AggregatesPanel`)**: `도구가 센 값(검증됨)` / `모델 작성값(미검증)` / `제외된 값(제외됨)` 세 블록, 섹션 `aria-label`(`검증된 집계(도구가 센 값)`·`모델 작성값`·`제외된 값`)·제목·배지 문구(`검증됨`·`미검증`·`제외됨`)·각 항목 텍스트(`count_label`, 모델 항목 이름·값, 제외 항목)는 그대로. **`전체 N건 · 표시 N건` 줄은 삭제**한다. 출처 칩은 영문 도구명 대신 **한글 제목**을 보이고(`insight.ts`에 `toolTitle(tool)`을 추가: `TOOL_TITLES`에 있으면 그 제목, 없으면 `집계 항목`; `TOOL_TITLES`의 키 집합은 바꾸지 않는다), raw 도구명은 칩의 `data-tool` 속성으로만 남긴다(클래스 `gs-source-chip` 유지). **모델 작성값의 이름과 값의 영문 코드는 표시할 때만 한글로 치환**한다(`localizeText(문자열, names)` 사용: `sun_protection`·`hook_type`·`person_first`·`angle`·`how_to`·`format`·`ugc_style` 등. 원본 `data` 객체는 변형하지 않는다. 사전에 없는 이름·값은 기존 규칙대로 원문 그대로다). `AggregatesPanel`은 선택적 `names` prop(기본 `taxonomyNames()`)을 받고 `HistoryDetail`이 넘긴다. `localize.ts`에 축 코드 단어 사전 `axisNames = { hook_type: "훅", angle: "소구", format: "형식" }`을 내보내고(`PatternAlignment`가 같은 사전을 import해 쓴다) `localizeText`가 이 토큰도 치환한다(단어 전체 일치·`:` 토큰 보호·`other` 보호 규칙은 그대로).
   - **시장 인사이트 원천 표(`HistoryDetail.tsx`)**: 기본 **접힘**. 하나의 토글 버튼 **`원천 데이터 보기 (N)`**(N = `show_distribution` 명령 수, 0이면 영역 자체를 그리지 않음)이 모든 원천 표를 한꺼번에 연다(`aria-expanded`, `aria-controls`, 열림 상태면 버튼 이름은 `원천 데이터 접기 (N)`). 표마다 칩을 반복하지 않고 표 위에 **한글 제목 한 줄**(`toolTitle`이 아니라 `DistributionChart`가 쓰는 `insightTitle(data.tool, 막대 값들)`을 재사용해 차트 제목과 같게)을 둔다. 표의 `caption` `시장 인사이트 원천 데이터`와 `section` `aria-label` `시장 인사이트 원천`은 그대로. 열은 모든 행의 키 합집합이되 **모든 행에서 렌더 결과가 `—`인 열(현재 `항목`으로 보이는 객체·`null` 열)은 만들지 않는다**. 열 제목은 `insightColumnName(tool, key)`(아래 9번). 접힘·펼침은 공통 시각 기준대로 `grid-template-rows: 0fr → 1fr` 아코디언이다(`PlanResult.toggle()`과 같은 절차를 이 컴포넌트 안에 로컬로 구현하고 공유 훅·ui 키트 변경은 하지 마라: 펼칠 때 `hidden`을 동기적으로 제거하고 다음 프레임에 열림 클래스, 접을 때는 전환 뒤 `hidden`, reduced-motion·전환 시간 0이면 즉시).
   - **레이아웃**: 카드 안에 연한 녹색·회색 전체 폭 배경 블록을 만들지 않는다 → `globals.css`의 옛 `.verified-block`·`.model-block`·`.removed-block` 배경·`!important` 규칙은 삭제하고(이 클래스는 `AggregatesPanel`만 쓴다), 블록 구분은 기존 `.gs-aggregates section + section`의 위 구분선과 배지 글자·색으로 한다(색에만 의존하지 않음). 카드 padding과 섹션 간격은 토큰 두 개(`tokens.css`의 `--gs-card-padding: var(--gs-space-5)`, `--gs-section-gap: var(--gs-space-4)`)로 통일해 `.gs-aggregates`·`.gs-history-page .gs-plan-checks`(검사 결과 카드)·`.gs-history-source`가 같은 토큰을 쓴다(`.gs-distribution`의 기존 padding 선언이 `results.css`에 있으므로 새 토큰으로 바꿔도 되고, 그 규칙의 다른 선언은 건드리지 마라).
   - **소구 값 이름 교체(표시층만)**: `web/lib/taxonomy.ts`의 `taxonomyNames`가 소구(`angle`)의 `desire`를 해석하는 **한 곳**에 표시 이름 덮어쓰기를 둔다: `axisName("angle", "desire")`와 `valueName("desire")`는 스키마가 있든 없든 서버 이름(`욕구`)이나 빈 이름과 상관없이 **`이상형 제시형`**을 돌려준다. 다른 소구 값(`problem_solution`·`social_proof`·`comparison`·`ingredient_science`·`how_to`)의 이름은 서버 이름 그대로(스키마 없으면 원문)다. 이로써 시장 인사이트 차트, 원천 표, 경쟁사 패턴 표, 검증 탭, `localizeText`의 단어 치환, 근거 소재 카드가 같은 이름을 쓴다. 원본 데이터 객체는 변형하지 않는다. (`web/lib/graph.ts`가 `axisName`을 쓰므로 지식 그래프의 소구 노드 이름도 같은 표시 이름이 된다. 이는 의도된 결과다.)
8. **경쟁사 패턴 반영 표 용어(`PatternAlignment.tsx`, `PlanResult.tsx`)**: 근거: 시장 내 비중 = 기획안이 고른 방식을 쓴 경쟁사 광고 수 ÷ 전체 경쟁사 광고 수(`src/beautyads/agents/supervisor.py`), 경쟁사 최다 방식 = 같은 분류에서 가장 많이 쓰인 방식. 열 제목을 `["축", "기획안", "경쟁사 최다 방식", "일치 여부", "시장 내 비중"]`으로 바꾼다. 셀 앞의 `기획안: `·`경쟁사 지배 패턴: ` 접두는 삭제하고 값만 둔다(값이 없으면 기존처럼 `정보 없음`). 각 열 `th`에 `title`로 뜻을 단다(예: `경쟁사 최다 방식`: 같은 분류의 경쟁사 광고 중 가장 많이 쓰인 방식, `시장 내 비중`: 경쟁사 광고 전체 중 기획안과 같은 방식을 쓴 광고의 비율, `일치 여부`: 기획안의 방식이 경쟁사 최다 방식과 같은지). 표 아래에 고정 문장 두 줄을 각각 별도 요소로 둔다: `경쟁사 최다 방식: 같은 분류의 경쟁사 광고 중 가장 많이 쓰인 방식` / `시장 내 비중: 경쟁사 광고 전체 중 기획안과 같은 방식을 쓴 광고의 비율`. 일치 여부 값 문구 `같음`·`다름`·`비교 불가`는 그대로, 비중이 없으면 셀은 `비교 불가`(옛 `점유율 비교 불가` 문구는 없어진다), 있으면 기존처럼 `25.0%` 형식. 패널 안 `<small>{label}</small>`(`코드 계산, 판정 아님`)은 삭제하고 `PatternAlignment`의 `label` prop과 `PlanResult.tsx`의 전달을 지운다(문구는 7번의 검사 결과 카드로 이동했다). `비교한 축 N개 중 같은 축 N개` 문장과 region 이름 `경쟁사 패턴 반영`은 그대로다. 축 이름은 `localize.ts`의 `axisNames`를 쓴다.
9. **상위 vs 하위 비교 표(`insight.ts`, `DistributionChart.tsx`, `HistoryDetail.tsx`)**: 근거: 같은 출처·브랜드 안 조회수 상위·하위 25% 광고가 각 방식을 쓴 광고 수(`src/beautyads/agents/tools.py`, `metrics.py`). `TOOL_TITLES.top_vs_bottom_axis`를 **`조회수 상위·하위 25% 광고 비교`**로 바꾼다(`insightTitle`·`toolTitle`·칩·차트 제목이 모두 이를 쓴다). 제목 아래에 한 문장 `같은 플랫폼·브랜드 안에서 조회수 상위 25%와 하위 25% 광고가 각 방식을 쓴 광고 수입니다.`(`<p class="gs-insight-note">`, 이 도구일 때만, 제목 `h3`은 그대로 하나)를 둔다. `insight.ts`에 `insightDescription(tool): string | null`과 `insightColumnName(tool, key)`를 추가한다: `top_vs_bottom_axis`이면 `n_top` → `상위 25% 광고 수`, `n_bottom` → `하위 25% 광고 수`, `value` → `분류`, 그 밖의 열과 다른 도구는 기존 `columnName(key)`로 위임한다. **기존 `columnName`은 수정하지 마라**(`tests/insight.test.ts`의 `columnName("n_top") === "상위 25%"` 단언이 그대로 통과해야 한다). 결과 화면 차트(`DistributionChart`)와 검증 탭 원천 표가 모두 `insightColumnName(data.tool, key)`와 `insightDescription`을 쓴다(원천 표는 접힌 영역 안의 표 제목 아래).

**교체 단언(조언 세션 승인분. 이 표 밖의 기존 단언은 수정하지 마라. 행은 HEAD 27eedd0 기준이고 step 15가 단언을 추가해 행이 어긋나면 테스트 이름으로 찾는다)**

| # | 파일·행 | 이전 | 이후 |
|---|---|---|---|
| T1 | `web/tests/localize.test.ts` 14~20행 `it.each`의 입력 16행 | 입력 목록의 `"desire other question"`이 `localizeText`로 원문 그대로 | 이 입력 하나만 목록에서 빼고(나머지 8개 입력은 `toBe(text)` 그대로) 같은 엄격도의 별도 단언 `expect(localizeText("desire other question", names)).toBe("이상형 제시형 other question")`으로 교체. 보강: 스키마 없는 `taxonomyNames()`에서도 `localizeText("desire")`가 `"이상형 제시형"`, `how_to problem_solution social_proof comparison ingredient_science`는 서버 이름이 없을 때 원문 그대로 |
| T2 | `web/tests/history-page.test.tsx` 81~87행 `it("keeps every attempt's exact check, score, review and cost wording, localizing only displayed rationale")` 전체 | 평가 탭에서 `되돌림 1회` 배지, `.gs-history-attempt` 2개·`gs-history-reworked`, `차별성 (differentiation): 2` 등 문구 목록, `사유: 사용법 대비 차별성, 요청 적합성. profit`, JSON 스냅샷 불변 | 단계 탭의 시도 줄: `시도 1 · 검사 실패 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성`, `시도 2 · 검사 통과 · 최종 통과 · 차별성 4/5 · 요청 적합성 5/5`(정확 일치, 각각 `li` 하나), 탭 목록에 `평가` 탭 없음(`queryByRole("tab", { name: "평가" })`가 null, 탭 3개), 화면 어디에도 `(differentiation)`·`사유:` 문구 없음(`container.textContent`), `JSON.stringify(turn)` 스냅샷 불변 |
| T3 | `web/tests/history-page.test.tsx` 68~80행 `it("moves checks and all three aggregate blocks with labeled provenance and identical chart source values")` | (a) 70행 문구 목록의 `"전체 10건 · 표시 2건"`이 존재, (b) 72행 `getAllByText(distribution.tool)`이 모두 `gs-source-chip`, (c) 73행 원천 표를 바로 조회, (d) 74행 열 제목 `["분류", "상위 25%", "하위 25%"]` | (a) `"전체 10건 · 표시 2건"` 부재(`queryByText`가 null, `count_label` `합성 전체 10건 중 2건 표시` 단언은 그대로), (b) 칩의 `data-tool === "top_vs_bottom_axis"`이고 칩 텍스트가 한글 제목 `조회수 상위·하위 25% 광고 비교`(`.gs-source-chip` 클래스 유지), (c) 원천 표 조회 전에 `원천 데이터 보기` 버튼을 클릭 한 단계 추가(클릭 전에는 표가 접근 트리에 없음), (d) 열 제목 `["분류", "상위 25% 광고 수", "하위 25% 광고 수"]`. 행 값 `[["질문형","7","2"],["사용법","3","1"]]`과 차트 행과의 정확 일치 비교는 그대로 |
| T4 | `web/tests/results.test.tsx` 148행 `it("renders separate code checks, evaluation state, unknown badge, neutral pattern and raw taxonomy fallback")` | `expect(screen.getByText("question")).toBeTruthy();` | `const raw = screen.getAllByText("question"); expect(raw).toHaveLength(3);` + 하나는 `.gs-plan-summary .gs-result-badges` 안, 나머지 둘은 region `경쟁사 패턴 반영` 안에 있음을 단언(접두 삭제로 패턴 표 셀 두 곳이 정확히 `question`이 된다. 스키마 없을 때 원문으로 폴백한다는 의도는 같고 개수를 정확 일치로 고정) |
| T5 | `web/tests/results.test.tsx` 149행 | 문구 목록에 `"점유율 비교 불가"` | 이 항목만 삭제(`비교 불가`는 이미 목록에 있다) |
| T6 | `web/tests/results.test.tsx` 154~156행(같은 테스트) | `selectAuditTab("평가")`, `/되돌림 0회/`, `/차별성 \(differentiation\): 2/` | `selectAuditTab("단계")`, `getByText("재작업 0회")`, `getByText("시도 1 · 검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성")` |
| T7 | `web/tests/results.test.tsx` 370~387행 `it("keeps evaluation attempts in the inactive detail tab and reveals every attempt's checks, scores, review items and costs")` | 평가 탭의 숨김→표시, `ol` 항목 2개의 `textContent` 포함 문구(영문 병기 점수·`재검토 항목`·`시도 코드 검사`·`시도 텍스트 비용`) | 이름을 `keeps every evaluation attempt's checks, scores and review items in the default stage tab and costs in the cost tab`로 바꾸고: 단계 탭이 기본 선택이라 시도 줄이 `[hidden]` 안에 있지 않고, 줄 2개가 정확 일치(`시도 1 · 검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성`, `시도 2 · 검사 실패 · 최종 실패 · 차별성 4/5 · 요청 적합성 5/5 · 재검토: 요청 적합성`), 비용은 `selectAuditTab("비용")`에서 `시도 2 · 시도 텍스트 비용 $0.0123`, `평가` 탭 없음 |
| T8 | `web/tests/results.test.tsx` 425·428행 `it("shows a compact horizontal plan summary with a placeholder and preserves every detail in the DOM")` | 425행 숨김 목록에 `"평가 시도 보기 · 되돌림 0회"`, 428행 `within(selectAuditTab("평가")).getByText("평가 시도 보기 · 되돌림 0회")`가 `[hidden]` 아님 | 425행 목록에서 그 항목만 제거(나머지 항목은 `.closest("[hidden]")` truthy 그대로), 428행은 `within(selectAuditTab("단계")).getByText("시도 1 · 검사 통과 · 최종 실패 · 차별성 2/5 · 요청 적합성 3/5 · 재검토: 차별성").closest("[hidden]")`가 null이고 `평가` 탭이 없음(`queryByRole("tab", { name: "평가" })` null) |
| T9 | `web/tests/results.test.tsx` 642~653행 `it("localizes rationale only when displaying it, preserving numeric scores and the input object")` | `selectAuditTab("평가")`, `차별성 (differentiation): 3`·`요청 적합성 (fit): 4`, `사유: 합성 소구 대비 차별성, 요청 적합성. profit youtube:how_to` | `selectAuditTab("단계")`에서 `시도 1 · 검사 통과 · 최종 미실행 · 차별성 3/5 · 요청 적합성 4/5`가 정확히 있고, 화면 어디에도 `사유:`·`rationale`·`합성 소구 대비`·`(differentiation)` 문구가 없고(`document.body.textContent`), `JSON.stringify(data)`가 스냅샷과 같다(입력 객체 불변). 테스트 이름은 `never displays the model-written rationale and leaves the input object unchanged`로 바꾼다. 기존 `품질 검사 통과 · 평가 차별성 3/5, 요청 적합성 4/5` 단언은 그대로 |
| T10 | `web/tests/results.test.tsx` 약 620~621행 `it("cards each detail section, numbers scenes, quotes copies and tabulates neutral pattern facts")` | 열 제목 `["축", "기획안", "지배 패턴", "같음/다름", "점유율"]`, 문구 목록에 `"점유율 비교 불가"` | 열 제목 `["축", "기획안", "경쟁사 최다 방식", "일치 여부", "시장 내 비중"]`(정확 일치), 문구 목록에서 `"점유율 비교 불가"`만 삭제(`같음`·`다름`·`비교 불가` 각각 단독 요소 단언과 `25.0%` 단언은 그대로) |
| T11 | `web/tests/results.test.tsx` 666~667행 `it("renders market insights with Korean titles and columns, without tool captions, and retains meter names")` | 제목 `상위 vs 하위 광고 비교`, 열 `["분류", "상위 25%", "하위 25%"]` | 제목 `조회수 상위·하위 25% 광고 비교`, 열 `["분류", "상위 25% 광고 수", "하위 25% 광고 수"]`. 나머지(`caption` 없음, 도구 이름 비노출, `기타`·meter 이름, 개수, `accent-color`)는 그대로 |
| T12 | `web/tests/insight.test.ts` 5행 | `["top_vs_bottom_axis", ["question"], "상위 vs 하위 광고 비교"]` | 제목만 `조회수 상위·하위 25% 광고 비교`로(20행의 `TOOL_TITLES` 전체 `insightTitle` 일치 단언과 15~19행 키 목록은 수정 없이 통과) |
| T13 | `web/tests/results.test.tsx` 약 143~185행의 `Audit` 기반 집계 단언(`it("keeps aggregate provenance in three distinct blocks, including removed-only and empty")`) | 수정 불필요(집계 카드의 `aria-label`·제목·`count_label`·모델 값·제외 항목·빈 패널 `innerHTML === ""` 그대로 통과해야 한다) | 변경 없음(회귀 확인용으로 이 표에 남김) |

`"keeps only marketer summaries…"`(`results.test.tsx` 677행 부근)와 411행의 `평가 시도 보기 · 되돌림 0회` 부재 단언은 계속 참이라 **수정하지 않는다**.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `toolTitle`·`insightDescription`·`insightColumnName` | `web/lib/insight.ts` | `AggregatesPanel.tsx`, `DistributionChart.tsx`, `HistoryDetail.tsx`, `insight.test.ts` |
| `axisNames` | `web/lib/localize.ts` | `PatternAlignment.tsx`, `localizeText`, `localize.test.ts` |
| `angle.desire` 표시 이름 덮어쓰기 | `web/lib/taxonomy.ts` | `displayValue`·`localizeText`·`PatternAlignment`·`DistributionChart`·`HistoryDetail`·`EvidenceCardView`·`graph.ts`, 새 `taxonomy.test.tsx` |
| `--gs-card-padding`·`--gs-section-gap` | `web/app/tokens.css` | `results.css`, `history.css`, CSS 구조 테스트 |
| 시도 줄 목록 | `web/components/history/HistoryDetail.tsx` | `history-page.test.tsx`, `results.test.tsx` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/history/HistoryDetail.tsx`, `/web/components/results/{AggregatesPanel,PatternAlignment,DistributionChart,PlanResult,ResultsView}.tsx`, `/web/lib/{insight,localize,taxonomy,graph,history,stages,unknown}.ts`, `/web/app/{globals,results,history,tokens}.css`
- `/src/beautyads/agents/{supervisor,tools}.py`(점유율·상위/하위 정의, 읽기 전용), `/src/beautyads/domain/labels.py`(소구 닫힌 값, 읽기 전용)
- `/web/tests/{history-page,results,insight,localize,tabs,plan}.test.ts*`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/{taxonomy,localize,insight}.ts`, `web/components/history/HistoryDetail.tsx`, `web/components/results/{AggregatesPanel,PatternAlignment,DistributionChart,PlanResult}.tsx`, `web/app/{globals,results,history,tokens}.css`, `web/tests/{taxonomy.test.tsx,localize.test.ts,insight.test.ts,history-page.test.tsx,results.test.tsx}`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/{taxonomy,localize,insight}.ts`, `web/components/history/HistoryDetail.tsx`, `web/components/results/{AggregatesPanel,PatternAlignment,DistributionChart,PlanResult}.tsx`, `web/app/{globals,results,history,tokens}.css`, `web/tests/{taxonomy.test.tsx,localize.test.ts,insight.test.ts,history-page.test.tsx,results.test.tsx}`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `taxonomy.ts`(`desire` 표시 이름), `localize.ts`(`axisNames`), `insight.ts`(`toolTitle`·`insightDescription`·`insightColumnName`, 새 제목). **2.** `PatternAlignment.tsx`·`PlanResult.tsx`(표 용어·`label` prop 제거). **3.** `AggregatesPanel.tsx`·`DistributionChart.tsx`. **4.** `HistoryDetail.tsx`(평가 탭 삭제·시도 줄·검사 카드의 라벨 문장·원천 표 토글). **5.** `globals.css`·`results.css`·`history.css`·`tokens.css`. **6.** 테스트(아래). 위 설계 결정 6~9와 "교체 단언" 표를 그대로 구현한다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/taxonomy.test.tsx`(새, 입력 객체는 합성): (1) `taxonomyNames`(스키마 있음·없음·`angle`의 `desire` 이름이 `욕구`이거나 빈 이름인 스키마, 모두)에서 `axisName("angle", "desire")`와 `valueName("desire")`가 `이상형 제시형`, (2) 소구의 다른 값 `problem_solution`·`social_proof`·`comparison`·`ingredient_science`·`how_to`는 스키마 이름 그대로(스키마 없으면 원문), (3) `compare_axis_by_category`의 소구 행 `{ value: "desire", creatives: 3 }`가 `DistributionChart` 차트 행·`HistoryDetail`의 원천 표(펼친 뒤)·`PatternAlignment`(`dominant: ["desire"]`) 패턴 표에서 모두 `이상형 제시형`으로 보인다, (4) 세 화면 렌더 결과(`container.textContent`) 어디에도 `욕구` 문자열이 없다(스키마가 `욕구`를 내려줘도), (5) 입력 객체(`rows`·`pattern_alignment`·스키마)의 JSON 스냅샷이 렌더 전후 같다.
- `web/tests/localize.test.ts`: 교체 T1만, 새 단언 추가: (6) `hook_type angle format`이 `훅 소구 형식`으로 바뀌고 `how_to_use`·`youtube:angle`·`angles`는 그대로.
- `web/tests/insight.test.ts`: 교체 T12만. 새 단언: (7) `toolTitle`(`top_vs_bottom_axis` → 새 제목, `compare_axis_by_category` → `카테고리별 광고 비교`, 모르는 도구 → `집계 항목`), (8) `insightDescription`(`top_vs_bottom_axis`만 설명 문장, 나머지는 `null`), (9) `insightColumnName("top_vs_bottom_axis", "n_top")` = `상위 25% 광고 수`, `n_bottom` = `하위 25% 광고 수`, `value` = `분류`, 다른 도구나 다른 키는 `columnName`과 같다, (10) `columnName("n_top")`는 `상위 25%` 그대로(기존 단언).
- `web/tests/history-page.test.tsx`: 교체 T2·T3만. 새 단언: (11) 탭이 `단계`·`검증`·`비용` 3개, (12) 기획안이 둘이면 `기획안 1`·`기획안 2` 라벨 아래에 각각 시도 줄이 있다, (13) 시도가 없으면 단계 탭에 시도 줄 목록이 없고 `정보 없음` 개수가 늘지 않는다, (14) 점수가 없는 시도는 해당 항목만 생략되고(`scores: null`이면 `시도 2 · 검사 실패 · 최종 실패`), `low_items`가 없으면 `재검토` 문구가 없다, (15) 검증 탭: 원천 표 영역은 기본 접힘이고 토글 `원천 데이터 보기 (1)`을 누르면 `aria-expanded="true"`가 되고 표가 보이며 이름이 `원천 데이터 접기 (1)`로 바뀐다(아코디언: 펼칠 때 `hidden`이 동기적으로 제거되고 다음 프레임에 열림 클래스, 접을 때 `transition-duration` 0이면 즉시 `hidden`), 표 위에 한글 제목 한 줄이 있고 원천 영역에 영문 도구명 텍스트가 없다, (16) 모든 행에서 `—`인 열(예: 객체·`null`뿐인 키)은 열로 만들지 않는다, (17) 집계 카드: 칩 텍스트가 한글 제목이고 모르는 도구는 `집계 항목`, `data-tool`에 원본 도구명, `전체 N건 · 표시 N건` 없음, 모델 작성값의 이름·값 영문 코드가 한글로 보이고(`sun_protection`·`hook_type`·`person_first` 등 합성 입력, 사전에 없는 코드는 원문) 입력 객체는 불변, (18) 검사 결과 카드 안에 `pattern_alignment_label`이 작은 회색 문장(`gs-pattern-label`)으로 있고 `경쟁사 패턴 반영` 표 영역에는 없다, (19) CSS 구조(`readFileSync(join(process.cwd(), "app/…"))` 기존 방식): `globals.css`에 `.verified-block`·`.model-block`·`.removed-block`의 `background`·`!important`가 없고, `.gs-aggregates`·`.gs-history-page .gs-plan-checks`·`.gs-history-source` 규칙이 같은 토큰 `var(--gs-card-padding)`를 쓰며 `tokens.css`가 `--gs-card-padding`·`--gs-section-gap`을 정의한다, (20) 상위·하위 25% 비교 원천 표에 설명 문장이 있다, (26) 같은 합성 `top_vs_bottom_axis` 입력에서 `DistributionChart`의 열 제목 배열과 펼친 원천 표의 열 제목 배열이 정확히 같고(`["분류", "상위 25% 광고 수", "하위 25% 광고 수"]`) 설명 문장도 같은 문구다(두 곳이 같은 이름 함수를 쓴다는 것을 고정).
- `web/tests/results.test.tsx`: 교체 T4~T11만(T13은 회귀 확인). 새 단언: (21) 패턴 표 설명 문장 두 줄이 각각 별도 요소로 있고 `기획안: `·`경쟁사 지배 패턴: ` 접두 문구는 부재, 각 열 `th`에 비어 있지 않은 `title`이 있다, (22) `비교 불가`가 일치 여부와 비중 셀 모두에서 단독 요소이고 `25.0%` 셀은 그대로, (23) 패턴 영역에 `코드 계산, 판정 아님` 문구가 없다(검증 탭으로 이동), (24) `top_vs_bottom_axis` 차트에 설명 문장 `같은 플랫폼·브랜드 안에서 조회수 상위 25%와 하위 25% 광고가 각 방식을 쓴 광고 수입니다.`이 제목 아래에 있고 `h3`은 하나다(다른 도구 차트에는 없다), (25) `selectAuditTab`·`PlanWithAudit` 헬퍼에 `평가` 탭 참조가 남지 않는다.
- 해시 시드·객체 순회 순서에 기대는 단언을 만들지 마라. 합성 데이터만 쓴다.
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
- 위 "교체 단언" 표(T1~T12)에 없는 기존 단언을 수정·삭제·약화하지 마라. 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체만 허용된다.
- `web/lib/insight.ts`의 기존 `columnName` 맵과 `TOOL_TITLES`의 키 집합을 바꾸지 마라(값은 `top_vs_bottom_axis`의 제목만). `tests/test_taxonomy_freeze.py`·`src/beautyads/domain/labels.py`·`src/`(서버)·`web/lib/{api,sse,types}.ts`를 수정하지 마라. 이유: 서버 계약·동결 값은 불변이고 이름은 표시층에서만 바꾼다.
- 서버가 보낸 평가 사유(`rationale`)·점수·`unknown_codes`·집계·분포 원본 객체를 변형하지 마라(치환은 표시 시점에만). 시도별 텍스트 비용을 비용 탭 밖으로 옮기거나 문구를 바꾸지 마라(`CostDetail`·`CostLine`·`시도 N · 시도 텍스트 비용` 문구 불변). 이유: 데이터는 서버가 만든 사실이고 비용 단언은 정확 일치다.
- 평가 탭을 지우면서 평가 정보를 삭제하지 마라(시도별 검사·최종 판정·점수·재검토 항목은 단계 탭 시도 줄에 있어야 한다). 영문 코드 병기(`(differentiation)`)와 모델이 쓴 사유 문장을 어느 화면에도 표시하지 마라. 이유: 정보는 옮기고 영문·모델 문장은 표시하지 않는다는 승인 범위다.
- `PlanResult.toggle()`·공유 훅·`web/components/ui/*`를 수정하지 마라(원천 표 토글은 `HistoryDetail.tsx` 안 로컬 구현). 카드 안에 카드·전체 폭 배경 블록을 만들지 마라. 이유: 기존 아코디언 단언과 ui 키트 테스트를 건드리지 않는다.
- 6b-clarify 동작과 `web/app/page.tsx`·`web/components/plan/*`·`web/components/shell/*`를 수정하지 마라(step 15의 범위). 이유: 범위 분리.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
