import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, getPlanImage, getSavedPlans, postAsk } from "../lib/api";
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

describe("saved plan API", () => {
  it("returns the plans array and sends the workspace header", async () => {
    const plans = [{ plan_id: "synthetic", title: "합성 기획", has_image: false }];
    const fetch = fakeFetch(Response.json({ plans }));
    expect(await getSavedPlans("workspace-a")).toEqual(plans);
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/plans", { headers: { "X-Tenant-Id": "workspace-a" } });
  });
  it("returns an empty list when plans is absent", async () => {
    fakeFetch(Response.json({}));
    expect(await getSavedPlans("workspace-a")).toEqual([]);
  });
  it("preserves the list error status and code", async () => {
    fakeFetch(Response.json({ detail: "TENANT_INVALID" }, { status: 403 }));
    const result = getSavedPlans("workspace-a");
    await expect(result).rejects.toBeInstanceOf(ApiError);
    await expect(result).rejects.toMatchObject({ status: 403, code: "TENANT_INVALID" });
  });
  it("returns image bytes as a Blob and encodes the complete plan ID", async () => {
    const fetch = fakeFetch(new Response("synthetic image", { headers: { "Content-Type": "image/png" } }));
    const blob = await getPlanImage("workspace-a", "synthetic/id ?#");
    expect(blob).toBeInstanceOf(Blob);
    expect(await blob.text()).toBe("synthetic image");
    expect(blob.type).toBe("image/png");
    expect(fetch).toHaveBeenCalledExactlyOnceWith("/api/plans/synthetic%2Fid%20%3F%23/image", { headers: { "X-Tenant-Id": "workspace-a" } });
  });
  it.each(["PLAN_NOT_FOUND", "DESIGN_NOT_FOUND"])("preserves image error %s", async code => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ detail: code }, { status: 404 })));
    vi.stubGlobal("fetch", fetch);
    await expect(getPlanImage("workspace-a", "synthetic")).rejects.toBeInstanceOf(ApiError);
    await expect(getPlanImage("workspace-a", "synthetic")).rejects.toMatchObject({ status: 404, code });
  });
});
