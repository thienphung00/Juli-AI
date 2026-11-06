"use client";

import { fmt, vnd } from "../../lib/shopee-analytics/format";
import { breachLine, expectedRows, spendLine, sureRows, type NumberRow } from "../../lib/shopee-decisions/model";
import type { Card } from "../../lib/shopee-decisions/types";

/**
 * The card's numbers, as `CardWhatIf.dc.html` lays them out: five numbers before -> after in VND and %,
 * in two layers. "Chắc chắn" is arithmetic on the shop's real orders (buyers behaving as before; number
 * (2) is the break-even extra orders, never a red "0đ / 1đ"); "Dự kiến" is a range, not a promise.
 */

function Rows({ rows, testPrefix }: { readonly rows: readonly NumberRow[]; readonly testPrefix: string }) {
  return (
    <>
      {rows.map((r) => (
        <div className="sd-num__row" data-testid={`${testPrefix}-${r.key}`} key={r.key} role="row">
          <span className="sd-num__k" role="cell">
            {r.label}
          </span>
          <span role="cell">{r.before}</span>
          <b role="cell">{r.after}</b>
          <span className={`sd-num__d sa-tone--${r.tone}`} role="cell">
            {r.dv}
          </span>
          <span className={`sd-num__d sa-tone--${r.tone}`} role="cell">
            {r.dp}
          </span>
        </div>
      ))}
    </>
  );
}

export function NumbersTable({ card }: { readonly card: Card }) {
  const five = card.five_numbers;
  if (!five) {
    // Listing changes (tên, mô tả, ảnh bìa, ẩn, gom phân loại) have no price or spend to put in numbers.
    return (
      <p className="sa-hint" data-testid="sd-no-numbers">
        Thay đổi nội dung listing: không có 5 con số trước khi chạy. Kết quả đo sau khi làm, ở Đo lường.
      </p>
    );
  }
  const days = card.window.days;
  const orders = five.orders.before;
  const sure = sureRows(card);
  const expected = expectedRows(card);
  return (
    <section aria-label="5 con số chính" className="sd-num" data-testid="sd-numbers" role="table">
      <div className="sd-num__head" role="row">
        <span role="columnheader">5 con số chính · {days} ngày</span>
        <span role="columnheader">Hiện tại (A)</span>
        <span role="columnheader">Sau thay đổi</span>
        <span role="columnheader">Thay đổi (₫)</span>
        <span role="columnheader">(%)</span>
      </div>
      <div className="sd-num__band" data-testid="sd-sure" role="row">
        <b>Chắc chắn</b>
        <span>
          tính lại từ {typeof orders === "number" ? fmt(orders, 0) : "—"} đơn thật, giả định khách mua như cũ · ② chỉ có ở “Dự kiến”, ở đây là số đơn hoà vốn
        </span>
      </div>
      <Rows rows={sure} testPrefix="sd-sure" />
      <div className="sd-num__band sd-num__band--exp" data-testid="sd-expected" role="row">
        <b>Dự kiến</b>
        <span>khoảng có thể xảy ra khi khách đổi hành vi (từ thấp đến cao), không phải cam kết</span>
      </div>
      <Rows rows={expected} testPrefix="sd-exp" />
      <p className="sd-num__foot">{five.chi_definition}. ③ tính trên doanh thu khách trả; ② = ΔGMV ÷ Δchi.</p>
    </section>
  );
}

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
