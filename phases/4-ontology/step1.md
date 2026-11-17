# Step 1: claim-rules

## 읽어야 할 파일

먼저 아래 파일들을 읽고 프로젝트의 아키텍처와 설계 의도를 파악하라:

- `/AGENTS.md` — 계층 경계 표와 CRITICAL 규칙
- `/docs/ARCHITECTURE.md` — 디렉토리 구조, 온톨로지 절, 데이터 흐름
- `/tests/test_architecture.py` — 계층 가드. 이 step이 만드는 모듈은 이 가드를 통과해야 한다
- `/docs/PHASES.md` — P4 절과 변경 기록 #36
- `/docs/COMPETENCY_QUESTIONS.md` — v1(2026-11-15 동결), 홉 정의와 한계
- `/docs/ADR.md` — ADR-014(표현 규칙의 출처·종류·적용 범위), ADR-012 후속 결정(`SkinType`·`SkinConcern` 목록)
- `/docs/CONTRACTS.md` — "식약처 안내서 PDF 내려받기" 절(출처 주소·크기·해시)
- `/docs/TAXONOMY.md` — `claims` 축 값 목록
- `/src/beautyads/domain/labels.py`, `/src/beautyads/sources/config.py` — 닫힌 값 목록, 설정 파일 로더 방식(**그대로 따른다**)

이전 step에서 만들어진 코드를 꼼꼼히 읽고, 설계 의도를 이해한 뒤 작업하라.

## 작업

**수정할 파일**: `config/claim_rules.yaml`(새 파일, 내용은 아래 "확정된 규칙" 절을 **그대로** 옮긴다), `src/beautyads/domain/claims.py`(새 파일), `src/beautyads/domain/skin.py`(새 파일), `src/beautyads/sources/claim_rules.py`(새 파일), `tests/test_claim_rules.py`(새 파일), `tests/test_domain.py`

열람 금지 경로: `data/interim/`
수정 허용 경로: `config/claim_rules.yaml`, `src/beautyads/domain/claims.py`, `src/beautyads/domain/skin.py`, `src/beautyads/sources/claim_rules.py`, `tests/test_claim_rules.py`, `tests/test_domain.py`(해당 케이스 추가에 한함, 단언 약화 금지)
열람 금지의 범위: 이 금지는 **Codex 세션이 해당 경로의 파일을 직접 열람·출력·인용하는 것**에 대한 것이다. 이 step의 코드가 런타임에 그 경로를 다루는 것(기본 입력·출력 경로 등)은 대상이 아니다. 테스트가 그 경로의 실제 파일 **내용**을 읽는 것은 여전히 금지이며 테스트는 임시 디렉터리와 합성 데이터만 쓴다.

식약처 「화장품 표시·광고 관리 지침」(민원인 안내서 안내서-0086-07, 2025-08-14, 17쪽)의 표현 규칙을 코드가 읽을 수 있는 형태로 옮긴다. **규칙 내용(`config/claim_rules.yaml`)은 조언 세션이 원문 PDF와 대조해 확정했고(2026-11-15) 이 step은 아래 "확정된 규칙" 절의 본문을 파일로 그대로 옮기고, 형식 검증·금지어 검사 함수를 만든다.** 규칙의 내용·쪽 번호·표현을 바꾸거나 더하지 않는다(추정·기억으로 쓴 규칙 금지).

- **파일 형식**(최상위 키): `source`(`title`·`registration_no`·`page_url`·`file_url`·`file_sha256`·`pages`·`legal_effect`, 모두 필수), `status`, `verification`, `transcription_rules`, `general_principles`, `excluded_scope`, `rules`. 규칙 한 개의 키: `rule_id`, `rule_type`, `source_page`(필수, 1 이상), `source_page_end`(선택), `law_basis`, `group`, `source_items`(원문 항목, 비어 있으면 안 된다), `terms_ko`, `terms_en`(원문에 있는 영어), `terms_en_added`(원문 외 영어, 조언 세션 추가), `en_origin`, `en_pending`, `en_waived`, `en_note`(선택), `matchable`, `exception_note`, `exceptions`(예외 문구), `exception_refs`(예외로 참조하는 규칙 ID 목록), `applies_to`(목록, 항목은 `kind`·`value`·`status`).
- **`domain/skin.py`**: `SkinType`(건성·지성·복합성·민감성)과 `SkinConcern`(건조, 트러블·여드름, 홍조·민감, 모공·피지, 칙칙함·잡티, 탄력 저하, 주름, 거친 피부결) 값 목록(`StrEnum`, ADR-012 후속 결정 5)이다. 값은 한글 그대로다. 이 step 이후 `layer1-graph`가 같은 목록을 쓴다.
- **`domain/claims.py`**(pydantic·표준 라이브러리만, `yaml` import 금지): `RuleType`(`prohibited`·`requires_functional_cert`·`requires_substantiation`), `ClaimRule`, `parse_claim_rules(document: dict)`(순수 함수, 형식 오류는 `CLAIM_RULES_INVALID`와 위치를 돌려준다), `CLAIM_CHECK_DISCLAIMER = "식약처 안내서 기준 점검이며 법적 판단이 아님"`, `find_claim_terms(text, rules)`, `check_plan_fields(fields: Mapping[str, str], rules)`.
  - **검증**: `source_page`가 없거나 0 이하이면 오류. `matchable == true`이면 `terms_ko`가 비어 있으면 안 되고 `false`이면 비어 있어야 한다(문장형 항목은 단어로 잡지 않는다 — 안내서 III.6 "전체적인 광고의 인상"). `matchable == true`인데 영어(`terms_en`·`terms_en_added`)가 둘 다 비어 있으면 `en_pending`이나 `en_waived` 중 하나가 `true`여야 한다. `terms_en_added`가 비어 있지 않으면 `en_origin`이 `advisor_added_en`이어야 한다. `exception_refs`는 존재하는 규칙 ID여야 하고 자기 자신을 참조할 수 없다. `applies_to`의 `kind`는 `efficacy`(값은 `domain.labels.Claim`)·`skin_concern`(값은 `SkinConcern`)·`category`(값은 `Category`)이고 `status`는 `draft`·`advisor_approved`·`confirmed` 중 하나다. `rule_id` 중복·빈 규칙 목록은 오류다.
  - **한국어 표현 비교**: 정규화(NFKC·대소문자 무시·공백 제거) 뒤 부분 일치.
  - **영어 표현 비교(`terms_en`·`terms_en_added`)**: 정규화는 NFKC·대소문자 무시·공백을 한 칸으로 줄이기(공백을 지우지 않는다)이고, **단어 경계로만 일치**한다 — 일치 구간의 앞뒤가 ASCII 영문자·숫자가 아닐 때만 일치다(`drug`가 `drugstore`에 걸리지 않고 `UV차단`의 `UV`는 걸린다). 부분 문자열 일치를 영어에 쓰지 않는다.
  - **예외**: 규칙의 `exceptions` 문구와, `exception_refs`가 가리키는 규칙들의 `terms_ko`가 걸린 구간은 그 규칙의 일치에서 뺀다(예외 구간과 겹치는 일치는 버린다). 어떤 규칙의 어떤 표현이 걸렸는지와 규칙 종류를 돌려준다.
  - **`check_plan_fields`**: 기획안의 **제목(`title`)·카피·자막** 같은 필드를 모두 검사한다(안내서 III.7: 광고의 제목명에 기재된 문구도 판단 대상, 7쪽). 결과는 필드별 일치 목록과 `CLAIM_CHECK_DISCLAIMER`를 함께 담는다(평가 출력에 이 문구를 표시하기 위함, 평가 에이전트는 P5 `checks` step).
- **`sources/claim_rules.py`**: `load_claim_rules(path)`가 YAML을 읽고 `parse_claim_rules`를 부른다. 파일이 없거나 읽을 수 없으면 `CLAIM_RULES_UNREADABLE`, 형식이 틀리면 `CLAIM_RULES_INVALID`(기존 `sources/config.py` 로더와 같은 방식).
- `requires_substantiation`은 차단이 아니라 "실증 필요" 경고로만 쓴다(ADR-014): 결과가 규칙 종류를 그대로 돌려주고 차단/경고 판정은 `checks/`(P5)가 한다. 이 step은 판정하지 않는다.
- 규칙은 **기획안 검사**에만 쓰고 경쟁 소재에는 "관찰"만 한다는 원칙을 `domain/claims.py` 모듈 설명에 한 줄로 적는다.

## 확정된 규칙

조언 세션이 원문 PDF(sha256 `a3efa6c204c73cb1bfd08bb7be5598c7344c9494c3180256577e315bbfdeb8bf`, 17쪽) 9~16쪽과 대조해 확정했다(2026-11-15). 아래 YAML 전체(sha256 `ef57571e91d805150f092df226966c85cbb33bae398e35ad66ea0aafa0d243dc`)를 `config/claim_rules.yaml`에 **한 글자도 바꾸지 말고** 옮긴다(첫 줄 주석 포함).

```yaml
# 조언 세션이 원문 PDF 9~16쪽과 대조하고 수정한 확정본(2026-11-15).
source:
  title: 화장품 표시·광고 관리 지침(민원인 안내서)
  registration_no: 안내서-0086-07
  issued: '2025-08-14'
  issuer: 식품의약품안전처 바이오생약국 화장품정책과
  page_url: https://www.mfds.go.kr/brd/m_1060/view.do?seq=15700
  file_url: https://www.mfds.go.kr/brd/m_1060/down.do?brd_id=data0011&seq=15700&data_tp=A&file_seq=2
  file_size_bytes: 360654
  file_sha256: a3efa6c204c73cb1bfd08bb7be5598c7344c9494c3180256577e315bbfdeb8bf
  pages: 17
  legal_effect: 본 안내서는 대외적으로 법적 효력을 가지는 것이 아니므로 참고로만 활용(3쪽). 2025년 8월 기준.
status: advisor_confirmed_2026-11-15
verification:
  method: 모든 source_items·exceptions·exception_note를 PDF 추출 텍스트(Swift PDFKit)와 공백·문자 변형 정규화 뒤 부분 문자열로 대조
  unmatched_checked_visually:
  - CR-023(13~14쪽에 걸친 셀)
  - CR-037(16쪽 열 겹침, 목록 기호 ‘-’ 누락)
  page_images_viewed:
  - 9
  - 10
  - 11
  - 12
  - 13
  - 14
  - 15
  - 16
transcription_rules:
- source_items는 PDF 본문에서 옮긴 원문 항목이다(공백만 정규화). 표의 열 구분(구분·금지표현·비고)은 쪽 이미지로 확인했다.
- terms_ko는 코드 검사용 검색어다. 원문이 단어 목록이면 원문 항목을 그대로 쓰되, ‘·’나 ‘,’로 나열된 단어는 나눈 것이 있다(살균·소독 등). 문장형 항목은 단어로 나눌 수 없어 terms_ko를 비우고 matchable=false로 둔다(전체적인 인상 판단, III.6, 7쪽).
- terms_en은 원문에 영어 표기가 있는 경우에만 적었다. 원문에 영어가 없는 항목의 영어 대응어는 이 초안에 없고, 그런 규칙은 en_pending=true로 표시했다(조언 세션 검토에서 번역을 추가하면 en_pending을 내린다).
- applies_to의 효능·피부 고민 값은 원문에 없는 프로젝트 대응이며 조언 세션이 승인했다(status=advisor_approved).
- terms_en_added는 원문에 없는 영어 대응어로 조언 세션이 추가했다(en_origin=advisor_added_en, 근거 안내서 III.4 7쪽). 영어 terms는 ASCII 영문자·숫자에 붙어 있지 않은 단어 경계로만 비교한다(drug가 drugstore에 걸리지 않게).
- exception_refs는 비고가 '[별표2] 1.에 해당하는 표현은 제외'라고 한 규칙이 15~16쪽 [별표 2] 항목(CR-029~032, 3.은 CR-037)을 참조하는 규칙 ID 목록이다. 참조된 규칙의 terms가 예외 문구로 쓰인다.
- exception_note는 비고 칸의 원문이다. exceptions는 비고가 가리키는 [별표 2]의 표현 중 같은 쪽에 있는 것만 옮겼다.
general_principles:
- page: 7
  ref: III.4
  text: 사용금지 표현에 해당하는 단어와 동일/유사한 의미의 영어 등 외국어로 표현하는 경우에도 일반적인 소비자가 받아들이는 전체적인 광고의 인상을 고려하여 금지표현의 범주로 판단할 수 있다.
- page: 7
  ref: III.6
  text: 이 지침 외의 광고 표현의 경우에도 화장품법령, 고시 및 민원인 안내서 등을 바탕으로 판단하되, 단어만으로 판단이 곤란한 경우에는 일반적인 소비자가 받아들이는 전체적인 광고의 인상을 고려하여 금지표현의 범주로 판단할 수 있다.
- page: 7
  ref: III.7
  text: 온라인 부당광고 해당 여부 검토 시, 광고의 제목명에 기재되어 있는 문구도 고려하여 판단한다.
excluded_scope:
- pages:
  - 10
  - 15
  what: 모발 관련 표현(탈모·발모·모발 손상 등)
  reason: 대상 카테고리(마스크팩·세럼/앰플·선케어)와 무관(구현 세션 판단, 조언 세션 검토 필요)
- pages:
  - 11
  what: 신체 개선 표현(다이어트·체형변화·얼굴 윤곽 등)
  reason: 위와 같음
- pages:
  - 14
  what: 성생활·저속·혐오 표현
  reason: 위와 같음
rules:
- rule_id: CR-001
  rule_type: prohibited
  source_page: 9
  law_basis: 화장품법 제13조 제1항 제1호
  group: 질병을 진단·치료·경감·처치 또는 예방, 의학적 효능·효과 관련
  source_items:
  - 아토피
  - 모낭충
  - 심신피로 회복
  - 건선
  - 소양증
  - 살균·소독
  - 항염·진통
  - 해독
  - 이뇨
  - 항암
  - 항진균·항바이러스
  - 근육 이완
  - 통증 경감
  - 면역 강화, 항알레르기
  - 찰과상, 화상 치료·회복
  - 기저귀 발진
  terms_ko:
  - 아토피
  - 모낭충
  - 심신피로 회복
  - 건선
  - 소양증
  - 살균
  - 소독
  - 항염
  - 진통
  - 해독
  - 이뇨
  - 항암
  - 항진균
  - 항바이러스
  - 근육 이완
  - 통증 경감
  - 면역 강화
  - 항알레르기
  - 찰과상
  - 기저귀 발진
  terms_en: []
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - atopy
  - atopic dermatitis
  - demodex
  - psoriasis
  - pruritus
  - sterilizing
  - disinfecting
  - anti-inflammatory
  - analgesic
  - detoxifying
  - diuretic
  - anticancer
  - antifungal
  - antiviral
  - muscle relaxation
  - pain relief
  - immune boosting
  - anti-allergy
  - diaper rash
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-002
  rule_type: prohibited
  source_page: 9
  law_basis: 화장품법 제13조 제1항 제1호
  group: 질병을 진단·치료·경감·처치 또는 예방, 의학적 효능·효과 관련
  source_items:
  - 관절, 림프선 등 피부 이외 신체 특정 부위에 사용하여 의학적 효능, 효과 표방
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-003
  rule_type: prohibited
  source_page: 9
  law_basis: 화장품법 제13조 제1항 제1호
  group: 질병을 진단·치료·경감·처치 또는 예방, 의학적 효능·효과 관련
  source_items: &id001
  - 여드름
  terms_ko: *id001
  terms_en: []
  matchable: true
  exception_note: 단, 기능성화장품의 심사(보고)된 ‘효능효과’ 표현 또는 [별표2] 1.에 해당하는 표현은 제외
  exceptions:
  - 여드름성 피부에 사용에 적합
  applies_to:
  - kind: skin_concern
    value: 트러블·여드름
    status: advisor_approved
  - kind: efficacy
    value: acne_trouble
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - acne
  en_origin: advisor_added_en
  exception_refs:
  - CR-029
  - CR-030
  - CR-031
  - CR-032
  en_waived: false
- rule_id: CR-004
  rule_type: prohibited
  source_page: 9
  law_basis: 화장품법 제13조 제1항 제1호
  group: 질병을 진단·치료·경감·처치 또는 예방, 의학적 효능·효과 관련
  source_items:
  - 기미, 주근깨(과색소침착증)
  terms_ko:
  - 기미
  - 주근깨
  - 과색소침착증
  terms_en: []
  matchable: true
  exception_note: 단, [별표2] 1.에 해당하는 표현은 제외
  exceptions:
  - 기미, 주근깨 완화에 도움
  applies_to:
  - kind: skin_concern
    value: 칙칙함·잡티
    status: advisor_approved
  - kind: efficacy
    value: brightening
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - melasma
  - freckles
  - hyperpigmentation
  en_origin: advisor_added_en
  exception_refs:
  - CR-029
  - CR-030
  - CR-031
  - CR-032
  en_waived: false
- rule_id: CR-005
  rule_type: prohibited
  source_page: 9
  law_basis: 화장품법 제13조 제1항 제1호
  group: 질병을 진단·치료·경감·처치 또는 예방, 의학적 효능·효과 관련
  source_items: &id002
  - 항균
  terms_ko: *id002
  terms_en: []
  matchable: true
  exception_note: 단, [별표2] 1.에 해당하는 표현은 제외하되, 이 경우에도 액체비누에 대해 트리클로산 또는 트리클로카반 함유로 인해 항균 효과가 ‘더 뛰어나다’, ‘더 좋다’ 등의 비교 표시·광고는 금지
  exceptions:
  - 항균(인체세정용 제품에 한함)
  applies_to: []
  en_pending: false
  terms_en_added:
  - antibacterial
  - antimicrobial
  en_origin: advisor_added_en
  exception_refs:
  - CR-029
  - CR-030
  - CR-031
  - CR-032
  en_waived: false
- rule_id: CR-006
  rule_type: prohibited
  source_page: 10
  law_basis: 화장품법 제13조 제1항 제1호
  group: 피부 관련 표현
  source_items:
  - 임신선, 튼살
  terms_ko:
  - 임신선
  - 튼살
  terms_en: []
  matchable: true
  exception_note: 단, 기능성화장품의 심사(보고)된 ‘효능효과’ 표현은 제외
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - stretch marks
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-007
  rule_type: prohibited
  source_page: 10
  law_basis: 화장품법 제13조 제1항 제1호
  group: 피부 관련 표현
  source_items:
  - 피부 독소를 제거한다(디톡스, detox)
  - 상처로 인한 반흔을 제거 또는 완화한다.
  terms_ko:
  - 디톡스
  - detox
  terms_en:
  - detox
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-008
  rule_type: prohibited
  source_page: 10
  law_basis: 화장품법 제13조 제1항 제1호
  group: 피부 관련 표현
  source_items:
  - 가려움을 완화, 개선, 해결한다.
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: '* 기능성화장품의 심사된 ‘효능효과’ 표현은 제외 / * 보습을 통해 피부건조에 기인한 가려움의 일시적 완화에 도움을 준다는 표현 제외(단, ‘보습’과 ‘일시적’인 경우에 한함)'
  exceptions: []
  applies_to:
  - kind: efficacy
    value: hydration
    status: advisor_approved
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-009
  rule_type: prohibited
  source_page: 10
  law_basis: 화장품법 제13조 제1항 제1호
  group: 피부 관련 표현
  source_items:
  - ○○○의 흔적을 없애준다. <예시> 여드름, 흉터의 흔적을 제거
  - 홍조, 홍반을 개선, 제거한다.
  - 뾰루지를 개선한다.
  terms_ko:
  - 홍조
  - 홍반
  - 뾰루지
  terms_en: []
  matchable: true
  exception_note: 단, (색조 화장용 제품류 등으로서) ‘가려준다’는 표현은 제외
  exceptions: []
  applies_to:
  - kind: skin_concern
    value: 홍조·민감
    status: advisor_approved
  - kind: efficacy
    value: soothing
    status: advisor_approved
  - kind: skin_concern
    value: 트러블·여드름
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - redness
  - erythema
  - pimples
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-010
  rule_type: prohibited
  source_page: 10
  law_basis: 화장품법 제13조 제1항 제1호
  group: 피부 관련 표현
  source_items:
  - 피부의 상처나 질병으로 인한 손상을 치료하거나 회복 또는 복구한다.
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: 일부 단어만 사용하는 경우도 포함. 단, [별표2] 1.에 해당하는 표현은 제외
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs:
  - CR-029
  - CR-030
  - CR-031
  - CR-032
  terms_en_added: []
  en_waived: false
- rule_id: CR-011
  rule_type: prohibited
  source_page: 10
  law_basis: 화장품법 제13조 제1항 제1호
  group: 피부 관련 표현
  source_items:
  - 피부노화
  - 셀룰라이트
  - 붓기·다크서클
  - '피부구성 물질(예 : 효소, 콜라겐 등)을 증가, 감소 또는 활성화시킨다.'
  terms_ko:
  - 피부노화
  - 셀룰라이트
  - 붓기
  - 다크서클
  terms_en: []
  matchable: true
  exception_note: 단, [별표2] 1.에 해당하는 표현은 제외
  exceptions: []
  applies_to:
  - kind: efficacy
    value: anti_aging
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - skin aging
  - cellulite
  - puffiness
  - dark circles
  en_origin: advisor_added_en
  exception_refs:
  - CR-029
  - CR-030
  - CR-031
  - CR-032
  en_waived: false
- rule_id: CR-012
  rule_type: prohibited
  source_page: 11
  law_basis: 화장품법 제13조 제1항 제1호
  group: 생리활성 관련
  source_items:
  - 혈액순환
  - 피부재생, 세포 재생
  - 호르몬 분비촉진 등 내분비 작용
  - 유익균의 균형 보호
  - 질 내 산도 유지, 질염 예방
  - 땀 발생을 억제한다.
  - 세포 성장을 촉진한다.
  - 세포 활력(증가), 세포 또는 유전자(DNA) 활성화
  terms_ko:
  - 혈액순환
  - 피부재생
  - 세포 재생
  - 호르몬 분비촉진
  - 내분비 작용
  - 유익균의 균형 보호
  - 질염 예방
  - 땀 발생을 억제
  - 세포 성장을 촉진
  - 세포 활력
  - 유전자(DNA) 활성화
  terms_en: []
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - blood circulation
  - skin regeneration
  - cell regeneration
  - hormone secretion
  - cell activation
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-013
  rule_type: prohibited
  source_page: 11
  law_basis: 화장품법 제13조 제1항 제1호
  group: 원료 관련 표현
  source_items:
  - 원료 관련 설명시 의약품 오인 우려 표현 사용(논문 등을 통한 간접적으로 의약품 오인 정보제공을 포함)
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-014
  rule_type: prohibited
  source_page: 11
  law_basis: 화장품법 제13조 제1항 제1호
  group: 기타
  source_items:
  - 메디슨(medicine), 드럭(drug), 코스메슈티컬, 치유 등을 사용한 의약품 오인 우려 표현
  terms_ko:
  - 메디슨
  - medicine
  - 드럭
  - drug
  - 코스메슈티컬
  - 치유
  terms_en:
  - medicine
  - drug
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - cosmeceutical
  - healing
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-015
  rule_type: requires_functional_cert
  source_page: 12
  law_basis: 화장품법 제13조 제1항 제2호
  group: 기능성 관련 표현
  source_items:
  - 기능성 화장품 심사(보고)하지 아니한 제품에 미백, 화이트닝(whitening), 주름(링클, wrinkle) 개선, 자외선(UV)차단 등 기능성 관련 표현
  terms_ko:
  - 미백
  - 화이트닝
  - whitening
  - 링클
  - wrinkle
  - 주름 개선
  - 자외선 차단
  - UV차단
  terms_en:
  - whitening
  - wrinkle
  - UV
  matchable: true
  exception_note: null
  exceptions: []
  applies_to:
  - kind: efficacy
    value: brightening
    status: advisor_approved
  - kind: efficacy
    value: anti_aging
    status: advisor_approved
  - kind: efficacy
    value: sun_protection
    status: advisor_approved
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-016
  rule_type: prohibited
  source_page: 12
  law_basis: 화장품법 제13조 제1항 제2호
  group: 기능성 관련 표현
  source_items:
  - 기능성화장품 심사(보고) 결과와 다른 내용의 표시·광고 또는 기능성화장품 안전성·유효성에 관한 심사를 받은 범위를 벗어나는 표시·광고
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-017
  rule_type: requires_functional_cert
  source_page: 12
  law_basis: 화장품법 제13조 제1항 제2호
  group: 원료 관련 표현
  source_items:
  - 기능성화장품으로 심사(보고)하지 아니한 제품에 ‘식약처 미백 고시 성분 OO 함유’ 등의 표현
  terms_ko:
  - 식약처 미백 고시 성분
  terms_en: []
  matchable: true
  exception_note: null
  exceptions: []
  applies_to:
  - kind: efficacy
    value: brightening
    status: advisor_approved
  en_pending: true
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-018
  rule_type: prohibited
  source_page: 12
  law_basis: 화장품법 제13조 제1항 제2호
  group: 원료 관련 표현
  source_items:
  - 기능성 효능·효과 성분이 아닌 다른 성분으로 기능성을 표방하는 표현
  - 원료 관련 설명시 기능성 오인 우려 표현 사용(주름개선 효과가 있는 OO 원료)
  - 원료 관련 설명시 완제품에 대한 효능·효과로 오인될 수 있는 표현
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-019
  rule_type: prohibited
  source_page: 13
  law_basis: 화장품법 제13조 제1항 제4호
  group: 특정인 또는 기관의 지정, 공인 관련
  source_items:
  - OO 아토피 협회 인증 화장품
  - OO 의료기관의 첨단기술의 정수가 탄생시킨 화장품
  - OO 대학교 출신 의사가 공동 개발한 화장품
  - OO 의사가 개발한 화장품
  - OO 병원에서 추천하는 안전한 화장품
  - 병원용, 병원전용, 피부과전용, 피부과시술용, 약국용, 약국전용 화장품
  terms_ko:
  - 병원용
  - 병원전용
  - 피부과전용
  - 피부과시술용
  - 약국용
  - 약국전용
  terms_en: []
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - hospital-only
  - dermatologist-only
  - pharmacy-only
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-020
  rule_type: prohibited
  source_page: 13
  law_basis: 화장품법 제13조 제1항 제4호
  group: 화장품의 범위를 벗어나는 광고
  source_items:
  - 배합금지 원료를 사용하지 않았다는 표현(무첨가, free 포함) <예시> 無(무) 스테로이드, 無(무) 벤조피렌 등
  - 부작용이 전혀 없다.
  - 먹을 수 있다.
  - 일시적 악화(명현현상)가 있을 수 있다.
  - 지방볼륨생성
  - 보톡스
  - 레이저, 카복시 등 시술 관련 표현
  terms_ko:
  - 無 스테로이드
  - 무 스테로이드
  - 스테로이드 무첨가
  - 벤조피렌 무첨가
  - 부작용이 전혀 없
  - 먹을 수 있
  - 명현현상
  - 지방볼륨생성
  - 보톡스
  - 레이저
  - 카복시
  terms_en: []
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - steroid-free
  - benzopyrene-free
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-021
  rule_type: prohibited
  source_page: 13
  law_basis: 화장품법 제13조 제1항 제4호
  group: 화장품의 범위를 벗어나는 광고
  source_items: &id003
  - 체내 노폐물 제거
  terms_ko: *id003
  terms_en: []
  matchable: true
  exception_note: 단, 피부·모공 노폐물 제거 관련 표현 제외
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - removing body waste
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-022
  rule_type: prohibited
  source_page: 13
  law_basis: 화장품법 제13조 제1항 제4호
  group: 화장품의 범위를 벗어나는 광고
  source_items:
  - 필러(filler)
  terms_ko:
  - 필러
  - filler
  terms_en:
  - filler
  matchable: true
  exception_note: 단, (색조 화장용 제품류 등으로서) ‘채워준다’, ‘연출한다’는 의미의 표현을 함께 나타내는 경우 제외
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-023
  rule_type: prohibited
  source_page: 13
  law_basis: 화장품법 제13조 제1항 제4호
  group: 인체 유래 성분 관련 표현
  source_items:
  - 특정인의 ‘인체 세포·조직 배양액’ 기원 표현
  - 인체에서 유래한 줄기세포가 들어 있는 것으로 오인할 수 있는 표현 <예시> 줄기세포 화장품, stem cell, ○억 세포 등
  - 인체에서 유래한 특정성분(엑소좀, 리포좀 등)이 들어 있는 것으로 오인할 수 있는 표현 <예시> 엑소좀 화장품, 엑소좀 등
  terms_ko:
  - 줄기세포 화장품
  - stem cell
  - 엑소좀 화장품
  - 엑소좀
  terms_en:
  - stem cell
  matchable: true
  exception_note: ·「화장품 안전기준 등에 관한 규정」 [별표 3]에 적합한 원료를 사용한 경우에만 불특정인의 ‘인체 세포·조직 배양액’ 표현 가능 ·식물 등 인체 외에서 유래한 경우에는 제외 <예시> 우유 엑소좀, 식물 엑소좀 등
  exceptions: []
  applies_to: []
  en_pending: false
  source_page_end: 14
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-024
  rule_type: prohibited
  source_page: 14
  law_basis: 화장품법 제13조 제1항 제4호
  group: 사실과 다르거나 소비자가 사실로 오인할 수 있는 표현
  source_items:
  - 제품 사용방법을 사실과 다르거나 오인할 수 있는 표현 <예시> 바늘, 니들, 마이크로니들, 미세침, MTS(Microneedle Therapy System), 외음부세정제의 ‘이너케어’, ‘질 내 주입/사용’ 등
  terms_ko:
  - 바늘
  - 니들
  - 마이크로니들
  - 미세침
  - MTS
  terms_en: []
  matchable: true
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - needle
  - microneedle
  - micro-needle
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-025
  rule_type: requires_substantiation
  source_page: 14
  law_basis: 화장품법 제13조 제1항 제4호
  group: 사실과 다르거나 소비자가 사실로 오인할 수 있는 표현
  source_items:
  - 「천연화장품 및 유기농화장품 표시·광고 안내서」(대한화장품협회)에 적합하지 않은 제품에 ‘천연(Natural)’, ‘유기농(organic)’ 관련 표현
  terms_ko:
  - 천연
  - Natural
  - 유기농
  - organic
  terms_en:
  - Natural
  - organic
  matchable: true
  exception_note: 제품에 천연, 유기농 표현을 사용하려면 「천연화장품 및 유기농화장품 표시·광고 안내서」(대한화장품협회)에 따른 적합한 자료 구비 필요 단, [별표2] 3.에 해당하는 표현은 제외
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs:
  - CR-037
  terms_en_added: []
  en_waived: false
- rule_id: CR-026
  rule_type: prohibited
  source_page: 14
  law_basis: 화장품법 제13조 제1항 제4호
  group: 그 밖의 기타 표현
  source_items:
  - 동 제품은 식품의약품안전처 허가, 인증을 받은 제품임
  terms_ko:
  - 식품의약품안전처 허가
  - 식품의약품안전처 인증
  terms_en: []
  matchable: true
  exception_note: 단, 기능성화장품 심사(보고) 관련 표현 제외
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - MFDS approved
  - MFDS certified
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-027
  rule_type: prohibited
  source_page: 14
  law_basis: 화장품법 제13조 제1항 제4호
  group: 그 밖의 기타 표현
  source_items:
  - 원료 관련 설명 시 완제품에 대한 효능·효과로 오인될 수 있는 표현
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: null
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-028
  rule_type: prohibited
  source_page: 14
  law_basis: 화장품법 제13조 제1항 제4호
  group: 그 밖의 기타 표현
  source_items:
  - 피부 나이 n(세 등 기간을 의미하는 단위) 감소 또는 어려진다는 표현 <예시> 피부나이 10년 감소, 피부나이 5세 어려짐, 피부나이 -3살 등
  terms_ko:
  - 피부나이
  - 피부 나이
  terms_en: []
  matchable: true
  exception_note: 단, [별표2] 1.에 해당하는 표현은 제외
  exceptions: []
  applies_to:
  - kind: efficacy
    value: anti_aging
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - skin age
  en_origin: advisor_added_en
  exception_refs:
  - CR-029
  - CR-030
  - CR-031
  - CR-032
  en_waived: false
- rule_id: CR-029
  rule_type: requires_substantiation
  source_page: 15
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 1. 「화장품 표시·광고 실증에 관한 규정」(식약처 고시) 별표 등에 따른 표현'
  group: null
  source_items:
  - 여드름성 피부에 사용에 적합
  - 항균(인체세정용 제품에 한함)
  - 일시적 셀룰라이트 감소
  - 붓기 완화
  - 다크서클 완화
  - 피부 혈행 개선
  - 피부장벽 손상의 개선에 도움
  - 피부 피지분비 조절
  - 미세먼지 차단, 미세먼지 흡착 방지
  terms_ko:
  - 여드름성 피부에 사용에 적합
  - 항균
  - 일시적 셀룰라이트 감소
  - 붓기 완화
  - 다크서클 완화
  - 피부 혈행 개선
  - 피부장벽 손상의 개선에 도움
  - 피부 피지분비 조절
  - 미세먼지 차단
  - 미세먼지 흡착 방지
  terms_en: []
  matchable: true
  exception_note: 인체 적용시험 자료로 입증
  exceptions: []
  applies_to:
  - kind: efficacy
    value: acne_trouble
    status: advisor_approved
  - kind: efficacy
    value: barrier
    status: advisor_approved
  - kind: efficacy
    value: pore_sebum
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - sebum control
  - fine dust blocking
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-030
  rule_type: requires_substantiation
  source_page: 15
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 1.'
  group: null
  source_items:
  - 피부노화 완화, 안티에이징, 피부노화 징후 감소, 피부노화지수 감소
  terms_ko:
  - 피부노화 완화
  - 안티에이징
  - 피부노화 징후 감소
  - 피부노화지수 감소
  terms_en: []
  matchable: true
  exception_note: 인체 적용시험 자료, 인체 외 시험 자료로 입증. 다만, 자외선차단 주름개선 등 기능성 효능·효과를 통한 피부노화 완화 표현의 경우 기능성화장품 심사(보고) 자료를 근거자료로 활용 가능 / 피부노화지수의 단위는 ‘n(세 등 기간을 의미하는 단위)’으로 표기 불가
  exceptions: []
  applies_to:
  - kind: efficacy
    value: anti_aging
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - anti-aging
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-031
  rule_type: requires_substantiation
  source_page: 15
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 1.'
  group: null
  source_items:
  - 콜라겐 증가, 감소 또는 활성화
  - 효소 증가, 감소 또는 활성화
  terms_ko:
  - 콜라겐 증가
  - 콜라겐 감소
  - 콜라겐 활성화
  - 효소 증가
  - 효소 감소
  - 효소 활성화
  terms_en: []
  matchable: true
  exception_note: 주름 완화 또는 개선 기능성화장품으로서 이미 심사받은 자료에 포함되어 있거나 해당 기능을 별도로 실증한 자료로 입증
  exceptions: []
  applies_to:
  - kind: efficacy
    value: firming_elasticity
    status: advisor_approved
  en_pending: false
  terms_en_added:
  - collagen boost
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-032
  rule_type: requires_substantiation
  source_page: 15
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 1.'
  group: null
  source_items: &id004
  - 기미, 주근깨 완화에 도움
  terms_ko: *id004
  terms_en: []
  matchable: true
  exception_note: 미백 기능성화장품 심사(보고) 자료로 입증
  exceptions: []
  applies_to:
  - kind: efficacy
    value: brightening
    status: advisor_approved
  en_pending: true
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-033
  rule_type: requires_substantiation
  source_page: 16
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 2. 효능·효과·품질에 관한 내용'
  group: null
  source_items:
  - 화장품의 효능·효과에 관한 내용 <예시> 수분감 30% 개선 효과 피부결 20% 개선 2주 경과 후 피부톤 개선
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: 인체 적용시험 자료 또는 인체 외 시험 자료로 입증
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-034
  rule_type: requires_substantiation
  source_page: 16
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 2.'
  group: null
  source_items:
  - 시험·검사와 관련된 표현 <예시> 피부과 테스트 완료 oo시험검사기관의 oo 효과 입증
  terms_ko:
  - 피부과 테스트 완료
  terms_en: []
  matchable: true
  exception_note: 인체 적용시험 자료 또는 인체 외 시험 자료로 입증
  exceptions: []
  applies_to: []
  en_pending: false
  terms_en_added:
  - dermatologist tested
  en_origin: advisor_added_en
  exception_refs: []
  en_waived: false
- rule_id: CR-035
  rule_type: requires_substantiation
  source_page: 16
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 2.'
  group: null
  source_items:
  - 제품에 특정성분이 들어 있지 않다는 ‘무(無) oo’ 표현1)
  terms_ko:
  - 무(無)
  terms_en: []
  matchable: true
  exception_note: 시험 분석 자료로 입증 / 1) 금지표현(배합금지 원료를 사용하지 않았다는 표현)을 제외한 경우에 한함
  exceptions: []
  applies_to: []
  en_pending: false
  en_waived: true
  en_note: 영어 일반어는 추가하지 않는다(조언 세션 결정, 2026-11-15)
  exception_refs: []
  terms_en_added: []
- rule_id: CR-036
  rule_type: requires_substantiation
  source_page: 16
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 2.'
  group: null
  source_items:
  - 타제품과 비교하는 내용의 표시·광고 <예시> “○○보다 지속력이 5배 높음”
  terms_ko: []
  terms_en: []
  matchable: false
  exception_note: 인체 적용시험 자료 또는 인체 외 시험 자료로 입증
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
- rule_id: CR-037
  rule_type: requires_substantiation
  source_page: 16
  law_basis: '[별표 2] 화장품 표시·광고 주요 실증대상 3. ISO 천연·유기농 지수 표시·광고에 관한 내용'
  group: null
  source_items:
  - ISO 천연·유기농 지수2) 표시·광고 <예시> 천연지수 00% (ISO 16128 계산 적용) 천연유래지수 00% (ISO 16128 계산 적용) 유기농지수 00% (ISO 16128 계산 적용) 유기농유래지수 00% (ISO 16128 계산 적용)
  terms_ko:
  - 천연지수
  - 천연유래지수
  - 유기농지수
  - 유기농유래지수
  - ISO 16128
  terms_en:
  - ISO 16128
  matchable: true
  exception_note: 해당 완제품 관련 실증자료로 입증 / 이 경우 ISO 16128(가이드라인)에 따른 계산이라는 것과 소비자 오인을 방지하기 위한 문구도 함께 안내 필요(주의 사항 참고)
  exceptions: []
  applies_to: []
  en_pending: false
  exception_refs: []
  terms_en_added: []
  en_waived: false
```

### 반드시 있어야 하는 테스트

- 파싱: 합성 규칙 문서(모든 종류·원문 항목·영어·예외·`exception_refs`·쪽 번호·`applies_to`)가 `ClaimRule` 목록이 된다. 쪽 번호 없음·0 이하, `matchable`과 `terms_ko` 불일치, 영어가 없고 `en_pending`·`en_waived`도 `false`, `terms_en_added`가 있는데 `en_origin`이 다름, 존재하지 않는 `exception_refs`·자기 참조, 알 수 없는 `rule_type`, 닫힌 목록 밖의 `applies_to` 값·`status`, 중복 `rule_id`, 빈 규칙 목록은 각각 `CLAIM_RULES_INVALID`와 위치를 돌려준다(B-FP-069).
- 한국어 검사: 합성 표현이 걸린다·안 걸린다, 공백·대소문자·전각 변형이 걸린다, `matchable == false` 규칙은 걸리지 않는다, 같은 입력은 같은 결과이고 결과가 어떤 규칙에서 나왔는지 담는다.
- **영어 단어 경계**: 합성 규칙의 영어 표현 `drug`가 `drug`·`a drug test`·`DRUG.`에는 걸리고 `drugstore`·`undrugged`에는 걸리지 않는다, `UV차단`에서 `UV`가 걸리고 `UVA`·`guv`에는 걸리지 않는다, 여러 단어 표현(`anti-aging`·`stem cell`)이 공백이 한 칸 또는 여러 칸이어도 걸린다.
- 예외: 규칙 자신의 `exceptions` 문구 안의 표현은 걸리지 않는다, `exception_refs`가 가리키는 규칙의 `terms_ko`(합성 규칙)가 포함된 구간은 걸리지 않는다, 예외 구간 밖의 같은 표현은 여전히 걸린다.
- `check_plan_fields`: `title` 필드의 금지 표현이 걸린다(제목도 검사 대상), 여러 필드 결과가 필드 이름별로 나뉜다, 결과에 `CLAIM_CHECK_DISCLAIMER`가 있다.
- 로더: 없는 파일→`CLAIM_RULES_UNREADABLE`, 깨진 YAML→`CLAIM_RULES_UNREADABLE`, 형식 오류→`CLAIM_RULES_INVALID`. 합성 임시 파일만 쓴다.
- 실제 `config/claim_rules.yaml`을 읽는 테스트 1개: 로더가 통과하고 모든 규칙에 `source_page`가 있으며 `rule_type`이 세 종류 안이고 `source.file_sha256`이 `docs/CONTRACTS.md`에 적힌 PDF 해시와 같다(**규칙의 개수나 표현을 단언하지 않는다**).
- `SkinType`·`SkinConcern`의 값 이름 집합이 ADR-012 후속 결정 5의 목록과 같다.
- `domain`이 `yaml`을 import하지 않는다(`tests/test_architecture.py` 통과).

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

- 규칙의 내용(금지 표현, 쪽 번호, 영어 대응어)을 바꾸거나 더하거나 번역하지 마라. 이유: 조언 세션이 원문과 대조해 확정한 본문이다. "확정된 규칙" 절이 비어 있으면 `blocked`.
- 영어 표현을 부분 문자열로 비교하지 마라. 이유: `drug`가 `drugstore`에 걸린다(조언 세션 검토).
- `requires_substantiation`을 차단 판정으로 만들지 마라. 이유: 실증자료를 확인할 방법이 없다(ADR-014).
- 안내서 원문(PDF·본문 전체)을 저장소에 복사하지 마라. 이유: 쪽 번호와 옮긴 표현만 남긴다.
- `applies_to`의 `status`를 바꾸지 마라. 이유: 값은 조언 세션이 승인한 것이다.
- 이 검사 결과를 "법적 판단"이라고 표현하지 마라. 이유: 안내서는 법적 효력이 없고 참고용이다(3쪽). 결과에는 `CLAIM_CHECK_DISCLAIMER`가 붙는다.
- TikTok EU 광고·글로벌 소재를 위반으로 표시하는 코드를 만들지 마라. 이유: 규칙은 국내 표시·광고 기준이고 경쟁 소재에는 관찰만 한다(ADR-014).
