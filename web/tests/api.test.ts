import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, postAsk } from "../lib/api";
import type { ClaimChoice } from "../lib/types";

afterEach(() => vi.unstubAllGlobals());

function fakeFetch(response: Response) {
  const fetch = vi.fn().mockResolvedValue(response);
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("postAsk", () => {
  it("posts the exact default body without absent or null optional fields", async () => {
    const fetch = fakeFetch(new Response('event: token\ndata: {"text":"응답"}\n\n', {
      headers: { "X-Thread-Id": "demo:thread" },
    }));
    const result = await postAsk({ tenantId: "demo", message: "synthetic" });
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Tenant-Id": "demo" },
      body: JSON.stringify({ message: "synthetic", with_image: false }),
    });
    expect(result.threadId).toBe("demo:thread");
    expect(await Array.fromAsync(result.events)).toEqual([
      { event: "token", data: { text: "응답" } },
    ]);
  });

  it("passes optional request fields and abort signal exactly", async () => {
    const fetch = fakeFetch(new Response(""));
    const signal = new AbortController().signal;
    const choice: ClaimChoice = {
      mode: "selected", claims: ["hydration"], requested_claim: "hydration",
    };
    const result = await postAsk({
      tenantId: "demo", message: "synthetic", threadId: "demo:thread",
      claimChoice: choice, withImage: true, signal,
    });
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Tenant-Id": "demo" },
      body: JSON.stringify({
        message: "synthetic", with_image: true, thread_id: "demo:thread", claim_choice: choice,
      }),
      signal,
    });
    expect(result.threadId).toBeNull();
  });

  it.each([
    [403, '{"detail":"TENANT_INVALID"}', "TENANT_INVALID"],
    [422, '{"detail":[{"type":"missing"}]}', null],
    [500, "not JSON", null],
    [500, "null", null],
    [500, "{}", null],
    [201, '{"detail":"UNEXPECTED_STATUS"}', "UNEXPECTED_STATUS"],
  ])("rejects HTTP %i with only a string detail as code", async (status, body, code) => {
    fakeFetch(new Response(body, { status }));
    let caught: unknown;
    try {
      await postAsk({ tenantId: "demo", message: "synthetic" });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ApiError);
    expect(caught).toMatchObject({ status, code });
  });

  it("propagates fetch cancellation", async () => {
    const error = new DOMException("Aborted", "AbortError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
    await expect(postAsk({ tenantId: "demo", message: "synthetic" })).rejects.toBe(error);
  });
});
