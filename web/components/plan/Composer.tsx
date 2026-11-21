"use client";

import { useId, useRef, useState } from "react";
import { Button } from "../ui";

export function Composer({ enabled, busy, imageEnabled, onSend }: {
  enabled: boolean; busy: boolean; imageEnabled: boolean;
  onSend: (message: string, withImage?: boolean) => void;
}) {
  const id = useId();
  const [message, setMessage] = useState("");
  const [withImage, setWithImage] = useState(true);
  const composing = useRef(false);
  function send() {
    if (!enabled || !message.trim() || busy || composing.current) return;
    onSend(message, imageEnabled ? withImage : undefined);
    setMessage("");
  }
  return <form className="gs-composer" onSubmit={event => { event.preventDefault(); send(); }}>
    <label htmlFor={id}>요청</label>
    <textarea id={id} rows={4} maxLength={2000} value={message} disabled={!enabled || busy}
      aria-describedby={`${id}-hint`} placeholder="광고 기획 요청을 입력하세요"
      onChange={event => setMessage(event.target.value.slice(0, 2000))}
      onCompositionStart={() => { composing.current = true; }}
      onCompositionEnd={() => { composing.current = false; }}
      onKeyDown={event => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && !composing.current && event.keyCode !== 229) {
          event.preventDefault(); send();
        }
      }} />
    <div className="gs-composer-actions">
      <small id={`${id}-hint`}>{message.length}/2000 · Enter 전송, Shift+Enter 줄바꿈</small>
      {imageEnabled && <label className="gs-image-option"><input type="checkbox" checked={withImage} disabled={busy || !enabled}
        onChange={event => setWithImage(event.target.checked)} />시안 이미지 포함</label>}
      <Button type="submit" disabled={!enabled || busy || !message.trim()}>전송</Button>
    </div>
  </form>;
}
