# Step 6: web-evidence-plan

## 설계 검토 기록

**배경(P7 설계 승인 + 추가 요구 1)**: 결과 화면이다. 근거 카드, 기획안 카드(근거 연결 없음 건수 배지, 경쟁사 패턴 반영 패널), aggregates 분리 영역, 분포 막대, 시안 이미지, 승인·반려, 요청 비용 한 줄을 그린다. step 5가 상태에 **저장만 해 둔** 화면 명령(`CommandSlot`)을 이 step이 채운다. 그래프 화면은 step 7이다.

**포트폴리오 원칙(사용자)**: 화면은 "푼 문제와 측정된 긍정 결과"가 보이게 만든다. 실험 한계·미입증 서술을 앞세우지 않는다. 그렇다고 사실과 다른 문구(예: 그래프가 벡터보다 정답률이 높다, 경쟁사 패턴과 같으면 좋은 기획안이다)를 만들지 않는다. 서버가 준 면책 문구(`disclaimer`·`design_disclaimer`·`pattern_alignment_label` "코드 계산, 판정 아님")는 **그대로** 작게 보여 주되 화면의 주인공은 근거·기획·검사 결과다.

**서버 계약(코드로 확인한 사실, `api/ask_view.py` 108~262행)**:
- `show_evidence_cards.data = {cards: [{evidence_id, source, url, brand, title, published_at, view_count, like_count}], missing: int}`(카드는 최대 20, 값은 `null`일 수 있다). 소재 ID 형식은 `EVIDENCE_ID_PATTERN = ^[a-z]+:[A-Za-z0-9_-]{1,64}$`(예: `youtube:<영상 ID>`).
- `show_plan.data`: `plan`(`Plan` 필드 중 `title`, `hook_type`, `hook_text`, `scenes[]`, `copy_lines[]`, `image_brief`, `cta_type`, `angle`, `format`, `category`, `product_url`, `claimed_efficacy[]`, `evidence_ids[]`), `plan_id`, `passed`(코드 검사 통과), `unknown_count`, `unknown_codes`(코드 → 건수), `efficacy_status`(효능 → 상태), `efficacy_summary{supported, unknown}`, `count_label`, `result_counts`, `evidence_counts{in_plan, in_pool}`, `status`(`pe_status`: `done` | `needs_review` | `failed`), `attempts[{attempt, scores{...}, low_items[], checks_passed, final_passed, cost_usd?}]`, `pattern_alignment`, `pattern_alignment_label`("코드 계산, 판정 아님"), `disclaimer`, `image`(`{request_key, index, mime, size, sha256, composed?: {mime, size, sha256, contrast_adjusted?, min_contrast?}}` 또는 `null`), `design_disclaimer`, `product_display{brand, display_name, product_name}`.
- `pattern_alignment`(`domain/supervisor.py` `pattern_alignment`, 447~): `{axes: {hook_type|angle|format: {plan: 값|null, dominant: [값...], same: bool|null, share: 0~1|null}}, compared, same_count, skipped}`. **`same`은 기획안 값이 경쟁사 지배 패턴과 같은지의 사실이지 좋고 나쁨이 아니다**(기획 프롬프트는 지배 패턴과 다르게 쓰라고 요구하므로 "다름"이 의도일 수 있다): 화면에 일치 여부를 가치 판단 없이("같음"/"다름"/"비교 불가") 중립 색으로 보인다. `null`(`same`·`share`·`plan`)과 빈 `dominant`를 처리한다.
- `show_distribution.data = {tool, rows[:50]}`: 행 모양은 도구마다 다르다(비교 질의 행은 `{value, creatives, creative_ids, total}`, 그 밖의 집계 도구는 다른 열, `agents/tools.py`·`graph/evidence_queries.py`·`graph/queries.py`). 열을 추측해 하드코딩하지 않는다: `value`(문자열)와 `creatives`(정수)가 모두 있는 행은 막대로, 그 밖의 행은 스칼라 열만 표로 그린다(중첩 값은 건수로 줄이거나 생략).
- `show_aggregates.data`·`show_cost.data`·`token.display_text`: step 3에서 추가한 형태(`{label, verified_counts[{tool,row_count,shown_count,count_label}], model_written[{name,value}], removed[]}`, `{label, text_spent_usd, max_text_cost_usd}`).
- 근거 연결 없음(unknown) 코드: `checks/plan_checks.py`가 `severity=unknown`으로 내는 코드는 `CERT_REQUIRED_UNVERIFIED`·`EFFICACY_UNKNOWN`(그리고 효능 판정에서 `EFFICACY_UNSUPPORTED`와 같은 자리에 `unknown`이 날 수 있다). 코드의 한국어 설명은 `domain/plan.py` `CheckCode`와 `checks/plan_checks.py`를 읽고 정하되 **모르는 코드는 원 코드 그대로** 보인다.
- 분류 값 한국어 이름: `GET /api/graph/schema`(step 2)의 `taxonomy`(`hook_type`·`angle`·`format`: `[{value, name, definition}]`, `other` 제외)와 `claims`(`[{value, name}]`). 없는 값(`other`, `cta_type`, `category`)은 원 값 그대로.
- `POST /feedback`(`api/feedback.py`): 본문 `{plan_id, decision: "approved"|"rejected", reason: str}`, 헤더 `X-Tenant-Id`, 성공 `{"status":"ok"}`, 오류 404 `PLAN_NOT_FOUND`·422 `FEEDBACK_INPUT_INVALID`·500 `FEEDBACK_INTERNAL_ERROR`(코드만).
- `GET /design/{request_key}/{index}`(`api/ask.py` 199~): 헤더 `X-Tenant-Id` 필요(**`<img src>`로 직접 못 부른다** → `fetch` 후 blob URL), 합성본이 있으면 합성 PNG, 404 `DESIGN_NOT_FOUND`.

**사용자 결정 반영**:
- **근거 연결 없음(`unknown_count`)은 눈에 띄는 배지**다(P5 결정 40의 10번). 0이면 중립·긍정 색의 "근거 연결 없음 0건", 1 이상이면 강조색 "근거 연결 없음 N건" + 코드별 건수.
- **aggregates는 세 블록으로 분리**한다(승인 Q6): "검증된 집계(도구가 센 값)" = `verified_counts`의 `count_label`, "모델 작성값 · 검증되지 않음" = `model_written`(서버 `label` 그대로, 회색·작게), "제외된 값" = `removed`(도구 출력에 없는 수치라 빠졌다는 설명). **`model_written`은 검증된 블록 안에 절대 들어가지 않는다.** 서버가 구조화 명령을 내므로 `token` 텍스트에서 줄을 해석하지 않는다(`display_text`만 쓴다).
- 근거 카드 썸네일(승인 Q7): `source == "youtube"`이고 `evidence_id`의 `youtube:` 뒤 ID가 `^[A-Za-z0-9_-]{1,64}$`이면 `https://i.ytimg.com/vi/<ID>/hqdefault.jpg`를 `<img referrerPolicy="no-referrer" loading="lazy">`로 불러온다(저장·프록시 없음). Instagram·TikTok 등은 출처 아이콘(텍스트·SVG)으로 대체한다. 이미지 로드 실패 시 아이콘으로 되돌린다.
- 외부 링크(`url`)는 **`https:`·`http:`만** `href`로 쓰고 `rel="noopener noreferrer" target="_blank"`. 그 밖의 스킴(`javascript:` 등)이나 빈 값이면 링크 없이 제목만.
- 요청 비용(승인 Q8): "이 요청의 텍스트 모델 비용 $0.0123 (이미지 제외)" 한 줄(`label`은 서버 값, 금액은 소수 4자리). 서버가 명령을 안 내면 줄이 없다.
- 시안 이미지: `image`가 있으면 blob으로 표시하고 `design_disclaimer`를 아래에 작게. 불러오기 실패는 "시안 이미지를 불러오지 못했습니다"(원 오류 코드는 `DESIGN_NOT_FOUND`일 때만 병기). blob URL은 컴포넌트가 사라질 때 `URL.revokeObjectURL`로 해제한다.
- 승인·반려: `plan_id`가 `null`이면 버튼을 그리지 않는다. 반려는 사유 1자 이상 필수, 승인은 사유 선택(빈 문자열 전송 가능, 서버 `reason: str`). 한 번 저장되면 "저장했습니다"로 바뀌고 같은 기획안에 다시 보내지 못한다. 전송 중 중복 클릭 방지. 오류는 코드를 보인다.
- **근거 카드의 분석 속성(P7 승인 추가)**: 카드에는 step 2·3이 만든 여섯 키(`hook_type`·`angle`·`format`·`talent`·`cta_type`·`claims`)가 온다. 각 값이 있으면 한국어 이름 배지로 보인다: 훅·소구·형식은 `taxonomy`(스키마), 효능은 `claims`(스키마), **출연자(`talent`)·CTA(`cta_type`)는 서버가 이름을 주지 않으므로** `web/lib/taxonomy.ts`에 닫힌 정적 표를 둔다(`talent`: `none` 출연자 없음, `ordinary_person` 일반 출연자, `creator` 크리에이터, `celebrity` 유명인, `expert` 전문가, `staff` 직원 / `cta_type`: `none` 행동 유도 없음, `shop_now` 구매 유도, `learn_more` 자세히 알아보기, `store_mention` 판매처 언급, `event` 할인·증정·기간, `follow_engage` 팔로우·참여 유도; 출처: `analysis/prompts.py`의 `_TALENT_CRITERIA`·`_CTA_CRITERIA` 설명). 표에 없는 값은 원 값. **값이 전부 `null`(`claims`가 비었거나 `null`)이면 오류가 아니라 중립 문구 "분석 대상 아님"**을 작게 보인다(분석된 소재만 라벨이 있다: 7,429개 중 1,172개). 카드에 우열·성능을 말하는 문구(좋음·효과적·인기 등)를 넣지 않는다(속성은 "이 소재의 분석 결과"로만 표시). 기획안 카드의 경쟁사 패턴 반영 패널과 함께 경쟁사 광고 분석을 화면에 보여 주는 자리다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `getSchema`·`getDesignImage`·`postFeedback` | `web/lib/api.ts`(**추가만**) | 컴포넌트, `web/lib/taxonomy.ts` |
| 분류 한국어 이름 조회(+ 출연자·CTA 정적 표) | `web/lib/taxonomy.ts` | `PlanCard`·`PatternAlignment`·`EvidenceCards`, `tests/test_web_contract.py`(표 키 ↔ `Talent`·`CtaType` 멤버 대조) |
| 화면 명령 → 컴포넌트 연결 | `web/components/CommandSlot.tsx`(step 5의 자리를 채움) | `Chat.tsx`의 턴 렌더링(변경 없음) |
| 컴포넌트들 | `web/components/{EvidenceCards,PlanCard,PatternAlignment,AggregatesPanel,DistributionChart,DesignImage,FeedbackBar,CostLine}.tsx` | `CommandSlot.tsx` |

**기존 단언과의 충돌 점검**: step 5의 `web/tests/`(reducer·stages·claim·컴포넌트)는 바꾸지 않는다. `CommandSlot`이 이제 무언가를 그리므로 step 5 컴포넌트 테스트가 화면 명령이 있는 턴을 쓰면 렌더 결과에 영향이 있는지 확인한다(영향이 있으면 단언을 약화하지 말고 `blocked`로 보고한다). `tests/test_web_contract.py`는 서버에 없는 이벤트·명령 이름을 더하지 않는 한 영향이 없다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/PRD.md`(시연과 포트폴리오 산출물), `/docs/ARCHITECTURE.md`(스트리밍 이벤트와 화면 명령)
- `/src/beautyads/api/ask_view.py`, `/src/beautyads/api/ask.py`(시안 이미지 경로 부분), `/src/beautyads/api/feedback.py`, `/src/beautyads/api/graph_routes.py`(`/graph/schema` 응답), `/src/beautyads/domain/plan.py`(`CheckCode`, `Plan`), `/src/beautyads/checks/plan_checks.py`, `/src/beautyads/domain/supervisor.py`(`pattern_alignment`), `/src/beautyads/agents/plan_eval.py`(`pe_status` 값), `/src/beautyads/agents/tools.py`(`ToolKind`·도구 목록, 분포 행의 출처)
- `/tests/test_ask_view.py`(`result()` 합성 결과의 모양)
- `/web/lib/types.ts`, `/web/lib/api.ts`, `/web/lib/reducer.ts`, `/web/components/`, `/web/tests/`(step 4·5 산출물)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/`, `tests/test_web_contract.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `web/`, `tests/test_web_contract.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `web/lib/`**: `api.ts`에 `getSchema(tenantId)`(`GET /api/graph/schema`), `getDesignImage(tenantId, requestKey, index): Promise<Blob>`(`GET /api/design/<requestKey>/<index>`, 키·인덱스는 URL 인코딩), `postFeedback(args)`(`POST /api/feedback`, 비-200은 `ApiError`)를 **추가**한다. `taxonomy.ts`: 스키마 응답에서 `axisName(axis, value)`·`claimName(value)`을 만드는 순수 함수(없으면 원 값, 스키마를 못 불러와도 화면은 원 값으로 동작). 타입은 서버 코드에서 읽은 키만(`types.ts`에 **추가만**).

**2. `web/components/`**: 위 표의 컴포넌트와 `CommandSlot.tsx` 채우기. 배치 순서: 근거 카드 → 기획안 카드(여러 개면 순서대로) → 분포 → aggregates 패널 → 비용 줄. 기획안 카드 구성: 제목·훅 문구·장면·카피, 분류 배지(훅·앵글·포맷, 한국어 이름), 주장 효능 칩(`claimed_efficacy`와 `efficacy_status`: 확인됨/근거 연결 없음을 구분), **근거 연결 없음 배지**, 코드 검사 `passed`와 평가 상태 `status`를 **서로 다른 표시**로(P5: 코드 판정과 모델 점수·최종 상태를 섞지 않는다), 평가 시도 목록(되돌림 횟수와 점수), **경쟁사 패턴 반영 패널**(축마다 "기획안: ○○ · 경쟁사 지배 패턴: ○○ · 같음/다름/비교 불가 · 점유율 ○%", 패널 머리말과 `pattern_alignment_label`·건수 요약 "비교한 축 N개 중 같은 축 M개"), 근거 소재 목록(`plan.evidence_ids`를 위 근거 카드로 이동하는 앵커 링크, 카드에 없는 ID는 ID 텍스트만), 면책 문구(`disclaimer`), 시안 이미지, 피드백 바.

**3. 테스트(`web/tests/`, 가짜 `fetch`·합성 데이터, `tests/test_ask_view.py`의 `result()` 모양을 참고해 키를 맞춘다)**
- (1) `PlanCard`: `unknown_count` 0과 N(코드별 건수)의 배지, `passed`와 `status`가 별개 표시, `pattern_alignment`가 `same: true/false/null`·`share: null`·빈 `dominant`에서 각각 중립 문구("같음"/"다름"/"비교 불가")로 나오고 **가치 판단 문구(좋음·나쁨·우수·미달 등)가 렌더 결과에 없음**, 스키마를 못 불러오면 원 값 표시.
- (2) `AggregatesPanel`: 세 블록이 분리돼 있고 `model_written`의 이름·값이 "검증된 집계" 블록의 DOM 안에 **없으며** "모델 작성값 · 검증되지 않음" 문구(서버 `label`)가 `model_written` 블록에 있음, `removed`만 있는 경우, 셋 다 비면 아무것도 그리지 않음.
- (3a) `EvidenceCards` 분석 속성: 여섯 키가 있으면 한국어 이름 배지(스키마의 이름, 출연자·CTA는 정적 표, 표에 없는 값은 원 값), 전부 `null`이면 "분석 대상 아님" 중립 문구(오류 스타일 아님), 일부만 값이 있으면 있는 것만, 렌더 결과에 우열·성능 문구가 없음.
- (3) `EvidenceCards`: YouTube 썸네일 URL이 규칙대로 만들어지고 ID가 패턴에 맞지 않으면 썸네일 없음, Instagram·TikTok은 아이콘, `javascript:` 링크는 `href` 없음, `http(s)` 링크는 `rel`·`target` 속성, `null` 값(조회수·게시일) 처리, `missing > 0` 안내.
- (4) `DistributionChart`: `value`+`creatives` 행은 막대, 다른 모양의 행은 표, 중첩 값이 있어도 렌더 오류 없음.
- (5) `DesignImage`: 가짜 `fetch`가 받은 요청에 `X-Tenant-Id`가 있고 blob URL이 만들어지며 **언마운트 때 `revokeObjectURL`이 불림**, 404는 안내 문구.
- (6) `FeedbackBar`: 반려는 사유 없이 제출 비활성, 승인은 사유 없이 가능, 전송 본문 정확 일치(`{plan_id, decision, reason}`), 성공 후 재전송 불가, 전송 중 중복 클릭이 한 번만 전송, `plan_id: null`이면 버튼 없음, 오류 코드 표시.
- (7) `CostLine`: `show_cost`가 있으면 서버 `label`과 소수 4자리 금액, 없으면 줄 없음.
- (8) 통합: step 5의 `Chat`에 정상 이벤트열(근거 카드·기획안·aggregates·비용 명령 포함)을 흘리면 위 컴포넌트가 순서대로 나타남.
- `tests/test_web_contract.py`(케이스 추가에 한함, 단언 약화 금지): (9) `web/lib/taxonomy.ts`의 출연자 표 키 집합이 `domain/labels.py`의 `Talent` 멤버 값 집합과, CTA 표 키 집합이 `CtaType` 멤버 값 집합과 정확히 같다(검사한 키 수 0이면 실패), (10) `web/lib/types.ts`의 카드 타입 키 집합이 `ask_view.py`의 `_CARD_FIELDS`와 같다.
- 서버가 만든 문장·분류 값을 기대값으로 굳히지 않는다(합성 문자열과 닫힌 값 목록의 형식만 검사).

## Acceptance Criteria

```bash
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

- `model_written`을 "검증된" 블록에 넣거나 "검증됨"·"확인됨" 문구를 붙이지 마라. 이유: 검증을 통과해도 모델이 쓴 값이다. 분리는 출처 구분이다(P5 결정 50). 판정할 수 있는 것은 코드가 판정한다(AGENTS.md).
- `pattern_alignment`의 `same`에 좋음·나쁨·점수를 붙이거나 일치율로 기획안을 평가하는 문구를 만들지 마라. 이유: 서버가 "코드 계산, 판정 아님"으로 정의했고 기획은 지배 패턴과 다르게 쓰도록 되어 있다(`pattern_alignment` docstring, 9c). 사실과 다른 우열 문구는 만들지 않는다(사용자 원칙).
- 서버 `url`을 검사 없이 `href`에 넣지 마라. 외부 이미지를 저장·프록시하지 마라(`i.ytimg.com`은 화면이 직접 불러온다). 이유: DB의 URL이 `javascript:`일 수 있고, 수집 영상·이미지를 저장하지 않는다는 규칙이다(AGENTS.md CRITICAL).
- `/design` 이미지를 `<img src="/api/design/...">`로 직접 부르지 마라. 이유: 이 경로는 `X-Tenant-Id` 헤더가 있어야 하고 헤더는 `<img>`가 못 보낸다. 쿼리로 테넌트를 넘기도록 서버를 바꾸지 않는다(ADR-009).
- `src/`·`tests/`(파이썬)·`Makefile`·step 4·5의 기존 테스트 단언을 약화하거나 바꾸지 마라. 서버(`make serve`)와 `pnpm dev`를 서버 연결 상태로 실행하지 마라. 이유: 서버 계약은 step 2·3에서 끝났고 서버 실행은 사용자가 한다(A-FP-040).
