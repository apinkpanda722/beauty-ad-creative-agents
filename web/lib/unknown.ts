// Keep the established check-detail wording, separate from the compact review badge.
export const unknownNames: Record<string, string> = {
  CERT_REQUIRED_UNVERIFIED: "인증 연결 없음",
  EFFICACY_UNKNOWN: "효능 근거 연결 없음",
  EFFICACY_UNSUPPORTED: "효능 근거가 뒷받침하지 않음",
};
const reasonNames = { ...unknownNames, CERT_REQUIRED_UNVERIFIED: "인증 자료 연결 없음" } as Record<string, string>;
export const unknownExplanation = "코드 검사가 확인하지 못한 항목의 수입니다. 실패가 아니라 근거가 연결되지 않아 확인이 필요한 항목입니다.";

export function unknownReasons(codes: Record<string, number>, count: number): string {
  if (count === 0) return "";
  const sorted = Object.keys(codes).sort((a, b) => codes[b] - codes[a] || (a < b ? -1 : a > b ? 1 : 0));
  const reasons = sorted.slice(0, 2).map(code => Object.hasOwn(reasonNames, code) ? reasonNames[code] : code);
  if (sorted.length > 2) reasons.push(`외 ${sorted.length - 2}종`);
  return reasons.join(" · ");
}
