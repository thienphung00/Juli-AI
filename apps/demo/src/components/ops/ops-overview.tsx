"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { fmtGmvShort, fmtRate, fmtUsd, fmtWhen } from "../../lib/ops/format";
import type { OpsMe, Overview, OverviewShop, StageId } from "../../lib/ops/types";
import { C, OpsHeader, OpsPage, STAGE_STYLE } from "./ops-shell";

/** "Tổng quan" — artboard OpsOverview.dc.html (D25.5). */

const GRID = "minmax(0, 2fr) 120px 120px 110px 130px 80px 80px 100px 110px 260px";
const CONN: Record<string, [string, string]> = {
  ok: ["Đang kết nối", C.green],
  expired: ["Token hết hạn", C.red],
  none: ["Chưa kết nối", C.muted2],
};
const FILTERS: [StageId | "all", string][] = [
  ["all", "Tất cả"],
  ["trial", "Thử nghiệm"],
  ["self", "Tự vận hành"],
  ["pilot", "Pilot đặc biệt"],
];

function ownerLine(shop: OverviewShop): string {
  if (shop.owned_by_team) return shop.invite_pending ? "Đội ngũ vận hành · đang mời seller" : "Đội ngũ vận hành · chưa bàn giao";
  return `seller: ${shop.owner_email ?? "—"}`;
}

export function OpsOverview({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Pick<OpsApi, "overview" | "disconnect"> }) {
  const [data, setData] = useState<Overview | null>(null);
  const [confirm, setConfirm] = useState<OverviewShop | null>(null);
  const [epoch, setEpoch] = useState(0);
  const [failed, setFailed] = useState(false);
  const [stage, setStage] = useState<StageId | "all">("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    let live = true;
    api
      .overview()
      .then((d) => live && setData(d))
      .catch(() => live && setFailed(true));
    return () => {
      live = false;
    };
  }, [api, epoch]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (data?.shops ?? []).filter(
      (s) =>
        (stage === "all" || s.stage === stage) &&
        (!q || s.shop_name.toLowerCase().includes(q) || (s.tiktok_shop_id ?? "").toLowerCase().includes(q)),
    );
  }, [data, stage, query]);

  const t = data?.totals;
  const kpis = t
    ? [
        { label: "Đã kết nối", value: String(t.connected), sub: `trên ${t.accounts} tài khoản`, color: undefined },
        { label: "Đang hoạt động", value: String(t.active), sub: "lấy dữ liệu trong 24 giờ", color: C.green },
        { label: "Mất kết nối", value: String(t.disconnected), sub: "token hết hạn", color: C.red },
        {
          label: "Thẻ đã duyệt (30 ngày)",
          value: String(t.cards_approved_30d),
          sub: `tỷ lệ duyệt ${fmtRate(t.approval_rate_30d)}`,
          color: undefined,
        },
        {
          label: "OpenAI tháng này",
          value: fmtUsd(t.openai_cost_month_usd),
          sub: t.openai_cap_alerts ? `${t.openai_cap_alerts} shop chạm trần` : "chưa shop nào chạm trần",
          color: t.openai_cap_alerts ? C.red : undefined,
        },
      ]
    : [];

  return (
    <OpsPage>
      <OpsHeader active="overview" me={me} />
      <main style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 18 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700 }}>Gian hàng đã kết nối</h1>
        {failed ? <p role="alert">Không tải được tổng quan.</p> : null}
        {!data && !failed ? <p role="status">Đang tải…</p> : null}
        {data ? (
          <>
            <div className="ops-kpis" style={{ display: "grid", gridTemplateColumns: "repeat(5, minmax(0, 1fr))", gap: 12 }}>
              {kpis.map((k) => (
                <div
                  key={k.label}
                  style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 12, padding: "14px 16px", display: "flex", flexDirection: "column", gap: 4 }}
                >
                  <span style={{ fontSize: 12, fontWeight: 600, color: C.muted }}>{k.label}</span>
                  <span style={{ fontSize: 26, fontWeight: 700, color: k.color }}>{k.value}</span>
                  <span style={{ fontSize: 12, color: C.muted2 }}>{k.sub}</span>
                </div>
              ))}
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <span style={{ fontSize: 13, fontWeight: 600 }}>Giai đoạn:</span>
              {FILTERS.map(([id, label]) => (
                <button
                  aria-pressed={stage === id}
                  key={id}
                  onClick={() => setStage(id)}
                  style={{
                    font: "inherit",
                    fontSize: 13,
                    fontWeight: 600,
                    borderRadius: 999,
                    minHeight: 36,
                    padding: "0 12px",
                    cursor: "pointer",
                    ...(stage === id
                      ? { color: "#fff", background: C.ink, border: `1px solid ${C.ink}` }
                      : { color: C.body, background: "#fff", border: `1px solid ${C.line}` }),
                  }}
                  type="button"
                >
                  {label}
                </button>
              ))}
              <label style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8, fontSize: 13 }}>
                Tìm shop
                <input
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Tên shop, mã shop"
                  style={{ font: "inherit", fontSize: 14, border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 36, padding: "0 10px", width: 220 }}
                  type="search"
                  value={query}
                />
              </label>
            </div>
            <div style={{ background: "#fff", border: `1px solid ${C.line}`, borderRadius: 14, overflowX: "auto" }}>
              <div role="table" aria-label="Gian hàng" style={{ minWidth: 1300 }}>
                <div
                  role="row"
                  style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "10px 16px", background: "#f7f7f9", fontSize: 12, fontWeight: 600, color: C.muted }}
                >
                  {["Shop", "Giai đoạn", "Kết nối", "Lấy dữ liệu", "Thẻ mở / duyệt / từ chối", "Tỷ lệ duyệt", "Chạy lỗi", "OpenAI tháng", "GMV 30 ngày", ""].map(
                    (h, i) => (
                      <span key={i} role="columnheader">
                        {h}
                      </span>
                    ),
                  )}
                </div>
                {rows.map((s) => {
                  const [connLabel, connColor] = CONN[s.connection] ?? CONN.none;
                  const none = s.connection === "none";
                  return (
                    <div
                      data-testid="ops-shop-row"
                      key={s.shop_id}
                      role="row"
                      style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, padding: "10px 16px", borderTop: `1px solid ${C.lineSoft}`, alignItems: "center", fontSize: 14 }}
                    >
                      <span role="cell" style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                        <b>{s.shop_name}</b>
                        <span style={{ fontSize: 12, color: C.muted2 }}>{ownerLine(s)}</span>
                      </span>
                      <span role="cell">
                        <span style={{ fontSize: 12, fontWeight: 600, borderRadius: 999, padding: "3px 10px", ...STAGE_STYLE[s.stage] }}>{s.stage_label}</span>
                      </span>
                      <span role="cell" style={{ fontSize: 13, fontWeight: 600, color: connColor }}>
                        {connLabel}
                      </span>
                      <span role="cell" style={{ fontSize: 13 }}>
                        {none ? "chưa kết nối shop" : fmtWhen(s.last_poll_at)}
                      </span>
                      <span role="cell" style={{ fontSize: 13 }}>
                        {none ? "— / — / —" : `${s.cards_open} / ${s.cards_approved_30d} / ${s.cards_rejected_30d}`}
                      </span>
                      <span role="cell" style={{ fontSize: 13 }}>
                        {fmtRate(s.approval_rate)}
                      </span>
                      <span role="cell" style={{ fontSize: 13, ...(s.failed_runs_30d > 0 ? { color: C.red, fontWeight: 700 } : {}) }}>
                        {none ? "—" : s.failed_runs_30d}
                      </span>
                      <span role="cell" style={{ fontSize: 13, display: "flex", flexDirection: "column" }}>
                        {fmtUsd(s.openai_cost_month_usd)}
                        {s.openai_cap_reached ? (
                          <span data-testid="cap-badge" style={{ fontSize: 11, fontWeight: 700, color: C.red }}>
                            Chạm trần {fmtUsd(s.openai_cap_usd)}
                          </span>
                        ) : null}
                      </span>
                      <span role="cell" style={{ fontSize: 13 }}>
                        {fmtGmvShort(s.gmv_30d)}
                      </span>
                      <span role="cell" style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
                        <Link href={`/ops/shops/${s.shop_id}/xem`} style={{ fontSize: 13, fontWeight: 600, textDecoration: "none", minHeight: 36, display: "inline-flex", alignItems: "center", color: C.pink }}>
                          Xem như shop
                        </Link>
                        <Link href={`/ops/shops/${s.shop_id}`} style={{ fontSize: 13, fontWeight: 600, textDecoration: "none", minHeight: 36, display: "inline-flex", alignItems: "center", color: C.pink }}>
                          Cài đặt
                        </Link>
                        {me.role === "admin" && s.connection !== "none" ? (
                          <button
                            onClick={() => setConfirm(s)}
                            style={{ font: "inherit", fontSize: 13, fontWeight: 600, color: C.red, background: "transparent", border: 0, minHeight: 36, cursor: "pointer" }}
                            type="button"
                          >
                            Huỷ kết nối
                          </button>
                        ) : null}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: C.muted2 }}>Không có dữ liệu người mua trên trang nội bộ.</p>
          </>
        ) : null}
      </main>
      {confirm ? (
        <DisconnectDialog
          onCancel={() => setConfirm(null)}
          onConfirm={async (reason, typed) => {
            await api.disconnect(confirm.shop_id, reason, typed);
            setConfirm(null);
            setEpoch(epoch + 1);
          }}
          shop={confirm}
        />
      ) : null}
    </OpsPage>
  );
}

/** D25.13 "Huỷ kết nối" confirmation (artboard OpsOverview.dc.html). */
function DisconnectDialog({
  shop,
  onCancel,
  onConfirm,
}: {
  readonly shop: OverviewShop;
  readonly onCancel: () => void;
  readonly onConfirm: (reason: string, typed: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = reason.trim().length > 0 && typed.trim() === shop.shop_name.trim() && !busy;
  const field = { font: "inherit", fontSize: 14, border: `1px solid ${C.line}`, borderRadius: 8, minHeight: 40, padding: "0 10px" } as const;
  return (
    <div style={{ position: "fixed", inset: 0, background: "rgba(26,26,31,0.42)", display: "flex", alignItems: "center", justifyContent: "center", padding: 16 }}>
      <div
        aria-labelledby="disc-q"
        aria-modal="true"
        role="dialog"
        style={{ boxSizing: "border-box", width: 520, maxWidth: "100%", background: "#fff", borderRadius: 16, padding: "22px 24px", display: "flex", flexDirection: "column", gap: 12, boxShadow: "0 20px 48px rgba(20,20,30,0.25)" }}
      >
        <h3 id="disc-q" style={{ margin: 0, fontSize: 19, fontWeight: 700 }}>
          Huỷ kết nối {shop.shop_name}?
        </h3>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14, color: C.body, display: "flex", flexDirection: "column", gap: 4 }}>
          <li>Juli thu hồi quyền TikTok của shop và ngừng lấy dữ liệu, ngừng tạo thẻ.</li>
          <li>Lượt chạy đang chờ được huỷ; không ghi gì thêm lên TikTok.</li>
          <li>Lịch sử, Quy tắc và kết quả đo được giữ lại; kết nối lại sẽ dùng tiếp.</li>
          <li>Seller nhận email báo đã huỷ kết nối.</li>
        </ul>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: C.muted }}>
          Lý do (bắt buộc, ghi vào nhật ký)
          <input onChange={(e) => setReason(e.target.value)} placeholder="Ví dụ: seller yêu cầu dừng dùng thử" style={field} type="text" value={reason} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: C.muted }}>
          Gõ tên shop để xác nhận
          <input onChange={(e) => setTyped(e.target.value)} placeholder={shop.shop_name} style={field} type="text" value={typed} />
        </label>
        <span style={{ fontSize: 12, color: C.muted2 }}>Chỉ vai trò Admin được huỷ kết nối.</span>
        {error ? (
          <span role="alert" style={{ color: C.red, fontSize: 13 }}>
            {error}
          </span>
        ) : null}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button
            onClick={onCancel}
            style={{ font: "inherit", fontSize: 14, fontWeight: 600, color: C.ink, background: "#fff", border: `1px solid ${C.line}`, borderRadius: 10, minHeight: 44, padding: "0 16px", cursor: "pointer" }}
            type="button"
          >
            Quay lại
          </button>
          <button
            disabled={!ready}
            onClick={async () => {
              setBusy(true);
              setError(null);
              try {
                await onConfirm(reason.trim(), typed.trim());
              } catch (e) {
                setError(e instanceof Error ? e.message : "Không huỷ kết nối được.");
                setBusy(false);
              }
            }}
            style={{ font: "inherit", fontSize: 14, fontWeight: 600, color: "#fff", background: C.red, border: 0, borderRadius: 10, minHeight: 44, padding: "0 18px", cursor: ready ? "pointer" : "not-allowed", opacity: ready ? 1 : 0.6 }}
            type="button"
          >
            Huỷ kết nối
          </button>
        </div>
      </div>
    </div>
  );
}
