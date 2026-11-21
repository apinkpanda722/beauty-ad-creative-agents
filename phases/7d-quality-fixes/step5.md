# Step 5: image-prompt-refine

## 설계 검토 기록

**배경(사용자 live 확인, 2026-11-21)**: 7d step 1의 이미지 개선(빈 병·물병·코에 대는 구도·서양인·어두운 사각형)은 test A 3장·test B 3장 확인에서 해소됐다. **남은 문제 세 가지**를 같은 phase의 step 5로 보완한다.
1. test B 요청 6번: 서 있는 **튜브의 아래쪽 절반이 투명하게 비친다**. 원인 추정: step 1이 넣은 `IMAGE_STYLE_CLAUSE`의 "용기가 나오면 내용물이 보여야 한다"가 **불투명해야 할 튜브에도** 적용된다.
2. test B 요청 5번: **튜브 끝이 볼 쪽을 향해** 짜서 바르는 모습(경계선).
3. test A 요청 2번: **스포이트를 든 손과 병 안의 스포이트가 둘 다** 그려진다.
수정은 `agents/design_images.py`의 **`IMAGE_STYLE_CLAUSE`에서만** 한다(`IMAGE_NO_TEXT_CLAUSE`·`image_prompt`의 정리 로직·2000자 한도·합성(`design_compose.py`)은 그대로). 이 step의 live 확인은 7d PR·병합의 조건이 아니다(사용자가 다음 live 확인에서 같은 요청을 여러 번 해서 본다).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `agents/design_images.py`(step 1 이후): `IMAGE_STYLE_CLAUSE`(여러 문자열 조각을 이은 한 문자열), `IMAGE_NO_TEXT_CLAUSE`(불변), `IMAGE_PROMPT_SUFFIX = IMAGE_STYLE_CLAUSE + " " + IMAGE_NO_TEXT_CLAUSE`, `image_prompt(plan)`(장면 정리 후 `scene[: 2000 - len(IMAGE_PROMPT_SUFFIX) - 1]` + `IMAGE_PROMPT_SUFFIX`). 접미사가 길어지면 장면 상한이 자동으로 줄어든다(코드 변경 없음).
- 현재 `IMAGE_STYLE_CLAUSE`의 해당 부분(글자 그대로): `용기가 나오면 내용물이 보여야 한다(맑은 물처럼 보이는 투명 액체 금지, 세럼은 약간 점성이 있는 연한 색 액체와 스포이트나 펌프 형태, 튜브는 닫힌 튜브). `
- 소비자 테스트(`tests/test_design_images.py`, step 1이 만듦): `test_image_style_and_no_text_instructions_are_exact`(`IMAGE_STYLE_CLAUSE == (...)` 글자 그대로 고정, 288~302행 부근), `test_style_suffix_survives_cleaning_and_long_scenes`(`brief ∈ {None, "SYNTH_SCENE (REMOVE)", "가"*3000}`에서 `endswith(IMAGE_PROMPT_SUFFIX)`, `len(prompt) <= 2000`, `len == 2000`(긴 장면), 그리고 **접미사 문구 포함 단언** `"(손등이나 볼에 제품을 바르는 손과 피부 클로즈업)" in prompt`와 **`"(맑은 물처럼 보이는 투명 액체 금지," in prompt`**), 정확 일치 `prompt == "SYNTH_VISUAL\n" + IMAGE_PROMPT_SUFFIX`류(상수 이름으로 비교해 문구가 바뀌어도 통과). `tests/test_api_assembly.py` 137행은 `endswith(IMAGE_NO_TEXT_CLAUSE)`만 단언한다.

**설계 결정**: `IMAGE_STYLE_CLAUSE`의 "용기가 나오면 내용물이 보여야 한다(…)" 한 문장을 아래 세 문장으로 **바꾼다**(앞뒤 문장은 글자 그대로 둔다). 새 `IMAGE_STYLE_CLAUSE` 전체(글자 그대로 고정, 줄바꿈 없는 한 문자열):
`장면은 훅 문구를 가장 잘 보여 주는 하나의 순간으로 고르고 기본은 사용 장면이다(손등이나 볼에 제품을 바르는 손과 피부 클로즈업). 얼굴 전체를 정면으로 잡는 구도와 병이나 튜브를 코나 입에 대는 구도는 그리지 않는다. 유리병 용기는 내용물이 보여야 한다(맑은 물처럼 투명한 액체 금지, 세럼은 약간 점성이 있는 연한 색 액체와 스포이트 형태). 튜브는 전체가 불투명한 단색 소재의 닫힌 튜브이며 내용물이 비쳐 보이지 않고(내용물은 손가락 끝에 덜어낸 모습으로만 보인다) 튜브 끝을 얼굴 쪽으로 향하게 하거나 얼굴에 대지 않는다. 같은 제품은 화면에 한 개만 그리고 스포이트를 든 손이 있으면 병 안에 스포이트를 또 그리지 않는다. 제품을 얼굴에 직접 대거나 문지르지 말고 손가락 끝에 덜어 바르는 모습으로 그린다. 인물이 나오면 한국인 모델이다.`
- 바뀐 것: ① 병과 튜브를 **구분**(유리병은 내용물이 보임, 튜브는 전체 불투명·단색·닫힘·내용물이 비치지 않음) → 문제 1, ② 튜브 끝을 얼굴 쪽으로 향하게 하거나 얼굴에 대지 않음 → 문제 2, ③ 같은 제품은 한 개만, 스포이트를 든 손이 있으면 병 안에 스포이트를 또 그리지 않음 → 문제 3, ④ 세럼의 "스포이트나 펌프 형태"는 **"스포이트 형태"**로 좁힌다(문제 3과 충돌하지 않게. 펌프를 금지하는 것이 아니라 이 문구가 병 안 스포이트를 권하지 않도록 줄였다는 점을 변경 기록에 적는다).
- 바꾸지 않는 것(글자 그대로): 첫 문장(사용 장면 기본·손등이나 볼에 바르는 손과 피부 클로즈업), 얼굴 정면·코나 입에 대는 구도 금지, "제품을 얼굴에 직접 대거나 문지르지 말고 손가락 끝에 덜어 바르는 모습으로 그린다", "인물이 나오면 한국인 모델이다", 그리고 `IMAGE_NO_TEXT_CLAUSE`.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| 새 `IMAGE_STYLE_CLAUSE` 값 | `agents/design_images.py` | `IMAGE_PROMPT_SUFFIX`·`image_prompt`, `tests/test_design_images.py`, `api/assembly.py`(`image_prompt` 호출, 코드 변경 없음), 이미지 프롬프트를 Langfuse generation 입력으로 수집하는 `api/assembly.py`(7d step 3, 코드 변경 없음) |
| 변경 기록 행 | `docs/PROMPT_CHANGELOG.md` | 사람(조언 세션), 상세 페이지 "부딪힌 문제" 원천 |

**기존 단언과의 충돌 점검**: (1) `test_image_style_and_no_text_instructions_are_exact`의 `IMAGE_STYLE_CLAUSE == (...)`는 **새 문구로 갱신**한다(정확 일치 유지, 부분 문자열로 바꾸지 않음). (2) `test_style_suffix_survives_cleaning_and_long_scenes`의 `"(맑은 물처럼 보이는 투명 액체 금지," in prompt`는 새 문구에서 사라지므로 **새 문구의 같은 위치**로 갱신한다: `"(맑은 물처럼 투명한 액체 금지,"`(단언을 지우지 않고 같은 의미를 같은 엄격도로). `"(손등이나 볼에 제품을 바르는 손과 피부 클로즈업)"` 단언은 그대로 통과한다. (3) 접미사가 길어졌지만 `len(prompt) <= 2000`·`len == 2000`(긴 장면)·`endswith(IMAGE_PROMPT_SUFFIX)`·`image_brief=None`이면 접미사만 반환하는 단언은 코드가 `len(IMAGE_PROMPT_SUFFIX)`로 계산하므로 그대로 통과해야 한다(**길이 테스트가 그대로 통과해야 한다**). (4) 상수 이름으로 비교하는 정확 일치(`== "SYNTH_VISUAL\n" + IMAGE_PROMPT_SUFFIX` 등)는 문구가 바뀌어도 불변. 동결 가드: `design_images.py`는 동결 줄·해시 대상이 아니다(7d step 1에서 확인, `tests/test_prereg.py`·`tests/test_freeze_guard.py`는 `design_*`를 참조하지 않음).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`(CRITICAL: 동결 기준을 바꾸지 않는다), `/docs/PROMPT_CHANGELOG.md`(7d step 1이 더한 이미지 프롬프트·합성 행의 형식), `/docs/ARCHITECTURE.md`
- `/src/beautyads/agents/design_images.py`, `/src/beautyads/agents/planning.py`(`image_brief` 규칙은 읽기 전용)
- `/tests/test_design_images.py`(전체), `/tests/test_api_assembly.py`(137행 부근, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/design_images.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_design_images.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `src/beautyads/agents/design_images.py`, `docs/PROMPT_CHANGELOG.md`, `tests/test_design_images.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

**1. `agents/design_images.py`**: `IMAGE_STYLE_CLAUSE`를 위 "설계 결정"의 새 문구로 **글자 그대로** 바꾼다(문자열 조각을 이은 현재 형식을 유지해도 되고, 이은 결과가 위 문자열과 정확히 같아야 한다). 다른 상수·함수는 바꾸지 않는다.

**2. `docs/PROMPT_CHANGELOG.md`**: 표 끝에 행을 **추가**한다(기존 행은 고치지 않는다): `2026-11-21 | — | agents/design_images.py(이미지 프롬프트, 코드, 7d step 5)` — `IMAGE_STYLE_CLAUSE`의 용기 문장을 병·튜브 구분으로 바꿈(유리병은 내용물이 보이게, 튜브는 전체 불투명한 단색 닫힌 튜브로 내용물이 비치지 않게, 튜브 끝을 얼굴 쪽으로 향하게 하거나 얼굴에 대지 않기, 같은 제품은 한 개만·스포이트를 든 손이 있으면 병 안에 스포이트를 또 그리지 않기, 세럼 형태는 "스포이트나 펌프 형태"에서 "스포이트 형태"로 좁힘), 이유: 사용자 live 확인에서 튜브 아래쪽 절반이 투명하게 비침(test B 6번)·튜브 끝이 볼 쪽을 향해 짜서 바르는 모습(test B 5번)·스포이트를 든 손과 병 안 스포이트가 둘 다 그려짐(test A 2번), 동결 줄(`planning.py`의 `image_brief` 규칙)이 아니라서 사전 등록 문서는 건드리지 않는다.

**테스트(합성 데이터, 모델·네트워크 없음)**
- `tests/test_design_images.py`(위 두 기대값 갱신 + 케이스 추가, 단언 약화 금지): (1) `IMAGE_STYLE_CLAUSE`가 새 문구와 **글자 그대로** 같다(테스트에 그 문자열을 그대로 적는다), (2) `IMAGE_PROMPT_SUFFIX == IMAGE_STYLE_CLAUSE + " " + IMAGE_NO_TEXT_CLAUSE`이고 `IMAGE_NO_TEXT_CLAUSE` 값 불변(기존 문구 단언 유지), (3) 새 문구에 다음이 **모두 포함**된다: `유리병 용기는 내용물이 보여야 한다`, `튜브는 전체가 불투명한 단색 소재의 닫힌 튜브`, `내용물이 비쳐 보이지 않고`, `튜브 끝을 얼굴 쪽으로 향하게 하거나 얼굴에 대지 않는다`, `같은 제품은 화면에 한 개만 그리고`, `병 안에 스포이트를 또 그리지 않는다`, (4) 옛 문구 `튜브는 닫힌 튜브`와 `스포이트나 펌프 형태`는 **더 이상 없다**(병·튜브 구분이 실제로 바뀜), (5) 바뀌지 않아야 할 문장이 그대로 있다(첫 문장, 얼굴 정면·코나 입 금지, 제품을 얼굴에 직접 대거나 문지르지 말고 손가락 끝에 덜어 바르기, 한국인 모델), (6) 길이 테스트 그대로 통과(`image_brief="가"*3000` → 길이 2000, 끝이 접미사, 접미사가 잘리지 않음), (7) 접미사의 괄호 문구가 장면 정리로 지워지지 않는다(`(손등이나 볼에 …)`와 `(맑은 물처럼 투명한 액체 금지,`가 결과에 남음), (8) `image_brief=None`이면 접미사만 반환.
- 모델이 만든 문장·그림을 기대값으로 굳히지 않는다(합성 문자열만).

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

- `agents/planning.py`·`agents/evaluation.py`·`agents/supervisor.py`(프롬프트·동결 줄·해시·`image_brief` 규칙)·`docs/results/`·`docs/EVAL.md`의 동결 기준·`tests/test_prereg.py`·`tests/test_freeze_guard.py`를 수정하지 마라. 이유: 동결 값은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL). 이미지 프롬프트 보완은 동결 줄이 아닌 `design_images.py`의 `IMAGE_STYLE_CLAUSE`로만 한다.
- `IMAGE_NO_TEXT_CLAUSE`의 값, 장면 정리 로직(괄호·주석·따옴표·URL 제거), 2000자 한도, "글자·로고·브랜드·제품명·라벨 금지" 지시, `IMAGE_STYLE_CLAUSE`에서 위 "바꾸지 않는 것"의 문장을 바꾸거나 약화하지 마라. `design_compose.py`를 수정하지 마라. 이유: 이미 live로 해소가 확인된 규칙과 합성(어두운 사각형 제거)을 건드리면 회귀한다.
- 기존 테스트 단언을 약화·삭제하지 마라(위 "기존 단언과의 충돌 점검"의 두 갱신만 허용: 정확 일치 상수 값 갱신, 접미사 괄호 문구 단언을 새 문구의 같은 위치로 갱신). 길이 테스트를 느슨하게 바꾸지 마라. 이유: 가드를 약화하면 회귀를 못 잡는다.
- 이미지 모델을 호출하거나 `data/design/`의 파일을 읽지 마라. 이미지 품질 확인은 사용자가 다음 live 확인에서 같은 요청을 여러 번 해서 한다. 이유: 실제 호출은 사용자가 실행하고(A-FP-040) 사람이 보는 산출물의 확인은 사람이 한다(B-FP-075).
- 새 문구를 모델 응답 기대값처럼 쓰지 마라(이 step의 테스트는 문구가 **글자 그대로** 고정됐는지와 포함·제외 관계만 검사한다). 이유: 프롬프트가 이미지를 반드시 바꾼다고 단정하지 않는다. 효과는 사용자의 O/X 확인이 판정한다.
