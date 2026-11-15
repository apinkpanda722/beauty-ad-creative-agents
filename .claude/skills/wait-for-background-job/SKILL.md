---
name: wait-for-background-job
description: 오래 걸리는 백그라운드 작업(execute.py, live-* 실행, 대기 루프)이 끝나기를 기다릴 때 반드시 먼저 읽는다. Monitor·until 루프에서 `pgrep -f "<패턴>"`이 자기 자신의 명령줄에 걸려 영원히 끝나지 않는 실수를 막는다.
---

# 백그라운드 작업 대기

## 겪은 일 (2026-11-15 P4 step 9·10)

`Monitor`로 `until ! pgrep -f "scripts/execute.py" >/dev/null; do sleep 10; done` 를 걸었다. `pgrep -f`는 전체 명령줄을 검색하는데, 대기 루프를 실행하는 셸 프로세스의 명령줄에 같은 문자열(`scripts/execute.py`)이 들어 있어 **루프가 자기 자신을 찾았다.** 실행기는 이미 끝났고 `index.json`도 completed였지만 루프는 끝나지 않았고, 사용자가 "뭐가 아직 돌고 있니?"라고 물어서야 발견했다.

## 규칙

1. **`pgrep -f`·`pkill -f`·`ps | grep`에 넣는 패턴이 그 명령 자신의 텍스트에 들어 있으면 안 된다.** 대기 루프는 항상 자기 자신을 매치한다. 불가피하면 대괄호 트릭(`pgrep -f "[s]cripts/execute.py"`)을 쓰되, 아래의 더 나은 방법을 먼저 고른다.
2. **PID로 기다린다.** 작업을 띄울 때 PID를 받아 두고 그 PID만 본다: `cmd & echo $! > pidfile`, 대기는 `while kill -0 "$(cat pidfile)" 2>/dev/null; do sleep 5; done`. 프로세스 이름·명령줄 검색은 쓰지 않는다.
3. **작업 자체를 백그라운드로 실행해 알림을 받는다.** `Bash`의 `run_in_background: true`로 작업을 직접 실행하면 끝날 때 알림이 온다. 이 경우 별도 대기 루프(`Monitor`)가 필요 없고 폴링하지 않는다. 별도 대기가 필요해도 그 알림이 우선이다.
4. **완료 신호를 파일에서 찾는다.** 작업이 남기는 산출물이 더 확실하다: `phases/<phase>/index.json`의 step `status`, 로그의 `completed!` 줄, 보고서 파일의 갱신. 대기 조건은 이 신호로 쓰고 프로세스 존재 여부로 쓰지 않는다.
5. **`Monitor` 대기에는 항상 상한을 둔다.** 조건이 영원히 거짓이 될 수 있는지 먼저 생각하고, `timeout`을 걸거나 루프 안에서 완료 신호(규칙 4)를 함께 확인해 빠져나온다.
6. **"아직 돌고 있다"고 말하기 전에 실제로 확인한다.** 대기 알림이 오지 않으면 가정하지 말고 `index.json`·로그 끝·`git log`를 한 번 직접 확인한다. 같은 대기를 두 번째로 거는 일은 첫 대기가 왜 안 끝났는지 확인한 뒤에만 한다.
7. **작업 트리를 건드리는 일(코드 수정·커밋)은 실행기가 끝났는지 확인한 뒤에 한다**(B-FP-057). 이 확인도 위 규칙을 따른다(`.harness/executing` 잠금 파일 또는 `index.json`).

## 확인용 한 줄

```bash
# 실행기가 정말 끝났는가 (자기 매치 없음)
python3 -c "import json;print([(s['step'],s['status']) for s in json.load(open('phases/<phase>/index.json'))['steps']])"; ls .harness/executing 2>/dev/null
```
