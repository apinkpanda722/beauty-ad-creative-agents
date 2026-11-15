# 역량 질문 (v1, 2026-11-15 동결)

> 상태: **v1, 2026-11-15 동결**(사용자 승인). 이전 판은 2026-11-12 초안(사용자 검토 반영: CQ-06·07 합침, CQ-13~15 추가, 가격 반영으로 CQ-16 추가)이다. 온톨로지가 **답할 수 있어야 하는 질문**이다. 이 목록이 노드·관계 설계의 입력이자 완성 기준이다(**모든 질문이 1~4홉으로 답해져야 한다**). 동결 뒤에는 실험 E3의 관계형 질문 세트로 쓴다.
>
> **홉의 정의**: 홉은 노드 사이를 건너는 관계 수이고, 속성 필터(집행 주체, 게시 시각, 가격 범위, 지표 백분위 등)는 세지 않는다. 기준을 3홉에서 4홉으로 바꾼 것은 관계를 하나씩 센 결과 CQ-05·13·14·16이 4홉이었기 때문이다(ADR-012 후속 결정).

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
| CQ-09 | (TikTok 한정) 브랜드가 직접 집행한 광고와 판매처 광고는 훅이 다른가 | 2 | Creative(집행 주체 속성)→USES_HOOK→Hook | 리서치, E3 |
| CQ-10 | 이 기획안이 주장한 효능은 대상 제품의 성분·인증으로 뒷받침되는가 | 1 | Product→CONTAINS→Ingredient→HAS_EFFICACY→Efficacy, Product→CERTIFIED_AS | 평가(코드 검사) |
| CQ-11 | 이 기획안의 효능 표현에 걸리는 표현 규칙이 있는가 | 1 | ClaimRule→APPLIES_TO→Efficacy 또는 SkinConcern(또는 Category) | 평가(코드 검사) |
| CQ-12 | 이 작업 공간(브랜드)이 최근 반려한 기획의 패턴은 | 2 | Feedback(tenant_id)→ABOUT→Hook·Efficacy | 기획(피드백 메모리) |
| CQ-13 | 우리 제품과 핵심 성분을 공유하는 경쟁 제품은 무엇이고, 그 제품들은 광고에서 어떤 효능을 앞세우나 | 1+2 | Product→CONTAINS→Ingredient←CONTAINS←Product(경쟁)←PROMOTES←Creative→CLAIMS→Efficacy | 리서치, 기획, E3 |
| CQ-14 | 우리 제품만 가진 성분·인증 중, 경쟁 광고가 아무도 앞세우지 않는 효능은 | 1+2 | Product→CONTAINS→Ingredient→HAS_EFFICACY→Efficacy, 경쟁 제품의 Creative→CLAIMS→Efficacy와 차집합 | 기획, 평가(차별성) |
| CQ-15 | 시카 계열 성분(별칭 포함)을 앞세운 광고가 최근 3개월 사이 늘었나 | 1+2 | IngredientAlias→ALIAS_OF→Ingredient←CONTAINS←Product←PROMOTES←Creative(게시 시각) | 리서치, E3 |
| CQ-16 | 우리 제품과 같은 가격대(단위당 정가 기준)의 경쟁 제품은 무엇이고, 그 제품들의 광고는 어떤 효능과 훅을 쓰나 | 1+2 | Product(단위당 가격 범위)←같은 Category→Product(경쟁)←PROMOTES←Creative→CLAIMS/USES_HOOK | 리서치, 기획, E3 |

한계와 조건 (2026-11-15 동결 시 정리):
- **CQ-01·02·04·05·10·14의 답은 성분→효능 연결(`HAS_EFFICACY`)이 있는 범위에서만 나온다.** 이 연결의 출처는 (a) 식약처 기능성 고시 성분(미백·주름 개선·자외선 차단), (b) 진정·보습 등 그 밖의 효능은 출처(문헌·성분 데이터베이스 등)를 붙인 소규모 수기 표로 한정한다(ADR-012 후속 결정). 출처 없는 연결은 만들지 않으므로 범위가 제한적이고, 연결이 없는 성분·효능은 "답 없음"이 아니라 "근거 연결 없음"으로 보고한다.
- **CQ-03·10·11은 식약처 품목과 제품의 연결 규칙(제품명 일치)이 정해져야 답할 수 있다.** 규칙은 `mfds-source`·`product-records` step에서 정하고, 답과 함께 **커버리지**(식약처 품목과 연결된 제품 수 ÷ 대상 제품 수)를 보고한다. 연결되지 않은 제품은 "인증 없음"이 아니라 `unknown`이다(`docs/CONTRACTS.md` 식약처 절).
- **CQ-06**의 "상위·하위"는 `docs/EVAL.md`의 지표 정규화(채널 내 조회수 백분위, 게시 14일 이상)를 따르며, 조회수 값이 있는 소재에서만 나눈다. Instagram 소재에는 조회수 필드가 있으나 값이 비어 있는 소재가 섞여 있다(2026-11-15 읽기 전용 확인, 있음·없음만 확인). 출처 간 조회수는 직접 비교하지 않으며, TikTok은 조회수가 아니라 도달 구간이다(`docs/ARCHITECTURE.md`).
- **CQ-09는 TikTok 한정이다.** TikTok 분석분은 시드 표본이라 소규모다(2026-11-15 실측: `content_type@v1` 완료 221건, 제품 소재 분석(`hook@v1`) 92건). 집행 주체 분류는 `config/retailers.yaml`(사용자 확인 대기)에 의존한다. **사용자가 광고주를 분류한 뒤 `brand_direct`·`retailer` 중 한쪽의 소재 수가 30건 미만이면 CQ-09는 "표본 부족으로 방향만 제시"로 표시하고, 결론으로 쓰지 않는다.** **2026-11-15 분류 결과(훅·full 분석 결과가 있는 TikTok 소재 92건, 광고주 44곳): `brand_direct` 29건, `retailer` 26건, `unknown` 37건이다. 두 쪽 모두 30건 미만이므로 CQ-09는 "표본 부족으로 방향만 제시"이며 결론으로 쓰지 않는다.** 분류는 사용자가 확인 대상 16곳을 채팅으로 답한 값과, 이름에 브랜드명·판매처 시드가 들어 있거나 이름이 숫자 ID·공백인 광고주에 대한 규칙 값이다.
- **2층 질문(CQ-04·05·06·08·13·14·15·16 중 `PROMOTES`를 거치는 것)은 YouTube·Instagram 소재에서만 제품에 연결된다.** TikTok 소재는 제목·캡션 필드가 비어 있어 `PROMOTES` 규칙(`docs/ARCHITECTURE.md`)으로 연결되지 않는다. **TikTok은 CQ-09와 분포 용도로만 쓰고, 제품 연결(`PROMOTES`)을 거치는 질문의 답은 YouTube·Instagram에서만 나온다.** `layer2-links`에서 YouTube·Instagram의 test 커버리지가 부족하면 그때 영상에서 제품을 식별하는 별도 추출을 사용자에게 제안한다. 토리든·넘버즈인은 제품 정보를 받지 못해 `PROMOTES` 커버리지에서 빠진다. `PROMOTES` 규칙은 dev 브랜드에서 다듬고 test 브랜드에서 커버리지를 보고한다. CQ-09는 `PROMOTES`를 거치지 않으므로 영향이 없다.
- **대표 단품 선정(2026-11-15 사용자 확정, 71개)의 근거는 약하다.** 광고 텍스트(YouTube·Instagram 제목·캡션)에서 이름이 확인되는 것은 31개뿐이고 나머지 40개는 공식몰 목록 순서로 채웠다. 선정은 브랜드×카테고리별 최대 2개이며 목록을 끝까지 보지 못한 몰이 있다. 이 때문에 제품 소재 중 `PROMOTES`가 이어지는 비율이 낮을 수 있고 2층 질문의 답이 작아질 수 있다.
- **CQ-12는 P4에서는 합성 데이터로만 검증하고, P5 피드백 메모리 이후 실데이터로 검증한다.**
- CQ-13·14는 "우리 제품"이 작업 공간(테넌트)의 브랜드 프로필에서 정해진다. CQ-15의 "최근"은 서버가 정한 기준일에서 계산한다.
- **`cq-verify`는 질문마다 "연결된 소재 수(`PROMOTES` 커버리지)"를 답과 함께 보고한다.** 소재가 제품에 연결되지 못하면(`PROMOTES`를 만들지 않음) 2층 질문의 답이 작아지므로, 답의 크기를 해석하려면 이 수가 필요하다.
- 이번 검토에서 나온 약점: CQ-06·09는 관계형 조인 한두 번으로도 답이 나온다. 그래프가 확실히 나은 질문은 별칭 경유(CQ-05·15), 3~4홉 경로(CQ-02는 3홉, CQ-05·13·14·16은 4홉), 규칙 상속(CQ-11), 차집합 비교(CQ-14)다.
