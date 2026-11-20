export function publishedDate(value: string | null): string {
  return value === null ? "게시일 정보 없음" : /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : value;
}
