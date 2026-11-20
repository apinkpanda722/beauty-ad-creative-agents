"use client";

import { useEffect, useReducer, useRef, useState } from "react";
import { ApiError, postChatAsk } from "../lib/api";
import { examples } from "../lib/examples";
import { initialState, reducer } from "../lib/reducer";
import type { Action, Turn } from "../lib/reducer";
import type { Workspace } from "../lib/types";
import { TurnView } from "./TurnView";
import { WorkspacePicker } from "./WorkspacePicker";
import { CommandTenantContext } from "./CommandSlot";
import { FeedbackSession } from "./FeedbackBar";

export function Chat({ workspaces, imageEnabled }: { workspaces: Workspace[]; imageEnabled: boolean }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [message, setMessage] = useState("");
  const [withImage, setWithImage] = useState(true);
  const controller = useRef<AbortController | null>(null);
  const composing = useRef(false);
  const busy = state.activeTurnId !== null;
  useEffect(() => () => { controller.current?.abort(); controller.current = null; }, []);

  async function run(turn: Turn, tenantId: string) {
    const request = new AbortController();
    controller.current = request;
    const current = () => controller.current === request && !request.signal.aborted;
    try {
      const response = await postChatAsk({ tenantId, message: turn.message,
        ...(turn.threadId ? { threadId: turn.threadId } : {}),
        ...(turn.claimChoice ? { claimChoice: turn.claimChoice } : {}),
        ...(turn.withImage !== undefined ? { withImage: turn.withImage } : {}), signal: request.signal });
      if (!current()) return;
      dispatch({ type: "thread_received", turnId: turn.id, threadId: response.threadId });
      for await (const frame of response.events) {
        if (!current()) break;
        dispatch({ type: "stream_event", turnId: turn.id, frame });
      }
    } catch (error) {
      if (current()) dispatch({ type: "request_failed", turnId: turn.id,
        error: { code: error instanceof ApiError ? error.code ?? `HTTP_${error.status}` : "STREAM_ENDED_EARLY" } });
    } finally {
      if (current()) { controller.current = null; dispatch({ type: "stream_ended", turnId: turn.id }); }
    }
  }
  function start(action: Action) {
    if (controller.current || !state.tenantId) return;
    const next = reducer(state, action);
    const turn = next.turns.at(-1);
    if (!turn || next === state) return;
    dispatch(action);
    void run(turn, state.tenantId);
  }
  function send() {
    if (!message.trim() || busy || composing.current) return;
    start({ type: "request_started", message, ...(imageEnabled ? { withImage } : {}) });
    setMessage("");
  }
  return <CommandTenantContext.Provider value={state.tenantId}><FeedbackSession key={state.tenantId}>
    <WorkspacePicker workspaces={workspaces} value={state.tenantId} onChange={tenantId => {
      if (state.tenantId === tenantId) return;
      controller.current?.abort(); controller.current = null;
      dispatch({ type: "workspace_selected", tenantId }); setMessage(""); setWithImage(true);
    }} />
    <section className="conversation" aria-label="대화">
      {state.turns.map(turn => <TurnView key={turn.id} turn={turn} busy={busy}
        onChoice={(choice, label) => start({ type: "choice_submitted", turnId: turn.id, choice, label })}
        onCancel={() => dispatch({ type: "stopped", turnId: turn.id })}
        onRetry={() => start({ type: "retry_requested", turnId: turn.id })} />)}
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
