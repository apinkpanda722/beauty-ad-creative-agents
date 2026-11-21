"use client";
import { createContext, useContext, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, postFeedback } from "../../lib/api";
import { Button } from "../ui";
type Session = {
  saved: Set<string>; pending: Set<string>;
  begin: (key: string) => boolean; finish: (key: string, saved: boolean) => void;
};
const FeedbackContext = createContext<Session | null>(null);
export function FeedbackSession({ children }: { children: ReactNode }) {
  const [saved, setSaved] = useState(new Set<string>());
  const [pending, setPending] = useState(new Set<string>());
  const locks = useRef(new Set<string>());
  return <FeedbackContext.Provider value={{ saved, pending,
    begin(key) {
      if (locks.current.has(key) || saved.has(key)) return false;
      locks.current.add(key); setPending(previous => new Set(previous).add(key)); return true;
    },
    finish(key, success) {
      locks.current.delete(key);
      setPending(previous => { const next = new Set(previous); next.delete(key); return next; });
      if (success) setSaved(previous => new Set(previous).add(key));
    },
  }}>{children}</FeedbackContext.Provider>;
}
export function FeedbackBar({ tenantId, planId }: { tenantId: string; planId: string | null }) {
  const session = useContext(FeedbackContext);
  const key = JSON.stringify([tenantId, planId]);
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const isSaved = saved || session?.saved.has(key);
  const isPending = pending || session?.pending.has(key);
  if (!planId) return null;
  async function submit(decision: "approved" | "rejected") {
    if (!planId || lock.current || isSaved || (decision === "rejected" && !reason.trim())) return;
    if (session && !session.begin(key)) return;
    lock.current = true; setPending(true); setError(null);
    let success = false;
    try { await postFeedback({ tenantId, planId, decision, reason }); success = true; setSaved(true); }
    catch (error) { setError(error instanceof ApiError ? error.code ?? `HTTP_${error.status}` : "피드백을 저장하지 못했습니다"); }
    finally { lock.current = false; setPending(false); session?.finish(key, success); }
  }
  return <section className="gs-feedback-bar" aria-label="기획안 피드백">{isSaved ? <p role="status">저장했습니다</p> : <>
    <label>피드백 사유<textarea value={reason} disabled={isPending} onChange={event => setReason(event.target.value)} placeholder="반려할 때는 사유를 입력하세요" /></label>
    <div className="gs-feedback-actions"><Button disabled={isPending} onClick={() => void submit("approved")}>승인</Button><Button variant="secondary" disabled={isPending || !reason.trim()} onClick={() => void submit("rejected")}>반려</Button>{isPending && <small role="status">저장 중입니다.</small>}</div>
    {error && <p role="alert">{error}</p>}
  </>}</section>;
}
