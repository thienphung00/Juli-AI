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

/** Unix seconds of 00:00 GMT+7 on `date` ("YYYY-MM-DD"). */
export function gmt7DateStart(date: string): number {
  const [y, m, d] = date.split("-").map(Number) as [number, number, number];
  return Date.UTC(y, m - 1, d) / 1000 - OFFSET_SECONDS;
}

/** "YYYY-MM-DD" → "YYYYMMDD", the traffic dashboard's `dt`. */
export function compactDate(date: string): string {
  return date.replaceAll("-", "");
}

/**
 * The last `count` finished GMT+7 days before `nowMs`, NEWEST first
 * (yesterday, the day before, ...).
 */
export function lastFinishedDays(nowMs: number, count: number): string[] {
  const today = gmt7DayStart(Math.floor(nowMs / 1000));
  return Array.from({ length: count }, (_, i) => gmt7Date(today - (i + 1) * DAY_SECONDS));
}

/**
 * The single GMT+7 day a data response covers, or null when it is not exactly one
 * finished day (real-time "Hôm nay", 7 / 30-day aggregates, week, month): those
 * cannot be split into days and are never posted.
 *
 * Recorded range shapes (Seller Centre, 2026-10-26), both starting on a GMT+7
 * midnight:
 * - "Hôm qua": `period=yesterday`, `end_time = start_time + 86399`;
 * - a picked day ("Theo ngày"): `period=day`, `end_time = start_time + 86400` (the
 *   next midnight). `period=day` with `+ 86399` is refused by Shopee (code 10006),
 *   so it is not a real shape and is rejected here too.
 * The traffic dashboard sends `period` + `dt` instead (`dt=YYYYMMDD` recorded;
 * `YYYY-MM-DD` and unix seconds are still read).
 */
export function singleDay(params: URLSearchParams, capturedAtMs: number): string | null {
  const period = params.get("period");
  const start = Number(params.get("start_time"));
  const end = Number(params.get("end_time"));
  const hasRange = Number.isInteger(start) && Number.isInteger(end) && start > 0 && end > 0;
  if (period !== null && period !== "yesterday" && period !== "day") return null;
  const capturedDay = gmt7Date(Math.floor(capturedAtMs / 1000));
  // A day that has not finished yet is partial.
  const finished = (day: string) => (day < capturedDay ? day : null);
  if (hasRange) {
    if (gmt7DayStart(start) !== start) return null;
    const span = end - start;
    const fullDay =
      period === "day"
        ? span === DAY_SECONDS
        : period === "yesterday"
          ? span === DAY_SECONDS - 1
          : span === DAY_SECONDS || span === DAY_SECONDS - 1;
    return fullDay ? finished(gmt7Date(start)) : null;
  }
  const dt = params.get("dt");
  if (dt && /^\d{4}-\d{2}-\d{2}$/.test(dt)) return finished(dt);
  if (dt && /^\d{8}$/.test(dt)) {
    const day = `${dt.slice(0, 4)}-${dt.slice(4, 6)}-${dt.slice(6, 8)}`;
    // Reject impossible dates (20261340): they would not round-trip.
    if (gmt7Date(gmt7DateStart(day)) !== day) return null;
    return finished(day);
  }
  if (dt && /^\d{10}$/.test(dt)) return finished(gmt7Date(Number(dt)));
  if (period === "yesterday") return yesterdayRange(capturedAtMs).date;
  return null;
}
