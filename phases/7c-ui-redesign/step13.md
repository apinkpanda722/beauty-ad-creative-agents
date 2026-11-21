# Step 13: result-polish

## 설계 검토 기록

**배경**: 사용자 시각 확인에서 결과 카드·전체 보기·분포 차트의 수정 항목이 모였다. 이 step은 **결과 영역**을 다룬다. 새 패키지·서버 변경·live 호출 없음. **표시하던 항목을 지우지 않는다**: 다른 화면으로 옮길 항목(평가 시도·검사 결과·집계)은 이 step에서 **현재 위치(`전체 보기` 안, `ResultsView`의 집계 영역)에 그대로 남기고** step 14에서 실행 기록·검증 페이지로 옮긴다(중간 커밋에서 항목이 사라지지 않게). **기존 단언은 수정하지 않고 구현을 단언에 맞춘다**(조언 세션 원칙)는 이 step의 최우선 제약이며, 사용자 요구가 흐름 자체를 바꾸는 `반려` 사유 입력 하나만 예외로 교체한다(10번).

**코드를 열어 확인한 사실**
- `web/components/results/PlanResult.tsx`: 가로 카드(`.gs-plan-media` 이미지, `.gs-plan-summary` 배지·제목·훅·축 칩·`PatternSummary`·`FeedbackBar`·`전체 보기 →` 버튼), `div.gs-plan-expanded`(`hidden={!expanded}`)에 장면·카피·주장 효능·검사 결과·`PatternAlignment`·근거 목록(`evidenceAnchors`로 `#anchor` 링크, 텍스트는 raw `evidence_id`)·`<details>` 평가 시도·면책 문구·`CostDetail`. 헤더 줄 `기획안 · {product_display의 값을 ` · `로 이음}`이 `brand`(슬러그, 예: `beauty_of_joseon`)·`display_name`(예: `조선미녀 평가 작업 공간`)·`product_name`을 그대로 보인다. 배지 `근거 연결 없음 N건`은 `data.unknown_count`이고 아래 `unknown_codes`(코드→건수)는 `unknownNames` 상수(`CERT_REQUIRED_UNVERIFIED: 인증 연결 없음`, `EFFICACY_UNKNOWN: 효능 근거 연결 없음`, `EFFICACY_UNSUPPORTED: 효능 근거가 뒷받침하지 않음`)로 한글화한다. `unknown_count`는 **코드 검사가 확인하지 못한 항목의 수**이고 실패와 구분된다(`passed`가 별도).
- `FeedbackBar.tsx`: 사유 `textarea`(`피드백 사유`, placeholder `반려할 때는 사유를 입력하세요`)가 항상 보이고 `승인`·`반려` 버튼, 사유 없이 반려 불가, 중복 방지, `저장했습니다`, 오류 코드, 같은 기획안 복사본 간 저장 공유. 소비자: `PlanResult.tsx`, `PlanPage.tsx`(`FeedbackSession`), `tests/results.test.tsx`.
- `DesignImage.tsx`: 블롭 URL의 `img`(`object-fit: contain`, `.gs-plan-media`의 회색 배경), 이미지 크기는 서버 응답에 없다(`ImageReference`는 `request_key, index, mime, size, sha256, composed?`).
- `PatternAlignment.tsx`: 요약 `PatternSummary`와 축별 `기획안: … · 경쟁사 지배 패턴: … · 같음/다름` 목록. `DistributionChart.tsx`: 제목 `분포 · {data.tool}`, 막대(`meter`, 값 이름 `names.valueName`, `N건`), 그 외 행은 표(머리글이 `Object.keys` 원문 `value`·`n_top`·`n_bottom`·`creatives` 등)와 `caption {tool} 도구 결과`. `AggregatesPanel.tsx`: `검증된 집계(도구가 센 값)`(`item.tool`: `count_label`), `모델 작성값`, `제외된 값`. 분포 명령은 서버가 `ToolKind.aggregate|compare` 도구마다 보낸다(`api/ask_view.py`, 도구 정의는 `agents/tools.py`).
- 평가 시도의 `scores` 객체에는 `differentiation`·`fit` 점수와 **`rationale`(LLM이 쓴 한국어 자유 문장, 200자 이내)**가 함께 있다(`agents/evaluation.py`, `agents/plan_eval.py`). 현재 `PlanResult`는 `Object.entries(attempt.scores)`를 그대로 나열한다. 소비자: `PlanResult.tsx`와 `tests/results.test.tsx`(평가 시도 펼침 단언).
- `web/lib/workspace.ts`의 `workspaceLabel`은 `display_name`에서 접미사(` 평가 작업 공간`·` 개발 작업 공간`·` 작업 공간`)를 떼어 한글 브랜드명을 만든다(step 10).
- `web/lib/taxonomy.ts`: `taxonomyNames(schema)`의 `axisName`·`claimName`·`valueName`(서버 `/graph/schema`의 한글 이름, 없으면 원문), 정적 `talentName`·`ctaName`. 닫힌 코드값은 `domain/labels.py`의 `HookType`(question·problem·result_first·bold_claim·product_first·person_first·other), `Angle`(problem_solution·desire·social_proof·comparison·ingredient_science·how_to·other), `Format`(ugc_style·studio_film·demo·text_motion·static_image·other) 등이다.
- 결합 지점(수정 허용 목록에 포함): `tests/results.test.tsx`의 평가 시도·근거 목록·피드백·분포·집계 단언, `ResultsView.tsx`(분포·집계 렌더).

**설계 결정**

1. **시안 이미지 칸**: 이미지가 로드되면 `img`의 `naturalWidth/naturalHeight`로 칸의 `aspect-ratio`를 정하고(상태로 저장, 로드 전·오류 시 자리 표시 비율) 이미지가 칸을 **위아래 회색 여백 없이** 채운다. 시안에는 카피·라벨 글자가 합성되어 있으므로 **`object-fit: cover`로 자르지 않는다**(`contain`이되 칸 비율이 이미지 비율이라 여백이 없다). 카드 높이는 이미지 비율에 따른다. 오른쪽 텍스트가 더 길어도 스크롤이 아니라 칸 정렬로 처리한다(`align-items: start`, 이미지 칸 `position: sticky` 없이 상단 정렬).
2. **헤더 한글화(`PlanResult.tsx`)**: `기획안 · {한글 브랜드} · {제품명}`. 한글 브랜드는 `workspaceLabel`과 같은 해석(`display_name`의 접미사 제거)을 **`web/lib/workspace.ts`의 새 export(예: `koreanBrand(productDisplay)`)로 재사용**하고(중복 구현 금지), `display_name`이 없으면 `brand` 슬러그 대신 `정보 없음`이 아니라 슬러그를 한글 사전 없이 숨기지 말고 `브랜드 정보 없음`으로 표시한다. 중복되는 `작업 공간` 문구는 제거한다.
3. **배지 문구와 설명(`PlanResult.tsx`, 새 `web/lib/unknown.ts`)**: `근거 연결 없음 N건` → `확인 필요 N건 · {사유}`. 사유는 `unknown_codes`의 키를 **기존 `unknownNames` 상수를 `web/lib/unknown.ts`로 옮겨 재사용**한 한글 매핑으로 만든다(`CERT_REQUIRED_UNVERIFIED`→`인증 자료 연결 없음`, `EFFICACY_UNKNOWN`→`효능 근거 연결 없음`, `EFFICACY_UNSUPPORTED`→`효능 근거가 뒷받침하지 않음`, 모르는 코드는 `확인 필요 항목`). 사유가 여럿이면 건수 순으로 `·`로 잇고 길면 앞 2개 + `외 N종`. 마우스를 올리면(`title`과 접근 가능한 툴팁 `aria-describedby`) 설명이 나온다: `코드 검사가 확인하지 못한 항목의 수입니다. 실패가 아니라 근거가 연결되지 않아 확인이 필요한 항목입니다.` `N`이 0이면 배지를 숨기지 말고 `확인 필요 0건`으로 표시(사유 없음). **기존 `근거 연결 없음` 단언은 새 문구로 같은 엄격도 교체**하고 코드→한글 매핑 단언(알려진 3개, 모르는 코드, 사유 순서)을 추가한다.
4. **반려 사유 입력창(`FeedbackBar.tsx`)**: 사유 입력은 `반려`를 누른 뒤에만 나타난다. 흐름: `승인`/`반려` 버튼 → `반려`를 누르면 사유 입력과 `반려 제출`(및 `취소`)이 나타나고 사유가 비어 있으면 제출 불가. 저장 단언(승인 저장, 사유 있는 반려 저장, 중복 방지, `저장했습니다`, 오류 코드, 복사본 간 저장 공유, `plan_id` 없음이면 숨김)은 **같은 엄격도로 유지**(흐름 단계만 바뀐 헬퍼로 교체).
5. **전체 보기 아코디언(조언 세션 결정, 기존 단언은 한 줄도 수정하지 않는다)**: `div.gs-plan-expanded`의 **접힌 최종 상태는 기존과 같이 `hidden` 속성**이다(DOM 유지, `aria-controls` 요소 그대로, `inert`·`aria-hidden`으로 바꾸지 않는다). 내부에 `min-height: 0; overflow: hidden` 래퍼를 두고 바깥을 `display: grid; grid-template-rows: 0fr → 1fr` 전환으로 높이를 늘린다. 버튼 화살표(`→`)는 회전한다(`aria-expanded`).
   - **펼칠 때**: `hidden`을 **즉시(동기적으로)** 제거한 뒤 **다음 프레임**(`requestAnimationFrame`)에 열림 클래스(`gs-open`)를 붙여 `0fr → 1fr` 전환을 시작한다.
   - **접을 때**: 열림 클래스를 먼저 빼고 **전환이 끝난 뒤**(`transitionend` 또는 안전 타이머 약 300ms) `hidden`을 설정한다. 단 **`prefers-reduced-motion: reduce`이거나 전환 시간이 0**(`getComputedStyle(...).transitionDuration`이 비어 있거나 `0s`/`0ms`, jsdom 포함)이면 `hidden`을 **즉시 동기적으로** 설정한다. 이렇게 하면 테스트에서 클릭 직후 `expanded.hidden`이 `true`/`false`로 바로 읽혀 기존 단언이 그대로 통과한다.
   - 추가 단언만 더한다: 열림 클래스 토글, reduced-motion(또는 전환 시간 0)에서 `hidden`이 즉시 설정됨, 전환이 있는 경우(`transition-duration`을 모킹) `transitionend` 이벤트 뒤에 `hidden`이 설정됨.
6. **전체 보기 섹션 카드 구조(DOM 구조 불변, CSS로 카드화)**: `div.gs-plan-expanded`의 **자식 순서와 접근 이름은 그대로**다: `장면 구성`·`카피`·`주장 효능`·`검사 결과`·`경쟁사 패턴 반영`·`기획안 근거`·`DETAILS`(평가 시도)·`P`(면책 문구, 8번째 자식이고 `textContent`가 `data.disclaimer`와 정확히 같음)·(그 뒤 시안 고지·비용). 기존 `region` 접근 이름(`getByRole("region", { name })`)도 그대로다. 섹션 카드화는 각 `section` 요소에 카드 스타일(`gs-` 클래스)을 입히는 것으로 하고 래퍼를 추가해 자식 구조를 바꾸지 않는다. 내용 구조: 장면 구성은 **번호가 붙은 단계**(`ol`을 카드형 단계로 스타일), 카피는 **인용 스타일**(`blockquote` 또는 인용 CSS, 각 카피 문장은 기존처럼 정확한 텍스트의 단일 요소), 주장 효능은 검증 칩(기존 `Badge`), 경쟁사 패턴은 아래 표. 간격은 8px 리듬(`--gs-space-*`)으로 통일하고 줄 간격을 정리해 목록·들여쓰기가 섞이지 않게 한다.
   - **경쟁사 패턴 표**: `section[aria-label="경쟁사 패턴 반영"]` 안에 `table`(열: `축`·`기획안`·`지배 패턴`·`같음/다름`·`점유율`)을 둔다. **기존 `getAllByText` 단언이 통과하도록** `같음`·`다름`·`비교 불가`·`점유율 비교 불가`는 각각 **그 문구만 담은 요소**(셀 또는 셀 안 `span`)이고(점유율이 없으면 `점유율 비교 불가`, 있으면 `N%`), `비교한 축 N개 중 같은 축 M개`는 **그 문구만 담은 요소 하나**로 남기고(카드 요약의 `경쟁사 패턴 반영 · …` 줄과 별개), `pattern_alignment_label`도 그대로 한 요소로 남긴다. 좋음·나쁨 같은 평가어는 쓰지 않는다(기존 단언).
7. **영문 내부 용어 한글화(새 `web/lib/localize.ts`)**: 화면 표시용 매핑만 한다. 점수 이름은 기존 `scoreNames`, 닫힌 코드는 `taxonomyNames`(서버 한글 이름)·`talentName`·`ctaName`을 재사용하고 `other`는 `기타`로 표시한다(단, `meter`의 `aria-label` 등 **기존 단언이 확인하는 접근 이름은 기존 값을 유지**하고 시각 라벨만 바꾼다). **평가 사유(`rationale`) 같은 LLM 자유 텍스트의 코드**는 `localizeText(text, names)`가 **알려진 코드에 한해 표시 시점에만 단어 단위로 치환**한다(원문 데이터·프롬프트·생성 텍스트는 바꾸지 않는다). 평가 시도 목록은 기존대로 **숫자 점수를 `차별성 (differentiation): N`·`요청 적합성 (fit): N` 형식으로 유지**한다(기존 단언: 평가 시도는 관리·검증용 표면이므로 한글+코드 병기를 유지하고, 마케터 요약 줄 `평가 차별성 N/5, 요청 적합성 M/5`는 한글만 쓴다). `scores`의 문자열 항목 `rationale`은 숫자 점수 목록에서 빼고 **별도 줄 `사유: …`로 `localizeText`를 거쳐** 표시한다(기존에는 `Object.entries`로 그대로 나열됐다). 알려진 코드 집합은 `taxonomyNames`가 아는 `hook_type`·`angle`·`format` 값, `TALENT_NAMES`·`CTA_NAMES` 키, 효능 `claims`, 점수 이름 `differentiation`·`fit`이다. **치환 규칙**: 식별자 경계(`[A-Za-z0-9_]`에 이어지지 않을 때만)로 가장 긴 코드부터 매칭하고, 이름이 없는 코드·`other`는 치환하지 않는다. **치환 대상(예)**: `person_first`→`인물 먼저 제시형`, `how_to`→서버 한글 이름, `studio_film`→서버 한글 이름, `differentiation`→`차별성`, `fit`→`요청 적합성`. **비대상(오치환 금지, 테스트로 고정)**: `profit`·`benefit`·`fitness`·`outfit`(영단어 일부), `how_to_use`·`person_first_x`(더 긴 식별자의 일부), `youtube:how_to`·URL·`evidence_id` 안의 코드, 이미 한글인 문장의 한글 부분, 알려지지 않은 `snake_case` 토큰. 서버 이름이 비어 있으면 치환하지 않는다(원문 유지).
8. **근거 소재 목록(`기획안 근거` 섹션)**: 보이는 텍스트에서 raw `youtube:8rMt…` id를 없애고 **썸네일 칩**(작은 정사각 썸네일 + 브랜드, YouTube는 `i.ytimg.com` 직접 로드, 실패·다른 플랫폼은 기존 대체 타일의 소형)으로 보인다. 링크(`<a href="#anchor">`)와 **접근 이름은 기존처럼 raw `evidence_id`로 유지**한다(`aria-label={evidence_id}`, 보이는 글자는 아님). 앵커가 없는 id는 링크 없이 `근거 소재 N`(한글)로 표시한다. 클릭하면 근거 소재 화면의 해당 카드로 이동하는 앵커 동작과 `getByRole("link", { name: evidence_id })`·`queryByRole("link", { name: "youtube:absent" })` 단언은 수정하지 않는다. `근거 소재 목록` 제목 문구도 그대로 둔다.
9. **각주 한 블록(CSS로 묶기, DOM 순서 불변)**: 면책 문구 `P`(8번째 자식)와 그 뒤 시안 고지·비용 줄(`CostDetail`)을 **같은 각주 스타일 클래스**(`gs-footnote`, 작은 글씨·구분선은 첫 요소에만)로 묶어 한 블록처럼 보이게 한다. **요소를 합쳐 새 래퍼에 넣지 않는다**(기존 단언: 면책 `P`가 `expanded.children[7]`, 비용·상한은 면책 뒤, `aria-controls` 요소 안, 문구·4자리·횟수). 4c·step 10의 이 단언은 수정하지 않는다.
10. **마케터 요약 한 줄과 검증 상세(이 step에서는 위치 유지, step 14에서 이동)**: 카드 요약 영역에 한 줄 요약을 추가한다: `품질 검사 통과 · 평가 차별성 3/5, 요청 적합성 4/5`(마지막 시도의 `checks_passed`·점수, 점수가 없으면 해당 부분 생략, 코드 검사 실패면 `품질 검사 실패`, 한글만 사용). **`전체 보기` 영역 자체가 이미 접힌 보조 영역이므로 별도 `검증 상세(관리자용)` 접힘 래퍼는 만들지 않는다**(기존 구조 단언: `DETAILS`가 7번째 자식이고 `container.querySelector("details")`가 평가 시도 `<details>`여야 함). `검사 결과`·평가 시도 `<details>`·패턴 표 등은 **전체 보기 안에 그대로 두고**, 평가 시도 `<details>`의 `<summary>`(`평가 시도 보기 · 되돌림 N회`)와 `되돌림 N회` 문구는 그 한 곳에만 둔다(`getByText(/되돌림 0회/)`가 하나만 찾아야 함). `ResultsView`의 `분포`·`검증된 집계(도구가 센 값)` 영역은 **기존 위치와 접근 이름을 유지**한다(기존 순서 단언: 비용, 화면 문장, 기획안 제목들, `근거 소재`, `분포`, `검증된 집계(도구가 센 값)` 순서). 이 영역들과 `검사 결과`·평가 시도의 **상세 페이지 이동은 step 14**가 한다.
   - **배지(3번)와 기존 `근거 연결 없음 N건`**: 카드 요약의 새 배지 `확인 필요 N건 · 사유`가 마케터용이다. 기존 `근거 연결 없음 N건`(클래스 `clear`/`attention`, `getByText`로 하나만 찾아짐) 요소는 **`검사 결과` 섹션 안에 그대로 유지**한다(기존 단언 불변). `unknown_codes`의 기존 한글 목록(`인증 연결 없음` 등 정확한 텍스트의 `li`)도 `검사 결과` 안에 유지한다(새 배지의 사유 문구 `인증 자료 연결 없음`과 정확 일치가 겹치지 않게 새 배지는 한 요소 안에 `·`로 이은 하나의 문자열이다).
   - **반려 흐름(4번)과 기존 단언**: `FeedbackBar`의 사유 입력(`피드백 사유` 라벨, `INPUT`)은 DOM에 **항상 존재**하되 `반려`를 누르기 전에는 `hidden` 속성으로 숨겨 보이지 않는다(기존 `getByLabelText("피드백 사유")` INPUT 단언은 그대로 통과). **사용자 요구(사유 입력은 `반려`를 누른 뒤에만 나타남)가 바꾸는 흐름 단언만 교체**한다: 기존 `반려` 버튼이 사유가 비면 `disabled`(results.test.tsx 224행 부근)였던 것은 새 흐름에서 `반려`가 사유 입력을 여는 버튼이므로 성립할 수 없다. 교체: 초기에는 `반려`가 활성이고 누르면 사유 입력이 나타나며 `반려 제출`은 사유가 비면 비활성, 사유가 있으면 활성이고 제출하면 저장된다. 승인 저장·사유 있는 반려 저장·중복 방지·`저장했습니다`·오류 코드 표시·복사본 간 저장 공유·`plan_id` 없음이면 숨김 단언은 **수정하지 않는다**(사유 입력을 채우는 단계만 새 흐름의 헬퍼로 바뀐다). 이 교체는 **완료 보고(summary)에 `교체한 단언 → 새 단언`으로 명시**한다.
11. **분포 차트 → `시장 인사이트`(`DistributionChart.tsx`)**: 제목을 한글로: 도구별 제목 사전(`agents/tools.py`의 `ToolKind.aggregate|compare` 도구 이름 목록을 열어 각 도구에 한글 제목을 매핑, 모르는 도구는 `시장 인사이트`)과 막대 값의 축 판별(막대 값이 모두 `hook_type` 값이면 `오프닝 방식 분포`, `angle`이면 `메시지 유형 분포`, `format`이면 `제작 형식 분포`, `top_vs_bottom_axis` 도구면 `상위 vs 하위 광고 비교`)로 정한다. `분포 · {tool}`·`{tool} 도구 결과` 캡션·영문 표 머리글(`value`, `n_top`, `n_bottom`, `creatives`)·중복 제목을 없애고 한글 열 이름(`값`→`분류`, `n_top`→`상위 25%`, `n_bottom`→`하위 25%`, `creatives`→`소재 수`, 그 밖의 열은 원문을 숨기지 않고 한글 매핑이 없으면 `항목`)을 쓴다. 막대(`meter`)는 틸 토큰 색(`--gs-accent`)이고 `other`는 `기타`로 표시한다. 이 차트는 마케터 화면(결과 영역)에 남고, 도구 이름은 화면에서 제거하되 섹션에 `data-tool` 속성으로만 남기며 step 14의 검증 탭에서 작은 출처 칩으로 보인다. 섹션 `aria-label="분포"`와 `meter`의 접근 이름·막대 구조는 기존 단언대로 유지한다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `localizeText`, 점수·코드 이름 | `web/lib/localize.ts` | `PlanResult.tsx`, `PatternAlignment.tsx`, `localize.test.ts`, step 14 평가 탭 |
| `unknownReasons`(코드→한글) | `web/lib/unknown.ts` | `PlanResult.tsx`, `results.test.tsx` |
| `koreanBrand` | `web/lib/workspace.ts` | `PlanResult.tsx`, `workspace.test.ts` |
| 시장 인사이트 제목 규칙 | `web/lib/insight.ts` | `DistributionChart.tsx`, `insight.test.ts` |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/components/results/{PlanResult,PatternAlignment,DistributionChart,AggregatesPanel,DesignImage,FeedbackBar,CostDetail,CostLine,ResultsView}.tsx`, `/web/components/evidence/*`, `/web/lib/{workspace,taxonomy,types,evidence,format}.ts`, `/web/app/{results,evidence,tokens,ui}.css`
- `/src/beautyads/agents/tools.py`(분포 도구 이름 목록, 읽기 전용), `/src/beautyads/domain/labels.py`(닫힌 코드값, 읽기 전용), `/src/beautyads/api/ask_view.py`, `/src/beautyads/agents/{evaluation,plan_eval}.py`(rationale·attempt 필드, 읽기 전용)
- `/web/tests/{results,plan,shell,workspace,evidence}.test.ts*`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/lib/localize.ts`, `web/lib/unknown.ts`, `web/lib/insight.ts`, `web/lib/workspace.ts`, `web/components/results/PlanResult.tsx`, `web/components/results/PatternAlignment.tsx`, `web/components/results/FeedbackBar.tsx`, `web/components/results/DesignImage.tsx`, `web/components/results/DistributionChart.tsx`, `web/components/results/AggregatesPanel.tsx`, `web/components/results/ResultsView.tsx`, `web/components/evidence/EvidenceSummary.tsx`, `web/components/evidence/EvidenceCardView.tsx`, `web/app/results.css`, `web/app/evidence.css`, `web/app/tokens.css`, `web/tests/localize.test.ts`, `web/tests/unknown.test.ts`, `web/tests/insight.test.ts`, `web/tests/workspace.test.ts`, `web/tests/results.test.tsx`, `web/tests/plan.test.tsx`(결합 단언만), `web/tests/shell.test.tsx`(결합 단언만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/lib/localize.ts`, `web/lib/unknown.ts`, `web/lib/insight.ts`, `web/lib/workspace.ts`, `web/components/results/PlanResult.tsx`, `web/components/results/PatternAlignment.tsx`, `web/components/results/FeedbackBar.tsx`, `web/components/results/DesignImage.tsx`, `web/components/results/DistributionChart.tsx`, `web/components/results/AggregatesPanel.tsx`, `web/components/results/ResultsView.tsx`, `web/components/evidence/EvidenceSummary.tsx`, `web/components/evidence/EvidenceCardView.tsx`, `web/app/results.css`, `web/app/evidence.css`, `web/app/tokens.css`, `web/tests/localize.test.ts`, `web/tests/unknown.test.ts`, `web/tests/insight.test.ts`, `web/tests/workspace.test.ts`, `web/tests/results.test.tsx`, `web/tests/plan.test.tsx`(결합 단언만), `web/tests/shell.test.tsx`(결합 단언만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `web/lib/{localize,unknown,insight}.ts`와 `workspace.ts`의 `koreanBrand` 추가. **2.** `PlanResult.tsx`·`PatternAlignment.tsx`·`FeedbackBar.tsx`·`DesignImage.tsx`·`DistributionChart.tsx`·`AggregatesPanel.tsx`·`ResultsView.tsx`·`results.css` 재구성. **3.** 근거 목록의 썸네일 칩(소형, `evidence/` 재사용 가능). **4.** 테스트(아래).

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/localize.test.ts`(새): (1) 치환 대상: `person_first`, `how_to`, `studio_film`, `differentiation`, `fit`이 서버 한글 이름(합성 schema)·`scoreNames`로 바뀐다, (2) **비대상**: `profit`·`benefit`·`fitness`·`outfit`, `how_to_use`·`person_first_x`, `youtube:how_to`·URL 안의 코드, 이미 한글인 문장, 모르는 `snake_case`, 이름이 없는 코드와 `other`는 **바뀌지 않는다**, (3) 가장 긴 코드 우선(`product_first`가 `product`로 부분 치환되지 않음), (4) 같은 코드가 한 문장에 여러 번이어도 모두 치환, (5) 입력을 변경하지 않는다(원문 불변), (6) 빈 문자열·`null` 안전.
- `web/tests/unknown.test.ts`(새): (7) 알려진 3개 코드의 한글 문구, (8) 모르는 코드는 `확인 필요 항목`, (9) 사유 정렬(건수 내림차순, 동률은 코드 사전순)·`외 N종`, (10) `N=0`이면 사유 없음.
- `web/tests/insight.test.ts`(새): (11) 도구별 제목(`top_vs_bottom_axis`→`상위 vs 하위 광고 비교`, 막대 값 축 판별로 `오프닝 방식 분포`·`메시지 유형 분포`·`제작 형식 분포`, 모르는 도구→`시장 인사이트`), (12) 열 이름 한글 매핑과 모르는 열 처리, (13) `other`→`기타`.
- `web/tests/workspace.test.ts`: 기존 단언 유지 + (14) `koreanBrand`가 `config/workspaces.yaml`의 4개 `display_name`에서 한글 브랜드를 만들고 `display_name`이 없으면 `브랜드 정보 없음`.
- `web/tests/results.test.tsx`(**기존 단언은 수정하지 않는다. 예외는 10번의 반려 흐름 단언뿐**; 새 단언은 추가만): 기존 구조 단언(`.gs-plan-expanded` 자식 순서 `장면 구성·카피·주장 효능·검사 결과·경쟁사 패턴 반영·기획안 근거·DETAILS·P`, `expanded.children[7]`이 면책, `expanded.hidden`·`closest("[hidden]")` 판정, 정확한 `getByText` 문구들, 분포·집계·근거 소재·피드백·`CostLine`·`CostDetail` 단언, 첫 `details`가 평가 시도 `<details>`)이 **수정 없이 통과**해야 한다. 추가 단언: (15) 이미지 칸은 로드된 `naturalWidth/naturalHeight`로 `aspect-ratio`를 갖고 `object-fit: cover`가 아니다(CSS·인라인 스타일), (16) 헤더에 영문 슬러그(`beauty_of_joseon`)와 `작업 공간` 문구가 없고 한글 브랜드가 있다, (17) 카드 요약의 새 배지 `확인 필요 N건 · 사유`(툴팁 설명 문구, `N=0`이면 사유 없는 `확인 필요 0건`)가 있고 `검사 결과` 안의 기존 `근거 연결 없음 N건` 요소·`인증 연결 없음` 목록은 그대로다, (18) 반려 새 흐름: 초기에는 `피드백 사유` INPUT이 DOM에 있으나 `hidden`이고, `반려`를 누르면 보이며 `반려 제출`이 사유가 비면 비활성, 사유가 있으면 제출되고 저장된다(위 교체 단언) + 승인 저장 등 나머지 저장 단언은 수정 없이 통과, (19) 아코디언: 펼칠 때 `hidden`이 동기적으로 제거되고 다음 프레임에 `gs-open`이 붙고, 접을 때 reduced-motion·전환 시간 0이면 `hidden`이 즉시 설정되며 전환이 있으면(`transition-duration` 모킹) `transitionend` 뒤에 설정된다, CSS에 `grid-template-rows` 전환과 `prefers-reduced-motion`의 `transition: none`이 있다, (20) 섹션 카드 스타일 클래스가 각 섹션에 있고 장면은 번호 단계, 카피는 인용 요소이며 경쟁사 패턴 표의 5열과 `같음`·`다름`·`비교 불가`·`점유율 비교 불가` 각각 단독 요소(기존 단언)가 있다, (21) 근거 소재 칩은 raw `youtube:` id를 보이는 글자로 갖지 않고 링크의 접근 이름은 기존처럼 `evidence_id`이며 클릭 앵커(`#…`) 단언은 수정 없이 통과, (22) 각주 클래스가 면책 `P`·시안 고지·비용 줄에 적용되고 DOM 순서·문구는 불변이다, (23) 카드에 한 줄 요약 `품질 검사 통과 · 평가 차별성 N/5, 요청 적합성 M/5`가 있고(코드 검사 실패·점수 없음 변형 포함) 한글만 쓴다, (24) 평가 사유(`rationale`)는 별도 줄 `사유: …`로 표시 시점에만 치환되고 `data.attempts` 원본 객체는 바뀌지 않으며 숫자 점수 `차별성 (differentiation): N` 형식은 그대로다, (25) 시장 인사이트 차트: 한글 제목, 영문 머리글·도구 이름·`caption` 없음, 막대 색이 틸 토큰, `other`는 시각 라벨 `기타`이되 `meter`의 접근 이름은 기존 값, 섹션 `aria-label="분포"`는 유지.
- 새 문구·치환 대상·비대상은 합성 입력으로만 단언한다(모델이 만든 실제 문장을 기대값으로 굳히지 않는다).
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
- `src/`(서버)·`web/lib/api.ts`·`web/lib/sse.ts`·`web/lib/types.ts`의 서버 계약을 수정하지 마라. 평가 사유·점수·`unknown_codes`·분포 데이터의 **원문 데이터와 프롬프트·생성 텍스트를 바꾸지 마라**(치환은 표시 시점에만). 이유: 데이터는 서버가 만든 사실이고 표시만 한글화한다.
- 표시하던 항목(평가 시도, 검사 결과, 집계 3블록, 패턴 정렬, 근거 목록, 면책, 비용·상한)을 지우거나 옮기지 마라(상세 페이지 이동은 step 14). `.gs-plan-expanded`의 자식 구조·순서·접근 이름, 기존 `getByText`가 찾는 정확한 문구, 기존 `hidden` 판정 단언을 바꾸지 마라(10번의 반려 흐름 단언 교체만 예외). 이유: 옮기는 중간 커밋에서 항목이 사라지면 안 되고 기존 단언은 수정하지 않는다.
- `CostLine.tsx`·`CostDetail.tsx`의 출력 문자열을 바꾸지 마라(4c의 단언 불변). 이유: 정확 일치 단언이 있다.
- 알려지지 않은 영문 토큰을 임의로 번역하거나 사전에 없는 한글 이름을 지어내지 마라(`other`는 `기타`, 이름이 없으면 원문 유지). 이유: 표시 매핑은 서버가 내려주는 이름과 닫힌 코드값만 쓴다.
- `object-fit: cover`로 시안을 자르지 마라. 이유: 시안에 합성된 카피·라벨 글자가 잘린다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
