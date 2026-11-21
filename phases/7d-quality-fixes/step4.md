# Step 4: docs-release

## 설계 검토 기록

**배경(7d 브리프 4와 이미지 품질 검수)**: (1) 사용자가 실제 시연 요청의 Langfuse 타임라인과 비용 화면을 확인했다. 그래서 7b가 `[Langfuse 타임라인 확인 후 사용]` 표시를 붙여 둔 문장을 쓸 수 있게 풀고, 확인 기록(확인일과 확인 내용)을 남긴다. (2) 이 phase의 step 1이 시안 이미지 프롬프트·합성을 고쳤고 이미지는 사람이 봐야 하므로, **사람 검수 항목**을 DEMO.md의 리허설 확인에 더한다. 이 step은 문서와 문서 테스트만 바꾼다(서버·화면 코드 불변).

**사용자가 확인한 사실(조언 세션 전달, 2026-11-21, 이 저장소의 어느 파일에도 아직 없다)**: 실제 시연 요청 1건의 Langfuse 타임라인과 비용 화면에서 **요청 1건 약 31.65초, $0.0618, 단계별 지연과 호출별 비용**이 보였다. 이 값들은 **사용자 화면 확인에서 온 관측값**이다(`docs/results/`의 결과 문서 값이 아니므로 상세 페이지 `수치 표`(출처는 `docs/results/`만 허용)에는 넣지 않고, 확인 기록으로 DEMO.md에만 적는다).

**식별자 전수 대조(현재 코드, 모두 열어 확인)**:
- `DEMO.md`(7b step 5, 139줄): 장면 7 "확인 후 사용할 문장" 줄 `- **확인 후 사용할 문장:** [Langfuse 타임라인 확인 후 사용] 에이전트별 지연과 비용을 Langfuse에서 관측했다.`(94행), 리허설 확인 ⑨ 줄(138행: `...확인한 뒤에만 \`[Langfuse 타임라인 확인 후 사용]\` 문장을 DEMO·README·상세 페이지에 사용할 수 있다...`), 리허설 확인 ①~⑩(`- [ ] ① …` 형식, 각 줄에 `결과 기록:`).
- `README.md`·`docs/portfolio/DETAIL_PAGE.md`: 같은 표시 문장이 각각 한 줄(README 1372행 부근, DETAIL_PAGE 40행).
- `docs/CONTRACTS.md` Langfuse 절(350~352행): 7b step 3이 추가한 줄 중 `**미확인**: 서버 3.225.11이 ingestion 이벤트의 시간·cost_details를 받아 Langfuse 화면 타임라인을 그리는지는 … 갱신한다.`(351행). **기존 줄은 고치지 않는다**(측정 기록).
- `docs/PHASES.md`: 결정 표 끝의 P7 결정 행(7b step 5가 추가). 같은 방식으로 7d 행을 **추가**한다.
- `tests/test_demo_docs.py`(7b step 5, 155줄, 11개 테스트): `test_langfuse_claim_is_conditional(relative)`(70~81행 부근)가 `DEMO.md`·`README.md`·`DETAIL_PAGE.md`의 `관측했다` 줄이 모두 `[Langfuse 타임라인 확인 후 사용]`을 가지는지 단언한다. 리허설 테스트(`assert len(checks) == 10`, `all("결과 기록:" in check ...)`, `"사용자가 live로" in rehearsal`).

**설계 결정**:
- **표시 해제**: 세 파일의 문장에서 `[Langfuse 타임라인 확인 후 사용]` 표시를 **지우고** 사실만 쓴다: `에이전트별 지연과 비용을 Langfuse에서 관측했다.`(**과장 없이**, 수치는 문장에 넣지 않는다. 수치는 아래 확인 기록에만). README·DETAIL_PAGE의 문장 끝에 `(확인 기록: DEMO.md "Langfuse 확인 기록")`을 붙여 근거 위치를 가리킨다.
- **확인 기록(DEMO.md에 새 절 `## Langfuse 확인 기록`)**: 확인일 `2026-11-21`, 확인한 사람 `사용자(화면 확인)`, 확인 내용(실제 시연 요청 1건의 타임라인과 비용 화면, 요청 1건 약 31.65초, 합계 $0.0618, 단계별 지연과 호출별 비용이 화면에 보임), 확인 환경(로컬 `make obs-up`의 Langfuse `http://127.0.0.1:3001`, `make obs-check` 합성 trace 통과), **알려진 한계**(이 확인 당시의 span 구조는 7b 구조였고 7d step 2가 단계별 span을 나눴으므로 새 구조의 화면은 사용자가 다시 확인해야 한다: 결과 기록 칸 `______`), 숫자는 사용자 화면 관측값이라 `docs/results/`의 측정값이 아님.
- **장면 7**(DEMO.md): 새 span 구조(`ask` 아래 `supervisor` → `research` → `planning #1` → `evaluation #1` → (재작업이면 `planning #2` → `evaluation #2`) → `image`)와 호출의 입력·출력(요약·프롬프트·응답, 4,000자 상한, 키·토큰 가림)을 화면에서 확인하는 항목을 더한다. `BEAUTYADS_LANGFUSE_IO=0`으로 입력·출력 전송을 끌 수 있음을 한 줄 적는다(`.env.example`의 이름).
- **리허설 확인 ⑨**: "확인한 뒤에만" 조건을 **충족됨(2026-11-21, 확인 기록 참조)**으로 갱신하되, 7d 이후 새 span 구조·입력·출력 화면 확인은 새 항목 ⑪로 따로 둔다.
- **사람 검수 항목(리허설 확인에 5개 더함, ⑫~⑯)**: 시안 이미지를 사용자가 **같은 요청을 여러 번** 해서 눈으로 본다. 항목마다 **뜻·판정 기준·예시 하나·기록 방법**을 붙인다:
  1. ⑫ **빈 병·물병 여부**: 뜻 — 병·튜브가 내용물이 없는 투명한 맹물 병처럼 보이지 않는가. 판정 — 세럼 병이면 약간 점성이 있는 연한 색 액체와 스포이트·펌프 형태가 보이면 O, 맑은 물처럼 비어 보이면 X. 예시 — 투명한 병 안이 맹물처럼 보이는 그림은 X. 기록 — 요청 번호별 O/X와 한 줄 메모.
  2. ⑬ **코·입에 대는 구도**: 뜻 — 병이나 튜브를 코나 입에 대고 있거나 제품을 얼굴에 직접 대고 문지르는 장면이 없는가. 판정 — 손가락 끝에 덜어 바르거나 손등·볼에 바르는 모습이면 O, 코·입에 대면 X. 예시 — 병을 코에 가져다 댄 클로즈업은 X. 기록 — 요청 번호별 O/X.
  3. ⑭ **사용 장면과 기획안 장면의 일치**: 뜻 — 이미지가 기획안의 장면 구성·훅 문구가 말하는 상황과 맞는가. 판정 — 기획안의 핵심 장면(예: 볼에 바르는 손)이 그림에 있으면 O, 전혀 다른 상황이면 X. 예시 — 기획안이 "볼에 바르는 장면"인데 그림이 제품만 세워 둔 컷이면 X. 기록 — 요청 번호·기획안 제목·O/X.
  4. ⑮ **인물이 한국인으로 보이는가**: 뜻 — 인물이 나오는 시안에서 모델이 한국인으로 보이는가. 판정 — 한국인 모델로 보이면 O, 서양인으로 보이면 X, 인물이 없으면 해당 없음. 예시 — 금발 서양인 얼굴은 X. 기록 — 요청 번호별 O/X/해당 없음.
  5. ⑯ **합성 사각형 여부**: 뜻 — 글자 뒤의 어두운 막이 이미지 위·좌우 끝까지 부드럽게 이어지는가. 판정 — 위·좌우 경계에서 각진 사각형이 보이지 않으면 O, 사각형 윤곽이 보이면 X. 예시 — 헤드라인 주변에 직사각형 윤곽이 보이면 X. 기록 — 요청 번호별 O/X.
  각 항목은 `- [ ] ⑫ **…:**` 형식에 `결과 기록: ______`를 가진다(기존 항목과 같은 형식).
- **개수**: 기존 ①~⑩ 10개 + 새 항목 **⑪(새 span 구조·입력·출력)·⑫·⑬·⑭·⑮·⑯ 6개 = 16개**.
- `docs/CONTRACTS.md` Langfuse 절 끝에 줄을 **추가**한다(기존 줄 불변): `**사용자 화면 확인(2026-11-21)**: 실제 시연 요청 1건의 Langfuse 타임라인과 비용 화면에서 요청 1건 약 31.65초·$0.0618, 단계별 지연과 호출별 비용이 보였다(7b 구조, 사용자 관측값). ingestion 이벤트의 시간·cost_details가 타임라인에 반영되는 것은 이 확인으로 **확인됨**. 7d 이후 새 span 구조·입력·출력 화면은 **미확인**(사용자 확인 후 갱신).`
- `docs/PHASES.md` 결정 표 끝에 7d 행을 **추가**한다(번호는 다음 번호): 7d 범위(시안 이미지 프롬프트 접미사 `IMAGE_STYLE_CLAUSE`, 합성 막을 가장자리까지 확장, Langfuse span 구조 분리와 input/output 1·2단계, 문서 해제), 2단계 수집을 `llm/chat.py`가 아니라 `api/assembly.py` 경계에서 한 이유, 동결 줄 불변, Langfuse 확인 기록.

**만드는 파일 → 읽는 파일 (새 칸)**

| 새 칸 | 만드는 파일 | 읽는 파일 |
|---|---|---|
| `## Langfuse 확인 기록` 절 | `DEMO.md` | `tests/test_demo_docs.py`, README·DETAIL_PAGE의 `(확인 기록: DEMO.md …)` 참조 |
| 리허설 확인 ⑪~⑯ | `DEMO.md` | `tests/test_demo_docs.py`(개수·형식 단언), 사용자(사람 검수) |
| 해제된 문장 | `DEMO.md`·`README.md`·`docs/portfolio/DETAIL_PAGE.md` | `tests/test_demo_docs.py` |
| 확인 기록 줄 | `docs/CONTRACTS.md` | 사람(조언 세션) |
| 7d 결정 행 | `docs/PHASES.md` | 사람(조언 세션) |

**기존 단언과의 충돌 점검**: `tests/test_demo_docs.py`의 두 곳이 바뀐다. (1) `test_langfuse_claim_is_conditional`은 표시가 있어야 통과하는 단언이라 **표시가 사라지면 실패한다** → 약화하지 말고 **새 조건**으로 바꾼다: 세 파일의 `관측했다` 줄은 (a) `[Langfuse 타임라인 확인 후 사용]` 표시가 **없고**, (b) `DEMO.md`에는 `## Langfuse 확인 기록` 절이 있고 그 안에 `2026-11-21`·`31.65`·`$0.0618`·`단계별 지연`·`호출별 비용`이 모두 있으며, (c) README·DETAIL_PAGE의 `관측했다` 줄이 `확인 기록`을 가리키고, (d) 확인 기록에 과장 표현(`항상`·`모든 요청`·`완벽`)이 없다를 단언한다(검사한 줄이 0이면 실패). (2) 리허설 테스트의 `len(checks) == 10`은 **16으로 갱신**(`==` 유지, 부분 비교로 약화 금지)하고 `all("결과 기록:" in check ...)`·`"사용자가 live로" in rehearsal`은 불변이다. 그 밖의 테스트(장면 1~7 존재, 확정 문장 일치, `장애 주입` 등 금지어, 수치 표 출처, Makefile `demo-up`, PHASES·TROUBLESHOOTING 항목 존재)는 불변이어야 한다. `DETAIL_PAGE.md`의 수치 표에는 **새 행을 더하지 않는다**(출처가 `docs/results/`가 아니다).

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md`, `/docs/PRD.md`(시연과 포트폴리오 산출물, 사실과 다른 문구 금지), `/docs/PROMPT_CHANGELOG.md`(step 1이 더한 7d 행), `/docs/PHASES.md`(결정 표 끝), `/docs/CONTRACTS.md`(Langfuse 절 끝)
- `/DEMO.md`, `/README.md`(Langfuse 절 부근), `/docs/portfolio/DETAIL_PAGE.md`, `/.env.example`(`BEAUTYADS_LANGFUSE_IO`는 step 3이 더한 이름)
- `/tests/test_demo_docs.py`(전체), `/src/beautyads/obs/langfuse_sink.py`(span 이름 확인, 읽기 전용)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `DEMO.md`, `README.md`, `docs/portfolio/DETAIL_PAGE.md`, `docs/CONTRACTS.md`, `docs/PHASES.md`, `tests/test_demo_docs.py`

열람 금지 경로: `data/interim/`, `data/design/`
수정 허용 경로: `DEMO.md`, `README.md`, `docs/portfolio/DETAIL_PAGE.md`, `docs/CONTRACTS.md`, `docs/PHASES.md`, `tests/test_demo_docs.py`
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(예: 기본 출력 경로)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

위 "설계 결정"대로 문서를 갱신한다. 기존 문장·항목·행은 **고치지 않고** 필요한 줄만 바꾸거나(표시 해제, ⑨ 조건 갱신) 더한다(확인 기록 절, ⑪~⑯, CONTRACTS·PHASES 추가). 코드(`src/`·`web/`)는 읽기만 한다.

**테스트(`tests/test_demo_docs.py`, 합성 데이터, 파일만 읽는다)**: 위 "기존 단언과의 충돌 점검"의 두 변경과 함께 (3) 리허설 확인 16개가 **모두 `- [ ]` 형식**이고 ⑫~⑯ 항목에 `뜻`·`판정`·`예시`·`기록`이라는 네 요소가 모두 있다(항목마다 검사, 검사한 항목이 0이면 실패), (4) `DEMO.md`에 `장애 주입`·`표식 조회`·`격리 검사`가 여전히 없다(기존 단언 유지), (5) `DETAIL_PAGE.md` 수치 표의 모든 `출처`가 `docs/results/` 아래 실제 파일 또는 `agents/tools.py`이다(기존 단언 유지, 새 행 없음).

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

- `docs/results/`·`docs/EVAL.md`의 동결 기준·`docs/PROMPT_CHANGELOG.md`·`src/`·`web/`·`Makefile`을 수정하지 마라. 이유: 이 step은 문서 해제와 검수 항목뿐이고 동결 기준은 결과를 본 뒤 바꾸지 않는다(AGENTS.md CRITICAL). 프롬프트 변경 기록은 step 1이 한다.
- 사용자가 확인한 값(요청 1건 약 31.65초·$0.0618)을 `docs/results/`의 측정값처럼 쓰거나 상세 페이지 수치 표에 넣거나 일반화("모든 요청", "항상")하지 마라. 이유: 사용자 화면 관측값 1건이고 결과 문서의 측정값이 아니다(PRD 수치 표 규칙, 사실과 다른 문구 금지).
- 새 span 구조·입력·출력 화면을 사용자가 확인했다고 쓰지 마라(⑪은 미확인 항목으로 남긴다). 이미지 품질 검수 결과(⑫~⑯)를 미리 채우지 마라. 이유: 확인은 사용자가 live로 한다(A-FP-040).
- `tests/test_demo_docs.py`의 다른 테스트를 삭제·약화하거나 `[Langfuse 타임라인 확인 후 사용]` 표시를 지우면서 단언을 느슨하게 바꾸지 마라(새 조건은 확인 기록의 존재·날짜·내용으로 더 엄격하게). 이유: 표시를 푸는 근거가 사라지면 문구가 근거 없이 남는다.
- 서버·화면을 실행(`make demo-up`·`make serve`·`make obs-up`)하거나 문서의 명령을 돌려 보지 마라. 이유: 서버 기동·Docker·모델 호출은 사용자가 한다(AGENTS.md CRITICAL).
