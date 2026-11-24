// Connector 0.3.34 (batch-1124-hotfix C-H2): a post never spans more days than the gateway takes.
//
// The orders job reads back to its `sinceDay` (at most 30 days), but a card-list page can hold
// orders placed before it, so the mapped period could run past the gateway's 31-day cap and the
// whole post came back 422 `period_too_long` (tick 23/11: `orders:0_rows:rejected`). Rows placed
// before the job's read window are dropped, and what is left is posted in periods of at most
// MAX_POST_PERIOD_DAYS, each covering exactly the days of its own rows.

import { MAX_POST_PERIOD_DAYS } from "./config";
import type { Mapped, Row } from "./map";
import { gmt7DateStart } from "../../core/time";

const DAY = /^\d{4}-\d{2}-\d{2}/;

/** The GMT+7 day a row belongs to: its `date`, else the day of its `ordered_at` (order lines). */
export function rowDay(row: Row): string | undefined {
  for (const key of ["date", "ordered_at"] as const) {
    const value = row[key];
    if (typeof value === "string" && DAY.test(value)) return value.slice(0, 10);
  }
  return undefined;
}

/** Days from `start` to `end`, both counted (the gateway's `(end - start).days + 1`). */
export function periodDays(start: string, end: string): number {
  return Math.round((gmt7DateStart(end) - gmt7DateStart(start)) / 86_400) + 1;
}

/** The mapped post without the rows placed before `sinceDay`; its period starts at its first kept day. */
export function withinReadWindow(mapped: Mapped, sinceDay: string | undefined): Mapped {
  if (!sinceDay || mapped.rows.length === 0) return mapped;
  const kept = mapped.rows.filter((row) => {
    const day = rowDay(row);
    return day === undefined || day >= sinceDay;
  });
  if (kept.length === mapped.rows.length) return mapped;
  const days = kept.map(rowDay).filter((d): d is string => d !== undefined).sort();
  const start = days[0];
  const periodStart = mapped.periodStart !== undefined && start !== undefined && mapped.periodStart < start ? start : mapped.periodStart;
  return { ...mapped, rows: kept, ...(periodStart !== undefined ? { periodStart } : {}) };
}

/**
 * A `period` post that spans more than MAX_POST_PERIOD_DAYS, cut into posts of at most that many
 * days (by the rows' own days, oldest first). Posts that fit, day posts and posts whose rows carry
 * no day of their own are returned as they are.
 */
export function splitByPeriod(mapped: Mapped, maxDays: number = MAX_POST_PERIOD_DAYS): Mapped[] {
  const start = mapped.periodStart ?? mapped.date;
  if (mapped.granularity !== "period" || mapped.rows.length === 0 || periodDays(start, mapped.date) <= maxDays) return [mapped];
  const dated = mapped.rows.map((row) => ({ row, day: rowDay(row) }));
  if (dated.some((d) => d.day === undefined)) return [mapped];
  dated.sort((a, b) => (a.day as string).localeCompare(b.day as string));
  const out: Mapped[] = [];
  let chunk: { row: Row; day: string }[] = [];
  const flush = () => {
    if (chunk.length === 0) return;
    out.push({ ...mapped, periodStart: chunk[0]!.day, date: chunk[chunk.length - 1]!.day, rows: chunk.map((c) => c.row) });
    chunk = [];
  };
  for (const d of dated as { row: Row; day: string }[]) {
    if (chunk.length > 0 && periodDays(chunk[0]!.day, d.day) > maxDays) flush();
    chunk.push(d);
  }
  flush();
  return out;
}
