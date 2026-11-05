"use client";

import { useEffect, useState, type CSSProperties } from "react";

import { fmtDate } from "../../../lib/ops/format";
import type { DashboardsApi, OrderLeverKey, OrderRow, OrderStatusKey, OrdersPeriod, ShopeeOrders } from "../../../lib/shopee-analytics/dashboards-client";
import { C } from "../ops-shell";
import { OpsSkeleton } from "../ops-skeleton";
import { Empty, Section, TD, TD_LEFT, TH, TH_LEFT, TableWrap, errorText, fmtCount, fmtVnd } from "./shopee-ui";

/**
 * Đơn hàng, the read side (P92 B-8): the shop's orders one per row with the levers they used, status
 * and income per order. The order id is the short keyed hash (`order_key`); no buyer field is read
 * or drawn anywhere. Juli Ops "Xem như shop" and the seller's Demo both draw it.
 */

export type ShopeeOrdersApi = Pick<DashboardsApi, "shopeeOrders">;

export const ORDER_STATUS_LABEL: Record<OrderStatusKey, string> = {
  delivered: "Đã giao",
  refunded_accepted: "Hoàn tiền (đã nhận hàng)",
  in_transit: "Đang xử lý / vận chuyển",
  cancelled: "Đã hủy",
  refunded_not_received: "Hoàn tiền (chưa nhận hàng)",
};

export const ORDER_LEVER_LABEL: Record<OrderLeverKey, string> = {
  promotion: "Khuyến mãi",
  flash_sale: "Flash sale",
  voucher: "Voucher",
  combo: "Combo",
  affiliate: "Tiếp thị liên kết",
};

const PERIODS: readonly [OrdersPeriod, string][] = [
  ["7d", "7 ngày"],
  ["30d", "30 ngày"],
  ["90d", "90 ngày"],
];
const SORTS: readonly ["date" | "gmv" | "contribution", string][] = [
  ["date", "Ngày"],
  ["gmv", "GMV"],
  ["contribution", "Đóng góp"],
];
const PAGE = 100;

const SELECT: CSSProperties = { font: "inherit", fontSize: 13, padding: "6px 8px", borderRadius: 8, border: `1px solid ${C.line}` };
const LABEL: CSSProperties = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600 };

const statusText = (s: string) => ORDER_STATUS_LABEL[s as OrderStatusKey] ?? s;
const leverText = (l: string) => ORDER_LEVER_LABEL[l as OrderLeverKey] ?? l;

export function ShopeeOrdersBody({ shopId, api }: { readonly shopId: string; readonly api: ShopeeOrdersApi }) {
  const [period, setPeriod] = useState<OrdersPeriod>("30d");
  const [status, setStatus] = useState<OrderStatusKey | "">("");
  const [lever, setLever] = useState<OrderLeverKey | "">("");
  const [sort, setSort] = useState<"date" | "gmv" | "contribution">("date");
  const [offset, setOffset] = useState(0);
  const [first, setFirst] = useState<ShopeeOrders | null>(null);
  const [more, setMore] = useState<readonly OrderRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    api
      .shopeeOrders(shopId, { period, status: status || null, lever: lever || null, sort, limit: PAGE, offset })
      .then((r) => {
        if (!live) return;
        setError(null);
        if (offset === 0) {
          setFirst(r);
          setMore([]);
        } else {
          setMore((m) => [...m, ...r.orders]);
        }
      })
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [api, shopId, period, status, lever, sort, offset]);

  // A changed filter starts again from the first page.
  const change = <T,>(set: (v: T) => void) => (v: T) => {
    set(v);
    setOffset(0);
  };

  const rows = first ? [...first.orders, ...more] : [];
  const canMore = first !== null && rows.length > 0 && rows.length >= offset + PAGE;
  return (
    <>
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red }}>
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", gap: 16, alignItems: "flex-end", flexWrap: "wrap" }}>
        <label style={LABEL}>
          Khoảng thời gian
          <select onChange={(e) => change(setPeriod)(e.target.value as OrdersPeriod)} style={SELECT} value={period}>
            {PERIODS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label style={LABEL}>
          Trạng thái
          <select onChange={(e) => change(setStatus)(e.target.value as OrderStatusKey | "")} style={SELECT} value={status}>
            <option value="">Tất cả</option>
            {(Object.keys(ORDER_STATUS_LABEL) as OrderStatusKey[]).map((k) => (
              <option key={k} value={k}>
                {ORDER_STATUS_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label style={LABEL}>
          Đòn bẩy
          <select onChange={(e) => change(setLever)(e.target.value as OrderLeverKey | "")} style={SELECT} value={lever}>
            <option value="">Tất cả</option>
            {(Object.keys(ORDER_LEVER_LABEL) as OrderLeverKey[]).map((k) => (
              <option key={k} value={k}>
                {ORDER_LEVER_LABEL[k]}
              </option>
            ))}
          </select>
        </label>
        <label style={LABEL}>
          Sắp xếp
          <select onChange={(e) => change(setSort)(e.target.value as "date" | "gmv" | "contribution")} style={SELECT} value={sort}>
            {SORTS.map(([k, label]) => (
              <option key={k} value={k}>
                {label}
              </option>
            ))}
          </select>
        </label>
      </div>
      {!error && !first ? <OpsSkeleton /> : null}
      {first ? (
        <Section
          hint={`${first.order_basis?.label ?? ""}${first.window?.from && first.window?.to ? ` · ${fmtDate(first.window.from)} – ${fmtDate(first.window.to)}` : ""}`}
          title="Đơn hàng"
        >
          <div data-testid="orders-by-status" style={{ display: "flex", gap: 16, flexWrap: "wrap", fontSize: 13 }}>
            {Object.entries(first.by_status).map(([k, n]) => (
              <span key={k}>
                <b>{fmtCount(n)}</b> {statusText(k).toLowerCase()}
              </span>
            ))}
          </div>
          {first.privacy ? (
            <p data-testid="orders-privacy" style={{ margin: 0, fontSize: 12, color: C.muted2 }}>
              {first.privacy}
            </p>
          ) : null}
          {rows.length === 0 ? (
            <Empty>Chưa có đơn nào khớp bộ lọc trong khoảng này.</Empty>
          ) : (
            <TableWrap label="Đơn hàng">
              <thead>
                <tr>
                  <th style={TH_LEFT}>Mã đơn (băm)</th>
                  <th style={TH_LEFT}>Ngày</th>
                  <th style={TH_LEFT}>Trạng thái</th>
                  <th style={TH}>Sản phẩm</th>
                  <th style={TH_LEFT}>Đòn bẩy</th>
                  <th style={TH}>GMV</th>
                  <th style={TH}>Voucher</th>
                  <th style={TH}>Khuyến mãi</th>
                  <th style={TH}>Combo</th>
                  <th style={TH}>Khách trả</th>
                  <th style={TH}>Phí</th>
                  <th style={TH}>Giá vốn</th>
                  <th style={TH}>Đóng góp</th>
                  <th style={TH}>Thực nhận</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((o) => (
                  <tr data-testid={`order-${o.order_key}`} key={`${o.order_key}-${o.ordered_on}`}>
                    <td style={{ ...TD_LEFT, fontFamily: "ui-monospace, monospace" }}>{o.order_key}</td>
                    <td style={TD_LEFT}>{fmtDate(o.ordered_on)}</td>
                    <td style={TD_LEFT}>{statusText(o.status)}</td>
                    <td style={TD}>{fmtCount(o.units)}</td>
                    <td style={TD_LEFT}>{o.levers.length ? o.levers.map(leverText).join(", ") : "—"}</td>
                    <td style={TD}>{fmtVnd(o.gmv)}</td>
                    <td style={TD}>{fmtVnd(o.voucher)}</td>
                    <td style={TD}>{fmtVnd(o.promo_discount)}</td>
                    <td style={TD}>{fmtVnd(o.combo_discount)}</td>
                    <td style={TD}>{fmtVnd(o.buyer_paid)}</td>
                    <td style={TD}>{fmtVnd(o.fees)}</td>
                    <td style={TD}>{fmtVnd(o.cogs)}</td>
                    <td style={TD} title={o.contribution === null ? "Ngoài cơ sở tính lợi nhuận, hoặc thiếu giá vốn / phí" : undefined}>
                      {fmtVnd(o.contribution)}
                    </td>
                    <td style={TD}>{fmtVnd(o.income?.payout)}</td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
          )}
          {canMore ? (
            <div>
              <button
                onClick={() => setOffset(rows.length)}
                style={{ font: "inherit", fontSize: 13, fontWeight: 600, padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.line}`, background: "#ffffff", cursor: "pointer" }}
                type="button"
              >
                Xem thêm
              </button>
            </div>
          ) : null}
        </Section>
      ) : null}
    </>
  );
}
