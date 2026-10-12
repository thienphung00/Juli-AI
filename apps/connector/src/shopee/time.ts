// Seller Centre VN works in GMT+7: `start_time` / `end_time` are unix seconds of
// GMT+7 calendar boundaries and every ingest row is a GMT+7 day ("YYYY-MM-DD").

const OFFSET_SECONDS = 7 * 3600;
const DAY_SECONDS = 86_400;

export function gmt7Date(unixSeconds: number): string {
  return new Date((unixSeconds + OFFSET_SECONDS) * 1000).toISOString().slice(0, 10);
}

/** Unix seconds of 00:00 GMT+7 on the GMT+7 day containing `unixSeconds`. */
export function gmt7DayStart(unixSeconds: number): number {
  return Math.floor((unixSeconds + OFFSET_SECONDS) / DAY_SECONDS) * DAY_SECONDS - OFFSET_SECONDS;
}

export interface DayRange {
  date: string;
  start_time: number;
  end_time: number;
}

/** Yesterday (GMT+7) relative to `nowMs`, as the "Hôm qua" picker sends it. */
export function yesterdayRange(nowMs: number): DayRange {
  const today = gmt7DayStart(Math.floor(nowMs / 1000));
  const start = today - DAY_SECONDS;
  return { date: gmt7Date(start), start_time: start, end_time: start + DAY_SECONDS - 1 };
}

/**
 * The single GMT+7 day a data response covers, or null when it is not exactly one
 * finished day (real-time "Hôm nay", 7 / 30-day aggregates, week, month): those
 * cannot be split into days and are never posted.
 */
export function singleDay(params: URLSearchParams, capturedAtMs: number): string | null {
  const period = params.get("period");
  const start = Number(params.get("start_time"));
  const end = Number(params.get("end_time"));
  const hasRange = Number.isFinite(start) && Number.isFinite(end) && start > 0 && end > 0;
  if (period !== null && period !== "yesterday" && period !== "day") return null;
  if (hasRange) {
    if (end < start || end - start >= DAY_SECONDS) return null;
    if (gmt7Date(start) !== gmt7Date(end)) return null;
    const day = gmt7Date(start);
    // A day that has not finished yet is partial.
    if (day >= gmt7Date(Math.floor(capturedAtMs / 1000))) return null;
    return day;
  }
  // The traffic dashboard sends `period` + `dt` (format not pinned by the recon).
  const dt = params.get("dt");
  const capturedDay = gmt7Date(Math.floor(capturedAtMs / 1000));
  if (dt && /^\d{4}-\d{2}-\d{2}$/.test(dt)) return dt < capturedDay ? dt : null;
  if (dt && /^\d{10}$/.test(dt)) {
    const day = gmt7Date(Number(dt));
    return day < capturedDay ? day : null;
  }
  if (period === "yesterday") return yesterdayRange(capturedAtMs).date;
  return null;
}
