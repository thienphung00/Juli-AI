"use client";

import { useId, useState } from "react";

import { metricLabel } from "../../../lib/metrics";
import { DASH, vnCount, vnd } from "../../../lib/shopee-analytics/format";
import { amountText, type ForecastBlock, type MetricKey } from "../../../lib/shopee-decisions/forecast-display";
import type { OptionResult } from "../../../lib/shopee-decisions/option-result";

/** Voucher kinds only (min_spend_voucher, review_voucher, voucher_cap …). */
export const isVoucherResult = (r: Pick<OptionResult, "kind">): boolean => r.kind.includes("voucher");

/** The offer's wire label as the seller reads it: the voucher's own offer is keyed "voucher" (backend VOUCHER_OFFER_LABEL). */
const offerLabel = (label: string): string => (label === "voucher" ? "Voucher" : label);

const ok = (n: unknown): n is number => typeof n === "number" && Number.isFinite(n);
const money = (n: unknown): string => (ok(n) ? vnd(n) : DASH);
const count = (n: unknown): string => (ok(n) ? vnCount(n) : DASH);

const ROWS: readonly { readonly key: MetricKey; readonly label: string }[] = [
  { key: "profit", label: metricLabel("contribution") },
  { key: "gmv", label: metricLabel("gmv") },
  { key: "orders", label: "Đơn" },
  { key: "aov", label: metricLabel("aov") },
];

/**
 * Owner #87 Q8: tap the forecast of a voucher to see its numbers. Only what the API returned, as given:
 * each offer's lượt dùng × chi phí mỗi lượt = chi phí, and hiện tại → dự kiến for four metrics. No arithmetic here.
 */
export function VoucherNumbers({ result: r, forecast }: { readonly result: OptionResult; readonly forecast: ForecastBlock | null | undefined }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const offers = r.cost.offers ?? [];
  return (
    <div className="p3-numbers-wrap">
      <button aria-controls={id} aria-expanded={open} className="p3-numbers-btn" data-testid="p3-numbers-btn" onClick={() => setOpen((v) => !v)} type="button">
        Số liệu
      </button>
      {open ? (
        <div className="p3-numbers" data-testid="p3-numbers" id={id}>
          <div className="p3-numbers__title">Lượt dùng dự kiến × Chi phí mỗi lượt = Chi phí</div>
          {offers.length === 0 ? (
            <div className="p3-numbers__row" data-testid="p3-offers-none">
              {DASH}
            </div>
          ) : (
            offers.map((o, i) => (
              <div className="p3-numbers__row" data-testid={`p3-offer-${i}`} key={i}>
                <span>{offerLabel(o.label)}</span>
                <span>
                  {count(o.expected_uses)} × {money(o.per_use)} = {money(o.total)}
                </span>
              </div>
            ))
          )}
          {ROWS.map(({ key, label }) => {
            const x = forecast?.metrics?.[key];
            return (
              <div className="p3-numbers__row" data-testid={`p3-num-${key}`} key={key}>
                <span>{label}</span>
                <span>
                  {amountText(key, x?.hien_tai)} → {amountText(key, x?.du_kien)}
                </span>
              </div>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
