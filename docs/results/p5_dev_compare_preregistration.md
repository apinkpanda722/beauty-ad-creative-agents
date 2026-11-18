# P5 개발 비교 사전 등록 (2026-11-18)

상태: **등록됨**. 아래 두 비교(terra `reasoning_effort`, sonnet 구조화 출력 방식)를 실행하기 **전에** 커밋한다. 입력·지표·판정 규칙·상한은 결과를 본 뒤 바꾸지 않는다. 기준에 못 미치는 결과는 기대를 고치지 않고 그대로 보고한다. 비교 실행 도구는 `make live-compare`(`src/beautyads/eval/p5_compare.py`, P5 step 6d)이고 이 파일이 커밋돼 있지 않거나 수정됐으면 실행을 거부한다. 이 비교는 **개발 단계의 기본값을 정하는 용도**이며 E1~E5(`docs/EVAL.md`)의 실험이 아니다. `docs/EVAL.md`의 동결 기준은 바뀌지 않는다.

## 1. 공통 조건
- **dev workspace만 쓴다.** test 브랜드(isntree·beauty_of_joseon)는 쓰지 않는다. 입력 요청 5건의 "우리 제품"은 아래 두 dev 제품이다. 가격대는 우리 제품 단위당 정가 ±30%이다(P5 승인 사항).
  - `mixsoon` 세럼: `https://mixsoon.co.kr/product/detail.html?product_no=921`(`serum_ampoule`)
  - `cosrx` 선세럼: `https://www.cosrx.co.kr/product/%EC%9A%B8%ED%8A%B8%EB%9D%BC-%EB%9D%BC%EC%9D%B4%ED%8A%B8-%EC%9D%B8%EB%B9%84%EC%A0%80%EB%B8%94-%EC%84%A0%EC%84%B8%EB%9F%BC-50ml/740/category/57/display/1/`(`sun_care`)
- 경쟁 소재 검색은 전 브랜드를 대상으로 하므로 개발 중에도 test 브랜드 소재가 검색 대상에 들어간다(라벨·정답은 아니다). 이 한계를 결과 문서에 쓴다.
- `temperature`는 지정하지 않는다. 비교하는 변수 외의 입력·프롬프트·모델은 모든 조건에서 같다. 이미지는 쓰지 않는다(`with_image=False`).
- 호출 한 번에 기획안 **1안**을 만든다. 되돌림(재기획)은 하지 않는다(단발 호출).
- 모든 지표는 코드가 판정한다(`checks.run_checks`와 구조화 실패 집계). 모델이 만든 문장의 품질은 이 비교의 지표가 아니다.

## 2. 고정 입력 요청 5건
`ResearchBrief`의 고정 값이다(목표 문장은 한국어 원문 그대로 쓴다). 나머지 선택 조건은 비운다.

| # | workspace | category | claim | goal |
|---|---|---|---|---|
| 1 | mixsoon 세럼 | `serum_ampoule` | `soothing` | 진정 소구 세럼의 경쟁 광고 근거를 수집한다 |
| 2 | mixsoon 세럼 | `serum_ampoule` | `hydration` | 보습 소구 세럼의 경쟁 광고 근거를 수집한다 |
| 3 | mixsoon 세럼 | `serum_ampoule` | `brightening` | 미백 소구 세럼의 경쟁 광고 근거를 수집한다 |
| 4 | cosrx 선세럼 | `sun_care` | `sun_protection` | 자외선 차단 소구 선케어의 경쟁 광고 근거를 수집한다 |
| 5 | cosrx 선세럼 | `sun_care` | `soothing` | 진정 소구 선케어의 경쟁 광고 근거를 수집한다 |

입력 생성(`make live-compare ARGS='inputs'`): 위 5건에 리서치 에이전트(`gpt-6-luna`, `reasoning_effort="none"`)를 **1회씩** 돌려 만든 `ResearchHandoff` 5개를 고정 입력으로 저장한다(비교 간 리서치 변동 제거). 각 파일의 sha256은 **terra 비교 실행 전에 이 파일 §7에 추가 커밋**한다(해시가 §7에 없거나 다르면 `terra` 실행은 거부된다).

## 3. 비교 1: terra `reasoning_effort` (5-1, 2026-11-18 조언 세션 수정 B-1 반영)
- **조건**: 입력 5건 × `reasoning_effort` `none`·`low`·`medium` = **15호출**, 모델 `gpt-6.1-terra`, 구조화 출력 `json_schema` strict, 같은 프롬프트.
- **주 지표 = 쓸 수 있는 기획안 수**: 기획안 중 (a) `checks.run_checks`의 `passed`가 참이고 (b) `evidence_ids`가 1개 이상이며 (c) 모든 `evidence_ids`가 해당 입력 핸드오프의 근거 풀 안인 건의 수(값마다 0~5).
- **보조 지표**: 구조화 실패 수(재요청 1회 뒤에도 실패한 호출 수), 보고용으로 호출당 비용·추론 토큰·`unknown_count` 평균.
- **판정 규칙(위에서 아래 순서)**:
  1. 쓸 수 있는 기획안 수가 가장 많은 값을 고른다.
  2. 동률이면 구조화 실패 수가 적은 값.
  3. 그래도 같으면 비용이 낮은 값(`none` < `low` < `medium`).
  4. **모든 값의 쓸 수 있는 기획안 수가 3(5건 중) 미만이면 결정을 보류**하고 사용자에게 보고한다(자동 선택 없음).
- 확정 방식: 판정 결과는 보고 뒤 사용자 승인으로 `PLANNING_REASONING_EFFORT` 상수에 반영한다(도구가 직접 바꾸지 않는다).

## 4. 비교 2: sonnet 구조화 출력 (a) 대 (b) (5-2, 조언 세션 수정 B-2 반영)
- **조건**: 비교 1에서 생성된 기획안 15개 중 **파일 sha256 오름차순 앞 6건**(코드 검사 결과와 무관)을 `claude-sonnet-5-5`로 평가한다. 각 입력을 (a) `ToolCallStructured`(`tool_choice="auto"` + 단일 도구)와 (b) `NativeAnthropicStructured`(`litellm.anthropic.messages.acreate` + `output_config.format`)로 1번씩 = **12호출**(+재요청 최대 1회씩). 평가 항목은 차별성·요청 적합성 두 가지(1~5점), 같은 프롬프트.
- **판정 지표 = 재요청 뒤 구조화 실패율**(방식별 실패 호출 수 ÷ 호출 수).
- **보고용 지표**: 재요청 전 **첫 시도** 구조화 실패율, 두 방식 점수 차이 절댓값 평균과 완전 일치 비율, 호출당 입력 토큰·비용, 캐시 읽기 토큰(같은 접두를 연속 2호출에서 관찰, (b)의 `output_config.format` 변경 시 무효화 여부).
- **판정 규칙**: **(b)의 재요청 뒤 구조화 실패율이 (a)보다 엄격히 낮을 때만** (b)를 기본 방식으로 권고한다. 같거나 (a)가 낮으면 **(a)를 유지**한다(이유: (b)는 비동기 연결·캐시 무효화의 통합 비용이 있다). 호출당 비용은 보고용이다. 점수 차이 절댓값 평균이 1.0(5점 척도)을 넘으면 판정과 별도로 "검토 표시"를 붙인다.
- 한계: 호출 12건·표본 6건이라 통계적 근거가 아니며, 실패율의 차이가 우연일 수 있다(20호출 미만의 비율은 판단 근거로 쓰지 않는다는 기존 문구와 같은 취지로, 이 비교는 개발 기본값을 정하는 참고이고 실패율이 같거나 표본이 적으면 (a)를 유지한다).
- 확정 방식: 판정 결과는 보고 뒤 사용자 승인으로 평가 기본 방식에 반영한다.

## 5. 상한(목적별 장부 합계, 호출 직전 검사)
상한 `compare-inputs` = $0.02
상한 `compare-terra` = $0.12
상한 `compare-sonnet` = $0.10

합계 상한 약 $0.24(OpenAI `compare-inputs`·`compare-terra` $0.14, Anthropic `compare-sonnet` $0.10). 모두 기존 공급사 상한(OpenAI $10, Anthropic $8) 안이다. 비용 추정(실측 아님, `docs/COST_ESTIMATE.md` 가정과 2026-11-17 단가 기준): 입력 생성 5호출 약 $0.015, terra 15호출 약 $0.07~0.12, sonnet 12호출(+재요청) 약 $0.045~0.09.

## 6. 재현·기록
- 입력 핸드오프·기획안 파일은 `data/interim/p5_compare/`에 두고 커밋하지 않는다. 결과 문서에는 파일 sha256, 지표, 호출 수, 장부 비용, 모델 ID, 커밋 해시, 실행 날짜를 적는다(A-FP-044).
- 이 사전 등록 파일은 기존 내용을 고치지 않고 §7 이후를 추가 커밋으로만 쌓는다(B-FP-043).

## 7. 입력 해시 기록 (비교 1 실행 전에 추가한다)
(비어 있음 — `make live-compare ARGS='inputs'` 실행 뒤 사용자가 출력된 sha256 5개를 아래에 추가 커밋한다.)

입력 해시 (2026-11-18 추가, `make live-compare ARGS='inputs'` 성공 뒤: `complete: true`, 장부 `compare-inputs`·`openai`·`reasoning_effort` `none`, 합계 $0.00660485, 입력별 `unresolved` 목록은 5건 모두 비어 있음). 아래는 `data/interim/p5_compare/inputs/`의 실제 핸드오프 파일 sha256이다(커밋 전에 파일 해시와 같음을 확인했다). 이 절의 값은 이후 고치지 않는다.

- `01.json`: `ea394fe8c54db54f645bdac974f03d3d198d13e473830f01333afb810a39a2db`
- `02.json`: `c935238a096c68636d3ba0cd7cd4779894afc417b22474f882f7547d88cb187a`
- `03.json`: `4ad481f9d8881c4883c693f9bf2152d527cbb9e52fbeefefc39bd3705ac0058d`
- `04.json`: `79a6a4b6fcac89bf0ceae9357ffffb579071ea7c340b6c7078032c80708741fc`
- `05.json`: `5aabd7316dcc0689a5d7ef349236260d3904d29c966065c69d0ccb5a1a5489b6`

