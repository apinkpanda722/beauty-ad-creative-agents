---
name: phase-run
description: phase 설계, step 파일 작성, execute.py 실행, 보고, PR·병합까지의 절차를 다룬다. phase나 step을 새로 쓰거나 실행할 때, 사용자 live 확인 안내와 PR·병합을 준비할 때 먼저 읽는다.
---

# phase-run

phase 하나를 설계해서 병합까지 끌고 가는 절차다. 실제로 겪은 사고(7a~7d)에서 나온 규칙만 적는다. 아래 스킬의 내용은 여기서 되풀이하지 않고 참조한다.

- `failure-patterns`: 외부 계약, 테스트 단언, 설정, 평가 판정 등 step 설계에서 피할 실패 패턴. step을 쓰기 전에 먼저 읽는다.
- `wait-for-background-job`: 백그라운드 작업(execute.py) 대기 루프를 쓸 때 `pgrep -f` 자기 매칭을 피한다.
- `harness`: step 파일 형식, `index.json`, 공통 금지 블록, `execute.py`·`step_file_checks.py`의 기본 사용법.

## 1. 초안 보관

- step 초안은 작성 즉시 저장소 안 `.drafts/<phase>/`(`.git/info/exclude`에 등록되어 작업 트리가 깨끗하게 유지된다)와 저장소 밖 `~/.claude/drafts/<프로젝트>/<phase>/` 한 곳에 보관한다. scratchpad에만 두지 않는다(세션이 바뀌면 지워질 수 있다. 7d 초안 유실 사고).
- `phases/`로 옮길 때 복사와 커밋을 `&&` 한 줄로 잇지 않는다. 단계마다 결과를 확인한다: 복사 → `phases/<phase>/`의 파일 목록 확인 → 커밋 → **`git show --stat HEAD`로 step 파일과 `index.json`이 들어갔는지 확인** → 그다음에야 `execute.py`를 실행한다. 확인 없이 실행하면 step 파일이 없는 커밋 위에서 돌 수 있다.

## 2. step 설계 점검 체크리스트

과거에 blocked가 났거나 허용 밖 수정이 생긴 원인이다. step 파일을 커밋하기 전에 하나씩 점검한다.

- **요구와 금지의 모순**: 요구사항이 요구하는 변경을 금지사항이 막고 있지 않은지, 요구와 "수정 허용 파일 목록"이 어긋나지 않는지 대조한다(7a step 2·4, 7b step 5).
- **소비자 경고 전체를 허용 목록과 대조**: `step_file_checks.py`의 소비자 테스트 경고를 모두 읽고, 수정이 필요한 테스트가 허용 목록에 있는지 확인한다. 경고 한 건을 놓쳐 허용 목록 밖 테스트가 수정된 적이 있다(7b step 2).
- **해시 시드·집합 순회 순서에 기대는 새 테스트를 금지한다.** 리스트와 명시적 순서로 단언한다. 이 때문에 앞 step의 테스트가 시드에 따라 실패해 blocked가 났다(7b step 4). 단계의 테스트에 "여러 PYTHONHASHSEED에서 통과"를 확인하는 문장을 넣어도 된다.
- **승인 표기와 설치 허용의 일치**: step에서 설치를 허용하는 패키지는 사용자 승인 목록과 같아야 하고, 승인된 것을 "확인 필요"로 적지 않는다(7a step 4). 승인되지 않은 의존성은 `uv add`·`pnpm add` 지시에 넣지 않는다.
- **식별자 대조**: step 문서가 말하는 이름·키 집합·상수·함수 시그니처를 코드를 열어 확인한다. 상수를 정확 일치로 단언하는 테스트는 `rg`로 전부 찾아 기대값 갱신 목록에 넣는다. "만드는 파일 → 읽는 파일" 표로 새로 생기는 값의 소비자를 적는다.
- **동결 줄·해시를 건드리는 변경**은 허용 목록에 명시하고 사전 등록·동결 가드가 어떻게 되는지 적는다. 동결 값은 결과를 본 뒤 바꾸지 않는다(AGENTS.md).
- **코드를 열어 확인한 사실만 쓴다.** 기억이나 이전 요약으로 줄 번호·이름·값을 적지 않는다.
- 점검 후 `uv run python scripts/step_file_checks.py phases/<phase>/step*.md`(경고 0건 또는 경고마다 사유)와 `uv run pytest -q -o addopts="" scripts/test_step_files.py`를 실행한다.

## 3. 실행 절차

- feature 브랜치에서 작업 트리가 깨끗한 상태로 시작한다(`git status --short`가 비어 있어야 한다).
- `scripts/execute.py <phase>`는 **`run_in_background`로 직접 실행**한다. 셸의 `&` 분리는 종료 알림이 없어 쓰지 않는다. 한 step씩 돌릴 때는 `--steps 1`을 쓰고 완료 알림이 오면 결과를 확인한다(대기 루프를 쓸 때는 `wait-for-background-job` 참조).
- **blocked**: `index.json`의 `blocked_reason`을 읽고 원인을 step 파일의 충돌로 좁힌 뒤, step 파일만 고쳐 해당 step을 `pending`으로 되돌려 다시 실행한다. 가드와 기존 단언을 약화해서 통과시키지 않는다.
- **Codex 사용량 한도 중단**: 작업 트리의 부분 결과를 `git stash push -u -m "<phase> step N partial codex limit <날짜>"`로 보존하고 한도가 풀린 뒤 같은 step을 다시 실행한다. stash는 지우지 않는다.
- 사용자의 live 실행(모델 호출, 실제 서비스)이 필요한 확인은 step 안에서 실행하지 않는다. 사용자가 다음 live 확인에서 한다.

## 4. 보고 형식

step마다 같은 형식으로 보고한다.

- 통과 또는 blocked, 시도 횟수
- `make verify` 건수(파이썬·웹)
- 커밋 해시(기능 커밋, 완료 표시 커밋)
- 식별자 대조 결과(코드를 열어 확인한 이름·값, 허용 목록 밖 수정이 없는지)
- 승인안과 달라진 점(없으면 "없음")과 알려진 한계

phase가 끝나면 사용자가 직접 확인할 것을 순서와 명령과 함께 모아 보고한다(6번 규칙).

## 5. PR 흐름

- 이슈를 먼저 만들고 feature 브랜치에서 작업한다. 사용자 live 확인 전에는 PR을 만들지 않고, 사용자가 요청할 때만 만든다(`CLAUDE.md`의 git 규칙).
- 사용자의 live 실행으로 `data/manifest/costs.jsonl`이 바뀌어 있으면 **추가 줄만 있고 삭제·수정이 0인지, 시각·목적·모델이 live 실행분뿐인지** 열어 확인한 뒤 별도 `chore` 커밋으로 올린다. 다른 변경이 섞여 있으면 멈추고 보고한다. `execute.py`의 자동 커밋이 이 줄을 step 커밋에 쓸어 담는 일이 있으니(7d step 5) `git show --stat`으로 확인한다. `traces.jsonl`은 gitignore이고 `.env`는 열지 않는다.
- 병합 직전 `gh api repos/<owner>/<repo>`로 owner type이 User인지(조직 아님), 협업자가 본인뿐인지(`.../collaborators`), `mergeStateStatus`가 CLEAN인지 확인한다. 조건이 맞지 않으면 병합하지 않고 사용자 확인을 받는다.
- CI는 `gh pr checks <번호> --watch`로 **한 번만** 기다린다(반복 조회 금지). 실패하면 병합하지 않고 원인을 보고한다. 환경 차이로 인한 실패는 워크플로·환경 의존 테스트에 한해 최소 수정 커밋으로 고칠 수 있고, 단언 약화·동결 값·서버 로직 변경은 하지 않는다.
- 병합 커밋으로 병합하고 원격 브랜치를 삭제한다. 병합 후 `main`을 pull해서 `make verify` 건수를 확인하고 이슈가 닫혔는지 확인한다. 다음 phase 브랜치는 병합된 `main`에서 분기한다.
- PR 본문은 요약·검증·알려진 한계 순서로 쓰고 끝에 `Closes #N`과 "Generated with Claude Code" 줄을 넣는다. 커밋은 Conventional Commits(본문 한글)에 `Co-Authored-By` 줄을 넣는다.

## 6. 사용자용 live 확인 안내 작성 규칙

- 명령은 항목마다 코드 블록에 넣는다.
- "서버를 켜고 요청을 보내는 것이 비용 승인"임을 적는다.
- 예상 비용은 **추정과 실측을 구분**해서 적는다(실측은 날짜와 출처, 추정은 근거).
- 사람이 보는 검수 항목에는 처음부터 뜻, 판정 기준, 예시 하나, 기록 방법을 붙인다(나중에 덧붙이지 않는다).
- 확인 결과는 날짜와 "사용자 화면 관측값"임을 표시해 문서에 기록하고, `docs/results/` 측정값과 섞지 않는다.

## 7. 하지 않는 것

- 사용자 요청 없는 PR·병합·이력 변경(rebase, force push, amend)
- `make live-*`와 모델 호출이 드는 실행을 직접 실행하는 것
- 키·`.env` 열람과 출력, 허용 목록에 없는 패키지 설치
- 동결 값·사전 등록 파일 변경, 가드와 기존 단언 약화
- stash 삭제
