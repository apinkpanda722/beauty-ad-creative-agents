import { parseSseStream } from "./sse";
import type { ApiErrorBody, ClaimChoice, SseFrame } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string | null) {
    super(code ?? `HTTP ${status}`);
    this.name = "ApiError";
  }
}

export async function postAsk(args: {
  tenantId: string;
  message: string;
  threadId?: string;
  claimChoice?: ClaimChoice;
  withImage?: boolean;
  signal?: AbortSignal;
}): Promise<{ threadId: string | null; events: AsyncGenerator<SseFrame> }> {
  const body = {
    message: args.message,
    with_image: args.withImage ?? false,
    ...(args.threadId !== undefined ? { thread_id: args.threadId } : {}),
    ...(args.claimChoice !== undefined ? { claim_choice: args.claimChoice } : {}),
  };
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Tenant-Id": args.tenantId },
    body: JSON.stringify(body),
    ...(args.signal !== undefined ? { signal: args.signal } : {}),
  });
  if (response.status !== 200) {
    let code: string | null = null;
    try {
      const error: ApiErrorBody | null = await response.json();
      if (typeof error?.detail === "string") code = error.detail;
    } catch {
      // HTTP failures may contain non-JSON bodies.
    }
    throw new ApiError(response.status, code);
  }
  const stream = response.body;
  async function* events(): AsyncGenerator<SseFrame> {
    if (!stream) return;
    // The same-origin server owns this wire contract; the parser only checks framing.
    for await (const frame of parseSseStream(stream)) yield frame as SseFrame;
  }
  return { threadId: response.headers.get("X-Thread-Id"), events: events() };
}

export async function getWorkspaces(): Promise<import("./types").WorkspacesResponse> {
  const response = await fetch("/api/workspaces");
  if (!response.ok) throw new ApiError(response.status, null);
  return response.json();
}

// Keep postAsk's existing default-body contract. The chat omits with_image when
// the server disables images, while an explicit false still means unchecked.
export async function postChatAsk(
  args: Parameters<typeof postAsk>[0],
): ReturnType<typeof postAsk> {
  if (args.withImage !== undefined) return postAsk(args);
  const response = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Tenant-Id": args.tenantId },
    body: JSON.stringify({
      message: args.message,
      ...(args.threadId !== undefined ? { thread_id: args.threadId } : {}),
      ...(args.claimChoice !== undefined ? { claim_choice: args.claimChoice } : {}),
    }),
    ...(args.signal !== undefined ? { signal: args.signal } : {}),
  });
  if (response.status !== 200) {
    let code: string | null = null;
    try {
      const error: ApiErrorBody | null = await response.json();
      if (typeof error?.detail === "string") code = error.detail;
    } catch {
      // HTTP failures may contain non-JSON bodies.
    }
    throw new ApiError(response.status, code);
  }
  const stream = response.body;
  async function* events(): AsyncGenerator<SseFrame> {
    if (!stream) return;
    for await (const frame of parseSseStream(stream)) yield frame as SseFrame;
  }
  return { threadId: response.headers.get("X-Thread-Id"), events: events() };
}
