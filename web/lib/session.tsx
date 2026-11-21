"use client";

import { createContext, useContext, useEffect, useReducer, useRef } from "react";
import type { ReactNode } from "react";
import { ApiError, postChatAsk } from "./api";
import { initialState, reducer } from "./reducer";
import type { Action, State, Turn } from "./reducer";

type Session = {
  state: State;
  start: (action: Action) => void;
  send: (message: string, withImage?: boolean) => void;
  cancel: (turnId: number) => void;
  retry: (turnId: number) => void;
  selectWorkspace: (tenantId: string | null) => void;
};
const SessionContext = createContext<Session | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const controller = useRef<AbortController | null>(null);
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
  function send(message: string, withImage?: boolean) {
    start({ type: "request_started", message, ...(withImage !== undefined ? { withImage } : {}) });
  }
  function cancel(turnId: number) { dispatch({ type: "stopped", turnId }); }
  function retry(turnId: number) { start({ type: "retry_requested", turnId }); }
  function selectWorkspace(tenantId: string | null) {
    if (state.tenantId === tenantId) return;
    controller.current?.abort(); controller.current = null;
    dispatch({ type: "workspace_selected", tenantId });
  }
  return <SessionContext.Provider value={{ state, start, send, cancel, retry, selectWorkspace }}>{children}</SessionContext.Provider>;
}

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession requires SessionProvider");
  return session;
}
