# 공개 전 체크리스트

공개 전 점검 항목을 C1~C14로 옮겼다. 체크한 항목은 2026-11-22에 실제로 확인된 것만이며 각 항목 아래에 근거를 한 줄로 적는다. 체크하지 않은 항목은 미확인이다. **저장소를 public으로 바꾸는 일은 사용자가 직접 한다.** 출력은 비밀 값이나 개인정보가 아닌 건수·줄 번호·경로만 확인하고, 스캐너가 원문을 보여 주면 저장·공유하지 않는다. `.env`·토큰 파일·개인키를 직접 열거나 출력하지 않는다.

이력은 다시 쓰지 않는다(결과 문서가 인용한 커밋 해시를 보존). 이 문서의 비밀·개인정보 항목은 파일·커밋·패턴 종류만 적고 실제 값은 적지 않는다.

- [x] **C1 — 이력 비밀 값 검사.** `gitleaks`로 전체 이력을 검사한다. 합격: 비밀 값 발견 없음 또는 발견 건이 모두 비밀이 아님으로 확인됨.
  - 근거(2026-11-22): `gitleaks` 8.30.1로 593 commits(약 12.9 MB)를 검사했고 1건이 걸렸다. 규칙은 `gcp-api-key`, 위치는 `tests/test_analysis.py`의 로그 마스킹 테스트 파라미터다(커밋 `7719803`, 2026-11-14). 사용자가 이 문자열이 실제 키가 아님을 직접 확인했다(`.env`는 열지 않음). 이 변경에서 리터럴을 런타임 조립(`"AIza" + "X" * 35`)으로 바꿔 이후 스캔의 오탐을 없앴다. 마스킹 테스트가 확인하는 정규식과 나머지 `SYNTHETIC_*` 항목은 그대로다. 이력의 과거 커밋에는 해당 문자열이 남아 있다(재작성하지 않음).
  - 한계: 병합 전에 삭제한 stash 31개 커밋은 `gitleaks`가 읽지 못해(0바이트 스캔) 아래 C2의 패턴 검색으로 대신 확인했다.

  ```bash
  gitleaks git --log-opts="--all" --redact --no-banner .
  ```

- [x] **C2 — 형식 직접 검사.** 공급사 키·토큰·개인키·비밀번호·연결 문자열 형식을 이력 전체에서 찾는다. 일치는 위치만 확인한다.
  - 근거(2026-11-22): 전체 이력(631 commits)에서 `sk-`, `ghp_`, `github_pat_`, `xox`, `AKIA`, `AIza`, 개인키 헤더, `NEO4J_PASSWORD` 할당, 문자열 비밀번호 할당, `Authorization: Bearer|Basic`, 비밀번호가 든 `postgres://` URL 11개 패턴을 검색했다. 일치는 모두 합성 값이다: `tests/test_analysis.py`(키 형식 마스킹 테스트용 가짜 값), `tests/test_store.py`·`tests/test_migrate.py`·`tests/test_slice.py`(`synthetic-*` 비밀번호와 테스트 DSN), `deploy/docker-compose.yml`(`${...}` 환경 변수 보간). 개인키·GitHub·Slack·AWS 형식은 0건이다. 병합 전에 삭제한 stash 커밋 31개에도 같은 패턴을 적용해 같은 `tests/test_analysis.py`의 합성 값 외에는 없었다.

- [x] **C3 — 커밋 금지 경로 이력.** 경로만 확인한다. `.env.example`은 허용하며 `.env`·`*.pem`·`*.key`·토큰 파일 이력이 없어야 한다.
  - 근거(2026-11-22): 이력에서 비밀 후보 파일명(`.env*`, `*.pem`, `*.key`, 인증서·자격 증명 이름)으로 추가된 파일은 `.env.example` 하나뿐이다. `.gitignore`가 `.env`·`.env.*`(예제 제외), `logs/`, `data/raw/`, `data/interim/`, `data/design/`, `data/manifest/traces.jsonl`, `node_modules/`를 막는다.

  ```bash
  git log --all --diff-filter=A --name-only --format= | sort -u | grep -Ei '(^|/)\.env($|\.)|\.pem$|\.key$|id_rsa|credentials|secret'
  ```

- [x] **C4 — 대용량 이력과 저장소 크기.** 큰 blob이 의도한 자료인지 확인한다. 비용 원장을 크기만으로 삭제하거나 이력을 재작성하지 않는다.
  - 근거(2026-11-22): `.git`은 12 MB(pack 6.64 MiB, 5,245 객체)다. 가장 큰 blob 상위 10개는 모두 `data/manifest/costs.jsonl`의 이전 버전(2.7~2.8 MB)이며 호출 단위 비용·토큰만 담긴 원장이라 의도한 자료다. 현재 트리에서 큰 파일은 `costs.jsonl` 2.79 MB, Pretendard 폰트 2개(각 1.5 MB), `uv.lock` 0.70 MB다.

- [x] **C5 — 수집 데이터 포함 범위.** 추적되는 데이터의 종류·위치를 목록으로 확인한다. 저작권·약관 판단은 이 문서에서 하지 않는다.
  - 근거(2026-11-22): `data/raw`·`data/interim`·`data/design`은 추적하지 않는다. 추적되는 이미지·영상 파일은 없고(Pretendard `.otf` 2개 제외) 생성 시안 이미지도 없다. `data/evalset/`(질문 47·정답 47·요청 30·격리 요청 200)는 근거 소재를 플랫폼 ID(YouTube 72개·Instagram 27개)로 참조하며, `docs/results/`에는 플랫폼 URL·ID가 없다. `tests/fixtures/contracts/`의 72개 파일은 실제 API 응답 기록이고 공개 게시물 원문 일부(캡션·자막·제목), 썸네일 주소(이미지 파일은 없음), 계정·채널 이름을 포함한다.
  - 이 변경에서: [README의 데이터 고지](../README.md#데이터-고지)와 `tests/fixtures/contracts/README.md`에 권리 고지를 추가했고, 쇼핑몰 응답 기록(`mall_cafe24_image_only.html`)의 업체 이메일·전화번호는 가짜 값(`shop@example.com`, `000-0000-0000`)으로 바꿨다(이력에는 원래 값이 남아 있다). 나머지 수집 콘텐츠는 유지하고 데이터 고지로 처리한다.

- [ ] **C6 — 실존 기관·인물명.** 이 프로젝트는 공식 브랜드 계정의 실제 광고를 분석하므로 실제 브랜드·계정 이름이 데이터와 결과 문서에 나온다. 사용자가 준비한 이름 목록으로 검색하는 점검은 하지 않았다(미확인).

- [x] **C7 — 공개 신원.** 작성자 이름·이메일과 원격 계정을 확인한다. 이력 재작성은 하지 않는다.
  - 근거(2026-11-22): 모든 631 commits의 작성자는 같은 이름(Tommy Lee)과 같은 gmail 도메인 주소이고, 커밋터 598개가 같은 신원이며 나머지 33개는 GitHub 웹 병합 커밋(`noreply`)이다. `Co-Authored-By` 트레일러는 210개 커밋에 있다. `pyproject.toml`의 `authors`도 같은 이름·주소다. 커밋 작성자와 트레일러는 그대로 둔다(A·B와 같은 방식).
  - 확인 필요: A·B의 `pyproject.toml` `authors` 이름은 다른 표기(`SpanLee-Time`)이고 C는 저작권 표기와 같은 `Tommy Lee`다. 어느 쪽으로 통일할지는 사용자가 결정한다.

- [x] **C8 — 개인 경로·내부 URL.** 로컬 절대경로, 개인 연락처, 내부 호스트를 찾는다.
  - 근거(2026-11-22): 로컬 절대경로(`/Users/...`)는 `phases/7c-ui-redesign/step10.md` 한 곳의 2개였고 이 변경에서 `~/Desktop/...`으로 바꿨다(이력에는 남아 있음). 내부 호스트·사설 IP·`.local`/`.internal` 주소는 없다. 이메일 형태는 합성(`example.invalid`, `shop.example`)이거나 위 C5의 쇼핑몰 응답 기록 한 건(교체함)이고, 전화번호 형태도 그 한 건뿐이었다. 테스트 문자열 `@v1.ingredients`는 이메일이 아니다.

- [x] **C9 — `.env.example`.** 주석과 변수 이름만 있고 모든 할당값이 비어 있는지 확인한다. `.env`를 열거나 출력하지 않는다.
  - 근거(2026-11-22): 변수 14개 모두 값이 비어 있다. `deploy/docker-compose.yml`의 비밀 필드는 `${...}` 보간이며 리터럴은 로컬 MinIO 접근 식별자(`LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY`) 하나다.

- [x] **C10 — CI 시크릿.** `.github/workflows/*.yml`의 시크릿 사용과 fork PR 노출 위험을 확인한다.
  - 근거(2026-11-22): 워크플로는 `verify.yml` 하나이고 `push`·`pull_request`에서 돌며 `pull_request_target`이 없다. `permissions: contents: read`, `secrets.` 참조 0개, 외부 액션 4개가 모두 커밋 SHA로 고정되어 있다. 저장소 Secrets 설정 화면은 확인하지 못했다(사용자 몫).

- [ ] **C11 — 새 클론 검증.** 별도 디렉터리에 클론한 뒤 고정 의존성을 설치하고 `.env`·`data/` 없이 `make verify`가 통과하는지 확인한다. 이 점검에서는 하지 않았다(미확인, 사용자 실행).

  ```bash
  git clone https://github.com/apinkpanda722/beauty-ad-creative-agents.git beauty-ad-creative-agents-public-check
  cd beauty-ad-creative-agents-public-check
  uv sync --locked
  make web-install
  make verify
  ```

- [x] **C12 — 라이선스.** [LICENSE](../LICENSE)에 MIT 전문이 있고 [README](../README.md)가 링크하는지, 서드파티 고지가 있는지 확인한다.
  - 근거(2026-11-22): `LICENSE`는 A 저장소의 `LICENSE`와 같은 문구·연도·이름(`Copyright (c) 2026 Tommy Lee`)이다. `pyproject.toml`에 `license = "MIT"`, `web/package.json`에 `"license": "MIT"`(`"private": true` 유지)를 추가했다. [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)에 저장소에 포함된 서드파티(Pretendard 폰트 2개, OFL-1.1, 전문은 `assets/fonts/LICENSE-Pretendard.txt`)와 참조만 하는 자료(락 파일 의존성, Docker 이미지)를 구분해 적었다. Docker 이미지는 태그로 참조만 하며 저장소에 포함하거나 재배포하지 않는다. 참고: A·B의 `pyproject.toml`에는 `license` 필드가 없고 `LICENSE` 파일만 있다.

- [x] **C13 — A·B 저장소와의 관계.** README가 A·B를 링크하고 사실과 맞는지 확인한다.
  - 근거(2026-11-22): A(`ko-docs-agentic-rag`)와 B(`governed-ops-agent`)는 이미 공개되어 있고 둘 다 MIT다. README의 마지막 절과 이 문서를 제외하면 이 저장소의 코드·설정·문서(락 파일·`phases/`·결과 문서 제외)에 A·B 이름 참조가 없고 의존성도 없다. README의 마지막 절이 A·B를 링크하고 독립 실행임을 적는다.

- [x] **C14 — README(외부 독자).** 첫 화면이 프로젝트의 정체·핵심 관측·실행 방법·증거 링크를 알려 주는지, 비밀·내부 경로가 없는지 확인한다.
  - 근거(2026-11-22): README를 B와 같은 흐름(한 줄 정의와 핵심 관측 링크 → 목차 → 아키텍처 → 실행 방법 → 평가·관측 → 트레이드오프 → 알려진 한계 → 데이터 고지 → 라이선스)으로 다시 썼다. 수치는 `docs/results/`와 `DEMO.md`의 기록에서 확인되는 값만 옮겼고 모두 관측값으로 표기했다. 기존 README의 전체 내용은 [RUNBOOK](RUNBOOK.md)로 옮겼다. README에 비밀·로컬 경로는 없다. 시연 영상 섹션은 영상이 올라온 뒤 추가한다.

## 사용자가 남은 일

- C6 이름 목록 검색, C11 새 클론 검증, 저장소 Secrets 설정 확인.
- C7의 `authors` 이름 통일 여부.
- 이 변경이 병합된 뒤 저장소를 public으로 바꾸는 일.
