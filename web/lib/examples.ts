const serum = [
  { label: "정상", message: "보습을 내세운 세럼 광고 기획안 1안을 만들어 주세요." },
  { label: "되묻기 ②", message: "진정 효과를 내세운 세럼 광고 기획안 1안을 만들어 주세요." },
  { label: "되묻기 ③", message: "이 세럼의 광고 기획안 1안을 만들어 주세요." },
];
const sun = [
  { label: "정상", message: "자외선 차단을 내세운 선케어 광고 기획안 1안을 만들어 주세요." },
  { label: "되묻기 ②", message: "모공과 피지 관리를 내세운 선케어 광고 기획안 1안을 만들어 주세요." },
  { label: "되묻기 ③", message: "이 선세럼 제품의 광고 기획안 1안을 만들어 주세요." },
];
export const examples: Record<string, { label: string; message: string }[]> = {
  "test-isntree": serum, "dev-mixsoon": serum, "test-bojoseon": sun, "dev-cosrx": sun,
};
