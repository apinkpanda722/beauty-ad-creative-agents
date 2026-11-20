import type { TurnError } from "../lib/reducer";
const descriptions: Record<string, string> = {
  TENANT_CONTEXT_MISSING: "작업 공간을 선택해 주세요",
  TENANT_NOT_ALLOWED: "허용되지 않은 작업 공간입니다",
  TENANT_MISMATCH: "대화와 작업 공간이 일치하지 않습니다",
  WORKSPACE_MISSING: "작업 공간 정보가 없습니다",
  IMAGE_DISABLED: "시안 이미지 생성이 비활성화되어 있습니다",
  ASK_INPUT_INVALID: "요청 입력을 확인해 주세요",
  AGENT_INTERNAL_ERROR: "요청 처리 중 오류가 발생했습니다",
  CLAIM_CHOICE_INVALID: "효능 선택을 확인해 주세요",
  STREAM_ENDED_EARLY: "응답이 중간에 끊겼습니다",
};
export function Notice({ text, error, stopped, onRetry, disabled }: {
  text?: string; error?: TurnError | null; stopped?: boolean; onRetry?: () => void; disabled?: boolean;
}) {
  return <aside className={`notice${error ? " error" : ""}`} aria-live="polite">
    {text && <p>{text}</p>}
    {stopped && <p>중단했습니다. 새 요청을 입력하세요.</p>}
    {error && <>
      <p><code>{error.code}</code>{descriptions[error.code] && ` · ${descriptions[error.code]}`}</p>
      {error.detail && <p>{error.detail}</p>}
      {error.error_code && <p><code>{error.error_code}</code>{descriptions[error.error_code] && ` · ${descriptions[error.error_code]}`}</p>}
      <button type="button" disabled={disabled} onClick={onRetry}>다시 시도</button>
    </>}
  </aside>;
}
