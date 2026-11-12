# 역량 질문 (초안 v0)

> 상태: 초안 v1 (2026-11-12, 사용자 검토 반영: CQ-06·07 합침, CQ-13~15 추가, 가격 반영으로 CQ-16 추가). 온톨로지가 **답할 수 있어야 하는 질문**이다. 이 목록이 노드·관계 설계의 입력이자 완성 기준이다(모든 질문이 1~3홉으로 답해져야 한다). M1 그래프 적재 전에 동결하고, 동결 뒤에는 실험 E3의 관계형 질문 세트로 쓴다.

작성 원칙:
- 마케터가 실제로 기획 전에 묻는 질문의 형태로 쓴다. 근거로 삼은 공개 자료나 사례를 적는다.
- 1층(제품 지식)만, 2층(광고 관찰)만, 두 층을 함께 써야 답하는 질문을 섞는다. 두 층을 함께 써야 하는 질문이 이 설계의 이유다.
- 1인 작성이라 그래프에 유리한 질문만 고를 위험이 있다. 실험 E3에는 단순 검색형 질문 10개를 따로 둔다(`docs/EVAL.md`).

| ID | 질문 | 쓰는 층 | 탐색 경로(초안) | 쓰이는 곳 |
|---|---|---|---|---|
| CQ-01 | 진정 효능 근거가 있는 성분이 든 세럼은 무엇인가 | 1 | Product→CONTAINS→Ingredient→HAS_EFFICACY→Efficacy | 리서치 |
| CQ-02 | 트러블 고민에 맞는 마스크팩과 그 핵심 성분은 | 1 | SkinConcern←ADDRESSES←Efficacy←HAS_EFFICACY←Ingredient←CONTAINS←Product | 리서치 |
| CQ-03 | 미백 기능성 인증이 있는 제품은 무엇인가 | 1 | Product→CERTIFIED_AS→FunctionalCert | 평가 |
| CQ-04 | 진정을 주장한 세럼 광고 중, 진정 근거 성분이 실제로 든 제품의 광고는 몇 건인가 | 1+2 | Creative→CLAIMS→Efficacy, Creative→PROMOTES→Product→CONTAINS→Ingredient→HAS_EFFICACY→Efficacy | 리서치, E3 |
| CQ-05 | 병풀(별칭 포함) 성분 제품의 광고가 가장 많이 앞세우는 효능은 | 1+2 | IngredientAlias→ALIAS_OF→Ingredient←CONTAINS←Product←PROMOTES←Creative→CLAIMS→Efficacy | 리서치, E3 |
| CQ-06 | 카테고리별로 조회수 상위 소재가 쓰는 훅은 하위 소재와 무엇이 다르고, 그 훅이 다른 카테고리에서도 쓰이는가 (예: 마스크팩 상위 훅이 세럼에서도 쓰이나) | 2 | Category←IN_CATEGORY←Product←PROMOTES←Creative→USES_HOOK→Hook (지표 백분위로 나누고 카테고리끼리 비교) | 리서치, E3 |
| CQ-08 | 건성 피부용 제품의 광고에서 자주 쓰는 앵글과 포맷은 | 1+2 | SkinType←SUITS←Product←PROMOTES←Creative→HAS_ANGLE/HAS_FORMAT | 리서치, E3 |
| CQ-09 | 브랜드가 직접 집행한 광고와 판매처 광고는 훅이 다른가 | 2 | Creative(집행 주체 속성)→USES_HOOK→Hook | 리서치, E3 |
| CQ-10 | 이 기획안이 주장한 효능은 대상 제품의 성분·인증으로 뒷받침되는가 | 1 | Product→CONTAINS→Ingredient→HAS_EFFICACY→Efficacy, Product→CERTIFIED_AS | 평가(코드 검사) |
| CQ-11 | 이 기획안의 효능 표현에 걸리는 표현 규칙이 있는가 | 1 | ClaimRule→APPLIES_TO→Efficacy | 평가(코드 검사) |
| CQ-12 | 이 작업 공간(브랜드)이 최근 반려한 기획의 패턴은 | 2 | Feedback(tenant_id)→ABOUT→Hook·Efficacy | 기획(피드백 메모리) |
| CQ-13 | 우리 제품과 핵심 성분을 공유하는 경쟁 제품은 무엇이고, 그 제품들은 광고에서 어떤 효능을 앞세우나 | 1+2 | Product→CONTAINS→Ingredient←CONTAINS←Product(경쟁)←PROMOTES←Creative→CLAIMS→Efficacy | 리서치, 기획, E3 |
| CQ-14 | 우리 제품만 가진 성분·인증 중, 경쟁 광고가 아무도 앞세우지 않는 효능은 | 1+2 | Product→CONTAINS→Ingredient→HAS_EFFICACY→Efficacy, 경쟁 제품의 Creative→CLAIMS→Efficacy와 차집합 | 기획, 평가(차별성) |
| CQ-15 | 시카 계열 성분(별칭 포함)을 앞세운 광고가 최근 3개월 사이 늘었나 | 1+2 | IngredientAlias→ALIAS_OF→Ingredient←CONTAINS←Product←PROMOTES←Creative(게시 시각) | 리서치, E3 |
| CQ-16 | 우리 제품과 같은 가격대(단위당 정가 기준)의 경쟁 제품은 무엇이고, 그 제품들의 광고는 어떤 효능과 훅을 쓰나 | 1+2 | Product(단위당 가격 범위)←같은 Category→Product(경쟁)←PROMOTES←Creative→CLAIMS/USES_HOOK | 리서치, 기획, E3 |

미정:
- CQ-03, CQ-10, CQ-11은 제품 정보 출처와 규정 원문이 정해져야 답할 수 있다.
- CQ-06의 "상위·하위"는 `docs/EVAL.md`의 지표 정규화를 따른다.
- CQ-13·14는 "우리 제품"이 작업 공간(테넌트)의 브랜드 프로필에서 정해진다. CQ-15의 "최근"은 서버가 정한 기준일에서 계산한다.
- 이번 검토에서 나온 약점: CQ-06·09는 관계형 조인 한두 번으로도 답이 나온다. 그래프가 확실히 나은 질문은 별칭 경유(CQ-05·15), 3홉 이상 경로(CQ-02·13), 규칙 상속(CQ-11), 차집합 비교(CQ-14)다.
