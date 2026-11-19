# Step 14: request-wording

## 설계 검토 기록

**배경(조언 세션 요청)**: 요청 후보 문장이 "역량 질문 CQ-xx의 근거를 바탕으로 …"로 시작한다(`eval/evalset_candidates.py:325`). 이 문장을 받는 에이전트도 읽는 사용자도 CQ 번호의 뜻을 모르고 실제 사용자가 하는 말도 아니다. 접두어를 빼고 자연스러운 한국어 요청으로 바꾼다. **카테고리·효능·포맷·훅·앵글 조건과 `axes_used`는 그대로**다. 질문 문장(graph·simple_search)은 접두어가 없으므로 바꾸지 않는다.

**식별자 전수 대조(현재 코드)**: `eval/evalset_candidates.py`(`build_request_candidates(cq_rows, workspaces, *, briefs=None)`: `cqs`(`_eligible(cq_rows)` 중 usage에 "기획" 또는 "리서치"), 반복 `product(_workspaces(workspaces, split), cqs, briefs, _REQUEST_AXES)`, 값 순회에서 `other` 제외, 조건 문구 `condition = f" {phrase}{_object_particle(phrase)} 지정해"`, `message = f"역량 질문 {cq['id']}의 근거를 바탕으로 …"`, 중복 제거 `signature = (workspace.tenant_id, message)`, `id=f"req-{split}-{len(seen):04d}"`, `pools[stratum(axes)].setdefault(cq["id"], [])`, `_round_robin(groups, rng)`, 선택 `reliable[:ceil(limit*2/3)] + unreliable[...]`, `source_cq=cq["id"]`)·`_object_particle(word)`(`:272`)·`_REQUEST_AXES`·`_LABELS`·`WORKSPACE_CATEGORY`·`_FINAL_TARGETS`), `eval/evalset.py`(`RequestItem`: `source_cq: str(min_length=1)`·`axes_used`·`message`(비어 있지 않고 2000자 이하 검증뿐)).

**영향 grep(조사 결과)**: ① 접두어를 만드는 곳은 `evalset_candidates.py:325` 한 곳이고 요청 문장을 파싱·검증하는 코드는 없다(`RequestItem.message`는 공백·길이만 검증). ② `source_cq`를 읽는 다른 `src` 코드는 없고 다른 테스트의 `source_cq` 값은 각자의 합성 픽스처다. ③ `data/evalset/`가 아직 없고 사전 등록도 전이라 세트 해시 변경은 동결 값·사전 등록과 충돌하지 않는다. 프롬프트 `_SYSTEM`·버전·상수에도 영향이 없다. ④ **문장이 CQ와 무관해지므로 CQ 반복이 같은 문장을 CQ 수만큼 만들었고, 제거하면 `(tenant, message)` 중복 제거가 첫 CQ만 남겨 `source_cq`가 한 값으로 쏠린다.** 그래서 요청 생성에서 CQ 반복을 빼고 `source_cq`는 선택이 끝난 뒤 순환 배정한다(아래). ⑤ 실제 `BRIEFS`(5쌍)·작업 공간·`other` 제외 기준 고유 문장은 split마다 reliable 30·unreliable 60이라 목표(dev 15·test 30, reliable:unreliable = 2:1)를 채우고도 남는다. ⑥ **요청 `id`(`req-{split}-{열거 순번}`)는 CQ 차원이 빠지면 열거 순번이 달라져 바뀐다**(같은 입력이면 재생성해도 결정적). 시트가 비어 있고 세트가 동결 전이라 문제가 없으며 후보를 다시 생성해야 한다. 질문 문장·질문 id·순서는 이 step이 코드를 건드리지 않으므로 불변이다.

**상수 단언 grep**: `tests/test_evalset_candidates.py`의 다음 단언은 새 조사·문장 형태에 맞게 갱신하고 **검사 취지(`other` 제외·중복 없음·조사 정확)는 유지**한다.
- `:1126 test_object_particle_follows_final_consonant`(`_object_particle` 매개변수 테스트): 함수를 `_instrumental_particle`로 교체하므로 같은 취지(받침 있음·없음·ㄹ 받침·한글 아님)의 테스트로 바꾼다.
- `:1149`의 `f"{noun}{_object_particle(noun)} 지정해" in item.message`와 불량 문자열 목록(`"포맷 포맷"`, `"훅 훅"`, `"각도 각도"`, `"각도을"`): `f"{noun}{_instrumental_particle(noun)} 작성해 주세요"`로 바꾸고 불량 목록에 `"각도으로"`를 더한다(기존 항목은 유지, 각도 뒤에는 "로").
- `:1167 "합성 포맷을 지정해"`: `"합성 포맷으로 작성해 주세요"`로 바꾼다(`포맷 포맷` 없음 단언 유지).
- `:146 assert "기획안 1안" in r.message`: 새 문장에도 "기획안 1안"이 들어가므로 그대로 통과해야 한다. `:166`(`(tenant, message)` 유일)·요청 건수·층 비율(dev 15·test 30, reliable:unreliable 10:5·20:10)·`r.source_cq != "CQ-12"`·결정성 단언은 그대로다.
- `test_request_unknown_values_and_ineligible_rows_are_not_invented`(자격 CQ가 없거나 알 수 없는 값이면 요청 0건·부족 `{"requests_dev": 15, "requests_test": 30}`): 불변이다(자격 CQ가 없으면 요청을 만들지 않는 규칙을 유지한다).

**새 칸 대응표**: `source_cq`(요청: 선택 뒤 자격 CQ 순환 배정, 표시용 연결 → 시트 `source_cq` 열 → 사람 검수에서 수정하지 않는 칸), 요청 문장 템플릿(생성기 → 시트 `text` 열 → E2 요청 입력).

**비용(호출 수 기준)**: 모델 호출 0건, 접속 0건. 합성 테스트만 한다. 후보 재생성은 사용자가 DB를 켠 뒤 직접 실행한다.

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL: 실제 호출은 사용자가 실행한다, 모델이 만든 값을 테스트 기대값으로 굳히지 않는다
- `/src/beautyads/eval/evalset_candidates.py`(전체: `build_request_candidates`·`_object_particle`·`_apportion`·`_round_robin`·`write_review_sheet`의 지침 문자열), `/src/beautyads/eval/evalset.py`(`RequestItem`, 읽기 전용)
- `/tests/test_evalset_candidates.py`(전체: `synthetic` 픽스처·요청 관련 테스트 `:128-:170`·`:1112-:1170`)
- `/src/beautyads/eval/p5_compare.py`(읽기 전용: `BRIEFS`), `/config/workspaces.yaml`(읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/eval/evalset_candidates.py`, `tests/test_evalset_candidates.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/eval/evalset_candidates.py`, `tests/test_evalset_candidates.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

요청 후보 문장에서 "역량 질문 CQ-xx의 근거를 바탕으로" 접두어를 없애고 자연스러운 한국어 요청으로 바꾼다. **모델 호출·접속 없음. 이 step 안에서는 실제 실행을 하지 않는다. 테스트를 먼저 쓴다.**

새 식별자: `_instrumental_particle`

**1. 문장 형태(`build_request_candidates`)**
- 기본(조건 없음): `"{카테고리} 제품의 {효능} 광고 기획안 1안을 작성해 주세요."` (카테고리·효능은 기존 `_LABELS` 표시 이름).
- 조건 지정(포맷·훅·앵글 값): `"{카테고리} 제품의 {효능} 광고 기획안 1안을 {구절}{으로|로} 작성해 주세요."` 예: "선케어 제품의 자외선 차단 광고 기획안 1안을 시연 포맷으로 작성해 주세요." `구절`은 기존 규칙(`phrase = label if label.endswith(noun) else f"{label} {noun}"`, 명사는 포맷 `포맷`·훅 `훅 유형`·앵글 `각도`)을 그대로 쓴다. `other` 값 제외도 그대로다.
- `_instrumental_particle(word) -> "으로" | "로"`: 마지막 글자가 한글이고 받침이 있으며 **받침이 ㄹ이 아니면** `으로`, 받침이 없거나 ㄹ이면 `로`, 한글이 아니면 `로`(기본). `_object_particle`은 이제 쓰이는 곳이 없으므로 **삭제한다**(이 변경으로 고아가 된 코드다).
- 문장에 "역량 질문"·"CQ-"·"근거를 바탕으로"가 들어가지 않는다.

**2. 생성·선택 순서**
- 요청 생성 루프에서 CQ 반복을 뺀다: 반복은 `(작업 공간, 브랜드 쌍(brief), 템플릿, 값)`이다. 중복 제거(`(tenant_id, message)`)는 유지한다. 자격 CQ(`cqs`)가 없으면 **요청을 만들지 않는다**(기존 동작, 위 테스트 유지).
- 라운드 로빈 그룹 키는 CQ 대신 **작업 공간 `tenant_id`**로 바꿔 작업 공간 사이에 고르게 퍼지게 한다(층화 선택 `reliable[:ceil(limit*2/3)] + unreliable[...]`와 부족분 보충은 그대로). 시드 20261119도 그대로다.
- `id=f"req-{split}-{번호:04d}"`는 현재 방식(중복 제거를 통과한 열거 순번)을 유지한다(같은 입력에서 결정적, 이전과 번호가 달라지는 것은 알려진 변경).
- **`source_cq`는 선택이 끝난 뒤** split별 선택 순서대로 자격 CQ id 오름차순 목록을 순환해 배정한다(`i % len(자격 CQ)`). 항목을 새 `source_cq`로 다시 만든다(`RequestItem.model_validate`). 이 칸은 문장에 나타나지 않는 표시용 연결이며 어떤 판정·분석도 읽지 않는다.
- `axes_used`는 `_REQUEST_AXES[템플릿]` 그대로, `needs_human_review`·`reviewed` 불변이다.
- 시트 지침(`write_review_sheet`의 `review_instructions.md`)에 한 줄을 추가한다: 요청의 `source_cq`는 문장에 나타나지 않는 표시용 연결이며 수정하지 않는다. 기존 문장·해시 줄은 그대로다.

**테스트(합성 데이터·`tmp_path`, 모델·접속 없음; 위 "상수 단언 grep"의 갱신 대상은 취지를 유지)**
- (1) 모든 요청 문장에 "역량 질문"·"CQ-"가 없고 "기획안 1안"이 들어 있으며 `(tenant_id, message)`가 유일하다. (2) 조건 없는 요청은 기본 형태, 조건 있는 요청은 `{구절}{으로|로} 작성해 주세요` 형태이고 `포맷 포맷`·`훅 훅`·`각도 각도`·`각도을`·`각도으로`가 없으며 `other`의 표시 이름이 없다. (3) `_instrumental_particle`: 받침 있음(포맷→으로, 훅 유형→으로), 받침 없음(각도→로), ㄹ 받침(예: "달"→로), 한글 아님(→로), 빈 문자열(→로). (4) 같은 입력에서 같은 결과(문장·id·`source_cq`·순서), `axes_used`가 템플릿별로 `_REQUEST_AXES`와 같다. (5) `source_cq`가 split별로 자격 CQ를 순환(개수 차이 최대 1)하고 자격 CQ가 아닌 값(`CQ-12` 등 컨텍스트 CQ)이 없다. (6) dev 15·test 30, reliable:unreliable 10:5·20:10 건수와 `shortages` 불변. (7) 자격 CQ가 없으면 요청 0건. (8) 지침에 새 줄과 기존 문구·해시가 모두 있다. (9) 질문 후보 생성 결과(문장·id·순서)는 같은 합성 입력에서 이전 단언과 같다(질문 코드 불변).
- 합성 문장·분류 값을 기대값으로 굳히지 않는다(형식·건수·조사 규칙·결정성만 검사).

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

- 질문 문장·질문 생성·정답 제외·배정 코드(`build_question_candidates`·`_apportion` 등)를 수정하거나 `_FINAL_TARGETS`·`REVIEW_COLUMNS`·`CANDIDATE_FACTOR`·시드 값을 바꾸지 마라. 이유: 이 step은 요청 문장만 다루며 질문 후보는 step 12에서 확정되었다.
- 요청의 `axes_used`·카테고리·효능·포맷·훅·앵글 조건을 바꾸거나 `other` 값을 다시 허용하지 마라. 이유: 조건과 축은 그대로 두고 문장만 자연스럽게 하는 변경이다(E2 층화).
- `source_cq`를 요청 문장에 되돌려 넣거나 다른 코드가 `source_cq`를 읽게 만들지 마라. 이유: 이 칸은 표시용 연결일 뿐이다.
- `eval/evalset.py`·`eval/e3_live.py`·`eval/prereg.py`·`Makefile`을 수정하거나 새 의존성을 추가하지 마라. 이유: 허용 범위 밖이다(필요하면 `blocked`로 보고).
- 기존 테스트의 단언을 약화하지 마라(위 "상수 단언 grep"에 적힌 조사·문장 형태 갱신만 허용, 검사 취지 유지). 합성 문장·모델이 만든 값을 기대값으로 굳히지 마라. 이유: 이미 통과한 step의 계약이며 테스트는 형식과 코드가 하는 일을 검사한다(AGENTS.md CRITICAL).
