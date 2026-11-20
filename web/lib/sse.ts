type RawFrame = { event: string; data: Record<string, unknown> };

export async function* parseSseStream(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<{ event: string; data: Record<string, unknown> }> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let pending = "";
  let event = "";
  let data: string[] = [];

  function finish(): RawFrame | undefined {
    const name = event;
    const lines = data;
    event = "";
    data = [];
    if (!name || !lines.length) return;
    const value: unknown = JSON.parse(lines.join("\n"));
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      return { event: name, data: value as Record<string, unknown> };
    }
  }

  function line(value: string): RawFrame | undefined {
    if (value.endsWith("\r")) value = value.slice(0, -1);
    if (!value) return finish();
    if (value.startsWith("event:")) event = value.slice(6).trim();
    else if (value.startsWith("data:")) data.push(value.slice(5).trimStart());
  }

  try {
    while (true) {
      const { value, done } = await reader.read();
      pending += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let end: number;
      while ((end = pending.indexOf("\n")) !== -1) {
        const frame = line(pending.slice(0, end));
        pending = pending.slice(end + 1);
        if (frame) yield frame;
      }
      if (done) break;
    }
    if (pending) {
      const frame = line(pending);
      if (frame) yield frame;
    }
    const frame = finish();
    if (frame) yield frame;
  } finally {
    reader.releaseLock();
  }
}
