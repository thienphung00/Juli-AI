"use client";

import { Fragment, useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../../lib/ops/api";
import { pp } from "../../../lib/shopee-analytics/format";
import type { OpsMe, ShopeeFlows, ShopeeOrderType, ShopeeProduct, ShopeeProducts } from "../../../lib/ops/types";
import { C, OpsHeader, OpsPage } from "../ops-shell";
import { OpsSkeleton } from "../ops-skeleton";
import { StackedBars } from "./shopee-charts";
import {
  DayRange,
  Empty,
  ORDER_TYPE_LABEL,
  OrderTypeSelect,
  PageTitle,
  Section,
  TD,
  TD_LEFT,
  TH,
  TH_LEFT,
  TableWrap,
  errorText,
  fmtCount,
  fmtMonth,
  fmtPct,
  fmtRange,
  fmtVnd,
} from "./shopee-ui";

/**
 * Sản phẩm + luồng (ADR-117 step 4, G3 / G5): GMV by traffic flow with "Trang shop" shown
 * as a child of "Thẻ sản phẩm" (never summed into the total), then the funnel per product
 * for one export period with Shopee's flags and the 12-month history. Measured data only.
 * Not built: grouping products into brand vs distribution (needs a per-shop group config).
 */

export type ShopeeProductsApi = Pick<OpsApi, "shopeeProducts" | "shopeeFlows">;
type Api = ShopeeProductsApi;

const FLOW_SERIES = [
  { key: "product_card", label: "Thẻ sản phẩm" },
  { key: "seller_video", label: "Video" },
  { key: "seller_live", label: "Live" },
  { key: "affiliate", label: "Tiếp thị liên kết" },
];

export function OpsShopeeProducts({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="san-pham" shopId={shopId} title="Shopee · Sản phẩm + luồng" />
        <ShopeeProductsBody api={api} shopId={shopId} />
      </main>
    </OpsPage>
  );
}

/** The page's content without Ops' chrome: Juli Ops and the seller's Demo (P92 B-8) both draw it. */
export function ShopeeProductsBody({ shopId, api }: { readonly shopId: string; readonly api: Api }) {
  const [orderType, setOrderType] = useState<ShopeeOrderType>("confirmed");
  const [range, setRange] = useState<{ from: string; to: string } | null>(null);
  const [period, setPeriod] = useState<{ from: string; to: string } | null>(null);
  const [flows, setFlows] = useState<ShopeeFlows | null>(null);
  const [products, setProducts] = useState<ShopeeProducts | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const flowQuery = { orderType, ...(range ? { from: range.from, to: range.to } : {}) };
    const productQuery = { orderType, ...(period ? { periodFrom: period.from, periodTo: period.to } : {}) };
    Promise.all([api.shopeeFlows(shopId, flowQuery), api.shopeeProducts(shopId, productQuery)])
      .then(([f, p]) => {
        if (!live) return;
        setError(null);
        setFlows(f);
        setProducts(p);
      })
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [api, shopId, orderType, range, period]);

  return (
    <>
        {error ? (
          <p role="alert" style={{ margin: 0, color: C.red }}>
            {error}
          </p>
        ) : null}
        <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
          <OrderTypeSelect onChange={setOrderType} value={orderType} />
          <DayRange onApply={(from, to) => setRange({ from, to })} value={flows?.range ?? null} />
        </div>
        {!error && (!flows || !products) ? <OpsSkeleton /> : null}
        {flows ? <FlowsSection flows={flows} /> : null}
        {products ? <ProductsSection onPeriod={setPeriod} products={products} /> : null}
    </>
  );
}

function FlowsSection({ flows }: { readonly flows: ShopeeFlows }) {
  const chart = flows.monthly.map((m) => ({ label: fmtMonth(m.month), ...m.streams }));
  return (
    <Section hint={`${fmtRange(flows.range)} · ${ORDER_TYPE_LABEL[flows.order_type]}`} title="GMV theo luồng">
      {!flows.has_data ? (
        <Empty>Chưa có dữ liệu luồng truy cập cho khoảng ngày này.</Empty>
      ) : (
        <>
          <TableWrap label="GMV theo luồng">
            <thead>
              <tr>
                <th style={TH_LEFT}>Luồng</th>
                <th style={TH}>GMV</th>
                <th style={TH}>Đơn</th>
                <th style={TH}>Lượt hiển thị</th>
                <th style={TH}>Lượt nhấp</th>
                <th style={TH}>Tỷ trọng</th>
              </tr>
            </thead>
            <tbody>
              {flows.flows.map((f) => (
                <Fragment key={f.stream}>
                  <tr>
                    <td style={{ ...TD_LEFT, fontWeight: 600 }}>{f.label}</td>
                    <td style={TD}>{f.has_total_row ? fmtVnd(f.gmv) : "—"}</td>
                    <td style={TD}>{fmtCount(f.orders)}</td>
                    <td style={TD}>{fmtCount(f.impressions)}</td>
                    <td style={TD}>{fmtCount(f.clicks)}</td>
                    <td style={TD}>{f.gmv && flows.total_gmv ? fmtPct(f.gmv / flows.total_gmv, 1) : "—"}</td>
                  </tr>
                  {f.children.map((c) => (
                    <tr data-testid={`child-${f.stream}-${c.segment}`} key={c.segment} style={{ color: C.muted }}>
                      <td style={{ ...TD_LEFT, paddingLeft: 26 }}>↳ {c.label}</td>
                      <td style={TD}>{fmtVnd(c.gmv)}</td>
                      <td style={TD}>{fmtCount(c.orders)}</td>
                      <td style={TD}>{fmtCount(c.impressions)}</td>
                      <td style={TD}>{fmtCount(c.clicks)}</td>
                      <td style={TD} />
                    </tr>
                  ))}
                </Fragment>
              ))}
              <tr>
                <td style={{ ...TD_LEFT, fontWeight: 700 }}>Tổng các luồng</td>
                <td style={{ ...TD, fontWeight: 700 }}>{fmtVnd(flows.total_gmv)}</td>
                <td style={{ ...TD, fontWeight: 700 }}>{fmtCount(flows.total_orders)}</td>
                <td style={TD} colSpan={3} />
              </tr>
              {flows.ads_overlay ? (
                <tr data-testid="ads-overlay" style={{ color: C.muted }}>
                  <td style={TD_LEFT}>{flows.ads_overlay.label} (lớp phủ, không cộng vào tổng)</td>
                  <td style={TD}>{fmtVnd(flows.ads_overlay.gmv)}</td>
                  <td style={TD}>{fmtCount(flows.ads_overlay.orders)}</td>
                  <td style={TD} colSpan={3} />
                </tr>
              ) : null}
            </tbody>
          </TableWrap>
          <p style={{ margin: 0, fontSize: 12, color: C.muted2 }}>
            Các dòng con (↳) là phần tách của luồng mẹ, không cộng vào tổng. Mỗi luồng tính theo loại đơn hàng đã chọn.
          </p>
          {chart.length > 0 ? <StackedBars data={chart} label="GMV theo tháng và luồng" series={FLOW_SERIES} /> : <Empty>Chưa có lịch sử theo tháng.</Empty>}
          {flows.shop_monthly.length > 0 ? (
            <TableWrap label="GMV cả shop theo tháng">
              <thead>
                <tr>
                  <th style={TH_LEFT}>Tháng</th>
                  {flows.shop_monthly.map((m) => (
                    <th key={m.month} style={TH}>
                      {fmtMonth(m.month)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style={TD_LEFT}>GMV cả shop</td>
                  {flows.shop_monthly.map((m) => (
                    <td key={m.month} style={TD}>
                      {fmtVnd(m.gmv)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td style={TD_LEFT}>Đơn</td>
                  {flows.shop_monthly.map((m) => (
                    <td key={m.month} style={TD}>
                      {fmtCount(m.orders)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </TableWrap>
          ) : null}
        </>
      )}
    </Section>
  );
}

function ProductsSection({ products, onPeriod }: { readonly products: ShopeeProducts; readonly onPeriod: (p: { from: string; to: string }) => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const current = products.period ? `${products.period.from}|${products.period.to}` : "";
  return (
    <Section hint={products.has_data ? `${products.items_total} sản phẩm · ${ORDER_TYPE_LABEL[products.order_type]}` : undefined} title="Phễu theo sản phẩm">
      {products.periods.length > 0 ? (
        <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600, maxWidth: 320 }}>
          Kỳ báo cáo
          <select
            onChange={(e) => {
              const [from, to] = e.target.value.split("|");
              if (from && to) onPeriod({ from, to });
            }}
            style={{ font: "inherit", fontSize: 13, padding: "6px 8px", borderRadius: 8, border: `1px solid ${C.line}` }}
            value={current}
          >
            {products.periods.map((p) => (
              <option key={`${p.from}|${p.to}`} value={`${p.from}|${p.to}`}>
                {fmtRange(p)} ({p.items} sản phẩm)
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {!products.has_data ? (
        <Empty>Chưa có dữ liệu sản phẩm cho kỳ này. Nạp file Seller Centre (Hiệu suất sản phẩm theo kỳ) để xem phễu.</Empty>
      ) : (
        <TableWrap label="Phễu theo sản phẩm">
          <thead>
            <tr>
              <th style={TH_LEFT}>Sản phẩm</th>
              <th style={TH}>Giá</th>
              <th style={TH}>Biên</th>
              <th style={TH}>Lượt hiển thị</th>
              <th style={TH}>Lượt nhấp</th>
              <th style={TH}>CTR</th>
              <th style={TH}>Thêm vào giỏ</th>
              <th style={TH}>Đơn</th>
              <th style={TH}>Nhấp → đơn</th>
              <th style={TH}>GMV</th>
              <th style={TH_LEFT}>Cờ Shopee</th>
            </tr>
          </thead>
          <tbody>
            {products.totals ? (
              <tr data-testid="products-total" style={{ background: "#faf9fb" }}>
                <td style={{ ...TD_LEFT, fontWeight: 700 }}>Tất cả sản phẩm</td>
                <td style={TD} />
                <td style={TD} />
                <ProductCells row={products.totals} />
                <td style={TD} />
              </tr>
            ) : null}
            {products.products.map((p) => (
              <Fragment key={p.item_id}>
                <tr>
                  <td style={TD_LEFT}>
                    <button
                      aria-expanded={open === p.item_id}
                      onClick={() => setOpen(open === p.item_id ? null : p.item_id)}
                      style={{ font: "inherit", fontSize: 13, background: "none", border: 0, padding: 0, cursor: "pointer", color: C.ink, textAlign: "left" }}
                      type="button"
                    >
                      {open === p.item_id ? "▾" : "▸"} {p.name ?? `Sản phẩm ${p.item_id}`}
                    </button>
                  </td>
                  <PriceMarginCells product={p} />
                  <ProductCells row={p} />
                  <td style={TD_LEFT}>
                    {p.flags.length === 0 ? "—" : p.flags.map((f) => (
                      <span key={f.flag} style={{ display: "inline-block", fontSize: 11, background: "#fff4e0", color: C.amber, borderRadius: 999, padding: "2px 8px", marginRight: 4 }}>
                        {f.label}
                      </span>
                    ))}
                  </td>
                </tr>
                {open === p.item_id ? (
                  <tr>
                    <td colSpan={11} style={{ ...TD_LEFT, background: "#faf9fb" }}>
                      <ProductDetail product={p} />
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            ))}
          </tbody>
        </TableWrap>
      )}
    </Section>
  );
}

/** P92 B-9: giá (min-max, list price struck through when higher) and biên with its basis label. */
function PriceMarginCells({ product }: { readonly product: ShopeeProduct }) {
  const lo = product.price_min ?? null;
  const hi = product.price_max ?? null;
  const price = lo === null && hi === null ? "—" : lo !== null && hi !== null && Math.round(lo) !== Math.round(hi) ? `${fmtVnd(lo)} – ${fmtVnd(hi)}` : fmtVnd(lo ?? hi);
  const struck = product.list_price != null && hi != null && Math.round(product.list_price) > Math.round(hi);
  const basis = product.margin_basis ?? "chưa tính";
  const known = basis !== "chưa tính" && product.margin_pct != null;
  return (
    <>
      <td data-testid={`price-${product.item_id}`} style={TD}>
        {price}
        {struck ? <s style={{ marginLeft: 6, color: C.muted }}>{fmtVnd(product.list_price ?? null)}</s> : null}
      </td>
      <td data-testid={`margin-${product.item_id}`} style={TD}>
        {known ? pp(product.margin_pct ?? null, 1) : "chưa tính"}
        <div style={{ fontSize: 11, color: C.muted }}>{basis}</div>
      </td>
    </>
  );
}

type FunnelNumbers = Pick<ShopeeProduct, "impressions" | "clicks" | "ctr" | "add_to_cart" | "orders" | "click_to_order" | "gmv">;

function ProductCells({ row }: { readonly row: FunnelNumbers }) {
  return (
    <>
      <td style={TD}>{fmtCount(row.impressions)}</td>
      <td style={TD}>{fmtCount(row.clicks)}</td>
      <td style={TD}>{fmtPct(row.ctr, 2)}</td>
      <td style={TD}>{fmtCount(row.add_to_cart)}</td>
      <td style={TD}>{fmtCount(row.orders)}</td>
      <td style={TD}>{fmtPct(row.click_to_order, 2)}</td>
      <td style={TD}>{fmtVnd(row.gmv)}</td>
    </>
  );
}

const STREAM_LABEL: Record<string, string> = { product_card: "Thẻ sản phẩm", seller_video: "Video", seller_live: "Live", affiliate: "Tiếp thị liên kết" };

function ProductDetail({ product }: { readonly product: ShopeeProduct }) {
  const flows = Object.entries(product.by_flow);
  return (
    <div style={{ display: "flex", gap: 24, flexWrap: "wrap", fontSize: 13 }}>
      <div>
        <b>Phễu</b>
        <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
          <li>Khách xem: {fmtCount(product.visitors)} · Lượt xem trang: {fmtCount(product.page_views)}</li>
          <li>Thêm vào giỏ / khách xem: {fmtPct(product.add_to_cart_rate, 2)}</li>
          <li>Người mua: {fmtCount(product.buyers)} · Số lượng: {fmtCount(product.units)}</li>
        </ul>
      </div>
      <div>
        <b>GMV theo luồng (kỳ này)</b>
        {flows.length === 0 ? (
          <div style={{ color: C.muted }}>Chưa có dữ liệu theo luồng.</div>
        ) : (
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {flows.map(([stream, v]) => (
              <li key={stream}>
                {STREAM_LABEL[stream] ?? stream}: {fmtVnd(v.gmv)} · {fmtCount(v.orders)} đơn
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <b>Lịch sử 12 tháng</b>
        {product.history.length === 0 ? (
          <div style={{ color: C.muted }}>Chưa có dữ liệu theo tháng.</div>
        ) : (
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>
            {product.history.map((h) => (
              <li key={h.month}>
                {fmtMonth(h.month)}: {fmtVnd(h.gmv)} · {fmtCount(h.orders)} đơn
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
