# Step 3: checks

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표(`checks`는 `domain`만), CRITICAL 규칙(판정은 코드)
- `/docs/ARCHITECTURE.md` — "그라운딩 원칙", "컨텍스트 관리"(근거 ID 별도 칸)
- `/docs/ADR.md` — ADR-012, ADR-014(식약처 안내서 기준 점검, 법적 판단 아님)
- `/docs/COMPETENCY_QUESTIONS.md` — CQ-10·11과 "한계와 조건"(unknown은 "인증 없음"이 아니다)
- `/docs/TAXONOMY.md` — 닫힌 값 정의
- `/tests/test_architecture.py`
- `/src/beautyads/domain/claims.py`, `/src/beautyads/domain/labels.py`, `/src/beautyads/domain/skin.py`, `/src/beautyads/domain/tools.py`(step 2) — 규칙 모델, 닫힌 값, 근거 ID 형식

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/domain/plan.py`(새 파일), `src/beautyads/domain/lookups.py`(새 파일), `src/beautyads/checks/__init__.py`(새 파일), `src/beautyads/checks/plan_checks.py`(새 파일), `tests/test_plan_checks.py`(새 파일)

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/domain/plan.py`, `src/beautyads/domain/lookups.py`, `src/beautyads/checks/__init__.py`, `src/beautyads/checks/plan_checks.py`, `tests/test_plan_checks.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

기획안을 **코드로** 검사하는 결정론 검사기를 만든다. 모델도 네트워크도 쓰지 않는다(`checks`는 `domain`만 import한다). 그래프 조회는 `domain/lookups.py`의 `Protocol`로 주입받는다. **이 step 안에서는 실제 접속·실행을 하지 않는다.**

**`domain/plan.py`**(pydantic, `extra="forbid"`): `Plan`(`title`, `hook_type: HookType`, `hook_text`, `scenes: list[str]`, `copy_lines: list[str]`, `image_brief: str | None`, `cta_type: CtaType`, `angle: Angle`, `format: Format`, `category: Category`, `product_url: str | None`, `claimed_efficacy: list[Claim]`, `evidence_ids: list[str]`), `CheckSeverity`(StrEnum `fail`·`unknown`), `CheckCode`(StrEnum `EVIDENCE_MISSING`·`EVIDENCE_NOT_IN_HANDOFF`·`EVIDENCE_NOT_FOUND`·`TAXONOMY_INVALID`·`PROHIBITED_EXPRESSION`·`CERT_REQUIRED_UNVERIFIED`·`EFFICACY_UNSUPPORTED`·`EFFICACY_UNKNOWN`), `CheckIssue`(`code`, `severity`, `field: str | None`, `detail: str`), `PlanCheckReport`(`issues: list[CheckIssue]`, `disclaimer: str`(기본값 `domain.claims.CLAIM_CHECK_DISCLAIMER`), 속성 `passed: bool` = `fail` 이슈가 하나도 없음, 속성 `unknown_count: int` = `unknown` 심각도 이슈 수와 `unknown_codes: dict[str, int]` = 코드별 건수. 사용자가 보는 결과와 보고에서 "근거 연결 없음"이 눈에 띄게 드러나도록 하는 값이며 `passed`가 `True`여도 0이 아닐 수 있다). 근거 ID 형식은 step 2의 `domain.tools.EVIDENCE_ID_PATTERN`이다(새로 정의하지 않고 import한다).

**`domain/lookups.py`**(`Protocol`만): `EvidenceIndex.existing(ids: Collection[str]) -> set[str]`(그래프에 실제 있는 소재 ID), `EfficacySupportLookup.efficacy_support(product_url: str, efficacy: Claim) -> SupportStatus`, `CertLookup.cert_status(product_url: str, efficacy: Claim) -> CertStatus`. `SupportStatus`는 `supported`·`unsupported`·`unknown`, `CertStatus`는 `certified`·`not_certified`·`unknown`이다. `unknown`은 연결을 찾지 못한 것이고 "없음"이 아니다.

**`checks/plan_checks.py`**: `run_checks(plan: Plan, *, handoff_evidence_ids: Collection[str], rules: Sequence[ClaimRule], evidence_index: EvidenceIndex, support: EfficacySupportLookup, certs: CertLookup) -> PlanCheckReport`. 순수 함수이고 검사 순서가 고정이다.
1. **근거 ID**: `evidence_ids`가 비면 `EVIDENCE_MISSING`(fail). 핸드오프(리서치가 넘긴) 목록에 없는 ID는 `EVIDENCE_NOT_IN_HANDOFF`(fail), 그래프에 없는 ID는 `EVIDENCE_NOT_FOUND`(fail). 형식이 틀린 ID도 `EVIDENCE_NOT_FOUND`다.
2. **분류 값**: `Plan`의 분류 칸이 닫힌 목록 밖이면 `TAXONOMY_INVALID`(fail). 모델 출력을 `Plan`으로 검증할 때 이미 거르지만, 이 검사는 `Plan`을 거치지 않은 dict 입력(`run_checks_on_dict` 같은 별도 진입점)에도 같은 결과를 내야 한다. 이 진입점은 pydantic 검증 실패를 `TAXONOMY_INVALID` 이슈로 바꾼다.
3. **금지 표현**: `title`, `hook_text`, 각 `scenes`·`copy_lines`·`image_brief`를 필드 이름(`title`, `scene[0]` 등)과 함께 `domain.claims.check_plan_fields`에 넘긴다(**제목 포함**, 식약처 안내서 III.7). `prohibited` 규칙에 걸린 표현은 `PROHIBITED_EXPRESSION`(fail), `detail`에 필드·규칙 ID·표현을 적는다. `requires_functional_cert`·`requires_substantiation`에 걸리면 3-1·3-2로 간다.
   - 3-1. `requires_functional_cert`에 걸린 표현: `certs.cert_status`로 판정해 `certified`가 아니면 `CERT_REQUIRED_UNVERIFIED`(`not_certified`는 fail, `unknown`은 `unknown` 심각도).
   - 3-2. `requires_substantiation`에 걸린 표현은 4번의 효능 근거 검사로 위임한다(관찰만 남긴다).
4. **효능 근거**: `claimed_efficacy`의 각 값에 `product_url`이 있으면 `support.efficacy_support`로 확인한다. `unsupported`는 `EFFICACY_UNSUPPORTED`(fail), `unknown`은 `EFFICACY_UNKNOWN`(`unknown` 심각도, **실패가 아니다**: "근거 연결 없음"이지 "근거 없음"이 아니다). `product_url`이 없으면 이 검사는 `EFFICACY_UNKNOWN`으로 남기고 통과시키지 않는다.
- 리포트마다 `disclaimer`를 붙인다. 면책 문구를 이 모듈에서 다시 쓰지 않는다(`CLAIM_CHECK_DISCLAIMER`를 그대로 쓴다).
- **LLM 채점(차별성·요청 적합성)은 이 모듈에 없다**(step 6).

**반드시 있어야 하는 테스트**(`tests/test_plan_checks.py`, 가짜 `Protocol` 구현과 합성 `ClaimRule`·합성 문자열만, 실제 `config/claim_rules.yaml` 내용이나 모델이 만든 문장을 기대값으로 굳히지 않는다):
- 모든 근거 ID가 핸드오프 목록과 그래프에 있으면 근거 관련 이슈가 없다. 빈 `evidence_ids`는 `EVIDENCE_MISSING`이다(빈 목록이 통과가 아니다). 핸드오프 밖 ID, 그래프에 없는 ID, 형식이 틀린 ID가 각각 맞는 코드로 나온다.
- 분류 값이 닫힌 목록 밖인 dict는 `TAXONOMY_INVALID`이고 예외가 아니라 리포트로 나온다. 모든 닫힌 값은 통과한다.
- 금지 표현: 합성 규칙의 용어가 `title`에만 있어도, `scene`에만 있어도, `image_brief`에만 있어도 `PROHIBITED_EXPRESSION`이고 `field`가 맞다. 어디에도 없으면 이슈가 없다. 규칙이 0개이면 금지 표현 이슈는 없지만 보고서에 규칙 수 0이 드러난다(`detail` 또는 별도 필드, 통과를 가정하지 않는다).
- `requires_functional_cert` 규칙: `certified`면 통과, `not_certified`면 fail, `unknown`이면 `unknown` 심각도이고 `passed`를 깨지 않는다.
- 효능 근거: `supported` 통과, `unsupported` fail, `unknown`은 `EFFICACY_UNKNOWN`(`unknown`)이고 `passed`를 깨지 않는다, `product_url`이 `None`이면 `EFFICACY_UNKNOWN`이다.
- `unknown_count`·`unknown_codes`가 `unknown` 이슈 수와 코드별 건수와 같고, `passed`가 `True`인 리포트에서도 0이 아닐 수 있다.
- 같은 입력은 같은 `issues` 순서와 내용이다. 모든 리포트에 `disclaimer`가 있고 `CLAIM_CHECK_DISCLAIMER`와 같다.
- `tests/test_architecture.py`가 통과한다(`checks`는 `domain`만 import한다).

## Acceptance Criteria

```bash
make verify   # lint + test 통과
```

## 검증 절차

1. 위 AC 커맨드를 실행한다.
2. 아키텍처 체크리스트를 확인한다:
   - ARCHITECTURE.md 디렉토리 구조를 따르는가?
   - ADR 기술 스택을 벗어나지 않았는가?
   - AGENTS.md CRITICAL 규칙을 위반하지 않았는가?
3. 결과를 최종 응답(JSON)으로 보고한다. `phases/` 아래 파일은 수정하지 않고 git commit도 하지 않는다:
   - 성공 → `"status": "completed"`, `"summary": "산출물 한 줄 요약(설치한 패키지 버전 포함)"`
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

- `checks/`에 `llm`·`graph`·`store`·`neo4j`를 import하거나 모델을 부르지 마라. 이유: `checks`는 `domain`만 import하고 판정할 수 있는 것은 코드가 판정한다(AGENTS.md).
- 검사 대상이 0건인 경우(빈 근거 ID, `product_url` 없음, 규칙 0개)를 통과로 처리하지 마라. 이유: "검사한 것 0건, 실패 0건"은 통과가 아니다(B-FP-069).
- `unknown`(근거 연결 없음)을 `unsupported`나 "인증 없음"으로 바꾸거나 `passed`에 합쳐 숨기지 마라(`unknown_count`로 별도 노출). 이유: 성분→효능 표와 인증 연결은 범위가 제한적이고 연결 없음이 곧 없음이 아니다(COMPETENCY_QUESTIONS 한계).
- 테스트 기대값에 실제 규칙 내용이나 모델이 만든 문장·분류 값을 굳히지 마라. 이유: FP-C03. 합성 규칙과 합성 문자열만 쓴다.
- 기획안 `title`을 검사 대상에서 빼지 마라. 이유: 식약처 안내서 III.7은 제목도 광고 표현으로 본다.
- `CLAIM_CHECK_DISCLAIMER` 문구를 바꾸거나 다시 쓰지 마라. 이유: 면책 문구는 한 곳에서 정의하고 그대로 표시한다(ADR-014).
