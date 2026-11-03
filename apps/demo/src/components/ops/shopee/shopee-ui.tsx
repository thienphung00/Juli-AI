"use client";

import Link from "next/link";
import { useState, type CSSProperties, type ReactNode } from "react";

import { fmtDate, fmtInt, fmtPct } from "../../../lib/ops/format";
import type { ShopeeOrderType } from "../../../lib/ops/types";
import { C, card } from "../ops-shell";

/** Shared bits of the two Shopee dashboards (ADR-117 step 4). Vietnamese labels and number formats. */

export const ORDER_TYPE_LABEL: Record<ShopeeOrderType, string> = {
  confirmed: "Đơn đã xác nhận",
  paid: "Đơn đã thanh toán",
  placed: "Đơn đã đặt",
};

export const CHART_COLORS = ["#c2306d", "#1d4f91", "#1f8a3d", "#c96a00", "#6b6b76", "#7a3fb0"];

/** "1.234.567 ₫". */
export function fmtVnd(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : `${fmtInt(n)} ₫`;
}

/** "tháng 10/2026" from "2026-10-01". */
export function fmtMonth(iso: string): string {
  const [y, m] = iso.slice(0, 10).split("-");
  return `${m}/${y}`;
}

/** ROAS "4,28"; `null` is "—". */
export function fmtRoas(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toFixed(2).replace(".", ",");
}

export function fmtCount(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : fmtInt(n);
}

export { fmtPct };

export function fmtRange(r: { readonly from: string; readonly to: string } | null | undefined): string {
  return r ? `${fmtDate(r.from)} – ${fmtDate(r.to)}` : "—";
}

export const TH: CSSProperties = { textAlign: "right", fontSize: 12, fontWeight: 600, color: C.muted, padding: "6px 8px", borderBottom: `1px solid ${C.line}`, whiteSpace: "nowrap" };
export const TD: CSSProperties = { textAlign: "right", fontSize: 13, padding: "6px 8px", borderBottom: `1px solid ${C.lineSoft}`, whiteSpace: "nowrap" };
export const TD_LEFT: CSSProperties = { ...TD, textAlign: "left", whiteSpace: "normal" };
export const TH_LEFT: CSSProperties = { ...TH, textAlign: "left" };

export function Section({ title, hint, children }: { readonly title: string; readonly hint?: string; readonly children: ReactNode }) {
  return (
    <section style={{ ...card, gap: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10, flexWrap: "wrap" }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>{title}</h2>
        {hint ? <span style={{ fontSize: 12, color: C.muted2 }}>{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

export function Empty({ children }: { readonly children: ReactNode }) {
  return (
    <p data-testid="shopee-empty" style={{ margin: 0, fontSize: 13, color: C.muted, background: "#faf9fb", border: `1px dashed ${C.line}`, borderRadius: 10, padding: "12px 14px" }}>
      {children}
    </p>
  );
}

export function TableWrap({ children, label }: { readonly children: ReactNode; readonly label: string }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table aria-label={label} style={{ borderCollapse: "collapse", width: "100%" }}>
        {children}
      </table>
    </div>
  );
}

type ShopeeTab = "san-pham" | "quang-cao" | "tu-khoa" | "don-hang" | "phan-tich" | "de-xuat";

export function PageTitle({ shopId, title, active }: { readonly shopId: string; readonly title: string; readonly active: ShopeeTab }) {
  const tab = (key: ShopeeTab, label: string) =>
    active === key ? (
      <span aria-current="page" key={key} style={{ fontWeight: 700, borderBottom: `2px solid ${C.pinkStrong}`, padding: "4px 2px" }}>
        {label}
      </span>
    ) : (
      <Link href={`/ops/shops/${shopId}/shopee/${key}`} key={key} style={{ color: C.pink, textDecoration: "none", padding: "4px 2px" }}>
        {label}
      </Link>
    );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <Link href={`/ops/shops/${shopId}`} style={{ fontSize: 14, textDecoration: "none", color: C.pink }}>
          ‹ Cài đặt shop
        </Link>
        <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>{title}</h1>
      </div>
      <nav aria-label="Dashboard Shopee" style={{ display: "flex", gap: 18, fontSize: 14 }}>
        {tab("san-pham", "Sản phẩm + luồng")}
        {tab("quang-cao", "Quảng cáo + khuyến mãi")}
        {tab("tu-khoa", "Từ khóa")}
        {tab("don-hang", "Đơn hàng")}
        {tab("phan-tich", "Phân tích shop")}
        {tab("de-xuat", "Đề xuất")}
      </nav>
    </div>
  );
}

export function OrderTypeSelect({ value, onChange }: { readonly value: ShopeeOrderType; readonly onChange: (v: ShopeeOrderType) => void }) {
  return (
    <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600 }}>
      Loại đơn hàng
      <select onChange={(e) => onChange(e.target.value as ShopeeOrderType)} style={{ font: "inherit", fontSize: 13, padding: "6px 8px", borderRadius: 8, border: `1px solid ${C.line}` }} value={value}>
        {(Object.keys(ORDER_TYPE_LABEL) as ShopeeOrderType[]).map((k) => (
          <option key={k} value={k}>
            {ORDER_TYPE_LABEL[k]}
          </option>
        ))}
      </select>
    </label>
  );
}

export function DayRange({ value, onApply }: { readonly value: { readonly from: string; readonly to: string } | null; readonly onApply: (from: string, to: string) => void }) {
  // The inputs show the server's resolved range until the user types; no effect needed.
  const [draft, setDraft] = useState<{ from?: string; to?: string }>({});
  const from = draft.from ?? value?.from ?? "";
  const to = draft.to ?? value?.to ?? "";
  const input: CSSProperties = { font: "inherit", fontSize: 13, padding: "5px 8px", borderRadius: 8, border: `1px solid ${C.line}` };
  return (
    <form
      aria-label="Khoảng ngày"
      onSubmit={(e) => {
        e.preventDefault();
        if (from && to) onApply(from, to);
      }}
      style={{ display: "flex", alignItems: "flex-end", gap: 8, flexWrap: "wrap" }}
    >
      <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600 }}>
        Từ ngày
        <input onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))} style={input} type="date" value={from} />
      </label>
      <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600 }}>
        Đến ngày
        <input onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))} style={input} type="date" value={to} />
      </label>
      <button disabled={!from || !to || from > to} style={{ font: "inherit", fontSize: 13, fontWeight: 600, padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.line}`, background: "#ffffff", cursor: "pointer" }} type="submit">
        Áp dụng
      </button>
    </form>
  );
}

/** What a dashboard says when the API answers with an error. */
export function errorText(e: unknown): string {
  const status = (e as { status?: number }).status;
  if (status === 409) return "Shop này không phải shop Shopee.";
  if (status === 404) return "Không tìm thấy shop.";
  if (status === 403) return "Bạn không có quyền xem dashboard này.";
  if (status === 422) return "Khoảng ngày không hợp lệ (tối đa 400 ngày).";
  return "Không tải được dữ liệu. Thử lại sau.";
}
