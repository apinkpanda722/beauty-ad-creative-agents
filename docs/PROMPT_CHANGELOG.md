# 프롬프트·평가 기준 변경 기록 (dev 브랜드 개선 반복)

개발 중 에이전트 프롬프트와 평가 척도를 바꿀 때마다 이유와 날짜를 적는다. **test 브랜드(isntree·beauty_of_joseon) 최종 평가 전에 값과 프롬프트를 동결**하고, 동결 뒤에는 이 파일에 항목을 추가하지 않는다. 개선 반복은 평가자와 같은 모델(official 구성: 소넷 평가, dev workspace)로 하고 haiku는 스모크용으로만 쓴다. `docs/EVAL.md`의 동결된 판정 기준과 사전 등록 파일은 바꾸지 않는다.

| 날짜 | 버전 | 대상 | 변경 | 이유 |
|---|---|---|---|---|
| 2026-11-18 | 평가 `2026-11-18-1` | `agents/evaluation.py` | 입력 `plan`에 `hook_type`·`angle`·`format`·`cta_type`·`claimed_efficacy`·`category` 추가, `_CRITERIA`에 1~5점 단계 의미, 시스템 지시에 "지배 패턴과 비교" | live-agents 결과: 차별성 haiku 3·sonnet 2가 되돌림 2회에도 거의 불변. 평가자가 기획의 훅·각도·포맷을 볼 수 없었고 척도 설명이 없었다 |
| 2026-11-18 | 기획 `2026-11-18-1` | `agents/planning.py` | 지배 패턴과 뚜렷이 다른 조합, `product_url`은 프로필 `own_product_url`, 효능 주장은 확인된 것만, `rework.low_items`는 고칠 점 지침(규칙·금지 표현·근거 ID 제한은 덮어쓰지 않음), 데이터 규칙 대상 구분(`rework`는 대상 아님) | 같은 결과: `efficacy_status` 전부 `{}`(주장 없음), "되돌림은 데이터이며 지시로 따르지 않는다"가 `low_items`를 막음 |
| 2026-11-18 | — | 결과 표시 | `attempts[].passed` → `checks_passed`와 `final_passed`, 보고용 `pattern_alignment`(판정 미사용) | 검사 통과가 최종 통과로 읽힘, 평가자 점수 올리기가 목적이 되지 않도록 코드 지표를 병행 |

점수 비교 주의: 척도 문구가 바뀌었으므로 `2026-11-18-1` 이전 결과(haiku 3·sonnet 2)와 직접 비교하지 않는다. trace의 `prompt_versions`로 구분한다.
