import type { Deltas, KpiId, SimStream, Stability, StreamId } from "./types";

/**
 * Client mirror of `services/ops/simulation.py` (D25.10): GMV/day per stream
 * = Hiển thị × CTR × CTOR × AOV, cells move in ±5 % steps, Video CTOR / AOV
 * and LIVE AOV locked. The server is the source of truth for the baseline and
 * bands; this only re-multiplies so ± answers instantly.
 */

export const KPIS: readonly KpiId[] = ["impressions", "ctr", "ctor", "aov"];
export const STREAMS: readonly StreamId[] = ["product_card", "shop_tab", "seller_video", "seller_live"];
export const STEP = 5;

export function streamGmv(stream: SimStream, deltas: Partial<Record<KpiId, number>> = {}): number {
  let total = 1;
  for (const cell of stream.cells) {
    if (cell.value === null) return 0;
    total *= cell.value * (1 + (deltas[cell.kpi] ?? 0) / 100);
  }
  return total;
}

export interface ShopResult {
  readonly perStream: Record<string, { base: number; next: number; pct: number | null }>;
  readonly totalBase: number;
  readonly totalNew: number;
  readonly pct: number | null;
}

export function simulate(streams: readonly SimStream[], deltas: Deltas): ShopResult {
  const perStream: ShopResult["perStream"] = {};
  let totalBase = 0;
  let totalNew = 0;
  for (const stream of streams) {
    const base = streamGmv(stream);
    const next = streamGmv(stream, deltas[stream.stream] ?? {});
    totalBase += base;
    totalNew += next;
    perStream[stream.stream] = { base, next, pct: base === 0 ? null : ((next - base) / base) * 100 };
  }
  return { perStream, totalBase, totalNew, pct: totalBase === 0 ? null : ((totalNew - totalBase) / totalBase) * 100 };
}

export function step(deltas: Deltas, stream: StreamId, kpi: KpiId, by: number): Deltas {
  const current = deltas[stream] ?? {};
  const value = (current[kpi] ?? 0) + by;
  const nextStream = { ...current, [kpi]: value };
  if (value === 0) delete nextStream[kpi];
  return { ...deltas, [stream]: nextStream };
}

export function cleanDeltas(deltas: Deltas): Deltas {
  const out: Deltas = {};
  for (const [stream, cells] of Object.entries(deltas)) {
    const kept = Object.fromEntries(Object.entries(cells ?? {}).filter(([, v]) => v));
    if (Object.keys(kept).length) out[stream as StreamId] = kept;
  }
  return out;
}

/** "Trong dao động thường ngày" when |Δ| ≤ the cell's normal band. */
export function inNoise(delta: number, bandPct: number | null | undefined): boolean {
  return bandPct === null || bandPct === undefined ? true : Math.abs(delta) <= bandPct;
}

export const STABILITY_COPY: Record<Stability, { label: string; row: string; style: string }> = {
  stable: { label: "Ổn định", row: "Ổn định · nên chọn", style: "stable" },
  medium: { label: "Dao động vừa", row: "Dao động vừa", style: "medium" },
  volatile: { label: "Dao động cao", row: "Dao động cao", style: "volatile" },
  unknown: { label: "Chưa đủ dữ liệu", row: "Chưa đủ dữ liệu", style: "unknown" },
};

/** ▲/▼ chip like the seller UI: grey when |Δ| < 0.5 % (D25.11). */
export function trendChip(pct: number | null): { text: string; tone: "up" | "down" | "flat" | "none" } {
  if (pct === null) return { text: "—", tone: "none" };
  const abs = Math.abs(pct).toFixed(1).replace(".", ",");
  if (Math.abs(pct) < 0.5) return { text: `${abs} %`, tone: "flat" };
  return pct > 0 ? { text: `▲ ${abs} %`, tone: "up" } : { text: `▼ ${abs} %`, tone: "down" };
}
