"use client";

import { useCallback, useEffect, useMemo, useState, type CSSProperties } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { addDaysIso, daysBetweenIso, fmtDate } from "../../lib/ops/format";
import type { OpsMe, ShopTermRow, SubscriptionPeriod, Term, TermState } from "../../lib/ops/types";
import { termStrip, TERM_STRIP_STYLE } from "../app-shell/term-strip";
import { ConfirmDialog, Toast } from "./ops-confirm";
import { C, OpsHeader, OpsPage, card } from "./ops-shell";

/**
 * Tab "Thời hạn" (D28.4, artboard OpsShopTerm.dc.html): every shop's term, sorted
 * by days left; Admins extend by package only (30 / 365 days, source "Hợp
 * đồng", the contract number required) through a confirm dialog; the right
 * panel shows the selected shop's periods and what its seller sees.
 */

type Filter = "all" | "soon" | "grace" | "read_only" | "none";
type Api = Pick<OpsApi, "terms" | "shopTerms" | "addTerm">;

const FILTERS: readonly [Filter, string][] = [
  ["all", "Tất cả"],
  ["soon", "Sắp hết hạn"],
  ["grace", "Ân hạn"],
  ["read_only", "Chỉ xem"],
  ["none", "Chưa đặt"],
];

const PILL_ON: CSSProperties = { color: "#ffffff", background: C.ink, border: `1px solid ${C.ink}` };
const PILL_OFF: CSSProperties = { color: C.body, background: "#ffffff", border: `1px solid ${C.line}` };

const STATE_PILL: Record<TermState, CSSProperties> = {
  ok: { color: C.green, background: "#e3f5e8" },
  soon: { color: C.amber, background: "#fff4e0" },
  grace: { color: C.amber, background: "#fff4e0", border: "1px solid #f3d9a8" },
  read_only: { color: C.body, background: "#f0f0f3" },
  none: { color: C.muted2, background: "#f7f7f9", border: "1px dashed #d6d6dc" },
};

export function termPill(term: Term): string {
  switch (term.state) {
    case "ok":
    case "soon":
      return `còn ${term.days_left} ngày`;
    case "grace":
      return `Ân hạn · còn ${term.grace_days_left} ngày`;
    case "read_only":
      return "Chỉ xem";
    default:
      return "Chưa đặt";
  }
}

const GRID = "minmax(0, 1fr) 130px 120px 170px 250px";

function sortRows(rows: readonly ShopTermRow[]): ShopTermRow[] {
  return [...rows].sort((a, b) => {
    if (a.days_left === null && b.days_left === null) return a.shop_name.localeCompare(b.shop_name, "vi");
    if (a.days_left === null) return 1;
    if (b.days_left === null) return -1;
    return a.days_left - b.days_left;
  });
}

/** What the next package would do, from the dialog's point of view (the server decides). */
export function extension(term: Term, today: string, days: 30 | 365) {
  const active = term.expires_on !== null && (term.days_left ?? -1) >= 0;
  const start = active && term.expires_on ? term.expires_on : today;
  const end = addDaysIso(start, days);
  const rule = active
    ? `Shop còn hạn: kỳ mới nối tiếp từ ${fmtDate(term.expires_on)}.`
    : term.state === "none"
      ? "Shop chưa có thời hạn: kỳ mới tính từ hôm nay."
      : "Shop đã hết hạn: kỳ mới tính từ hôm nay.";
  return { start, end, daysLeft: daysBetweenIso(today, end), rule };
}

function actorName(email: string | null): string {
  return email ? email.split("@")[0] : "hệ thống";
}

function SellerSees({ term }: { readonly term: Term | null }) {
  const strip = termStrip(term);
  const style: CSSProperties = strip ? TERM_STRIP_STYLE[strip.tone] : { color: C.body, background: "#f7f7f9" };
  return (
    <div data-testid="term-seller-sees" style={{ borderRadius: 10, padding: "10px 12px", fontSize: 13, ...style, borderBottom: undefined }}>
      {strip ? strip.text : "Không thấy gì khác."}
    </div>
  );
}

function ExtendDialog({
  row,
  today,
  initialDays,
  onCancel,
  onDone,
  api,
}: {
  readonly row: ShopTermRow;
  readonly today: string;
  readonly initialDays: 30 | 365;
  readonly onCancel: () => void;
  readonly onDone: (end: string) => void;
  readonly api: Api;
}) {
  const [days, setDays] = useState<30 | 365>(initialDays);
  const [reference, setReference] = useState("");
  const next = extension(row, today, days);
  const ref = reference.trim();
  return (
    <ConfirmDialog
      confirmDisabled={ref === ""}
      confirmLabel="Gia hạn"
      note={next.rule}
      onCancel={onCancel}
      onConfirm={async () => {
        await api.addTerm(row.shop_id, days, ref);
        onDone(next.end);
      }}
      rows={[
        { k: "Dùng đến", before: row.expires_on ? fmtDate(row.expires_on) : "Chưa đặt", after: fmtDate(next.end) },
        { k: "Còn lại", before: row.days_left === null ? "—" : termPill(row), after: `còn ${next.daysLeft} ngày` },
      ]}
      title={`Gia hạn ${row.shop_name}?`}
    >
      <div role="group" aria-label="Gói" style={{ display: "flex", gap: 8 }}>
        {([30, 365] as const).map((n) => (
          <button
            aria-pressed={days === n}
            key={n}
            onClick={() => setDays(n)}
            style={{ font: "inherit", fontSize: 14, fontWeight: 600, borderRadius: 10, minHeight: 44, padding: "0 16px", cursor: "pointer", ...(days === n ? PILL_ON : { ...PILL_OFF, color: C.ink }) }}
            type="button"
          >
            Gói {n} ngày
          </button>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8, fontSize: 13, flexWrap: "wrap" }}>
        <span style={{ fontWeight: 600, color: "#ffffff", background: C.ink, borderRadius: 8, padding: "8px 12px" }}>Nguồn: Hợp đồng</span>
        <span
          aria-disabled="true"
          title="Có khi hệ thống thanh toán hoàn thành"
          style={{ color: "#a8a8b0", border: "1px dashed #d6d6dc", borderRadius: 8, padding: "8px 12px" }}
        >
          Thanh toán · tự động, sắp có
        </span>
      </div>
      <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: C.muted }}>
        Số hợp đồng
        <input
          aria-required="true"
          maxLength={120}
          onChange={(e) => setReference(e.target.value)}
          placeholder="HĐ-2026-014"
          style={{ font: "inherit", fontSize: 14, color: C.ink, border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 40, padding: "0 10px" }}
          type="text"
          value={reference}
        />
      </label>
    </ConfirmDialog>
  );
}

export function OpsTerms({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Api }) {
  const [rows, setRows] = useState<ShopTermRow[] | null>(null);
  const [today, setToday] = useState<string>("");
  const [failed, setFailed] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<{ readonly shopId: string; readonly periods: readonly SubscriptionPeriod[] } | null>(null);
  const [dialog, setDialog] = useState<{ shopId: string; days: 30 | 365 } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const isAdmin = me.role === "admin";

  const load = useCallback(() => {
    api
      .terms()
      .then((page) => {
        const sorted = sortRows(page.shops);
        setRows(sorted);
        setToday(page.today);
        setSelected((current) => current ?? sorted[0]?.shop_id ?? null);
      })
      .catch(() => setFailed(true));
  }, [api]);

  useEffect(() => {
    load();
  }, [load]);

  const loadPeriods = useCallback(
    (shopId: string) => {
      api
        .shopTerms(shopId)
        .then((page) => setHistory({ shopId, periods: page.periods }))
        .catch(() => setHistory({ shopId, periods: [] }));
    },
    [api],
  );

  useEffect(() => {
    if (selected) loadPeriods(selected);
  }, [selected, loadPeriods]);

  const visible = useMemo(() => (rows ?? []).filter((r) => filter === "all" || r.state === filter), [rows, filter]);
  const current = rows?.find((r) => r.shop_id === selected) ?? null;
  // The selected shop's periods, or null while they load.
  const periods = history && history.shopId === selected ? history.periods : null;
  const dialogRow = dialog ? rows?.find((r) => r.shop_id === dialog.shopId) ?? null : null;

  return (
    <OpsPage>
      <OpsHeader active="terms" me={me} />
      <main className="ops-settings" style={{ padding: "22px 28px", display: "grid", gridTemplateColumns: "minmax(0, 1fr) 400px", gap: 20, alignItems: "start" }}>
        <section style={{ display: "flex", flexDirection: "column", gap: 14, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Thời hạn</h1>
            <div role="group" aria-label="Lọc theo thời hạn" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
              {FILTERS.map(([id, label]) => (
                <button
                  aria-pressed={filter === id}
                  key={id}
                  onClick={() => setFilter(id)}
                  style={{ font: "inherit", fontSize: 13, fontWeight: 600, borderRadius: 999, minHeight: 36, padding: "0 12px", cursor: "pointer", ...(filter === id ? PILL_ON : PILL_OFF) }}
                  type="button"
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
          {failed ? <p role="alert">Không tải được thời hạn các shop.</p> : null}
          {rows === null && !failed ? <p role="status">Đang tải…</p> : null}
          {rows ? (
            <div style={{ ...card, padding: "8px 18px 14px", gap: 0, overflowX: "auto" }}>
              <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, fontSize: 12, fontWeight: 600, color: C.muted, padding: "8px 0", minWidth: 760 }}>
                <span>Shop</span>
                <span>Giai đoạn</span>
                <span>Dùng đến</span>
                <span>Còn lại</span>
                <span>{isAdmin ? "Gia hạn theo gói" : ""}</span>
              </div>
              {visible.length === 0 ? <p style={{ fontSize: 14, color: C.muted }}>Không có shop nào.</p> : null}
              {visible.map((r) => (
                <div
                  aria-current={selected === r.shop_id ? "true" : undefined}
                  data-testid="term-row"
                  key={r.shop_id}
                  onClick={() => setSelected(r.shop_id)}
                  style={{
                    display: "grid",
                    gridTemplateColumns: GRID,
                    gap: 10,
                    fontSize: 14,
                    borderTop: `1px solid ${C.lineSoft}`,
                    padding: "10px 0",
                    alignItems: "center",
                    cursor: "pointer",
                    minWidth: 760,
                    ...(selected === r.shop_id ? { background: "#fff7fa", boxShadow: `inset 3px 0 0 ${C.pinkStrong}` } : {}),
                  }}
                >
                  <button
                    onClick={() => setSelected(r.shop_id)}
                    style={{ font: "inherit", fontSize: 14, fontWeight: 700, color: C.ink, background: "transparent", border: 0, padding: "0 0 0 6px", textAlign: "left", cursor: "pointer" }}
                    type="button"
                  >
                    {r.shop_name}
                  </button>
                  <span style={{ color: C.body }}>{r.stage_label}</span>
                  <span>{r.expires_on ? fmtDate(r.expires_on) : "—"}</span>
                  <span data-testid="term-pill" style={{ fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "4px 10px", justifySelf: "start", ...STATE_PILL[r.state] }}>
                    {termPill(r)}
                  </span>
                  <span style={{ display: "flex", gap: 6 }}>
                    {isAdmin
                      ? ([30, 365] as const).map((n) => (
                          <button
                            aria-label={`Gói ${n} ngày cho ${r.shop_name}`}
                            key={n}
                            onClick={(e) => {
                              e.stopPropagation();
                              setSelected(r.shop_id);
                              setDialog({ shopId: r.shop_id, days: n });
                            }}
                            style={{ font: "inherit", fontSize: 13, fontWeight: 600, color: C.ink, background: "#ffffff", border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 36, padding: "0 10px", cursor: "pointer" }}
                            type="button"
                          >
                            Gói {n} ngày
                          </button>
                        ))
                      : null}
                  </span>
                </div>
              ))}
            </div>
          ) : null}
          <div className="ops-kpis" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10, fontSize: 13 }}>
            <div style={{ borderRadius: 10, padding: "10px 12px", background: "#e3f5e8", color: C.green }}>
              <b>Còn hạn</b> · Juli chạy đầy đủ
            </div>
            <div style={{ borderRadius: 10, padding: "10px 12px", background: "#fff4e0", color: C.amber }}>
              <b>Ân hạn 7 ngày</b> · vẫn chạy, seller thấy nhắc
            </div>
            <div style={{ borderRadius: 10, padding: "10px 12px", background: "#f0f0f3", color: C.body }}>
              <b>Chỉ xem</b> · không thẻ mới, không chạy hành động
            </div>
          </div>
        </section>

        <aside style={{ display: "flex", flexDirection: "column", gap: 14, paddingTop: 50 }}>
          {current ? (
            <>
              <div data-testid="term-periods" style={{ ...card, gap: 8 }}>
                <b style={{ fontSize: 14 }}>{current.shop_name} · các kỳ sử dụng</b>
                <div style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr 1fr", gap: 8, fontSize: 12, fontWeight: 600, color: C.muted }}>
                  <span>Kỳ</span>
                  <span>Gói</span>
                  <span>Nguồn</span>
                </div>
                {periods === null ? <span style={{ fontSize: 13, color: C.muted }}>Đang tải…</span> : null}
                {periods && periods.length === 0 ? <span style={{ fontSize: 13, color: C.muted }}>Chưa có kỳ nào · Juli chạy bình thường.</span> : null}
                {(periods ?? []).map((p) => (
                  <div data-testid="term-period" key={p.id} style={{ display: "grid", gridTemplateColumns: "1.4fr 0.8fr 1fr", gap: 8, fontSize: 13, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6 }}>
                    <span>
                      {fmtDate(p.starts_on)} – {fmtDate(p.ends_on)}
                    </span>
                    <span>{p.days} ngày</span>
                    <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
                      <span style={{ fontWeight: 600, color: p.source === "payment" ? "#1d4f91" : C.ink }}>{p.source === "payment" ? "Thanh toán" : "Hợp đồng"}</span>
                      <span style={{ fontSize: 12, color: C.muted2, overflowWrap: "anywhere" }}>
                        {p.reference} · {actorName(p.actor_email)}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
              <div style={{ ...card, gap: 8 }}>
                <b style={{ fontSize: 14 }}>{current.shop_name} · seller thấy</b>
                <SellerSees term={current} />
              </div>
            </>
          ) : null}
        </aside>
      </main>
      {dialog && dialogRow ? (
        <ExtendDialog
          api={api}
          initialDays={dialog.days}
          key={`${dialog.shopId}-${dialog.days}`}
          onCancel={() => setDialog(null)}
          onDone={(end) => {
            setDialog(null);
            setToast(`Đã gia hạn ${dialogRow.shop_name} đến ${fmtDate(end)} · ghi 1 dòng nhật ký`);
            load();
            loadPeriods(dialogRow.shop_id);
          }}
          row={dialogRow}
          today={today}
        />
      ) : null}
      {toast ? <Toast onDone={() => setToast(null)} text={toast} /> : null}
    </OpsPage>
  );
}
