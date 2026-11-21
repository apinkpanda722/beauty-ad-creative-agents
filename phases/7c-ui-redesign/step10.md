# Step 10: visual-align

## 설계 검토 기록

**배경(사용자 시각 확인, 2026-11-21)**: step 1~4 결과가 승인한 시안과 다르다는 지적이 나왔다. 사용자가 준 현재 화면 캡처 1장과 승인 시안 캡처 1장(`~/Desktop/스크린샷 2026-11-21 오후 3.07.06.png`, `...3.08.49.png`)을 기준으로 **색은 승인된 흰 바탕·틸 #0F766E·라이트 전용을 유지하고 레이아웃·밀도·구성만 시안을 따른다**(시안은 어두운 배경 예시이므로 색을 따르지 않는다). 이 step은 step 4 뒤, step 5 앞에서 실행한다(`index.json`에서 step 4 다음 자리, 번호는 10). 새 패키지 없음(아이콘은 인라인 SVG), live 호출 없음.

**문제 1: 옛 임시 조각(코드를 열어 확인)**: `web/app/page.tsx`가 `view === "plan" || view === "graph"`일 때 옛 헤더(`<h1>Beauty Ad Creative Agents</h1>`와 부제)와 `대화`·`전체 스키마` 탭 막대를 그린다. 그 아래 `PlanPage`가 `PageHeader` `광고 기획`을 또 그려 제목이 두 번 나온다. 지식 그래프는 같은 임시 탭의 `schema-view`로 `SchemaView`를 그리며 작업 공간이 없으면 `대화 탭에서 작업 공간을 선택하세요.`를 보인다. 작업 공간 선택(`WorkspacePicker`)은 `PlanPage` 안의 큰 카드다.

**문제 2: 시안과의 차이(캡처 기준)**: ① 상단 바: 왼쪽 마크, 오른쪽 작업 공간 칩(상태 점 + 이름 + 화살표). ② 좌측 내비: 항목별 선형 아이콘, 활성은 둥근 알약. ③ 입력: 큰 폼 카드가 아니라 한 줄 입력 바 + 오른쪽 버튼. ④ 진행: 6단계 스테퍼가 아니라 입력 바 아래 한 줄(`요청 해석 1.6s › 리서치 7.9s › 기획·평가 22.1s [재작업 1회] › 시안 4.1s` + 오른쪽 끝 비용). ⑤ 결과: 세로로 긴 카드가 아니라 왼쪽 이미지·오른쪽 요약의 가로 카드. ⑥ 근거 소재: 플랫폼 소제목 + 한 줄 4열 컴팩트 카드. ⑦ 전반 밀도.

**설계 결정**

1. **옛 조각 제거(`web/app/page.tsx`)**: 옛 헤더와 탭 막대, 임시 `tabpanel` 래퍼를 제거한다. 광고 기획 = `PlanPage`. 지식 그래프 = `PageHeader`(제목 `지식 그래프`) 한 줄 + `SchemaView`(step 5가 `GraphPage`로 교체하므로 이 step은 임시 구성만). 작업 공간이 없을 때 안내는 `상단 바에서 작업 공간을 선택하세요.`로 바꾼다.
2. **상단 바(`TopBar.tsx`, 새 `WorkspaceChip.tsx`, 새 `Mark.tsx`)**: 왼쪽에 인라인 SVG 마크(단순한 선형 도형, 상표·시안 로고 모방 금지) + `BRAND.name` + `BRAND.nameKo`(`brand.ts` import, 리터럴 금지). 오른쪽에 **작업 공간 칩 하나**: 상태 점(선택됨=성공색, 없음=회색) + `브랜드 · 제품명` + 드롭다운 화살표. 칩은 `button`(`aria-haspopup="listbox"`, `aria-expanded`, 접근 이름 `작업 공간`)이고 열면 `role="listbox"` 목록과 맨 아래 작은 한 줄 `작업 공간은 서버를 시작할 때 정한 그룹 하나만 보입니다. 바꾸려면 서버를 다시 시작하세요.`(기존 문구 글자 그대로)가 나온다. 키보드: Enter·Space·ArrowDown으로 열기, ArrowUp/ArrowDown 이동, Enter 선택, Esc 닫고 칩으로 초점 복귀, 바깥 클릭 닫기. 큰 `작업 공간` 카드와 안내 문장 블록(`WorkspacePicker`)은 제거한다. 선택 동작은 기존 `PlanPage`의 `selectWorkspace`·`onWorkspaceChange`와 같은 계약(`state.tenantId === tenantId`면 무시)이다. 칩 라벨은 새 `web/lib/workspace.ts`의 `workspaceLabel(workspace)`: 한글 브랜드명은 `display_name`에서 끝의 ` 평가 작업 공간`·` 개발 작업 공간`·` 작업 공간`을 떼어 얻고(`config/workspaces.yaml`의 `믹순 개발 작업 공간`→`믹순`, `코스알엑스 개발 작업 공간`→`코스알엑스`, `이즈앤트리 평가 작업 공간`→`이즈앤트리`, `조선미녀 평가 작업 공간`→`조선미녀`), 제품명이 있으면 ` · {product_name}`을 붙인다. `display_name`이 없으면 `brand`(슬러그), 둘 다 없으면 `tenant_id`로 대체한다. 이것은 시안 문구(`조선미녀 · 인삼선세럼 SPF 50+`)를 만들기 위한 **해석**이다(한글 브랜드명 필드가 `/workspaces`에 없다). 서버 응답 계약은 바꾸지 않는다.
3. **좌측 내비(`Sidebar.tsx`, 새 `icons.tsx`)**: 항목마다 선형 인라인 SVG 아이콘(`aria-hidden`, `currentColor`, 20px; 광고 기획·근거 소재·지식 그래프·실행 기록·저장한 기획 5개). 활성 항목은 연한 틸 배경의 둥근 알약(`border-radius` 999px 또는 `--gs-radius-lg`), 3px 막대는 제거. 활성 글자색과 알약 배경의 대비는 4.5 이상(`contrast.test.ts`에 쌍을 추가). `aria-current="page"`와 항목 5개·순서는 그대로.
4. **입력(`Composer.tsx`)**: 큰 폼 카드 대신 한 줄 입력 바. `textarea`는 `rows=1`에서 내용 길이에 따라 높이가 자동으로 늘고 최대 높이(예: 6줄)를 넘으면 스크롤(`scrollHeight` 기반, CSS `max-height`), 오른쪽에 `기획하기` 버튼(전송 동작은 기존 `send`와 동일). `요청` 라벨은 시각적으로만 숨기고(`gs-sr-only`) 접근 이름은 유지한다(`getByLabelText("요청")`). `시안 이미지 포함` 체크는 바 아래 작은 토글 한 줄로, **글자 수 표시와 `Enter 전송, Shift+Enter 줄바꿈` 힌트는 입력값이 있을 때만** 보인다(`aria-describedby`는 힌트가 있을 때만). Enter 전송, Shift+Enter 줄바꿈, IME 조합 중 Enter 무시(`isComposing`·`keyCode 229`·`composing` ref), 2000자 상한, 전송 후 비우기, 작업 공간 미선택·진행 중 비활성은 **기존 동작 그대로**.
5. **진행 줄(`ProgressTracker.tsx`, `web/lib/stages.ts`, `web/lib/reducer.ts`, `web/lib/session.tsx`)**:
   - `deriveStages`와 `Stage` 타입은 **수정하지 않는다**(`stages.test.ts`의 기존 단언 그대로, `complete` 단계 포함). 화면용으로 새 순수 함수 `deriveProgress(stepEvents, turnStatus, times?)`를 `stages.ts`에 **추가**한다. 반환 항목: `{ id: "supervisor" | "research" | "plan_eval" | "image", label, status: "pending"|"running"|"done"|"failed", reworks: number, durationMs: number | null }`. 라벨은 `요청 해석`·`리서치`·`기획·평가`·`시안`(`시안`은 이미지 이벤트가 있을 때만). `기획·평가`는 `planning`과 `evaluation`을 합친 항목이다(재작업 루프가 있어 한 단계로 표시): 둘 중 하나가 failed면 failed, `evaluation`이 done이면 done, `planning`이 시작됐고 평가가 아직 없으면 running(진행 중 전체 규칙은 `deriveStages`와 같게), 둘 다 pending이면 pending. `reworks`는 `rework` 이벤트 수. **`complete` 단계는 항목으로 만들지 않는다**(요청이 끝나면 모든 항목이 체크로 바뀌는 것으로 표현하므로 라벨·상태 글자 중복이 구조적으로 사라진다).
   - **소요 시간**: 서버 SSE `step` 이벤트(`agent`, `phase`, `status`)에는 시각이 없다(`api/ask.py`의 `_step`은 세 키만 보냄). 그래서 **클라이언트가 이벤트를 받은 시각**(`performance.now()` 기반, 주입 가능한 시계)으로 구간을 계산한다. 규칙: `요청 해석` = 첫 `supervisor` 종료 이벤트 도착 − 요청 시작, `리서치` = `research` 종료 도착 − `supervisor` 종료 도착, `기획·평가` = 마지막 `evaluation`/`rework` 이벤트 도착 − `research` 종료 도착, `시안` = `image` 이벤트 도착 − 마지막 `evaluation`/`rework` 도착. 구간을 계산할 두 시각이 없으면 `durationMs: null`이고 시간은 표시하지 않는다. **알려진 한계**: 서버가 평가·재작업·시안 종료 이벤트를 한꺼번에 내보내는 경우(7d에서 확인된 동작) `시안`처럼 도착 시각이 거의 같은 구간은 0에 가깝게 보인다. 정확한 구간 시간이 필요하면 서버가 시각을 보내야 하며(범위 밖) 완료 보고에 한계를 적는다. 시간 표시 형식은 `1.6s`(소수 한 자리).
   - 시각 수집: `reducer.ts`의 `Turn`에 **선택 필드** `startedAt?: number`·`stepAt?: number[]`(`stepEvents`와 같은 길이)를 추가하고, `request_started`/`stream_event` 액션에 선택 필드 `at?: number`를 추가한다. `at`이 없으면 필드를 만들지 않는다(그래서 `reducer.test.ts`의 기존 기대값은 변하지 않는다). `session.tsx`가 액션을 보낼 때 `at`을 채운다(테스트에서 시계 주입 가능).
   - 표시: `<section aria-label="진행 단계" aria-live="polite">` 안의 `<ol>`에 항목마다 `<li data-status>`(상태 아이콘 `.gs-stage-icon` — 대기=윤곽, 진행=CSS 펄스, 완료=체크, 실패=✕ — + 라벨 + 소요 시간 + `기획·평가`의 재작업 배지 `재작업 N회`), 항목 사이에 `›` 구분. 상태 글자(`대기`·`진행 중`·`완료`·`실패`)는 **화면에 쓰지 않고** 아이콘의 접근 이름(`aria-label`)과 `data-status`로만 전달한다. 오른쪽 끝에 요청 비용: 같은 턴의 `show_cost` 명령의 `text_spent_usd`를 `$0.062`(소수 3자리)로 표시하고 접근 이름은 서버 라벨 `텍스트 모델 비용(이미지 제외)`. 비용 명령이 없으면 비용을 표시하지 않는다(이미지 비용은 스트림에 없으므로 합계가 아니다). `TurnCard`가 `costUsd`를 `ProgressTracker`에 넘긴다. 기존 `경과 시간` 요소(`aria-label="경과 시간"`, `N초 경과`, 진행 중에만 갱신하고 종료 시 정리하는 타이머, 주입 시계)는 **그대로 유지**하되 진행 중에만 보이고 끝나면 `gs-sr-only`로 시각적으로 숨긴다(텍스트·갱신 규칙 불변). `needs_choice`·`unavailable`·`stopped` 분기(`요청 해석 완료 · 선택을 기다리는 중`, 숨김)는 기존 그대로다.
   - 애니메이션: `@keyframes gs-progress-pulse`(진행 중 아이콘)와 연결선 전환은 CSS만, `@media (prefers-reduced-motion: reduce)`에서 `animation: none`·`transition: none`. JS 애니메이션 금지(경과 숫자 갱신만 타이머 허용).
6. **결과 카드(`PlanResult.tsx`, `PatternAlignment.tsx`, `FeedbackBar.tsx`, `DesignImage.tsx`, `ResultsView.tsx`, `results.css`)**: 가로 카드로 재구성한다. 왼쪽에 시안 이미지(`DesignImage`; 이미지가 없으면 `시안 이미지` 자리 표시), 오른쪽에 위에서 아래로: 주장 효능 배지(예: `자외선 차단 · 확인됨`)와 `근거 연결 없음 N건` 배지, 제목, 훅 문구, 축 칩(훅 유형·소구·형식), 구분선, **경쟁사 패턴 반영 한 줄 요약**(`경쟁사 패턴 반영 · 비교한 축 N개 중 같은 축 M개`, `pattern_alignment`의 `compared`·`same_count`), 버튼 줄(`승인`·`반려`)과 오른쪽 끝 `전체 보기 →`(버튼, `aria-expanded`). **기존에 표시하던 모든 항목(장면 구성, 카피, 주장 효능 상세 라벨, 근거 연결 없음 코드 목록, 코드 검사, 평가 상태, 패턴 정렬 전체 표, 근거 소재 목록과 앵커 링크, 평가 시도 `<details>`와 되돌림 횟수, 면책 문구, 시안 고지 문구, 피드백 사유)을 지우지 않고** `전체 보기`가 펼치는 영역 안에 **그대로 유지**한다. 펼침 영역은 접혀 있어도 DOM에 남기고 `hidden`으로 숨긴다(접근성 도구에서는 제외, `getByText` 검사는 유지). `FeedbackBar`는 동작(승인, 사유가 있어야 반려, 중복 방지, `저장했습니다`, 서버 오류 코드 표시, 같은 기획안 복사본 간 저장 공유)을 **그대로** 두고 모양만 바꾼다: 카드에는 `승인`·`반려` 버튼과 **한 줄로 줄인 사유 입력**(숨기지 않음)을 둔다. 기획안이 여러 개일 때와 `plan_id`가 없을 때의 기존 동작도 그대로다.
7. **근거 소재(`EvidenceSummary.tsx`, `EvidenceCardView.tsx`, `EvidencePage.tsx`, 새 `PlatformIcon.tsx`, `evidence.css`)**: 결과 아래 근거 요약은 플랫폼별 소제목(`PlatformIcon` 인라인 SVG — 상표 로고 모방 금지, 단순한 선형 도형 — + 플랫폼 이름 + `N건`) 아래 **한 줄 4열의 컴팩트 카드**(상단 썸네일 또는 대체 타일, 아래에 브랜드와 훅 유형)다. 자사 배지, YouTube 썸네일 `onError` 복귀, 앵커 id, `missing` 문구, 분석 속성 6종 표시, 링크 스킴 검사 동작은 유지하되 **컴팩트 카드에 다 담기지 않는 항목(게시일, 조회수·좋아요, 분석 배지 전체)은 카드 안에서 접근 가능하게 유지**(툴팁이 아니라 카드 아래쪽 작은 글씨 또는 펼침). 근거 소재 화면(`EvidencePage`)은 같은 카드 컴포넌트를 쓰고 전체 목록·필터(전체·플랫폼별·자사만)·빈 상태·플랫폼 묶음 제목을 유지한다. 좁은 폭에서는 열 수가 줄어든다(CSS 격자).
8. **전반(`tokens.css`, `ui.css`, `shell.css`, `plan.css`, `results.css`, `evidence.css`)**: 간격·글자 크기·카드 테두리·반경은 `tokens.css` 변수만 쓴다. 시안 밀도(요소 간 여백 작게, 카드 반경 12px 안팎, 그림자 거의 없음)를 따른다. 성공 색 토큰(`--gs-success`와 약한 배경)을 추가하고 **대비 4.5 이상**을 `contrast.test.ts`에 추가한다. 컨텐츠 최대 폭을 시안 비율에 맞게 넓힌다(예: 1120px). 옛 `globals.css` 규칙은 이 step에서 건드리지 않는다(step 9 정리).

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `workspaceLabel` | `web/lib/workspace.ts` | `WorkspaceChip.tsx`, `workspace.test.ts` |
| `deriveProgress`와 시간 규칙 | `web/lib/stages.ts` | `ProgressTracker.tsx`, `progress.test.ts` |
| `Turn.startedAt`·`stepAt`, 액션 `at` | `web/lib/reducer.ts` | `session.tsx`, `stages.ts` 호출부(`TurnCard`) |
| 작업 공간 칩 | `web/components/shell/WorkspaceChip.tsx` | `TopBar.tsx`, `page.tsx` |
| 내비 아이콘 | `web/components/shell/icons.tsx` | `Sidebar.tsx`, `PlatformIcon.tsx`(같은 선형 스타일, 별도 파일) |
| 비용 표시 | `TurnCard.tsx`가 `show_cost`에서 추출 | `ProgressTracker.tsx` |

**사전 점검(코드를 열어 확인한 소비자와 기존 테스트 결합)**: `rg`로 확인한 결과 `WorkspacePicker`의 소비자는 `PlanPage.tsx`뿐이고(삭제 가능), `ProgressTracker`의 소비자는 `TurnCard.tsx`와 `tests/plan.test.tsx`다. 기존 테스트가 DOM 구조에 결합된 곳은 다음이며 **행동 단언은 유지하고 DOM·문구 단언만 새 구조로 교체**한다.
- `tests/plan.test.tsx`: `selectWorkspace` 헬퍼(`getByLabelText("작업 공간")`의 `fireEvent.change`)와 `send` 헬퍼(`전송` 버튼 이름), `getAllByRole("button")` 목록이 `["전송"]`인 단언, 작업 공간 안내 문구 단언, 입력 바 구조, 진행 단계 `li` 5개(`done`×5)·`요청 해석 진행 중`·`리서치 실패` 텍스트·`getAllByText("완료")` 길이 1 단언, `기획 N회` 문구.
- `tests/shell.test.tsx`: `selectWorkspace` 변경 이벤트, `대화 탭에서 작업 공간을 선택하세요.` 안내.
- `tests/results.test.tsx`: 기획안 섹션 순서·`<details>` 접힘·카드 구조 단언, 근거 소재 카드 마크업.
이 교체는 승인된 시각 수정에 따른 것이며(옛 구조에서만 성립하는 DOM·문구 단언), 각 교체는 아래 **대응 원칙**을 따른다: (a) 같은 행동(작업 공간 선택 후 입력 활성, 전송, IME·Shift+Enter, 단계 상태 전달, 재작업 횟수 표시, 승인·반려 저장, 접힌 평가 시도 확인, 앵커 이동, 썸네일 복귀, 자사 배지)을 새 구조에서 같은 엄격도로 단언, (b) `라벨·상태 글자가 중복되지 않는다` 단언으로 `완료 정확히 한 번` 단언을 교체(각 단계 라벨이 정확히 한 번, `완료 완료`·`요청 해석 완료` 같은 `라벨+상태` 문구가 없음, 상태는 `data-status`와 아이콘 접근 이름으로 전달), (c) 완료 보고(summary)에 `교체한 단언 → 새 단언` 표를 적는다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/AGENTS.md`의 CRITICAL 규칙은 `/docs/ARCHITECTURE.md`와 함께 읽는다(웹 변경이므로 서버·계층 규칙은 해당 없음)
- `/web/app/page.tsx`, `/web/app/layout.tsx`, `/web/app/{tokens,shell,ui,plan,results,evidence}.css`, `/web/lib/{stages,reducer,session,types,evidence,brand,format,taxonomy}.ts*`
- `/web/components/shell/*`, `/web/components/plan/*`, `/web/components/results/*`, `/web/components/evidence/*`, `/web/components/ui/*`, `/web/components/WorkspacePicker.tsx`, `/web/components/{SchemaView,NodeDetail,GraphPanel}.tsx`(읽기 전용)
- `/web/tests/{plan,shell,results,stages,reducer,evidence,contrast,ui,brand}.test.ts*`
- 사용자 제공 캡처 2장(`~/Desktop/스크린샷 2026-11-21 오후 3.07.06.png`: 현재 화면, `~/Desktop/스크린샷 2026-11-21 오후 3.08.49.png`: 승인 시안). 열람 가능하면 레이아웃·밀도 기준으로 참고하고 색은 따르지 않는다.

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/app/page.tsx`, `web/app/tokens.css`, `web/app/shell.css`, `web/app/ui.css`, `web/app/plan.css`, `web/app/results.css`, `web/app/evidence.css`, `web/lib/workspace.ts`, `web/lib/stages.ts`, `web/lib/reducer.ts`, `web/lib/session.tsx`, `web/components/shell/*`, `web/components/plan/PlanPage.tsx`, `web/components/plan/Composer.tsx`, `web/components/plan/ProgressTracker.tsx`, `web/components/plan/TurnCard.tsx`, `web/components/results/PlanResult.tsx`, `web/components/results/PatternAlignment.tsx`, `web/components/results/FeedbackBar.tsx`, `web/components/results/DesignImage.tsx`, `web/components/results/ResultsView.tsx`, `web/components/evidence/EvidenceSummary.tsx`, `web/components/evidence/EvidenceCardView.tsx`, `web/components/evidence/EvidencePage.tsx`, `web/components/evidence/PlatformIcon.tsx`, `web/components/ui/*`, `web/components/WorkspacePicker.tsx`(삭제만), `web/tests/workspace.test.ts`, `web/tests/progress.test.ts`, `web/tests/plan.test.tsx`, `web/tests/shell.test.tsx`, `web/tests/results.test.tsx`, `web/tests/stages.test.ts`(추가만), `web/tests/reducer.test.ts`(추가만), `web/tests/evidence.test.ts`, `web/tests/contrast.test.ts`, `web/tests/ui.test.tsx`, `web/tests/graph-view.test.tsx`(깨지는 참조만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/app/page.tsx`, `web/app/tokens.css`, `web/app/shell.css`, `web/app/ui.css`, `web/app/plan.css`, `web/app/results.css`, `web/app/evidence.css`, `web/lib/workspace.ts`, `web/lib/stages.ts`, `web/lib/reducer.ts`, `web/lib/session.tsx`, `web/components/shell/*`, `web/components/plan/PlanPage.tsx`, `web/components/plan/Composer.tsx`, `web/components/plan/ProgressTracker.tsx`, `web/components/plan/TurnCard.tsx`, `web/components/results/PlanResult.tsx`, `web/components/results/PatternAlignment.tsx`, `web/components/results/FeedbackBar.tsx`, `web/components/results/DesignImage.tsx`, `web/components/results/ResultsView.tsx`, `web/components/evidence/EvidenceSummary.tsx`, `web/components/evidence/EvidenceCardView.tsx`, `web/components/evidence/EvidencePage.tsx`, `web/components/evidence/PlatformIcon.tsx`, `web/components/ui/*`, `web/components/WorkspacePicker.tsx`(삭제만), `web/tests/workspace.test.ts`, `web/tests/progress.test.ts`, `web/tests/plan.test.tsx`, `web/tests/shell.test.tsx`, `web/tests/results.test.tsx`, `web/tests/stages.test.ts`(추가만), `web/tests/reducer.test.ts`(추가만), `web/tests/evidence.test.ts`, `web/tests/contrast.test.ts`, `web/tests/ui.test.tsx`, `web/tests/graph-view.test.tsx`(깨지는 참조만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** 토큰·CSS·공용 부품: `tokens.css`(성공색 등 추가), 필요한 경우 `ui/*`와 `ui.css`.
**2.** 셸: `page.tsx`(옛 헤더·탭 막대 제거, 지식 그래프 임시 구성, 작업 공간 상태를 상단 바로 전달), `TopBar.tsx`, 새 `WorkspaceChip.tsx`·`Mark.tsx`·`icons.tsx`, `Sidebar.tsx`, `shell.css`, 새 `web/lib/workspace.ts`. `PlanPage.tsx`에서 `WorkspacePicker` 제거 후 `web/components/WorkspacePicker.tsx` 삭제(소비자 0 확인).
**3.** 입력과 진행: `Composer.tsx`, `ProgressTracker.tsx`, `TurnCard.tsx`(`costUsd` 전달), `stages.ts`(`deriveProgress` 추가), `reducer.ts`(선택 필드), `session.tsx`(`at` 채우기), `plan.css`.
**4.** 결과와 근거: `PlanResult.tsx`, `PatternAlignment.tsx`, `FeedbackBar.tsx`, `DesignImage.tsx`, `ResultsView.tsx`, `results.css`, `EvidenceSummary.tsx`, `EvidenceCardView.tsx`, `EvidencePage.tsx`, 새 `PlatformIcon.tsx`, `evidence.css`.
**5.** 테스트: 위 사전 점검의 교체와 아래 새 테스트를 작성한다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `web/tests/workspace.test.ts`(새): (1) `workspaceLabel`이 `config/workspaces.yaml`의 `display_name`(`믹순 개발 작업 공간`, `코스알엑스 개발 작업 공간`, `이즈앤트리 평가 작업 공간`, `조선미녀 평가 작업 공간`)에서 접미사를 떼고 `product_name`을 ` · `로 잇는다(예: `조선미녀 · 인삼선세럼 SPF 50+`), (2) `product_name`이 없으면 브랜드명만, `display_name`이 없으면 `brand` 슬러그, 둘 다 없으면 `tenant_id`, (3) 접미사가 없는 이름은 그대로.
- `web/tests/progress.test.ts`(새, 시계 주입·합성 이벤트): (4) `deriveProgress`는 `complete` 항목이 없고 항목이 `요청 해석`·`리서치`·`기획·평가`(·`시안`)이며 이미지 이벤트가 없으면 `시안`이 없다, (5) `기획·평가`는 `planning` 시작만 있으면 running, `evaluation` 종료가 있으면 done, 실패는 failed로 유지, (6) `reworks`는 `rework` 이벤트 수, (7) 소요 시간은 도착 시각 규칙대로이고 시각이 없으면 `null`, (8) `deriveStages`의 결과는 이 step 전후로 **동일**(기존 `stages.test.ts` 통과).
- `web/tests/reducer.test.ts`: 기존 단언은 **수정 없이** 통과하고 새 케이스 (9) `at`을 주면 `startedAt`·`stepAt`이 기록되고 `stepAt` 길이가 `stepEvents`와 같다, (10) `at`을 주지 않으면 필드가 생기지 않는다.
- `web/tests/shell.test.tsx`·`web/tests/plan.test.tsx`(교체 + 추가): (11) 옛 헤더 `Beauty Ad Creative Agents`와 `대화`·`전체 스키마` 탭 막대가 어느 화면에도 없다, (12) `광고 기획` 제목이 정확히 한 번, (13) 상단 바에 `BRAND`를 import해 비교한 제품 이름 두 값이 보이고(테스트에도 이름 리터럴을 쓰지 않는다) 작업 공간 칩이 있다, 칩을 열면 `role="listbox"`와 안내 한 줄이 있고 선택하면 입력이 활성화되며 키보드(ArrowDown·Enter·Esc)로 동작한다, (14) `작업 공간` 큰 카드와 select가 없다, (15) 내비 항목은 5개·순서 불변·`aria-current`, 각 항목에 `svg`가 있고 활성 항목에 알약 클래스가 있다, (16) 입력은 한 줄 `rows=1`에서 시작하고 `기획하기` 버튼이 있으며 입력이 없을 때 글자 수·힌트가 없고 입력하면 나타난다, (17) 기존 IME·Shift+Enter·Enter 전송·2000자 상한·진행 중 비활성 단언 유지, (18) **진행 줄**: 각 단계 라벨이 정확히 한 번이고 `완료 완료`·`요청 해석 완료` 같은 `라벨+상태` 문구가 없으며 상태는 `data-status`와 아이콘 접근 이름으로 전달된다, 모든 단계 done이면 모두 체크 상태, 재작업 1회가 `기획·평가` 옆 배지로 보인다, 소요 시간이 `1.6s` 형식이다, 비용 `$0.062`가 `show_cost`가 있을 때만 오른쪽에 보인다(접근 이름 `텍스트 모델 비용(이미지 제외)`), (19) `경과 시간` 요소는 기존 단언(주입 시계, 진행 중에만 갱신, 종료 시 정리)을 그대로 통과한다, (20) CSS에 `@keyframes gs-progress-pulse`와 `prefers-reduced-motion`의 `animation: none`·`transition: none`이 있다.
- `web/tests/results.test.tsx`(교체 + 추가, 기존 행동 단언 유지): (21) 결과 카드는 가로 구성으로 왼쪽 이미지(없으면 `시안 이미지` 자리 표시), 주장 효능 배지, `근거 연결 없음 N건` 배지, 제목, 훅, 축 칩, 패턴 한 줄 요약, `승인`·`반려`, `전체 보기 →`가 있다, (22) `전체 보기`를 누르면 `aria-expanded`가 참이 되고 장면·카피·주장 효능·검사 결과·패턴 전체 표·근거 목록·평가 시도·면책 문구가 모두 보이며, 접힌 상태에서도 DOM에는 남는다(기존 표시 항목이 하나도 없어지지 않았음을 항목 목록으로 단언), (23) 승인·반려 저장, 사유 없이 반려 불가, 중복 방지, `저장했습니다`, 오류 코드 표시, 복사본 간 저장 공유 단언은 **그대로**, (24) 근거 요약은 플랫폼 소제목(아이콘·이름·`N건`) 아래 컴팩트 카드, 자사 배지·썸네일 복귀·앵커 이동·`missing` 문구·분석 속성 단언 유지, (25) 근거 소재 화면은 같은 카드 컴포넌트로 전체 목록·필터·빈 상태를 유지.
- `web/tests/contrast.test.ts`: (26) 새 토큰 쌍(활성 내비 글자/알약 배경, 성공색/흰색, 성공색/약한 성공 배경)이 4.5 이상이고 `tokens.css` 값과 테스트 상수가 같다.
- 모든 새·교체 테스트는 합성 데이터와 주입 시계만 쓰고 네트워크·`.env`가 없다.
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
- `web/lib/stages.ts`의 `deriveStages`와 `Stage` 타입, `web/lib/reducer.ts`의 기존 필드·액션 의미, `web/lib/api.ts`·`web/lib/sse.ts`·`web/lib/types.ts`의 서버 계약을 바꾸지 마라(필드 추가는 위에서 허용한 선택 필드뿐). 이유: 서버 계약(SSE 이벤트 종류, `UiCommand`)은 불변이고 `stages.test.ts`·`reducer.test.ts`의 기존 단언은 그대로 통과해야 한다.
- 서버 코드(`src/`)를 수정하지 마라. 서버가 단계 시각을 보내도록 바꾸지 마라. 이유: 이 step은 웹 시각 수정이고, 시간은 도착 시각으로 계산한다(한계는 완료 보고에 적는다).
- 기존에 표시하던 항목(장면, 카피, 주장 효능, 검사, 패턴 표, 근거 목록, 평가 시도, 면책, 피드백 사유, 근거 카드 분석 속성)을 지우지 마라. 이유: 이 step은 구성 변경이고 항목 삭제가 아니다(승인 조건).
- 새 패키지를 추가하지 마라(`pnpm add` 금지, 아이콘은 인라인 SVG). 상표 로고나 이미지·폰트 파일을 추가하지 마라. 어두운 배경·다크 모드를 만들지 마라. 이유: 라이트 전용·흰색 바탕·틸 #0F766E이 승인 조건이다.
- 시안 이미지·플랫폼 로고를 흉내 내지 마라(플랫폼 아이콘은 단순한 선형 도형). 이유: 상표 모방 금지.
- 지식 그래프 화면을 이 step에서 새로 만들지 마라(`SchemaView` 임시 구성만). 저장한 기획·실행 기록 화면을 만들지 마라. 이유: 해당 화면은 step 5 이후의 범위다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라(변수·주석 포함). 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드가 이 문자열을 소스에서 찾는다. 예시 칩을 되살리지 마라.
- `web/app/globals.css`·`step 5~9`에서 다룰 파일을 정리 목적으로 삭제하지 마라(`WorkspacePicker.tsx`만 소비자 0 확인 후 삭제).
