"use client";

import { useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { fmtPctWhole, fmtUsd2 } from "../../lib/ops/format";
import type { SystemCost } from "../../lib/ops/types";

/**
 * D28.3: the system OpenAI limit banner on EVERY Ops page (artboard
 * OpsOpenAICap, shown by `OpsHeader`). Amber at ≥ 80 %, red at ≥ 100 %; nothing
 * below. One cheap call (`GET /v1/ops/costs/system`) per browser session: the
 * answer is cached in memory and refreshed only when the Chi phí tab changes
 * the cap or reloads (`publishCostSystem`).
 */

type Listener = (system: SystemCost | null) => void;

let cached: Promise<SystemCost | null> | null = null;
const listeners = new Set<Listener>();

export function loadCostSystem(api: Pick<OpsApi, "costSystem"> = opsApi): Promise<SystemCost | null> {
  if (!cached) {
    cached = api
      .costSystem()
      .then((r) => r.system)
      .catch(() => {
        cached = null; // not signed in yet / a blip: try again on the next page
        return null;
      });
  }
  return cached;
}

/** The Chi phí tab knows the newest figure: every mounted banner takes it. */
export function publishCostSystem(system: SystemCost | null): void {
  cached = Promise.resolve(system);
  for (const listener of listeners) listener(system);
}

/** Tests only. */
export function resetCostSystemCache(): void {
  cached = null;
  listeners.clear();
}

/** "01/11" — the first day of the month after `YYYY-MM`. */
export function nextMonthStart(month: string): string {
  const [y, m] = month.split("-").map(Number);
  const next = m === 12 ? 1 : m + 1;
  void y;
  return `01/${String(next).padStart(2, "0")}`;
}

export function bannerCopy(system: SystemCost | null | undefined): { readonly tone: "warn" | "stop"; readonly title: string; readonly text: string } | null {
  if (!system || system.level === null) return null;
  if (system.reached || system.level === 100) {
    return {
      tone: "stop",
      title: "Đã đạt giới hạn OpenAI",
      text: `Juli dừng soạn nội dung mới cho mọi shop đến ${nextMonthStart(system.month)} hoặc khi tăng giới hạn. Thẻ đề xuất vẫn tạo.`,
    };
  }
  return {
    tone: "warn",
    title: `Đã dùng ${fmtPctWhole(system.pct)} giới hạn OpenAI`,
    text: `${fmtUsd2(system.used_usd)} / ${fmtUsd2(system.cap_usd)}${system.alert_sent ? " · đã gửi email cho Admin" : ""}`,
  };
}

const TONE = {
  warn: { color: "#5c3a00", background: "#fff4e0", borderBottom: "1px solid #f3d9a8" },
  stop: { color: "#ffffff", background: "#a3222f" },
} as const;

export function CostBannerView({ system }: { readonly system: SystemCost | null | undefined }) {
  const copy = bannerCopy(system);
  if (!copy) return null;
  return (
    <div
      data-testid="ops-cost-banner"
      data-tone={copy.tone}
      role="status"
      style={{ display: "flex", alignItems: "center", gap: 12, padding: "12px 28px", fontSize: 14, flexWrap: "wrap", ...TONE[copy.tone] }}
    >
      <b>{copy.title}</b>
      <span>{copy.text}</span>
    </div>
  );
}

export function OpsCostBanner({ api = opsApi }: { readonly api?: Pick<OpsApi, "costSystem"> }) {
  const [system, setSystem] = useState<SystemCost | null>(null);
  useEffect(() => {
    let live = true;
    const listener: Listener = (s) => live && setSystem(s);
    listeners.add(listener);
    void loadCostSystem(api).then((s) => live && setSystem(s));
    return () => {
      live = false;
      listeners.delete(listener);
    };
  }, [api]);
  return <CostBannerView system={system} />;
}
