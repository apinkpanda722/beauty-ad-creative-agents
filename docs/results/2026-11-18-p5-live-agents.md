# P5 live 결과: `make live-agents` (dev workspace, 2026-11-18)

> 이 문서는 step 9·9b·9c 시점의 결과다. 이후 step 9d(구조화 실패 상세 계측)·9e(강제 대비 완화·이미지 프롬프트·한국어 카피)·9f(카피 글자 코드 합성)가 구현됐고, 그 효과는 사용자가 `--config official`·`--config image`를 다시 실행한 결과로 이 문서 아래에 추가한다(앞부분 수치는 바꾸지 않는다).

개발 반복 결과이며 **최종 평가(test 브랜드 A·B)가 아니다.** 점수·분포는 dev workspace(mixsoon 세럼·cosrx 선케어) 요청 몇 건의 관측이라 일반화하지 않는다. 모든 수치는 `data/interim/agents_live/*.json` 요약과 `data/manifest/traces.jsonl`(로컬, 커밋하지 않음)에서 옮겼다. 모델이 만든 문장은 기록하지 않았다.

## 1. 실행 개요

| 실행(UTC, 11-18) | 구성 | 평가 모델 | 이미지 | 시나리오 | 상태 |
|---|---|---|---|---|---|
| 10:08 | `dev` | haiku | 끔 | 5종(패턴·관계·기획 2·범위 밖) | 5/5 HTTP 200, 오류 코드 없음 |
| 10:09 | `official` | sonnet | 끔 | 기획 2 | 2/2 HTTP 200 |
| 10:12 | `image` | sonnet | 켬 | 기획 1 | HTTP 200, **이미지 미생성**(`limit_kinds ["image"]`) |
| 10:15 | `image`(재실행) | sonnet | 켬 | 기획 1 | HTTP 200, 이미지 미생성(`limit_kinds ["image"]`) |
| 10:52 | `image`(9b 뒤, `BEAUTYADS_CAP_GEMINI_USD=20.5`) | sonnet | 켬 | 기획 1 | HTTP 200, **이미지 생성 성공**(`limit_kinds []`) |
| 10:53 | `official`(9c 뒤) | sonnet | 끔 | 기획 2 | 2/2 HTTP 200 |

- 세션 누적 비용(원장 기준 기준점 대비): OpenAI 약 $0.093, Anthropic 약 $0.195, 이미지 약 $0.034, 합계 약 $0.32(세션 예산 $1.5 안).
- 이미지 미생성 원인: 조립이 `min(하드코딩 $12, 설정값)`으로 Gemini 상한을 깎아 승인된 환경변수(20.5)가 무시됐다(장부 Gemini $16.66). step 9b에서 수정(FP-C16).

## 2. 시나리오별 비용(dev 구성, haiku 평가)

| 시나리오 | 종류 | 텍스트 비용(USD) | 지연(ms) |
|---|---|---|---|
| serum-pattern | 패턴 | 0.0016 | 16,606 |
| ingredient-relation | 관계 | 0.0001 | 2,076 |
| serum-plan | 기획 | 0.0057 | 20,699 |
| sun-care-plan | 기획 | 0.0077 | 30,207 |
| unsupported-category | 범위 밖 | 0.0001 | 1,938 |

`ingredient-relation`은 의도가 `relation`으로 해석됐으나 카테고리가 정해지지 않아 코드가 `out_of_scope`로 종료했다(모델 호출 1회). 이 시나리오 문구가 지원 카테고리를 명시하지 않은 것이 원인으로 보이며(미확정), 관계 질의 경로(`research` 종류 종료)는 이번 live에서 검증되지 않았다.

## 3. 차별성·적합성 점수 경로(되돌림 사례)

`attempts[].scores`(차별성 / 적합성), `rework_count`, 최종 상태. 9c 이전 결과는 `passed`가 검사 통과를 뜻했으므로 점수와 `status`로 읽었다.

| 구성 | 시나리오 | 점수 경로 | 되돌림 | 최종 |
|---|---|---|---|---|
| dev (haiku) | serum-plan | 3/4 | 0 | done |
| dev (haiku) | sun-care-plan | 3/4 | 0 | done |
| official (sonnet, 9c 이전) | serum-plan | 2/4 → 2/4 → 2/3 | 2 | needs_review |
| official (sonnet, 9c 이전) | sun-care-plan | 2/4 → 2/4 → 2/4 | 2 | needs_review |
| image (sonnet, 9c 이전) | serum-plan | 2/4 → 3/4 | 1 | done |
| image (sonnet, 9c 이전) | serum-plan(재실행) | 2/4 → 2/4 → 2/4 | 2 | needs_review |
| image (sonnet, 9c 이후) | serum-plan | 4/3 | 0 | done |
| official (sonnet, 9c 이후) | serum-plan | 4/3(검사 실패 `EVIDENCE_MISSING`) → 3/4 | 1 | done |
| official (sonnet, 9c 이후) | sun-care-plan | 4/4 | 0 | done |

- 해석(관측, 일반화 아님): 9c 이전 sonnet은 차별성 2에서 되돌림 2회에도 움직이지 않았다. 9c(평가 입력에 훅·앵글·포맷 추가, 1~5점 척도, 기획 프롬프트에서 `low_items`를 개선 지침으로 사용)가 들어간 뒤 첫 시도 점수가 2 → 4로 올랐다. **척도 문구가 바뀌었으므로 9c 이전·이후 점수를 직접 비교하지 않는다**(`prompt_versions`로 구분). 점수가 올랐다는 사실이 차별성이 실제로 개선됐다는 증거는 아니다(평가자 기준이 달라짐).
- 되돌림 한 사례(official, 9c 이후): 첫 시도가 결정론 검사(`EVIDENCE_MISSING`)에 실패해 한 번 되돌렸고 둘째 시도에서 통과했다. 되돌림 루프가 검사 실패를 고친 사례다.

## 4. 효능 상태

- 9c 이전 8개 기획안 중 `efficacy_status`가 비어 있지 않은 것은 1건(`hydration: supported`)뿐이었다(주장 없음 `{}`가 다수). 9c 이후 official의 `sun-care-plan`은 `sun_protection: supported`, `unknown_count 2`(근거 연결 없음 2건)이었다. 화면 데이터는 `unknown_count`·효능 상태를 `passed`와 별도 칸으로 싣는다.

## 5. 구조화 실패 종류

| 구성 | 모델 | 호출 수 | 첫 시도 실패 | 재시도 뒤 실패 |
|---|---|---|---|---|
| dev | gpt-6-luna | 8 | 0 | 0 |
| dev | gpt-6.1-terra | 2 | 0 | 0 |
| dev | claude-haiku-5-5 | 2 | 0 | 0 |
| official(9c 이전) | claude-sonnet-5-5 | 6 | SCHEMA_VIOLATION 1 | 0 |
| image(9b 뒤) | claude-sonnet-5-5 | 1 | SCHEMA_VIOLATION 1 | 0 |
| official(9c 이후) | claude-sonnet-5-5 | 3 | SCHEMA_VIOLATION 3 | 0 |

- 소넷 평가는 이번 세션 첫 시도 `SCHEMA_VIOLATION`이 반복돼(조언 세션 집계 4/4) 평가가 항상 두 번 호출되고 비용·지연이 약 2배가 된다. 재시도 뒤에는 모두 성공(최종 실패 0). 호출 수가 20 미만이라 실패율의 통계적 의미는 없다(`sample_too_small`). 원인은 확인되지 않았다(가설: 길이 제한 필드 초과). step 9d에서 필드 경로·오류 종류 집계를 추가했고 사용자 재실행으로 확인한다.
- luna·terra·haiku는 첫 시도 실패가 없었다.

## 6. 이미지

- 9b 뒤 이미지 1건 생성(이미지 비용 약 $0.034, 로컬 `data/design/`에만 저장, 커밋하지 않음). 결과에는 경로가 없고 참조(`request_key`·`index`·`mime`·`size`·`sha256`)만 있다.
- 관측된 한계: 이미지에 지시·설명 같은 **메타 문구가 들어갔고 라벨 글자가 부정확했다**. 이미지 프롬프트가 `image_brief`와 `hook_text`(카피)를 그대로 합쳐 이미지 모델이 글자로 그려 넣은 것으로 보인다. step 9e에서 `image_prompt`를 장면 묘사만 쓰도록 바꾸고 화면 데이터에 고지 칸을 추가한다.

## 7. 알려진 한계

1. **근거 소재 풀이 얇다**: 비교 도구의 축별 소재 수 합이 7건 규모였고, 지배 값의 점유율이 5~16%에 그쳤다(9c 이후 기획안 3건의 `pattern_alignment.share` 관측 7개 값: 0.05·0.05·0.09·0.14·0.14·0.14·0.16, 계산 불가 2건). 이 규모에서는 "지배 패턴과 다르게" 요구가 의미 있는 대비를 만들지 못하고 평가자의 차별성 판단도 불안정하다.
2. **강제 대비 위험**: 지배 패턴과 달라야 한다는 지시는 점유율이 낮은 축에서도 무리한 대비를 만들 수 있다. 9e에서 점유율 기준 이상인 축에서만 요구하도록 완화하고 얇은 풀이면 코드가 한계를 `basis_notes`에 적는다(기준값은 잠정, 사용자 승인 전).
3. **소넷 평가 첫 시도 실패**(위 5절): 비용·지연 2배, 원인 미확정.
4. **이미지 라벨 글자 부정확, 메타 문구 혼입**(위 6절): 생성 시안은 참고용이다(결과 화면 고지 칸은 9e).
5. `pattern_alignment`의 같은 패턴 여부(`same`)는 9c 이후 기획안 3건의 모든 축에서 거짓이었다(`compared` 3). 보고용 지표이며 판정에는 쓰지 않는다.
6. 개발 반복 결과(dev workspace, 2~5건): 일반화·최종 평가 근거로 쓰지 않는다. test 브랜드(isntree·beauty_of_joseon) 최종 평가 전에 프롬프트·기준값을 동결한다(`docs/PROMPT_CHANGELOG.md`).

## 8. 시안 확인에서 추가로 지적된 점(사용자 확인, 9c 이후 image 실행)

- 헤드라인 "세안 후, 어떤 세럼을 고르세요?"가 한국어 광고 카피로 부자연스럽다.
- 병 라벨과 하단 제품명 글자가 이미지 모델 특유로 찌그러진다.
- 하단의 영문 발음 표기(예: 한글 제품명의 영문 음차)가 부자연스럽다.
- 대응(구현됨, live 미검증): 9e — 이미지 프롬프트에서 글자·로고·브랜드·제품명·라벨을 모두 없애고(무라벨 일반 제품) 기획 프롬프트에 긍정형 한국어 카피 지침을 넣었다. 9f — 카피 글자(헤드라인·CTA)는 코드가 오픈 라이선스 폰트(Pretendard OFL 1.1, 사용자가 `make fetch-font`로 내려받음)로 이미지 위에 합성하고 제품명·브랜드명은 화면 데이터 칸으로만 준다.

## 9. 재실행 후 추가할 항목(빈칸, 사용자 실행 뒤 채움)

- 소넷 구조화 첫 시도 실패의 필드 경로·오류 종류 집계(9d), 평가 `rationale` 200자 지시 뒤 변화
- 풀 크기와 축별 점유율 분포(`pattern_distribution`: `total`·`top_share`·`second_share`), 리서치 도구 우선순위 변경 뒤 풀 크기
- 차별성·적합성 점수 경로(프롬프트 버전 `2026-11-18-2`), `pattern_alignment`
- 합성 이미지의 글자 선명도·헤드라인 자연스러움(사용자 육안 확인)
