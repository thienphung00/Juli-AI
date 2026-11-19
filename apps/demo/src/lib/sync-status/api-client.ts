/**
 * `GET /v1/shops/me/sync-status` (P101 W2 B-5): the TikTok shop's backfill progress
 * (days out of 90) and the date its analytics run to. Bearer + `X-Shop-Id`, read-only.
 */

export const SYNC_STATUS_API_PATH = "/v1/shops/me/sync-status" as const;

export interface SyncStatus {
  readonly state: "disconnected" | "needs_reauth" | "backfilling" | "degraded" | "active" | string;
  readonly backfilling: boolean;
  readonly history_days_done: number;
  readonly history_days_total: number;
  /** ISO date (yyyy-mm-dd) of the last fully fetched analytics day, or null. */
  readonly data_through: string | null;
  readonly late: boolean;
}

export class SyncStatusFetchError extends Error {
  constructor(public readonly status: number) {
    super(`Sync status fetch failed (${status})`);
    this.name = "SyncStatusFetchError";
  }
}

function isSyncStatus(value: unknown): value is SyncStatus {
  if (!value || typeof value !== "object") return false;
  const body = value as Partial<SyncStatus>;
  return (
    typeof body.backfilling === "boolean" &&
    typeof body.history_days_done === "number" &&
    typeof body.history_days_total === "number"
  );
}

export async function fetchSyncStatus(options: {
  readonly token: string;
  readonly shopId: string;
  readonly fetchImpl?: typeof fetch;
}): Promise<SyncStatus> {
  const { token, shopId, fetchImpl = fetch } = options;
  const response = await fetchImpl(SYNC_STATUS_API_PATH, {
    headers: { Accept: "application/json", Authorization: `Bearer ${token}`, "X-Shop-Id": shopId },
    cache: "no-store",
  });
  if (!response.ok) throw new SyncStatusFetchError(response.status);
  const payload: unknown = await response.json();
  if (!isSyncStatus(payload)) throw new SyncStatusFetchError(response.status);
  return payload;
}

/** The single status line, or null when there is nothing to say. */
export function syncStatusLine(status: SyncStatus): string | null {
  if (status.state === "backfilling" && status.backfilling) {
    return `Đang tải dữ liệu ${status.history_days_total} ngày · ${status.history_days_done}/${status.history_days_total}`;
  }
  if (status.state === "disconnected" || status.state === "needs_reauth") return null;
  const match = status.data_through ? /^\d{4}-(\d{2})-(\d{2})$/.exec(status.data_through) : null;
  return match ? `Số liệu đến ${match[2]}/${match[1]}` : null;
}
