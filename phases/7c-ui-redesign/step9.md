# Step 9: history-cleanup

## 설계 검토 기록

**목적**: 실행 기록 화면 구현은 step 14·15·16에서 끝났다. 이 step은 **옛 컴포넌트·CSS·테스트 잔재 정리와 문서(DEMO.md 리허설 ⑰~, README, PHASES, DETAIL_PAGE) 갱신**만 한다. 새 패키지·서버 변경·live 호출 없음. **교체 단언은 아래 표 D1·D2 두 건뿐**이고 그 밖의 기존 단언은 수정하지 않는다. 표 밖에서 충돌을 발견하면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 컷이 발생한 화면(step 6·7·8 중 `phases/7c-ui-redesign/index.json`에서 `completed`가 아닌 것)이 있으면 **이 step을 시작하지 않는다**(사용자 지시를 먼저 받는다: 컷 순서 저장한 기획 → 데이터 그래프 → 근거 소재 별도 화면, 실행 기록은 필수). 이 step 문서는 step 5~8이 모두 `completed`인 경우를 기준으로 쓴다.

**코드를 열어 확인한 사실**
- `DEMO.md`의 `## 리허설 확인`에는 `- [ ] ①`~`- [ ] ⑯` 16개 항목이 있고 모두 `결과 기록:`을 포함한다(①~⑩은 `결과 기록: ______`, ⑫~⑯은 `결과 기록: 2026-11-21 사용자 live 확인 …`). 이미지 사람 검수 ⑫~⑯은 `- [ ] ⑫ **제목:** 뜻 — … 판정 — … 예시 — … 기록 방법 — … 결과 기록: …` 형식이다.
- `tests/test_demo_docs.py` 65~71행: `checks = re.findall(r"^- \[ \] (.+)$", rehearsal, re.MULTILINE)`에 대해 `assert len(checks) == 16`, `assert all("결과 기록:" in check for check in checks)`, `numbered = re.findall(r"^- .*?[①-⑯].*$", rehearsal, re.MULTILINE)`이 `[f"- [ ] {check}" for check in checks]`와 같음, `[check[0] for check in checks] == list("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯")`. 같은 파일의 ⑨·⑪ 항목 문구 단언과 이미지 검수 테스트(`[⑫-⑯]` 5개, 뜻·판정·예시·기록, `결과 기록: 2026-11-21 사용자 live 확인`)는 그대로 통과해야 한다. `docs/PHASES.md`의 `7c`는 옛 phase `ask-sse` 행이다(수정하지 않는다).
- 이 phase에서 이미 삭제·이동된 파일과 남은 레거시: `web/app/globals.css`에 옛 규칙(`.view-tabs`, `.workspace-picker`, `.composer`, `.step-bar`, `.verified-block` 등)이 남아 있을 수 있고 `web/components/`에는 `Notice.tsx`·`GraphCanvas.tsx`·`GraphPanel.tsx`·`SchemaView.tsx`·`NodeDetail.tsx`가 쓰인다. 어떤 파일·규칙이 참조 0인지는 Codex가 `rg`로 확인한다.
- `web/tests/shell.test.tsx`·`web/tests/graph-view.test.tsx` 등의 `준비 중` 단언은 step 8이 교체했다(소스에 `gs-placeholder`·`준비 중`이 남아 있지 않아야 한다).

**설계 결정**
- **정리**: step 3·4·5·10~16에서 삭제하지 않은 옛 컴포넌트와 사용되지 않는 `web/lib/*`, `globals.css`의 **사용되지 않는 규칙**을 제거한다. 제거 전 `rg`로 **참조가 없음을 확인**하고 목록을 summary에 적는다(참조가 남은 것은 지우지 않는다). `globals.css`에는 `*`·`body` 최소 리셋 등 아직 쓰이는 규칙만 남기거나 `tokens.css`로 흡수한다. 테스트가 읽는 CSS 규칙(`results.css`의 아코디언·`object-fit`·`accent-color`, `plan.css`·`graph.css`·`shell.css` 구조 검사)은 건드리지 않는다. `lib/localize.ts`의 `localizeText`는 집계 표시에 쓰이므로 지우지 않는다.
- **문서**: `DEMO.md`의 리허설에 항목 **⑰~㉗**(11개)을 이어 쓴다. **사람이 보는 항목마다 처음부터 뜻·칸별 판단 기준·예시 하나·기록 방법을 붙이고** 형식은 ⑫~⑯과 같다: `- [ ] ⑰ **제목:** 뜻 — … 판정 — (1) 칸 이름: 기준 (2) 칸 이름: 기준 … 예시 — … 기록 방법 — … 결과 기록: ______.` 항목 안에 확인할 칸이 둘 이상이면 `판정 —` 뒤에 `(1)`·`(2)`…로 칸마다 O/X 기준을 쓴다(한 문장으로 뭉뚱그리지 마라). 기록 방법은 칸 번호별 O/X와 한 줄 메모다.(결과는 비워 둔다: 사용자가 다음 live 확인에서 적는다). 항목:
  ⑰ **진행 줄**(스피너·shimmer·진행 단계 옆 경과 초·연결선 채움, 시안 단계는 체크만, 모션 줄이기에서 정지),
  ⑱ **기획 탭**(진행 중 새 기획·새 요청 비활성, 탭 이름 요약, 닫기 `×`가 버튼 중앙에 있고 라벨과 같은 세로 중심, 활성 탭을 닫으면 직전 탭으로 이동),
  ⑲ **입력창과 탭 줄 정렬**(스크롤바 없음·자동 높이, 탭 줄 가로줄 오른쪽 끝이 입력 칸 오른쪽 끝과 같고 `+ 새 기획`과 `기획하기`의 왼쪽 끝이 같음),
  ⑳ **사이드바 접기**(상단 로고 버튼으로 아이콘 레일 ↔ 펼침, 접힌 항목의 툴팁, 접어도 결과·그래프·표 폭이 깨지지 않음, 모션 줄이기),
  ㉑ **결과 카드**(시안 이미지 여백 없음, `확인 필요 N건` 배지와 설명 툴팁, 전체 보기 아코디언과 섹션 구조, 영문 코드 노출 없음),
  ㉒ **시장 인사이트와 경쟁사 패턴 표**(제목·열 용어 `경쟁사 최다 방식`·`시장 내 비중`, 설명 문장, 소구 값 `이상형 제시형` 표시, `조회수 상위·하위 25% 광고 비교` 표 용어),
  ㉓ **실행 기록·검증**(목록과 상세, 단계·검증·비용 탭, 단계 탭의 시도 줄, 집계 카드와 `원천 데이터 보기` 접기, `광고 기획으로 돌아가기`와 `목록으로`),
  ㉔ **근거 소재 화면**(플랫폼별 묶음, 자사 배지, 플랫폼 줄과 브랜드 줄 필터가 서로 독립),
  ㉕ **확인 질문 선택 뒤 요약 접힘**,
  ㉖ **지식 그래프**(스키마·데이터·근거 경로 탭, 확대·축소가 0.3~2.5 안에서 멈춤, 층·노드 종류 필터, 영문 노드·관계 이름 없음, 근거 그래프 보기 → 근거 경로 탭과 돌아가기, 데이터 탭의 이웃 펼치기),
  ㉗ **저장한 기획**(승인한 기획안 카드·상세·시안 이미지, 시안 이미지 실패 시 타일).
  기존 ⑧ **그래프 실데이터** 항목의 설명 문구는 새 화면 이름(지식 그래프 > 스키마·근거 경로)에 맞게 **최소한만** 고치고 `결과 기록: ______`를 유지한다. 기존 ⑨·⑪·⑫~⑯의 단언 문구는 바꾸지 않는다. 항목 위 안내 문단에 `⑰~㉗은 7c UI 개편 확인이며 PR·병합 조건이 아니다`를 한 문장 더한다. `README.md`의 화면 설명, `docs/PHASES.md`에 phase `7c-ui-redesign` 항목(기존 표 형식에 맞춘 한 줄과 변경 이력 한 줄, 기존 행은 수정 없음), `docs/portfolio/DETAIL_PAGE.md`의 UI 설명 한 곳(스크린샷은 사용자 촬영, 이미지 파일을 만들지 마라)을 갱신한다. 관측했다는 사실 주장 문장(`관측했다`)을 새로 쓰지 마라(`tests/test_demo_docs.py`의 확인 기록 가드).

**교체 단언(조언 세션 승인 범위: 리허설 항목 추가의 직접 결과. 이 표 밖의 기존 단언을 수정하지 마라)**

| # | 파일·행 | 이전 | 이후 |
|---|---|---|---|
| D1 | `tests/test_demo_docs.py` 67행 | `assert len(checks) == 16` | `assert len(checks) == 27`(⑰~㉗ 11개 추가) |
| D2 | `tests/test_demo_docs.py` 70~71행 | `numbered = re.findall(r"^- .*?[①-⑯].*$", …)`과 `assert [check[0] for check in checks] == list("①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯")` | 문자 클래스를 `[①-⑳㉑-㉗]`(두 구간: `①`~`⑳`은 U+2460~U+2473, `㉑`~`㉗`은 U+3251~U+3257, 사이의 다른 문자를 포함하는 한 구간 `①-㉗`은 쓰지 마라)로 넓히고, 번호 목록은 `[chr(0x2460 + i) for i in range(20)] + [chr(0x3251 + i) for i in range(7)]`와 정확히 같다(같은 정확 일치·순서 엄격도). `numbered == [f"- [ ] {check}" …]` 단언과 `all("결과 기록:" in check …)` 단언은 그대로 |

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 리허설 ⑰~㉗ | `DEMO.md` | `tests/test_demo_docs.py`, 사용자 |
| 정리 검증 | `web/tests/cleanup.test.ts` | 소스 전체(읽기) |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/app/{page.tsx,globals.css,tokens.css}`, `/web/components/`와 `/web/lib/` 전체(`rg`로 참조 확인), `/web/components/shell/*`, `/DEMO.md`, `/README.md`, `/docs/PHASES.md`, `/docs/portfolio/DETAIL_PAGE.md`, `/tests/test_demo_docs.py`, `/phases/7c-ui-redesign/index.json`(step 5~8 상태 확인, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/components/*`와 `web/lib/*`의 사용되지 않는 파일(참조 0 확인 후 삭제), `web/app/globals.css`, `web/app/page.tsx`(자리표시·사용되지 않는 import 제거만), `DEMO.md`, `README.md`, `docs/PHASES.md`, `docs/portfolio/DETAIL_PAGE.md`, `tests/test_demo_docs.py`, `web/tests/cleanup.test.ts`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/components/*`와 `web/lib/*`의 사용되지 않는 파일(참조 0 확인 후 삭제), `web/app/globals.css`, `web/app/page.tsx`(자리표시·사용되지 않는 import 제거만), `DEMO.md`, `README.md`, `docs/PHASES.md`, `docs/portfolio/DETAIL_PAGE.md`, `tests/test_demo_docs.py`, `web/tests/cleanup.test.ts`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** 옛 파일·규칙 정리(참조 0 확인 후, 목록을 summary에 보고). **2.** 문서 4곳과 `tests/test_demo_docs.py` 갱신. **3.** `web/tests/cleanup.test.ts`. 위 설계 결정과 교체 단언 표 D1·D2를 그대로 구현한다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_demo_docs.py`: 교체 D1·D2만. 새 단언 추가: ⑰~㉗ 11개 항목이 각각 `**제목:**` 형식이고 `뜻`·`판정`·`예시`·`기록` 요소를 모두 포함하고, `판정 —` 뒤에 `(1)`과 `(2)`가 모두 있으며(칸별 판단 기준), `결과 기록: ______`를 갖는다(항목이 0개면 실패). D1·D2의 정확 일치 단언은 이 구조 단언과 함께 통과해야 한다(구조 단언은 약화하지 않는다), ⑰~㉗은 ⑫~⑯과 달리 아직 비어 있는 결과 기록이라는 점이 통과해야 한다.
- `web/tests/cleanup.test.ts`(새): (1) `web/components`·`web/lib`에 어떤 파일도 import되지 않은 채 남아 있지 않다(파일 목록과 import 그래프를 테스트가 읽어 검사, 검사 대상 파일이 0개면 실패, 진입점은 `app/`의 페이지·레이아웃과 테스트가 직접 import하는 공개 API가 아니라 **소스의 import만** 본다), (2) `준비 중` 자리표시와 `gs-placeholder`가 소스에 없다, (3) `globals.css`에 소스(`web/app`·`web/components`·`web/lib`의 `className`)에서 쓰이지 않는 클래스 규칙이 없다(검사 방식은 완료 보고에 적는다).
- 해시 시드·집합·딕셔너리 순회 순서에 기대는 새 단언을 만들지 마라(리스트와 명시적 순서로 단언).
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
- 교체 단언 표(D1·D2) 밖의 기존 단언을 수정·삭제·약화하지 마라. 충돌이 나면 구현하지 말고 `blocked`로 멈춰 최소 교체안을 `reason`에 적어라. 이유: 승인된 교체만 허용된다.
- 서버 코드(`src/`)를 수정하지 마라. 실행 기록·그래프·저장한 기획 화면을 이 step에서 새로 만들지 마라. 이유: 구현은 앞 step에서 끝났다.
- 참조가 남아 있는 파일·규칙을 삭제하지 마라(`rg`로 확인). 스크린샷·이미지 파일을 만들지 마라. 사용자 live 결과를 지어내지 말고 ⑰~㉗의 결과 기록은 `______`로 둬라. 이유: 화면 촬영과 확인은 사용자가 한다.
- `web/tests`의 기존 단언이 읽는 CSS 규칙(`results.css`·`plan.css`·`shell.css`·`graph.css`·`saved.css`·`history.css`·`tokens.css`)을 지우지 마라. 이유: CSS 구조 검사 테스트가 있다.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
