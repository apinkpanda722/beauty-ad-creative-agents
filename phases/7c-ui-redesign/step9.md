# Step 9: history-cleanup

## 설계 검토 기록

**목적(변경됨)**: 실행 기록 화면 구현은 step 14(history-verify)로 이관됐다. 이 step은 **옛 컴포넌트·CSS·테스트 잔재 정리, 내비·자리표시 정리, 문서(DEMO.md 리허설 ⑰~, README, PHASES, DETAIL_PAGE) 갱신**만 한다. 컷이 발생한 화면의 내비 항목 정리는 이 step을 실행하기 전 사용자가 지시한다(컷 순서: 저장한 기획(step 7·8) → 데이터 그래프(step 6) → 근거 소재 별도 화면. **실행 기록은 필수**).

**설계 결정**
- 정리: step 3·4·5·10~14에서 이미 삭제하지 않은 옛 컴포넌트와 사용되지 않는 `web/lib/*`, `globals.css`의 사용되지 않는 규칙을 제거한다. 제거 전 `rg`로 **참조가 없음을 확인**하고 목록을 summary에 적는다. `globals.css`에는 `*`·`body` 최소 리셋만 남기거나 `tokens.css`로 흡수한다.
- 내비의 `준비 중` 자리표시(`gs-placeholder`)를 제거한다(컷된 화면은 항목 자체를 내비 배열에서 제거, 그룹 소제목 `작업`·`관리`의 항목 수가 바뀌어도 5개 이하 규칙을 깨지 않게).
- 문서: `DEMO.md`에 새 화면 리허설 항목 ⑰~(이어지는 번호)를 쓰되 **사람 검수 항목마다 뜻·판정 기준·예시 하나·기록 방법을 처음부터 붙인다**. 항목: 진행 줄(스피너·shimmer·경과 초·연결선 채움, 시안은 체크만, 모션 줄이기에서 정지), 새 기획 탭(진행 중 새 요청·새 기획 비활성, 탭 이름 요약, 닫기), 입력창 스크롤바 없음과 자동 높이, 결과 카드 시안 이미지 여백 없음, `확인 필요 N건` 배지 문구와 설명, 전체 보기 아코디언과 섹션 구조, 영문 코드 노출 없음, 시장 인사이트 차트, 실행 기록·검증 페이지(단계·검증·평가·비용 탭), 근거 소재 화면의 플랫폼 묶음·자사 배지·대체 타일, 확인 질문 선택 뒤 요약 접힘, 지식 그래프 3탭과 줌 한계, 저장한 기획 이미지 표시(해당 step이 컷되지 않았다면). `README.md`의 화면 설명, `docs/PHASES.md` 7c 행, `docs/portfolio/DETAIL_PAGE.md`의 UI 설명 한 곳(스크린샷은 사용자 촬영). `tests/test_demo_docs.py`는 **리허설 개수 단언(`== 16`과 이미지 검수 정규식)을 새 개수·번호로 갱신**하고 새 항목에도 같은 엄격도(뜻·판정·예시·기록 방법)를 요구한다.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 리허설 ⑰~ | `DEMO.md` | `tests/test_demo_docs.py`, 사용자 |

**공통 시각 기준(7c 시각 확인 반영, 이후 모든 새 화면이 따른다)**: 간격은 `tokens.css`의 `--gs-space-*`(4px 배수, 기본 리듬은 8px 단위)만 쓰고 색·반경·그림자·글자 크기도 `tokens.css` 변수만 쓴다. 화면에 보이는 문자열은 **한글**이다(영문 내부 코드·브랜드 슬러그·도구 이름·`value`·`n_top` 같은 필드명을 그대로 노출하지 않는다. `taxonomyNames`의 한글 이름, `web/lib/workspace.ts`의 `workspaceLabel`, 그리고 step 13의 한글 표시 매핑을 재사용하고 없는 이름은 새로 지어내지 말고 원문 대신 `기타`·`정보 없음` 같은 한글 대체를 쓴다). 펼침·접힘은 `grid-template-rows: 0fr → 1fr` 방식의 부드러운 아코디언(화살표 회전)이고, 모든 애니메이션·전환은 `@media (prefers-reduced-motion: reduce)`에서 즉시 동작·정지한다. 색에만 의존하지 않고 아이콘·글자를 함께 쓴다. 접힌 영역의 내용은 DOM에 유지하고 접힌 최종 상태는 기존처럼 `hidden` 속성이다(펼칠 때 `hidden`을 동기적으로 제거한 뒤 다음 프레임에 열림 클래스를 붙이고, 접을 때는 전환 뒤 `hidden`을 설정하되 reduced-motion·전환 시간 0이면 즉시 설정한다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/app/page.tsx`, `/web/app/globals.css`, `/web/components/`와 `/web/lib/` 전체(`rg`로 참조 확인), `/web/components/shell/*`, `/DEMO.md`, `/README.md`, `/docs/PHASES.md`, `/docs/portfolio/DETAIL_PAGE.md`, `/tests/test_demo_docs.py`

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/components/*`와 `web/lib/*`의 사용되지 않는 파일(참조 0 확인 후 삭제), `web/app/globals.css`, `web/components/shell/*`(항목 정리만), `web/app/page.tsx`(자리표시 제거만), `DEMO.md`, `README.md`, `docs/PHASES.md`, `docs/portfolio/DETAIL_PAGE.md`, `tests/test_demo_docs.py`, `web/tests/cleanup.test.ts`

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/components/*`와 `web/lib/*`의 사용되지 않는 파일(참조 0 확인 후 삭제), `web/app/globals.css`, `web/components/shell/*`(항목 정리만), `web/app/page.tsx`(자리표시 제거만), `DEMO.md`, `README.md`, `docs/PHASES.md`, `docs/portfolio/DETAIL_PAGE.md`, `tests/test_demo_docs.py`, `web/tests/cleanup.test.ts`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** 옛 파일·규칙 정리(참조 0 확인 후, 목록을 summary에 보고). **2.** 내비·자리표시 정리. **3.** 문서 4곳과 `tests/test_demo_docs.py` 갱신.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- `tests/test_demo_docs.py`: 개수·형식 단언 갱신(약화 금지), 새 항목이 뜻·판정·예시·기록 방법을 포함.
- 정리 검증(`web/tests/cleanup.test.ts` 신규): (1) `web/components`·`web/lib`에 어떤 파일도 import되지 않은 채 남아 있지 않다(파일 목록과 import 그래프를 테스트가 읽어 검사, 파일 0개면 실패), (2) `준비 중` 자리표시가 소스에 없다, (3) `globals.css`에 소스에서 쓰이지 않는 클래스 규칙이 없다(검사 방식은 완료 보고에 적는다).
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
- 서버 코드(`src/`)를 수정하지 마라. 실행 기록·검증 화면을 이 step에서 만들지 마라(step 14 범위). 이유: 구현은 step 14로 이관됐다.
- 참조가 남아 있는 파일·규칙을 삭제하지 마라(`rg`로 확인). 스크린샷·이미지 파일을 만들지 마라. 이유: 화면 촬영은 사용자가 한다.
