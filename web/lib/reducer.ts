import type { ClaimChoice, Clarification, SseFrame, StepEvent, UiCommand } from "./types";

export type TurnStatus = "running" | "done" | "needs_choice" | "unavailable" | "error" | "stopped";
export type TurnError = Extract<SseFrame, { event: "error" }>["data"];
export type Turn = {
  id: number;
  tabId?: number;
  message: string;
  threadId: string | null;
  claimChoice?: ClaimChoice;
  choiceLabel?: string;
  withImage?: boolean;
  status: TurnStatus;
  stepEvents: StepEvent[];
  startedAt?: number;
  stepAt?: number[];
  tools: Extract<SseFrame, { event: "tool_start" }>["data"][];
  commands: UiCommand[];
  displayText: string;
  clarification: Clarification | null;
  unavailable: Extract<SseFrame, { event: "efficacy_unavailable" }>["data"] | null;
  error: TurnError | null;
  terminalReceived: boolean;
};
export type State = {
  tenantId: string | null;
  threadId: string | null;
  turns: Turn[];
  activeTurnId: number | null;
  nextTurnId: number;
  tabs?: { id: number; threadId: string | null }[];
  activeTabId?: number;
};
export type Action =
  | { type: "workspace_selected"; tenantId: string | null }
  | { type: "tab_created" }
  | { type: "tab_selected"; tabId: number }
  | { type: "tab_closed"; tabId: number }
  | { type: "request_started"; message: string; withImage?: boolean; at?: number }
  | { type: "thread_received"; turnId: number; threadId: string | null }
  | { type: "stream_event"; turnId: number; frame: SseFrame; at?: number }
  | { type: "stream_ended"; turnId: number }
  | { type: "request_failed"; turnId: number; error: TurnError }
  | { type: "choice_submitted"; turnId: number; choice: ClaimChoice; label: string }
  | { type: "stopped"; turnId: number }
  | { type: "retry_requested"; turnId: number };

export const initialState: State = { tenantId: null, threadId: null, turns: [], activeTurnId: null, nextTurnId: 1,
  tabs: [{ id: 1, threadId: null }], activeTabId: 1 };

function tabsOf(state: State) { return state.tabs ?? [{ id: 1, threadId: state.threadId }]; }
function append(state: State, request: Pick<Turn, "message" | "withImage" | "claimChoice" | "choiceLabel">, at?: number, tabId = state.activeTabId ?? 1): State {
  if (!state.tenantId || state.activeTurnId !== null) return state;
  const tab = tabsOf(state).find(tab => tab.id === tabId);
  if (!tab) return state;
  const turn: Turn = {
    ...request, ...(at !== undefined ? { startedAt: at } : {}), id: state.nextTurnId, tabId, threadId: tab.threadId,
    status: "running", stepEvents: [], tools: [], commands: [], displayText: "",
    clarification: null, unavailable: null, error: null, terminalReceived: false,
  };
  return { ...state, nextTurnId: state.nextTurnId + 1, activeTurnId: turn.id,
    turns: [...state.turns.map(t => (t.tabId ?? 1) === tabId && t.status === "needs_choice" ? { ...t, status: "done" as const } : t), turn] };
}
function update(state: State, id: number, change: (turn: Turn) => Turn): State {
  return { ...state, turns: state.turns.map(turn => turn.id === id ? change(turn) : turn) };
}
function event(turn: Turn, frame: SseFrame, at?: number): Turn {
  switch (frame.event) {
    case "step": {
      const next = { ...turn, stepEvents: [...turn.stepEvents, frame.data] };
      // Partial timing cannot be indexed safely against the event list.
      if (at !== undefined && (turn.stepAt?.length ?? 0) === turn.stepEvents.length) next.stepAt = [...(turn.stepAt ?? []), at];
      else delete next.stepAt;
      return next;
    }
    case "tool_start": return { ...turn, tools: [...turn.tools, frame.data] };
    case "ui_command": return { ...turn, commands: [...turn.commands, frame.data] };
    case "needs_clarification": return { ...turn, status: "needs_choice", clarification: frame.data, displayText: "", terminalReceived: true };
    case "efficacy_unavailable": return { ...turn, status: "unavailable", unavailable: frame.data, displayText: "", terminalReceived: true };
    case "error": return { ...turn, status: "error", error: frame.data, terminalReceived: true };
    case "token": return { ...turn, terminalReceived: true,
      status: turn.status === "running" ? "done" : turn.status,
      displayText: turn.clarification || turn.unavailable ? "" : frame.data.display_text ?? frame.data.text };
  }
}
export function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "workspace_selected":
      return action.tenantId === state.tenantId ? state : { ...initialState, nextTurnId: state.nextTurnId, tenantId: action.tenantId };
    case "tab_created": {
      if (state.activeTurnId !== null) return state;
      const tabs = tabsOf(state);
      const id = Math.max(...tabs.map(tab => tab.id)) + 1;
      return { ...state, tabs: [...tabs, { id, threadId: null }], activeTabId: id, threadId: null };
    }
    case "tab_selected": {
      const tab = tabsOf(state).find(tab => tab.id === action.tabId);
      return tab ? { ...state, activeTabId: tab.id, threadId: tab.threadId } : state;
    }
    case "tab_closed": {
      const current = tabsOf(state);
      if (!current.some(tab => tab.id === action.tabId) || state.turns.some(turn => turn.id === state.activeTurnId && (turn.tabId ?? 1) === action.tabId)) return state;
      const remaining = current.filter(tab => tab.id !== action.tabId);
      const tabs = remaining.length ? remaining : [{ id: Math.max(...current.map(tab => tab.id)) + 1, threadId: null }];
      const active = tabs.find(tab => tab.id === (state.activeTabId ?? 1)) ?? tabs[0];
      return { ...state, tabs, activeTabId: active.id, threadId: active.threadId,
        turns: state.turns.filter(turn => (turn.tabId ?? 1) !== action.tabId) };
    }
    case "request_started": return append(state, { message: action.message, withImage: action.withImage }, action.at);
    case "choice_submitted": {
      const source = state.turns.find(t => t.id === action.turnId && t.status === "needs_choice");
      return source ? append(state, { message: source.message, withImage: source.withImage, claimChoice: action.choice, choiceLabel: action.label }, undefined, source.tabId ?? 1) : state;
    }
    case "retry_requested": {
      const source = state.turns.find(t => t.id === action.turnId && t.status === "error");
      if (!source) return state;
      const request = { ...source };
      delete request.startedAt;
      delete request.stepAt;
      return append(state, request, undefined, source.tabId ?? 1);
    }
    case "stopped": return update(state, action.turnId, t => t.status === "needs_choice" ? { ...t, status: "stopped", clarification: null } : t);
    case "thread_received": {
      if (state.activeTurnId !== action.turnId || !action.threadId) return state;
      const source = state.turns.find(turn => turn.id === action.turnId);
      if (!source) return state;
      const tabId = source.tabId ?? 1;
      // The first response owns its tab's thread, regardless of current selection.
      const tabs = tabsOf(state).map(tab => tab.id === tabId ? { ...tab, threadId: tab.threadId ?? action.threadId } : tab);
      const threadId = tabs.find(tab => tab.id === tabId)?.threadId ?? null;
      return update({ ...state, tabs, threadId: tabs.find(tab => tab.id === (state.activeTabId ?? 1))?.threadId ?? null }, action.turnId, t => ({ ...t, threadId }));
    }
    case "stream_event":
      return state.activeTurnId === action.turnId ? update(state, action.turnId, t => event(t, action.frame, action.at)) : state;
    case "request_failed":
      return state.activeTurnId === action.turnId ? update(state, action.turnId, t => ({ ...t, status: "error", error: action.error, terminalReceived: true })) : state;
    case "stream_ended":
      if (state.activeTurnId !== action.turnId) return state;
      return update({ ...state, activeTurnId: null }, action.turnId, t => t.terminalReceived ? t : { ...t, status: "error", error: { code: "STREAM_ENDED_EARLY" } });
  }
}
