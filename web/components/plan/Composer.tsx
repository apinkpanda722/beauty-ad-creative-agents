"use client";

import { useId, useLayoutEffect, useRef, useState } from "react";
import { Button } from "../ui";

export function Composer({ enabled, busy, imageEnabled, onSend }: {
  enabled: boolean; busy: boolean; imageEnabled: boolean;
  onSend: (message: string, withImage?: boolean) => void;
}) {
  const id = useId();
  const [message, setMessage] = useState("");
  const [withImage, setWithImage] = useState(true);
  const textarea = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const input = textarea.current;
    if (!input) return;
    input.style.overflowY = "hidden";
    input.style.height = "auto";
    const maximum = Number.parseFloat(getComputedStyle(input).maxHeight);
    const height = Number.isFinite(maximum) ? Math.min(input.scrollHeight, maximum) : input.scrollHeight;
    input.style.height = `${height}px`;
    if (Number.isFinite(maximum) && height >= maximum && input.scrollHeight > input.clientHeight) input.style.overflowY = "auto";
  }, [message]);
  const composing = useRef(false);
  function send() {
    if (!enabled || !message.trim() || busy || composing.current) return;
    onSend(message, imageEnabled ? withImage : undefined);
    setMessage("");
  }
  return <form className="gs-composer" onSubmit={event => { event.preventDefault(); send(); }}>
    <label className="gs-sr-only" htmlFor={id}>요청</label>
    <div className="gs-composer-bar"><textarea ref={textarea} id={id} rows={3} maxLength={2000} value={message} disabled={!enabled || busy}
      aria-describedby={message ? `${id}-hint` : undefined} placeholder="광고 기획 요청을 입력하세요"
      onChange={event => setMessage(event.target.value.slice(0, 2000))}
      onCompositionStart={() => { composing.current = true; }}
      onCompositionEnd={() => { composing.current = false; }}
      onKeyDown={event => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.keyCode !== 229) {
          event.preventDefault(); send();
        }
      }} />
    <Button type="submit" disabled={!enabled || busy || !message.trim()}>기획하기</Button></div>
    <div className="gs-composer-actions">
      {message && <small id={`${id}-hint`}>{message.length}/2000 · Enter 전송, Shift+Enter 줄바꿈</small>}
      {imageEnabled && <label className="gs-image-option"><input type="checkbox" checked={withImage} disabled={busy || !enabled}
        onChange={event => setWithImage(event.target.checked)} />시안 이미지 포함</label>}
    </div>
  </form>;
}
