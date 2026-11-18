# Step 9f: image-compose

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — CRITICAL 규칙(영상·이미지 파일은 로컬 전용·`data/design/`은 커밋하지 않는다, 외부 다운로드와 실제 호출은 사용자가 실행, 새 의존성은 step이 지시한 것만)
- `/docs/ARCHITECTURE.md` — 생성 시안 로컬 전용 규칙·"스트리밍 이벤트와 화면 명령"
- `/docs/CONTRACTS.md` — 이미지 생성 계약(Gemini 이미지 응답은 `completion` 경로, 이미 6a에서 실측)
- `/src/beautyads/agents/design_images.py`(`image_prompt`·`save_design_image`·`SavedImage`), `/src/beautyads/api/assembly.py`(`image_fn`·`image_index`·`request_key`), `/src/beautyads/api/ask.py`(`/design/{request_key}/{index}`·`designs` 맵), `/src/beautyads/api/ask_view.py`(`image_reference`·`_IMAGE_FIELDS`·`show_plan`), `/src/beautyads/domain/labels.py`(`CtaType`), `/src/beautyads/domain/plan.py`, `/src/beautyads/domain/supervisor.py`(`DESIGN_IMAGE_DISCLAIMER`), `/Makefile`, `/pyproject.toml`(Pillow는 P4에서 설치됨), `/tests/test_design_images.py`, `/tests/test_api_assembly.py`, `/tests/test_api_ask.py`, `/tests/test_ask_view.py`, `/tests/test_architecture.py` — step 6a·7c·7d·9e 산출물

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `src/beautyads/agents/design_compose.py`(새 파일), `src/beautyads/agents/design_images.py`, `src/beautyads/api/assembly.py`, `src/beautyads/api/ask.py`, `src/beautyads/api/ask_view.py`, `scripts/fetch_design_font.py`(새 파일), `Makefile`, `assets/fonts/README.md`(새 파일), `.gitignore`, `tests/test_design_compose.py`(새 파일), `tests/test_fetch_design_font.py`(새 파일), `tests/test_design_images.py`, `tests/test_api_assembly.py`, `tests/test_api_ask.py`, `tests/test_ask_view.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `src/beautyads/agents/design_compose.py`, `src/beautyads/agents/design_images.py`(합성본 저장 함수 추가에 한함, 기존 `image_prompt`·`save_design_image` 동작 불변), `src/beautyads/api/assembly.py`(`image_fn`이 원본을 저장한 뒤 합성본을 만들어 저장하고 참조에 합성본 칸을 더하는 데 한함, 모델 호출 모양·상한 처리·`IMAGE_FAILED`/`IMAGE_CAP_REACHED` 경로 불변), `src/beautyads/api/ask.py`(`/design` 응답이 합성본이 있으면 합성본을 서빙하는 데 한함, 테넌트 검사·경로 규칙 불변), `src/beautyads/api/ask_view.py`(`image_reference`가 합성본 칸을 통과시키는 데 한함, 경로를 싣지 않는 규칙 불변), `scripts/fetch_design_font.py`, `Makefile`(`fetch-font` 타깃과 별도 `.PHONY: fetch-font` 줄 추가에 한함, `verify`·기존 타깃 불변), `assets/fonts/README.md`, `.gitignore`(변경 필요 없으면 건드리지 않는다. 폰트·`LICENSE` 파일은 커밋 대상이라 무시하지 않는다), `tests/test_design_compose.py`, `tests/test_fetch_design_font.py`, `tests/test_design_images.py`·`tests/test_api_assembly.py`·`tests/test_api_ask.py`·`tests/test_ask_view.py`(케이스 추가에 한함, 기존 단언 변경 0줄. `image` 참조 정확 일치 단언이 있으면 새 칸 `composed`가 **없는 참조도 유효**하도록 새 칸은 선택 칸으로 두어 기존 단언이 통과하게 한다)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

이미지 모델이 그린 글자(찌그러진 라벨·제품명, 부자연스러운 영문 발음 표기)를 없애기 위해 **이미지 안의 글자는 전부 없애고 카피 글자는 코드가 합성**한다(9e에서 프롬프트가 글자·로고·브랜드·제품명을 넣지 않도록 바뀌었다). 이 step은 합성 함수, 폰트 내려받기 도구, 저장·서빙 연결을 만든다. **이 step은 모델·실제 서비스를 부르지 않고 폰트를 내려받지 않는다**(내려받기는 사용자가 `make fetch-font`로 실행한다). **이 step 안에서는 실제 접속·실행을 하지 않는다. 테스트를 먼저 쓴다.** 새 패키지는 없다(Pillow는 P4에서 `uv add pillow`로 설치됨, 설치 버전은 summary에 적는다).

**1. 폰트 선택과 라이선스(사용자 승인 전 잠정 결정)**: Pretendard `v1.3.9`(SIL Open Font License 1.1, 상업 이용·재배포 가능, 라이선스 전문 동봉 의무)의 정적 OTF `Pretendard-Bold.otf`(헤드라인)와 `Pretendard-SemiBold.otf`(CTA)를 쓴다. 출처: `https://github.com/orioncactus/pretendard`의 태그 `v1.3.9`, 경로 `packages/pretendard/dist/public/static/`. 정적 폰트를 고른 이유: Pillow에서 가변 폰트의 굵기 지정은 환경(FreeType·libraqm)에 따라 달라져 컨테이너 실행 환경에서 불안정하다. 크기: 한글 전 글리프를 담은 정적 OTF라 파일당 수 MB 규모로 **추정**되며(확인 전) 내려받기 도구가 실제 크기와 sha256을 출력한다. 저장소에는 `assets/fonts/`에 폰트 2개와 `LICENSE-Pretendard.txt`를 커밋한다(사용자가 내려받은 뒤). 컨테이너(k3d, P7)는 이 디렉터리를 이미지에 복사하면 되고 시스템 폰트·네트워크에 의존하지 않는다. `assets/fonts/README.md`에 출처·태그·라이선스(OFL 1.1)·다운로드 방법·sha256 기록 자리·"폰트 파일 단독 판매 금지" 등 OFL 요지를 적는다.

**2. 내려받기 도구(`scripts/fetch_design_font.py`, 사용자 실행)**: `make fetch-font`(`Makefile`에 타깃 추가, `verify`에는 넣지 않는다). 동작: 고정 URL 목록(상수, 위 태그의 `raw.githubusercontent.com` 경로 3개: Bold·SemiBold·LICENSE)을 표준 라이브러리(`urllib.request`)로 내려받아 `assets/fonts/`에 쓴다. 파일당 크기 상한(상수 `MAX_FONT_BYTES = 12 * 1024 * 1024`)을 넘으면 중단하고, 이미 있으면 `--force` 없이는 덮어쓰지 않으며, 끝나면 파일명·크기·sha256을 출력한다(사용자가 `assets/fonts/README.md`에 기록). 임시 파일에 쓴 뒤 완료되면 교체한다. 네트워크 오류는 `FONT_FETCH_FAILED`(URL 호스트만 표시, 값 미노출)로 종료 코드 2. **`httpx`를 쓰지 않는다**(`httpx`는 `sources` 계층 전용): 이 도구는 `scripts/` 아래라 계층 규칙 밖이지만 표준 라이브러리만 쓴다.

**3. 합성 함수(`agents/design_compose.py`, 순수 함수·Pillow만)**: `compose_design(image_bytes: bytes, *, headline: str, cta: str, font_dir: Path = Path("assets/fonts")) -> ComposedImage(png_bytes, width, height, headline_box, cta_box, headline_size, cta_size, lines)`. 이미지는 `PIL.Image.open`으로 열어 RGB 변환(원본 바이트는 건드리지 않는다), 결과는 **PNG 바이트**.
- **레이아웃(단순 고정)**: 가로·세로는 입력 이미지 크기. 바깥 여백 `margin = 5%`(가로 기준). 상단 헤드라인 영역: 위 여백부터 높이의 **상단 28%**, 하단 CTA 영역: 아래 여백 위로 **하단 12%**. 헤드라인은 가운데 정렬, 굵은 폰트, 글자색 흰색에 **반투명 어두운 띠**(헤드라인·CTA 영역 각각 `rgba(0,0,0,0.45)`)를 깔아 배경과 상관없이 읽히게 한다. 영역·색은 모듈 상수.
- **글자 크기·줄바꿈 규칙**: 헤드라인은 영역 너비(여백 제외) 안에서 **글자 단위로 줄바꿈**(공백 우선, 공백이 없거나 한 단어가 너비를 넘으면 글자 단위), 최대 **3줄**. 큰 크기(영역 높이 기반 시작 크기)에서 시작해 **들어가지 않으면 2px씩 줄여** 최소 크기(`MIN_FONT_PX = 18`)까지 시도하고, 그래도 넘으면 **마지막 줄을 말줄임표(`…`)로 자른다**. CTA는 한 줄, 같은 규칙(줄바꿈 없이 크기만 줄이고 최소 크기에서도 넘으면 말줄임표). 글자 크기·줄 수·상자 좌표는 반환값에 담는다.
- **CTA 문구는 코드 상수**: `CTA_LABELS: dict[CtaType, str]`(예: `shop_now` "지금 만나보기", `learn_more` "자세히 보기", `store_mention` "매장에서 만나보세요", `event` "이벤트 보러 가기", `follow_engage` "팔로우하고 소식 받기", `none`은 CTA 영역을 그리지 않음)와 헬퍼 `cta_label(cta_type) -> str | None`. 키 집합은 `set(CtaType)`와 같아야 한다(테스트가 `CtaType` import로 단언, 개수를 `== N`으로 굳히지 않는다).
- **입력 정리**: `headline`은 제어 문자·개행·이어진 URL을 제거하고 공백을 정리하며 **80자**로 자른다(빈 문자열이면 헤드라인 영역을 그리지 않는다). 폰트 파일이 없으면 `FontMissing`(`code="FONT_MISSING"`, 경로·값 미노출) 예외.
- 순수 함수라 파일 쓰기·네트워크가 없다.

**4. 저장·참조·서빙(추가에 한함)**: `agents/design_images.py`에 `save_composed_design(png_bytes, *, request_key, index, base_dir)`(원본과 같은 해시 디렉터리에 `<번호>_composed.png`를 **원자적으로** 쓴다, 원본은 그대로 둔다)를 더한다. `api/assembly.py`의 `image_fn`은 이미지 생성이 성공하면 원본을 저장한 뒤 `compose_design(원본 바이트, headline=plan["hook_text"], cta=cta_label(plan["cta_type"]) 또는 빈 값)`으로 합성본을 만들어 저장하고, 결과 참조에 **선택 칸** `composed: {"mime": "image/png", "size", "sha256"}`를 더한다(경로 없음). **합성이 실패하면(`FONT_MISSING` 포함) 원본만 쓰고 참조에 `composed`를 넣지 않으며 이미지 결과는 `ok True` 그대로**다(진단 값 미노출, 결과에 `compose_error` 코드 `FONT_MISSING`|`COMPOSE_FAILED`만 둔다). `api/ask_view.py`의 `image_reference`는 `composed` 칸을 형식 검증 뒤 통과시키고(경로·base64 금지 유지), `api/ask.py`의 `GET /design/{request_key}/{index}`는 **합성본이 있으면 합성본, 없으면 원본**을 서빙한다(`Content-Type`은 PNG/원본 mime, `Cache-Control: no-store`, 테넌트 검사·404 규칙 불변). 이미지 원본과 합성본은 **둘 다 `data/design/` 로컬 파일**이고 커밋하지 않는다. 화면 명령(`show_plan`)은 합성본을 가리키는 같은 `/design` 경로를 쓴다.

**반드시 있어야 하는 테스트**(합성 이미지·가짜 폰트 디렉터리. 네트워크·키·실제 폰트 다운로드 없음, 모델 문장을 기대값으로 굳히지 않는다):
- **합성(`tests/test_design_compose.py`)**: Pillow로 만든 합성 단색 이미지(예: 1024×1024)와 **테스트용 폰트**(Pillow 번들 기본 폰트로 영역·줄바꿈 계산이 되도록 `font_dir`을 주입 가능하게 하거나 `ImageFont.load_default(size)`를 대신 쓰는 주입 지점을 둔다)로: 결과가 PNG(매직 바이트)이고 입력과 같은 크기, `headline_box`·`cta_box`가 **이미지 경계와 안전 여백 안**에 있고 헤드라인 상자가 상단 영역·CTA 상자가 하단 영역 안에 있다. 긴 헤드라인이 **줄 수 3 이하**로 줄바꿈되고(공백 없는 긴 문자열은 글자 단위), 영역을 넘는 극단적으로 긴 문자열은 **크기가 줄다가 최소 크기에서 말줄임표**로 끝나며 상자가 영역을 넘지 않는다. 짧은 헤드라인은 큰 크기를 유지한다. 빈 헤드라인은 헤드라인 영역을 그리지 않고 `none` CTA는 CTA 영역을 그리지 않는다(상자 `None`). 합성 전후 **원본 바이트가 바뀌지 않음**, 합성 이미지의 배경 픽셀이 띠 영역 밖에서 원본과 같음. 제어 문자·URL 제거와 80자 절단. `CTA_LABELS` 키 집합 == `set(CtaType)`. 폰트 파일이 없는 `font_dir`이면 `FONT_MISSING`이고 메시지에 경로가 없다.
- **실제 폰트 사용 가능 여부(조건부)**: `assets/fonts/Pretendard-Bold.otf`·`Pretendard-SemiBold.otf`가 **있으면** 한글 헤드라인 합성이 성공하고 `headline_box`가 비어 있지 않다(글리프 렌더링 확인). **없으면 이 케이스는 `pytest.skip("font not fetched: run make fetch-font")`로 건너뛴다**(건너뜀 사유를 명시하고, `make verify`는 폰트 없이도 통과해야 한다).
- **저장·참조·서빙**: 가짜 `generate_image`(합성 PNG 바이트)와 가짜 합성기로 `image_fn`을 돌려 원본과 `_composed.png`가 `tmp_path` 아래 같은 해시 디렉터리에 쓰이고(원자적 교체), 참조에 `composed`(mime·size·sha256, **경로 없음**)가 있다. 합성기가 `FONT_MISSING`이면 원본만 있고 `composed`가 없으며 `ok True`·`compose_error == "FONT_MISSING"`이다. `/design`이 합성본이 있으면 합성본 바이트를, 없으면 원본 바이트를 돌려주고(다른 테넌트 404·헤더 없음 400·경로 조작 방지는 기존 테스트 그대로), `Cache-Control: no-store`이다. `show_plan`·결과 JSON에 파일 경로·base64가 없다(`json.dumps` 통과). 기존 `tests/test_design_images.py`·`tests/test_api_assembly.py`·`tests/test_api_ask.py`·`tests/test_ask_view.py` 단언은 그대로 통과한다.
- **내려받기 도구(`tests/test_fetch_design_font.py`)**: 가짜 `urlopen`(주입 지점)으로 파일을 `tmp_path`에 쓰고 크기·sha256을 출력하며, 상한 초과는 중단(파일이 남지 않음), 기존 파일은 `--force` 없이 덮어쓰지 않음, 네트워크 오류는 종료 코드 2·`FONT_FETCH_FAILED`·URL 호스트만 표시. **실제 네트워크 호출은 없다**. `Makefile`에 `fetch-font` 타깃과 별도 `.PHONY` 줄이 있고 `verify` 본문에 `fetch-` 문자열이 없다(기존 Makefile 소비자 테스트가 그대로 통과).
- `tests/test_architecture.py` 통과(`agents/design_compose.py`는 Pillow만, 새 계층 위반 없음).

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

- 폰트를 직접 내려받거나 폰트·라이선스 파일을 만들어 커밋하지 마라. 이유: 다운로드는 사용자가 실행한다(AGENTS.md CRITICAL). 이 step은 `make fetch-font` 도구와 합성 코드만 만든다. 폰트가 없어도 `make verify`가 통과해야 하므로 실제 폰트 케이스는 명시적 skip이다.
- 이미지 안에 글자를 그려 넣는 방식(프롬프트로 글자 요청)이나 모델이 만든 글자 이미지를 쓰지 마라. 이유: 이미지 모델이 글자를 깨뜨린다(live 관측). 카피 글자는 코드가 폰트로 합성하고 제품명·브랜드명은 이미지가 아니라 화면 데이터 칸으로만 준다.
- 합성이 실패했을 때 이미지 생성 결과를 실패로 돌리거나 예외를 올리지 마라. 이유: 원본 시안은 유효하다. `composed` 칸만 빠지고 `compose_error` 코드(`FONT_MISSING`·`COMPOSE_FAILED`)만 남긴다(값·경로 미노출).
- 결과·화면 명령·저장 `payload`에 파일 경로·base64·이미지 본문을 넣거나 `data/design/` 파일을 커밋하지 마라. 이유: 생성 시안은 로컬 전용이다(ARCHITECTURE, 6a·7c 규칙). 참조(`request_key`·`index`·`mime`·`size`·`sha256`, 선택 `composed`)와 테넌트 검사를 거친 `/design`만 쓴다.
- `image` 참조의 기존 필수 칸을 바꾸거나 `composed`를 필수로 만들지 마라. 이유: 기존 단언과 합성 없는 원본 경로가 그대로 통과해야 한다(B-FP-071). 새 칸은 선택이다.
- `httpx`를 import하거나 새 패키지를 설치하지 마라. 이유: `httpx`는 `sources` 계층 전용이고 Pillow는 이미 있다(P4). 내려받기 도구는 표준 라이브러리만 쓴다. 설치된 Pillow 버전은 summary에 적는다.
