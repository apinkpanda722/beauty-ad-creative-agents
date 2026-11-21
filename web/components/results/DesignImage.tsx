/* eslint-disable @next/next/no-img-element -- Authenticated bytes are fetched before using a blob URL. */
"use client";
import { useEffect, useState } from "react";
import { ApiError, getDesignImage } from "../../lib/api";
import type { ImageReference } from "../../lib/types";
export function DesignImage({ tenantId, image, disclaimer, onAspectRatio }: { tenantId: string; image: ImageReference; disclaimer: string | null; onAspectRatio?: (ratio: number | null) => void }) {
  const [result, setResult] = useState<{ key: string; url?: string; error?: string } | null>(null);
  const key = JSON.stringify([tenantId, image.request_key, image.index]);
  useEffect(() => {
    let active = true;
    let url: string | undefined;
    void getDesignImage(tenantId, image.request_key, image.index).then(blob => {
      if (!active) return;
      url = URL.createObjectURL(blob); setResult({ key, url });
    }).catch(error => {
      if (active) setResult({ key, error: error instanceof ApiError && error.code === "DESIGN_NOT_FOUND" ? " (DESIGN_NOT_FOUND)" : "" });
    });
    return () => { active = false; if (url) URL.revokeObjectURL(url); };
  }, [tenantId, image.request_key, image.index, key]);
  const current = result?.key === key ? result : null;
  return <figure className="gs-design-image">
    {current?.url ? <img src={current.url} alt="기획안 시안 이미지" onLoad={event => {
      const { naturalWidth, naturalHeight } = event.currentTarget;
      if (naturalWidth > 0 && naturalHeight > 0) onAspectRatio?.(naturalWidth / naturalHeight);
    }} onError={() => { setResult({ key, error: "" }); onAspectRatio?.(null); }} /> : current?.error !== undefined ? <p role="status">시안 이미지를 불러오지 못했습니다{current.error}</p> : <p className="muted">시안 이미지를 불러오는 중입니다.</p>}
    {disclaimer && <figcaption><small>{disclaimer}</small></figcaption>}
  </figure>;
}
