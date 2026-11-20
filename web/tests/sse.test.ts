import { describe, expect, it } from "vitest";
import { parseSseStream } from "../lib/sse";

function stream(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(chunk));
      controller.close();
    },
  });
}

async function parse(text: string, cuts: number[] = []) {
  const bytes = new TextEncoder().encode(text);
  const edges = [0, ...cuts, bytes.length];
  const chunks = edges.slice(1).map((end, i) => bytes.slice(edges[i], end));
  return Array.fromAsync(parseSseStream(stream(chunks)));
}

describe("parseSseStream", () => {
  it("handles every byte boundary including split Korean characters", async () => {
    const text = 'event: token\ndata: {"text":"한글 응답"}\n\nevent: step\ndata: {}\n\n';
    const expected = [
      { event: "token", data: { text: "한글 응답" } },
      { event: "step", data: {} },
    ];
    const length = new TextEncoder().encode(text).length;
    for (let cut = 1; cut < length; cut++) {
      expect(await parse(text, [cut])).toEqual(expected);
    }
    expect(await parse(text, Array.from({ length: length - 1 }, (_, i) => i + 1)))
      .toEqual(expected);
  });

  it("handles CRLF, field whitespace and multiline data", async () => {
    expect(await parse(': comment\r\nevent:  token \r\ndata:   {"text":\r\ndata: "응답"}\r\n\r\n'))
      .toEqual([{ event: "token", data: { text: "응답" } }]);
  });

  it.each(["[]", "null", '"text"', "42", "true"])("skips non-object JSON %s", async (json) => {
    expect(await parse(`event: token\ndata: ${json}\n\nevent: token\ndata: {}\n\n`))
      .toEqual([{ event: "token", data: {} }]);
  });

  it.each(["", "\n", "\r\n"])("flushes an end frame without a blank line (%j)", async (ending) => {
    expect(await parse('event:token\ndata:{"text":"끝"}' + ending))
      .toEqual([{ event: "token", data: { text: "끝" } }]);
  });

  it("requires both event and data and resets between frames", async () => {
    expect(await parse('event: token\n\ndata: {}\n\nevent: token\ndata: {}\n\n'))
      .toEqual([{ event: "token", data: {} }]);
  });

  it("releases the reader when the consumer stops early", async () => {
    const body = stream([new TextEncoder().encode('event: token\ndata: {}\n\n')]);
    for await (const frame of parseSseStream(body)) {
      expect(frame.event).toBe("token");
      break;
    }
    expect(body.locked).toBe(false);
  });
});
