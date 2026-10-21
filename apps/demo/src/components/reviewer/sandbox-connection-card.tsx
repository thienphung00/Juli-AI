"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  SANDBOX_CONNECTED_LABEL,
  SANDBOX_NEEDS_REAUTH_LABEL,
  SANDBOX_CONNECTION_TITLE,
  SANDBOX_LOAD_ERROR,
  SANDBOX_SYNC_ERROR,
  SANDBOX_SYNC_LABEL,
  SANDBOX_SYNC_QUEUED,
  SANDBOX_SYNC_UNAVAILABLE,
} from "../../lib/reviewer/copy";
import { fetchSandboxShop, syncSandboxShop, type SandboxShop, type SyncResult } from "../../lib/reviewer/sandbox-client";

/**
 * P64 (D73): the partner reviewer's TikTok connection card — the live sandbox
 * shop, "Đã kết nối", when it was authorised, the scopes, when its data last
 * synced, and "Đồng bộ ngay". The sync is rate limited by the API (one per
 * 60 s): a 429 disables the button with a countdown. Shown on Trang chủ only
 * when `mode == "sandbox"`.
 */

const TIME_ZONE = "Asia/Ho_Chi_Minh";
/** The API queues a poll; the card re-reads the shop once it had time to run. */
export const SYNC_REFRESH_MS = 10_000;

export function absoluteVn(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("vi-VN", {
    timeZone: TIME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export function relativeVn(iso: string | null | undefined, nowMs: number): string | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  const seconds = Math.max(0, Math.round((nowMs - then) / 1000));
  if (seconds < 60) return "vừa xong";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} giờ trước`;
  return `${Math.round(hours / 24)} ngày trước`;
}

type Load = { status: "loading" } | { status: "error" } | { status: "ready"; shop: SandboxShop };
type Notice = "queued" | "unavailable" | "error" | null;

export interface SandboxConnectionCardProps {
  readonly token: string;
  readonly shopId?: string;
  /** Test seams. */
  readonly fetchShop?: () => Promise<SandboxShop>;
  readonly sync?: () => Promise<SyncResult>;
  readonly refreshMs?: number;
}

export function SandboxConnectionCard({
  token,
  shopId,
  fetchShop = () => fetchSandboxShop({ token, shopId }),
  sync = () => syncSandboxShop({ token, shopId }),
  refreshMs = SYNC_REFRESH_MS,
}: SandboxConnectionCardProps) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [notice, setNotice] = useState<Notice>(null);
  const [busy, setBusy] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const fetchRef = useRef(fetchShop);
  useEffect(() => {
    fetchRef.current = fetchShop;
  });
  const refreshTimer = useRef<number | null>(null);

  const read = useCallback(() => {
    fetchRef.current().then(
      (shop) => setLoad({ status: "ready", shop }),
      () => setLoad((current) => (current.status === "ready" ? current : { status: "error" })),
    );
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(read, 0);
    return () => window.clearTimeout(timer);
  }, [read]);

  useEffect(
    () => () => {
      if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
    },
    [],
  );

  useEffect(() => {
    const timer = window.setInterval(() => {
      setNow(Date.now());
      setCountdown((value) => (value > 0 ? value - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, []);

  const onSync = () => {
    setBusy(true);
    setNotice(null);
    sync().then((result) => {
      setBusy(false);
      if (result.status === "queued") {
        setNotice("queued");
        setCountdown(result.retryAfterSeconds);
        if (refreshTimer.current !== null) window.clearTimeout(refreshTimer.current);
        refreshTimer.current = window.setTimeout(read, refreshMs);
      } else if (result.status === "rate_limited") {
        setCountdown(result.retryAfterSeconds);
      } else {
        setNotice(result.status === "unavailable" ? "unavailable" : "error");
      }
    });
  };

  if (load.status !== "ready") {
    return (
      <div className="card sandbox-connection" data-testid="sandbox-connection">
        <p className="eyebrow">{SANDBOX_CONNECTION_TITLE}</p>
        {load.status === "error" ? (
          <p className="qv-inline-error" role="alert">
            {SANDBOX_LOAD_ERROR}
          </p>
        ) : (
          <p className="text-muted" role="status">
            Đang tải…
          </p>
        )}
      </div>
    );
  }

  const { shop, connection, synced_at: syncedAt } = load.shop;
  const connected = connection.status === "active" || connection.status === "connected";
  const authorised = absoluteVn(connection.authorized_at);
  const relative = relativeVn(syncedAt, now);
  const absolute = absoluteVn(syncedAt);

  return (
    <div className="card sandbox-connection" data-testid="sandbox-connection">
      <p className="eyebrow">{SANDBOX_CONNECTION_TITLE}</p>
      <dl className="reviewer-sim__facts">
        <dt>Shop</dt>
        <dd>{shop.name}</dd>
        {shop.tiktok_shop_id ? (
          <>
            <dt>Mã shop TikTok</dt>
            <dd>{shop.tiktok_shop_id}</dd>
          </>
        ) : null}
        <dt>Trạng thái</dt>
        <dd data-testid="sandbox-connection-status">{connected
            ? SANDBOX_CONNECTED_LABEL
            : connection.status === "needs_reauth"
              ? SANDBOX_NEEDS_REAUTH_LABEL
              : connection.status}</dd>
        {authorised ? (
          <>
            <dt>Ủy quyền</dt>
            <dd>Ủy quyền lúc {authorised}</dd>
          </>
        ) : null}
        <dt>Đồng bộ</dt>
        <dd data-testid="sandbox-synced-at">
          {absolute ? `Đồng bộ lúc ${absolute}${relative ? ` (${relative})` : ""}` : "Chưa đồng bộ"}
        </dd>
      </dl>
      {connection.scopes.length > 0 ? (
        <details className="sandbox-connection__scopes">
          <summary>Quyền đã cấp ({connection.scopes.length})</summary>
          <ul>
            {connection.scopes.map((scope) => (
              <li key={scope}>{scope}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <div className="qv-dialog__actions">
        <button className="qv-btn qv-btn--secondary" disabled={busy || countdown > 0} onClick={onSync} type="button">
          {countdown > 0 ? `${SANDBOX_SYNC_LABEL} (${countdown}s)` : SANDBOX_SYNC_LABEL}
        </button>
      </div>
      {notice === "queued" ? (
        <p className="qv-status-line" role="status">
          {SANDBOX_SYNC_QUEUED}
        </p>
      ) : null}
      {notice === "unavailable" || notice === "error" ? (
        <p className="qv-inline-error" role="alert">
          {notice === "unavailable" ? SANDBOX_SYNC_UNAVAILABLE : SANDBOX_SYNC_ERROR}
        </p>
      ) : null}
    </div>
  );
}
