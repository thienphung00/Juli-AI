"use client";

import { useState } from "react";

import type { VariationList } from "../../../lib/shopee-decisions/builder-api";
import { VariationCompare } from "./variations";

/**
 * The stepper of Tự tạo phương án (artboards Flow1..Flow4) and the inline variation choice of step ① Sản phẩm
 * (it used to be a step of its own).
 */

export { sortProducts } from "../../../lib/shopee-decisions/picker-table";

export const STEP_NAMES = ["Sản phẩm", "Chiến lược", "Phương án", "So sánh & lưu"] as const;

/** `1 · Sản phẩm` … `4 · So sánh & lưu`: the steps before the current one (and any `reachable` one) are buttons. */
export function Stepper({ step, reachable, onGo }: { readonly step: 1 | 2 | 3 | 4; readonly reachable: readonly boolean[]; readonly onGo: (n: 1 | 2 | 3 | 4) => void }) {
  return (
    <nav aria-label="Các bước">
      <ol className="p2-tabs" data-testid="p2-stepper">
        {STEP_NAMES.map((name, i) => {
          const n = (i + 1) as 1 | 2 | 3 | 4;
          const label = `${n} · ${name}`;
          if (n === step) {
            return (
              <li aria-current="step" className="p2-tab p2-tab--on" data-testid={`p2-tab-${n}`} key={name}>
                {label}
              </li>
            );
          }
          const go = n < step || reachable[i] === true;
          return (
            <li key={name}>
              {go ? (
                <button className="p2-tab" data-testid={`p2-tab-${n}`} onClick={() => onGo(n)} type="button">
                  {label}
                  {n < step ? " ✓" : ""}
                </button>
              ) : (
                <span className="p2-tab" data-testid={`p2-tab-${n}`}>
                  {label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** The variations of the picked product, inline under the cards. */
export function VariationChoice({
  list,
  selected,
  all,
  onToggle,
  onAll,
  costLink,
}: {
  readonly list: VariationList;
  readonly selected: readonly string[];
  readonly all: boolean;
  readonly onToggle: (id: string) => void;
  readonly onAll: () => void;
  readonly costLink: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section className="sa-card p2-vstep" data-testid="p2-vstep">
      <div className="sa-card__head">
        <h2 className="sa-h2">Phân loại</h2>
      </div>
      <div className="sb-chips" role="group" aria-label="Phân loại">
        {list.variations.map((v) => {
          const on = all || selected.includes(v.variation_id);
          return (
            <button aria-pressed={on} className={`sb-pill ${on ? "sb-pill--on" : ""}`} key={v.variation_id || "default"} onClick={() => onToggle(v.variation_id)} type="button">
              {on ? "✓ " : ""}
              {v.name}
            </button>
          );
        })}
        {list.variations.length > 1 ? (
          <button aria-pressed={all} className={`sb-pill ${all ? "sb-pill--on" : ""}`} onClick={onAll} type="button">
            Tất cả phân loại
          </button>
        ) : null}
      </div>
      <button aria-expanded={open} className="sa-btn sa-btn--s p2-expand__btn" data-testid="p2-vcmp-toggle" onClick={() => setOpen((o) => !o)} type="button">
        So sánh phân loại {open ? "▾" : "▸"}
      </button>
      {open ? <VariationCompare costLink={costLink} data={list} /> : null}
    </section>
  );
}
