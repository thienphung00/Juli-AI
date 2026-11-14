"use client";

import { fmt, vnd } from "../../lib/shopee-analytics/format";
import { breachLine, spendLine } from "../../lib/shopee-decisions/model";
import type { Card } from "../../lib/shopee-decisions/types";

/**
 * The checks under the card's what-if (floor, ad margin, spend cap, break-even). One card, one number
 * (2026-11-14): the five-numbers "chắc chắn / khoảng" table is gone; the card page's Kết quả block
 * (`CardResultBlock`) shows the stored engine result as Tự tạo does.
 */

/** Floor, ad margin, spend cap and break-even lines under the sliders. */
export function Checks({ card }: { readonly card: Card }) {
  const floor = card.floor;
  const spend = spendLine(card);
  const c = card.certain;
  const be = c.break_even_extra_orders;
  return (
    <div className="sd-checks" data-testid="sd-checks">
      <div className={`sd-check ${floor.ok ? "sd-check--ok" : "sd-check--bad"}`} data-testid="sd-floor">
        <b aria-hidden="true">{floor.ok ? "✓" : "✕"}</b>
        <span>
          {floor.ok ? (
            <>Trên giá sàn vận hành: mọi SKU trong phạm vi đều giữ giá khách trả cao hơn giá sàn.</>
          ) : (
            <>
              <b>Chạm giá sàn.</b>
              {floor.breaches.map((b) => (
                <span className="sd-check__line" key={`${b.sku}-${b.kind}`}>
                  {breachLine(b)}
                </span>
              ))}
            </>
          )}
          {floor.unknown_skus.length > 0 ? <span className="sd-check__line">Chưa có giá vốn để tính giá sàn: {floor.unknown_skus.join(", ")}.</span> : null}
        </span>
      </div>
      {c.ad_margin_below_target !== undefined ? (
        <div className={`sd-check ${c.ad_margin_below_target ? "sd-check--warn" : "sd-check--ok"}`} data-testid="sd-ad-margin">
          <b aria-hidden="true">{c.ad_margin_below_target ? "!" : "✓"}</b>
          <span>
            {c.ad_margin_below_target ? "Đơn từ quảng cáo còn biên thấp hơn mục tiêu. " : "Đơn từ quảng cáo giữ biên đạt mục tiêu. "}
            {c.ad_attributed && c.organic ? `Đơn quảng cáo: ${vnd(c.ad_attributed.profit_per_order)}/đơn · đơn tự nhiên: ${vnd(c.organic.profit_per_order)}/đơn.` : ""}
          </span>
        </div>
      ) : null}
      {spend ? (
        <div className={`sd-check ${spend.over ? "sd-check--bad" : "sd-check--ok"}`} data-testid="sd-spend">
          <b aria-hidden="true">{spend.over ? "✕" : "✓"}</b>
          <span>{spend.text}</span>
        </div>
      ) : null}
      {typeof be === "number" && c.extra_cost !== undefined ? (
        <div className="sd-check sd-check--neutral" data-testid="sd-breakeven">
          <b aria-hidden="true">⇄</b>
          <span>
            {typeof c.extra_cost === "number" && c.extra_cost > 0
              ? `Hoà vốn: chi thêm ${vnd(c.extra_cost)} cần ≥ ${fmt(be, 0)} đơn thêm.`
              : `Tiết kiệm ${vnd(typeof c.extra_cost === "number" ? -c.extra_cost : null)}. Vẫn có lời nếu mất tối đa ${fmt(Math.abs(be), 0)} đơn.`}
          </span>
        </div>
      ) : null}
    </div>
  );
}
