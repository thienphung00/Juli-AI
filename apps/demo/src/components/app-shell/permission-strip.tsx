"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/**
 * D25.15: when the shop's TikTok grant lacks a scope Juli uses, ask the seller
 * to reconnect (the normal connect flow re-grants and resumes everything).
 */
export const RECONNECT_COPY = "Kết nối lại TikTok Shop để cấp quyền mới";
export const PERMISSIONS_PATH = "/v1/shops/me/permissions" as const;

export function PermissionStrip({
  token,
  shopId,
  fetchImpl = fetch,
}: {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}) {
  const [needed, setNeeded] = useState(false);
  useEffect(() => {
    let live = true;
    fetchImpl(PERMISSIONS_PATH, {
      headers: { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopId },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) return;
        const body = (await response.json()) as { data?: { needs_reconnect?: boolean } };
        if (live) setNeeded(Boolean(body.data?.needs_reconnect));
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [token, shopId, fetchImpl]);
  if (!needed) return null;
  return (
    <p className="demo-notice" data-testid="permission-strip" role="status">
      {RECONNECT_COPY} · <Link href="/auth/connect-shop">Kết nối lại ›</Link>
    </p>
  );
}
