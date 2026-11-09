"use client";

import type { ReactNode } from "react";

import type { OptionResult } from "../../../lib/shopee-decisions/option-result";
import { CompareTable, OptionCard } from "../option-card";

/** Dấu chấm phân cách nghìn, đồng. */
export const vnd = (n: number | null | undefined): string => (n === null || n === undefined ? "chưa có" : `${Math.round(n).toLocaleString("vi-VN")} đ`);
export const pct = (n: number | null | undefined): string => (n === null || n === undefined ? "chưa có" : `${n.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`);

/** Result cards of the rows that have a `result` (W3-H) and one compare table over them (W3-I's components). */
export function ResultCards({ items }: { readonly items: readonly { readonly title: string; readonly result?: OptionResult | null }[] }) {
  const have = items.filter((i): i is { title: string; result: OptionResult } => !!i.result);
  if (have.length === 0) return null;
  return (
    <section className="sa-card" data-testid="p98-results">
      <h3 className="sa-h2">Kết quả từng phương án</h3>
      {have.map((i) => (
        <div key={i.title} data-testid="p98-result">
          <h4 className="sa-h3">{i.title}</h4>
          <OptionCard result={i.result} />
        </div>
      ))}
      {have.length > 1 ? <CompareTable results={have.map((i) => i.result)} /> : null}
    </section>
  );
}

export function Field({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <label className="sa-field">
      <span className="sa-hint">{label}</span>
      {children}
    </label>
  );
}

/** Whole number from a text box; empty or bad = null. */
export const num = (s: string): number | null => {
  const t = s.replace(/[.\s]/g, "").replace(",", ".");
  if (t === "") return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
};
