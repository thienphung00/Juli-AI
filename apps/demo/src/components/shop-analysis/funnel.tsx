import {
  addToCartRate,
  aov,
  BUY_NOW,
  CTOR_DIRECT,
  ctor,
  ctr,
  ESTIMATED,
  isSellerContent,
  NOT_PROVIDED,
} from "../../lib/shop-analysis/derive";
import type { ChannelKey, FunnelComparison } from "../../lib/shop-analysis/types";
import { money, num, pct } from "../../lib/vn-format";
import { ChangeChip } from "./shared";

interface BoxProps {
  readonly label: string;
  readonly prior: string;
  readonly last: string;
  readonly priorValue?: number | null;
  readonly lastValue?: number | null;
  readonly note?: string;
  readonly unavailable?: boolean;
}

function Box({ label, prior, last, priorValue, lastValue, note, unavailable }: BoxProps) {
  return (
    <li className={unavailable ? "funnel-box funnel-box--na" : "funnel-box"}>
      <span className="funnel-box__label">{label}</span>
      <span className="funnel-box__value">{last}</span>
      <span className="funnel-box__prior">trước: {prior}</span>
      {!unavailable && <ChangeChip prior={priorValue} last={lastValue} />}
      {note && <span className="funnel-box__note">{note}</span>}
    </li>
  );
}

/**
 * Backend `render._funnel_boxes`: Lượt hiển thị sản phẩm → CTR → Lượt nhấp →
 * Tỷ lệ thêm vào giỏ hàng → Số lượt thêm vào giỏ hàng → Đơn hàng SKU → CTOR →
 * AOV (SKU) → GMV. 30 ngày gần đây as the big number, 30 ngày trước under it.
 */
export function FunnelBoxes({
  channel,
  comparison,
}: {
  readonly channel: ChannelKey;
  readonly comparison: FunnelComparison;
}) {
  const p = comparison.prior;
  const q = comparison.last;
  const sellerContent = isSellerContent(channel);
  const boxes: BoxProps[] = [
    {
      label: "Lượt hiển thị sản phẩm",
      prior: num(p.impressions),
      last: num(q.impressions),
      priorValue: p.impressions,
      lastValue: q.impressions,
    },
    { label: "CTR (Tỷ lệ nhấp)", prior: pct(ctr(p)), last: pct(ctr(q)), priorValue: ctr(p), lastValue: ctr(q) },
    {
      label: "Lượt nhấp vào sản phẩm",
      prior: num(p.clicks),
      last: num(q.clicks),
      priorValue: p.clicks,
      lastValue: q.clicks,
    },
  ];
  if (p.add_to_cart === null || q.add_to_cart === null) {
    boxes.push(
      { label: "Tỷ lệ thêm vào giỏ hàng", prior: "—", last: NOT_PROVIDED, unavailable: true },
      { label: "Số lượt thêm vào giỏ hàng", prior: "—", last: NOT_PROVIDED, unavailable: true },
    );
  } else {
    boxes.push(
      {
        label: "Tỷ lệ thêm vào giỏ hàng",
        prior: pct(addToCartRate(p)),
        last: pct(addToCartRate(q)),
        priorValue: addToCartRate(p),
        lastValue: addToCartRate(q),
      },
      {
        label: "Số lượt thêm vào giỏ hàng",
        prior: num(p.add_to_cart),
        last: num(q.add_to_cart),
        priorValue: p.add_to_cart,
        lastValue: q.add_to_cart,
      },
    );
  }
  if (p.sku_orders === null || q.sku_orders === null) {
    for (const label of ["Đơn hàng SKU", "CTOR", "AOV (SKU)"]) {
      boxes.push({ label, prior: "—", last: "—", unavailable: true });
    }
  } else {
    boxes.push(
      {
        label: "Đơn hàng SKU",
        prior: num(p.sku_orders),
        last: num(q.sku_orders),
        priorValue: p.sku_orders,
        lastValue: q.sku_orders,
        note: sellerContent
          ? `đơn trên thêm giỏ: ${BUY_NOW}`
          : p.orders_estimated
            ? ESTIMATED
            : undefined,
      },
      {
        label: "CTOR",
        prior: pct(ctor(p)),
        last: pct(ctor(q)),
        priorValue: ctor(p),
        lastValue: ctor(q),
        note: sellerContent ? CTOR_DIRECT : undefined,
      },
      { label: "AOV (SKU)", prior: money(aov(p)), last: money(aov(q)), priorValue: aov(p), lastValue: aov(q) },
    );
  }
  boxes.push({ label: "GMV", prior: money(p.gmv), last: money(q.gmv), priorValue: p.gmv, lastValue: q.gmv });

  return (
    <ol className="funnel-flow">
      {boxes.map((box) => (
        <Box key={box.label} {...box} />
      ))}
    </ol>
  );
}
