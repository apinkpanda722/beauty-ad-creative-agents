"use client";

import { useRef, useState } from "react";
import { examples } from "../lib/examples";
import { useSession } from "../lib/session";
import type { Workspace } from "../lib/types";
import { TurnView } from "./TurnView";
import { WorkspacePicker } from "./WorkspacePicker";
import { CommandTenantContext } from "./CommandSlot";
import { FeedbackSession } from "./FeedbackBar";

export function Chat({ workspaces, imageEnabled, onWorkspaceChange }: { workspaces: Workspace[]; imageEnabled: boolean; onWorkspaceChange?: (tenantId: string | null) => void }) {
  const { state, start, send: sendRequest, cancel, retry, selectWorkspace } = useSession();
  const [message, setMessage] = useState("");
  const [withImage, setWithImage] = useState(true);
  const composing = useRef(false);
  const busy = state.activeTurnId !== null;
  function send() {
    if (!message.trim() || busy || composing.current) return;
    sendRequest(message, imageEnabled ? withImage : undefined);
    setMessage("");
  }
  return <CommandTenantContext.Provider value={state.tenantId}><FeedbackSession key={state.tenantId}>
    <WorkspacePicker workspaces={workspaces} value={state.tenantId} onChange={tenantId => {
      if (state.tenantId === tenantId) return;
      selectWorkspace(tenantId); setMessage(""); setWithImage(true);
      onWorkspaceChange?.(tenantId);
    }} />
    <section className="conversation" aria-label="대화">
      {state.turns.map(turn => <TurnView key={turn.id} turn={turn} busy={busy}
        onChoice={(choice, label) => start({ type: "choice_submitted", turnId: turn.id, choice, label })}
        onCancel={() => cancel(turn.id)}
        onRetry={() => retry(turn.id)} />)}
    </section>
    <form className="composer" onSubmit={e => { e.preventDefault(); send(); }}>
      <div className="examples" aria-label="예시 요청">
        {(examples[state.tenantId ?? ""] ?? []).map(example => <button type="button" key={example.label}
          disabled={busy} onClick={() => setMessage(example.message)}>{example.label}</button>)}
      </div>
      <label htmlFor="request">요청</label>
      <textarea id="request" rows={3} maxLength={2000} value={message} disabled={!state.tenantId || busy}
        placeholder="광고 기획 요청을 입력하세요" onChange={e => setMessage(e.target.value.slice(0, 2000))}
        onCompositionStart={() => { composing.current = true; }} onCompositionEnd={() => { composing.current = false; }}
        onKeyDown={e => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && !composing.current && e.keyCode !== 229) {
            e.preventDefault(); send();
          }
        }} />
      <div className="composer-actions">
        <small>{message.length}/2000 · Enter 전송, Shift+Enter 줄바꿈</small>
        {imageEnabled && <label><input type="checkbox" checked={withImage} disabled={busy || !state.tenantId}
          onChange={e => setWithImage(e.target.checked)} />시안 이미지 포함</label>}
        <button type="submit" disabled={!state.tenantId || busy || !message.trim()}>전송</button>
      </div>
    </form>
  </FeedbackSession></CommandTenantContext.Provider>;
}
