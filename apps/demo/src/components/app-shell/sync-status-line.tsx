"use client";

import { useEffect, useState } from "react";

import { fetchSyncStatus, syncStatusLine, type SyncStatus } from "../../lib/sync-status/api-client";

/** While a backfill runs, re-read the progress this often. */
export const SYNC_STATUS_POLL_MS = 60_000;

/**
 * P101 W2 B-5: the one status line under a TikTok shop's name —
 * "Đang tải dữ liệu 90 ngày · n/90" while the backfill runs, then
 * "Số liệu đến dd/mm". Nothing else: a failed read, a disconnected shop and a
 * shop that needs re-authorising render no line.
 */
export function SyncStatusLine({
  token,
  shopId,
  fetchImpl,
  pollMs = SYNC_STATUS_POLL_MS,
}: {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
  readonly pollMs?: number;
}) {
  const [status, setStatus] = useState<SyncStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const next = await fetchSyncStatus({ token, shopId, fetchImpl });
        if (cancelled) return;
        setStatus(next);
        if (next.backfilling) timer = setTimeout(load, pollMs);
      } catch {
        if (!cancelled) setStatus(null);
      }
    };
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [token, shopId, fetchImpl, pollMs]);

  const line = status ? syncStatusLine(status) : null;
  if (!line) return null;
  return (
    <p className="shop-header__sub" data-testid="sync-status-line">
      {line}
    </p>
  );
}
