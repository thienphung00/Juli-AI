/**
 * Expiry countdown for a `waiting_approval` run's pending decision
 * (`WorkflowRunListItem.decision_summary.expires_at`), PUI-DESIGN.md §3/§4.
 *
 * Driven entirely by the server-carried `expires_at` wall-clock value and an
 * explicit `nowMs` the caller supplies -- never `Date.now()` read internally
 * -- so a fixed-clock test can prove the rendered countdown is exactly
 * `expires_at - now`, with no drift from the server's own value.
 */

interface ExpiryCountdown {
  /** e.g. "3 giờ 58 phút" or "42 phút" -- minute precision, no seconds (so a
   *  poll-driven re-render never has to tick every second). */
  label: string;
  expired: boolean;
}

const MS_PER_MINUTE = 60_000;
const MINUTES_PER_HOUR = 60;
const HOURS_PER_DAY = 24;

export function resolveExpiryCountdown(
  expiresAtIso: string,
  nowMs: number,
): ExpiryCountdown {
  const expiresAtMs = new Date(expiresAtIso).getTime();
  const remainingMs = expiresAtMs - nowMs;

  if (remainingMs <= 0) {
    return { label: "0 phút", expired: true };
  }

  const totalMinutes = Math.floor(remainingMs / MS_PER_MINUTE);
  const totalHours = Math.floor(totalMinutes / MINUTES_PER_HOUR);
  const minutes = totalMinutes % MINUTES_PER_HOUR;

  // Past a day, hours-and-minutes reads as noise ("633166 giờ 17 phút");
  // whole days and hours are enough at that distance.
  if (totalHours >= HOURS_PER_DAY) {
    const days = Math.floor(totalHours / HOURS_PER_DAY);
    const hours = totalHours % HOURS_PER_DAY;
    return { label: hours > 0 ? `${days} ngày ${hours} giờ` : `${days} ngày`, expired: false };
  }

  const label = totalHours > 0 ? `${totalHours} giờ ${minutes} phút` : `${minutes} phút`;
  return { label, expired: false };
}
