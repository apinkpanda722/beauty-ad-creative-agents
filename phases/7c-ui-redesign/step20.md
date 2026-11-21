# Step 20: design-slot-rollback

## 설계 검토 기록

**목적**: step 19의 항목 25(시안 이미지 칸 ① 다듬기)가 step 17 상태보다 부자연스럽다는 사용자 판단에 따라 **항목 25만** step 17 상태로 되돌린다. 과거 커밋을 `git revert`·`reset`하지 말고 이 step의 **새 변경**으로 필요한 줄만 되돌린다(이력 보존). 새 패키지·서버 변경·live 호출 없음. 항목 22(총 건수)·23(기타 마지막)·24(상위·하위 표, 서버 정렬)와 관련된 코드·테스트는 전부 그대로 둔다.

**코드를 열어 확인한 사실(선점검, `git diff c8ab9f6 8a06dcb`와 `git show 9898d5d:…`로 대조했다)**
- `web/app/results.css`에서 step 19가 항목 25로 바꾼 곳은 `.gs-design-image` 관련 4줄뿐이고, 항목 22·24의 추가분(`.gs-insight-head`·`.gs-insight-total`·`.gs-col-primary`·`.gs-col-muted`, 파일 아래쪽 `.gs-insight-note` 다음 4줄)과는 서로 다른 hunk다.
- step 17 커밋(`9898d5d`)의 해당 규칙(복원 목표, 정확히 이 값):
  - `.gs-design-image img { position: relative; display: block; width: 100%; height: 100%; object-fit: contain; }`
  - `.gs-design-image img.gs-design-backdrop { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; filter: blur(24px) brightness(0.85); transform: scale(1.1); }`
  - `.gs-design-image::before`·`::after` 규칙은 **없었다**.
- 현재(step 19) 값: 메인 이미지 규칙에 `z-index: 2`가 추가됨, 배경 규칙이 `z-index: 0`·`blur(32px) brightness(0.78)`·`scale(1.2)`, 그리고 `.gs-design-image::before`·`::after`(14% 전환 띠) 두 규칙이 추가됨. `.gs-design-image { … }`(컨테이너)·`.gs-design-image figcaption`·`.gs-design-placeholder`는 step 17 이후 변경이 없다.
- `web/tests/results.test.tsx`에서 step 19가 항목 25를 위해 추가한 테스트는 **하나**: `it("softens backdrop edges underneath the unmasked main image using surface-token bands", …)`(메인 이미지 `mask-image` 부재·새 `blur(32px)`·`brightness(0.78)`·`scale(1.2)`·`::before`/`::after` 띠 단언). 같은 커밋의 `it("uses shared tokens for insight totals and comparison column emphasis", …)`와 `it("adds comparison column spans and a limit note without sorting standalone rows", …)`는 **항목 22·24** 테스트이므로 남긴다. `it("fills the media slot with a contained image over a blurred backdrop and falls back on failure", …)`(step 17, `backdropRule`에 `object-fit: cover`·`blur(`, 규칙 전체 `object-fit: cover` 출현 1번, `mainRule`에 `contain`)는 수정하지 않고 통과해야 한다.
- `DEMO.md`: step 19가 바꾼 줄은 ㉑(1)의 판정 문구와 ㉒(6)~(8) 추가다. ㉑의 다른 칸(step 18이 바꾼 (4) 전체 보기의 비용 문구 포함)과 ㉒는 되돌리지 않는다. `README.md`·`docs/portfolio/DETAIL_PAGE.md`에는 항목 25 관련 문구가 없다(`rg "블러|전환 띠|blur" README.md docs/portfolio/DETAIL_PAGE.md`로 재확인하고, 있으면 같이 되돌린다).

**설계 결정(정확한 되돌림 범위)**
1. `web/app/results.css`: 위 "복원 목표" 두 규칙으로 정확히 교체하고(`z-index` 삭제, `blur(24px) brightness(0.85)`, `scale(1.1)`), `.gs-design-image::before`·`.gs-design-image::after` 두 규칙 줄을 **삭제**한다. 그 밖의 줄(특히 항목 22·24의 `.gs-insight-head`·`.gs-insight-total`·`.gs-col-primary`·`.gs-col-muted`)은 한 글자도 바꾸지 않는다.
2. `web/tests/results.test.tsx`: 위 "softens backdrop edges…" 테스트 **하나만 삭제**한다(새 테스트로 대체하지 않는다). 다른 테스트·import는 건드리지 않는다. 삭제로 쓰이지 않게 된 import가 생기면(이 테스트만 쓰던 것이 있을 때) 그것만 제거한다.
3. `DEMO.md` ㉑(1): 판정 문구를 step 17 시점으로 되돌린다. 현재 `(1) 시안 이미지: 이미지 칸이 카드 높이 전체를 채우고 시안 문구가 잘리지 않으며 남는 영역의 흐린 배경이 칸 위아래 가장자리로 부드럽게 이어지면 O, 아래 빈 여백이 생기거나 문구가 잘리거나 흐린 배경이 띠처럼 끊겨 보이면 X.`를 `(1) 시안 이미지: 이미지 칸이 카드 높이 전체를 채우고 시안 문구가 잘리지 않으며 남는 영역이 흐린 같은 이미지로 채워지면 O, 아래 빈 여백이 생기거나 문구가 잘리면 X.`로 교체한다(현재 문구는 파일에서 확인하고 정확히 이 부분만 바꾼다). 번호·개수(`⑰~㉗` 11개)·형식(`뜻 —`·`판정 —`·`예시 —`·`기록 방법 —`, 칸 번호 연속, 판정 안 괄호 문자 금지, `결과 기록: ______.`)과 `tests/test_demo_docs.py` 통과를 유지한다. ㉒와 ㉑의 나머지 칸은 수정하지 않는다.

**교체·삭제 단언 표**

| # | 파일 | 이전 | 이후 |
|---|---|---|---|
| X1 | `web/tests/results.test.tsx` 파일 끝부분 `it("softens backdrop edges underneath the unmasked main image using surface-token bands")` | 메인 이미지 `mask-image` 부재, 배경 `blur(32px)`·`brightness(0.78)`·`scale(1.2)`, `::before`/`::after` 14% 전환 띠 단언 | 테스트 삭제(항목 25 롤백의 일부, 대체 테스트 없음) |

위 표 밖의 기존 단언은 수정하지 마라. 되돌린 결과로 깨지는 단언이 나오면 구현하지 말고 `blocked`로 멈추고 최소 교체안을 `reason`에 적어라.

**불변 확인(완료 보고 `summary`에 결과를 적는다)**: 작업 후 `git diff 8a06dcb -- src web/lib web/components web/tests/insight-panel.test.tsx web/tests/insight.test.ts tests/test_agent_tools.py`가 **비어 있어야 한다**(항목 22~24 코드·테스트 불변). `git diff 8a06dcb -- web/app/results.css`에는 항목 25 규칙의 되돌림 hunk만 있어야 하고, `git diff 8a06dcb -- web/tests/results.test.tsx`에는 삭제 한 건(X1)만 있어야 한다. `git diff 9898d5d -- web/app/results.css`에서 `.gs-design-*` 규칙에 차이가 없어야 한다(step 17 상태와 동일).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/ARCHITECTURE.md`, `/docs/ADR.md`(ADR-009 테넌트), `/docs/PHASES.md`
- `/web/app/results.css`(`.gs-design-*`·`.gs-insight-*`·`.gs-col-*`), `/web/components/results/DesignImage.tsx`(읽기 전용), `/DEMO.md`(리허설 확인 ㉑)
- `/web/tests/results.test.tsx`(파일 끝부분 step 19 테스트 3개와 `fills the media slot…` 테스트), `/tests/test_demo_docs.py`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `web/app/results.css`(`.gs-design-image` 관련 규칙만), `web/tests/results.test.tsx`(X1 삭제만), `DEMO.md`(㉑(1) 문구만), `README.md`·`docs/portfolio/DETAIL_PAGE.md`(항목 25 관련 문구가 `rg`로 확인될 때만)

열람 금지 경로: `data/interim/`, `data/design/`, `.env`
수정 허용 경로: `web/app/results.css`(`.gs-design-image` 관련 규칙만), `web/tests/results.test.tsx`(X1 삭제만), `DEMO.md`(㉑(1) 문구만), `README.md`·`docs/portfolio/DETAIL_PAGE.md`(항목 25 관련 문구가 `rg`로 확인될 때만)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것은 대상이 아니다. 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1.** `git diff c8ab9f6 8a06dcb -- web/app/results.css web/tests/results.test.tsx DEMO.md`와 `git show 9898d5d:web/app/results.css`로 되돌릴 줄을 확인한다. **2.** `results.css`의 `.gs-design-image` 두 규칙을 step 17 값으로 복원하고 `::before`·`::after` 두 규칙을 삭제한다. **3.** `results.test.tsx`의 X1 테스트 하나를 삭제한다. **4.** `DEMO.md` ㉑(1) 문구를 되돌린다. **5.** 불변 확인 `git diff` 결과를 `summary`에 적는다.

**테스트(합성 데이터, 서비스·키·네트워크·`.env` 없음)**
- 새 테스트는 만들지 않는다(삭제 X1만). 기존 테스트는 모두 수정 없이 통과해야 한다: 특히 `web/tests/results.test.tsx`의 `fills the media slot with a contained image over a blurred backdrop and falls back on failure`(step 17), 항목 22~24 테스트(`insight-panel.test.tsx`·`insight.test.ts`·`results.test.tsx`의 `uses shared tokens for insight totals and comparison column emphasis`·`adds comparison column spans and a limit note without sorting standalone rows`), `tests/test_agent_tools.py`, `tests/test_demo_docs.py`.
- `make verify`의 파이썬·웹 개수를 `summary`에 적는다(웹은 삭제한 테스트 1개만큼 줄어야 한다).
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
- `git revert`·`git reset`·`git checkout <커밋> -- <파일>`로 과거 커밋 전체를 되돌리지 마라. 이 step의 변경은 새 커밋(하네스의 step 커밋)에 담기는 **새 변경**이어야 한다. 이유: 이력을 지우지 않는다.
- 되돌리는 범위는 `web/app/results.css`의 `.gs-design-image` 관련 규칙, `web/tests/results.test.tsx`의 X1 테스트 하나, `DEMO.md` ㉑(1) 문구뿐이다. 항목 22·23·24의 코드(`web/lib/insight.ts`·`web/components/results/{InsightPanel,DistributionChart}.tsx`·`src/beautyads/agents/tools.py`·`.gs-insight-*`·`.gs-col-*` CSS)와 테스트(`insight-panel.test.tsx`·`insight.test.ts`·`tests/test_agent_tools.py`·`results.test.tsx`의 항목 22·24 테스트), `DesignImage.tsx` 구조, step 17의 `fills the media slot…` 단언을 수정·삭제하지 마라. 이유: 사용자가 항목 25만 되돌리라고 했다.
- 위 "교체·삭제 단언 표"(X1) 밖의 기존 단언을 수정·삭제·약화하지 마라. 서버(`src/`)·`DataTable`을 포함한 `web/components/**`·새 패키지를 건드리지 마라. 이유: 범위 분리.
- `DEMO.md`는 ㉑(1) 판정 문구만 바꾸고 ㉒·㉑의 나머지 칸, ⑰~㉗의 번호·개수·형식 규칙을 깨지 마라. `docs/PHASES.md`의 `| 58 |` 행, `docs/portfolio/DETAIL_PAGE.md`의 수치 표 행, `docs/TROUBLESHOOTING_LOG.md`를 수정하지 마라. 이유: 문서 가드 테스트.
- `web/app`·`web/components`·`web/lib` 소스에 `examples`·`.examples`·`예시 요청` 문자열을 쓰지 마라. 이유: `tests/test_demo_docs.py`의 예시 칩 금지 가드.
