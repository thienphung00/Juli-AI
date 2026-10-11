"use client";

import { useCallback, useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import type { AuditEntry, AuditKind, OpsMe } from "../../lib/ops/types";
import { auditWhat, auditWhen, auditWho } from "./audit-text";
import { C, OpsHeader, OpsPage, card } from "./ops-shell";

/** "Nhân viên" (Admin) and "Nhật ký" — reached from the overview nav (D25.2). */

type StaffRow = { id: string; email: string; role: string; role_label: string; active: boolean; signed_in: boolean };

export function OpsStaff({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Pick<OpsApi, "staff" | "putStaff"> }) {
  const [rows, setRows] = useState<StaffRow[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api
      .staff()
      .then((r) => setRows(r.data))
      .catch(() => setError("Chỉ Admin xem được danh sách nhân viên."));
  }, [api]);
  useEffect(() => {
    load();
  }, [load]);
  const save = async (body: { email: string; role: string; active: boolean }) => {
    setError(null);
    try {
      await api.putStaff(body);
      setEmail("");
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Không lưu được.");
    }
  };
  return (
    <OpsPage>
      <OpsHeader active="staff" me={me} />
      <main style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 16, maxWidth: 900 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700 }}>Nhân viên</h1>
        {error ? <p role="alert">{error}</p> : null}
        {rows ? (
          <div style={card}>
            {rows.map((r) => (
              <div data-testid="staff-row" key={r.id} style={{ display: "flex", gap: 12, alignItems: "center", borderTop: `1px solid ${C.lineSoft}`, paddingTop: 8, fontSize: 14 }}>
                <b style={{ flex: 1 }}>{r.email}</b>
                <select aria-label={`Vai trò ${r.email}`} onChange={(e) => void save({ email: r.email, role: e.target.value, active: r.active })} value={r.role}>
                  <option value="viewer">Xem</option>
                  <option value="operator">Vận hành</option>
                  <option value="admin">Admin</option>
                </select>
                <label style={{ display: "flex", gap: 4 }}>
                  <input checked={r.active} onChange={(e) => void save({ email: r.email, role: r.role, active: e.target.checked })} type="checkbox" />
                  Hoạt động
                </label>
                <span style={{ fontSize: 12, color: C.muted2 }}>{r.signed_in ? "đã đăng nhập" : "chưa đăng nhập"}</span>
              </div>
            ))}
            <div style={{ display: "flex", gap: 8, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 8 }}>
              <input aria-label="Email nhân viên mới" onChange={(e) => setEmail(e.target.value)} placeholder="ten@app-juli.com" type="email" value={email} />
              <select aria-label="Vai trò mới" onChange={(e) => setRole(e.target.value)} value={role}>
                <option value="viewer">Xem</option>
                <option value="operator">Vận hành</option>
                <option value="admin">Admin</option>
              </select>
              <button disabled={!email.includes("@")} onClick={() => void save({ email, role, active: true })} type="button">
                Thêm
              </button>
            </div>
          </div>
        ) : null}
      </main>
    </OpsPage>
  );
}

const AUDIT_FILTERS: [AuditKind | "all", string][] = [
  ["all", "Tất cả"],
  ["config", "Cấu hình"],
  ["view", "Xem như shop"],
  ["system", "Hệ thống"],
];
const AGRID = "120px 150px 190px minmax(0, 1fr)";

/** The row's group; an older backend sends no `kind`, so it is read off the action. */
export function auditKind(entry: AuditEntry): AuditKind {
  if (entry.kind) return entry.kind;
  if (entry.action.startsWith("view_as_")) return "view";
  if (entry.actor_email === "system") return "system";
  return "config";
}

/** "Nhật ký" — artboard OpsLog.dc.html (D27.4, D27.6). */
export function OpsAudit({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Pick<OpsApi, "audit"> & Partial<Pick<OpsApi, "overview">> }) {
  const [filter, setFilter] = useState<AuditKind | "all">("all");
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    let live = true;
    api
      .audit(null, filter === "all" ? null : filter)
      .then((r) => live && setRows(r.data))
      .catch(() => live && setRows([]));
    return () => {
      live = false;
    };
  }, [api, filter]);
  useEffect(() => {
    // Shop names for rows the backend sent without `shop_name`.
    if (!api.overview) return;
    let live = true;
    api
      .overview()
      .then((o) => live && setNames(Object.fromEntries(o.shops.map((x) => [x.shop_id, x.shop_name]))))
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, [api]);
  const shown = (rows ?? []).filter((e) => filter === "all" || auditKind(e) === filter);
  return (
    <OpsPage>
      <OpsHeader active="audit" me={me} />
      <main style={{ padding: "22px 28px", display: "flex", flexDirection: "column", gap: 14, maxWidth: 1100 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Nhật ký</h1>
          <div style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
            {AUDIT_FILTERS.map(([id, label]) => (
              <button
                aria-pressed={filter === id}
                key={id}
                onClick={() => setFilter(id)}
                style={{
                  font: "inherit",
                  fontSize: 13,
                  fontWeight: 600,
                  borderRadius: 999,
                  minHeight: 36,
                  padding: "0 12px",
                  cursor: "pointer",
                  ...(filter === id ? { color: "#ffffff", background: C.ink, border: `1px solid ${C.ink}` } : { color: C.body, background: "#ffffff", border: `1px solid ${C.line}` }),
                }}
                type="button"
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <section style={{ background: "#ffffff", border: `1px solid ${C.line}`, borderRadius: 14, padding: "8px 18px 14px", display: "flex", flexDirection: "column", overflowX: "auto" }}>
          <div style={{ display: "grid", gridTemplateColumns: AGRID, gap: 12, fontSize: 12, fontWeight: 600, color: C.muted, padding: "8px 0", minWidth: 640 }}>
            <span>Lúc</span>
            <span>Ai</span>
            <span>Shop</span>
            <span>Thay đổi</span>
          </div>
          {rows === null ? <span role="status">Đang tải…</span> : null}
          {rows !== null && shown.length === 0 ? <span style={{ color: C.muted2, padding: "9px 0" }}>Chưa có thao tác nào.</span> : null}
          {shown.map((entry) => {
            const merged = (entry.merged_count ?? 1) > 1;
            const shop = entry.shop_name ?? (entry.shop_id ? (names[entry.shop_id] ?? "—") : "Tất cả shop");
            return (
              <div
                data-kind={auditKind(entry)}
                data-testid="ops-audit-row"
                key={entry.id}
                style={{ display: "grid", gridTemplateColumns: AGRID, gap: 12, fontSize: 14, borderTop: `1px solid ${C.lineSoft}`, padding: "9px 0", alignItems: "start", minWidth: 640 }}
              >
                <span style={{ color: C.muted2 }}>{auditWhen(entry.at)}</span>
                <b>{auditWho(entry)}</b>
                <span>{shop}</span>
                <span style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  <span>{auditWhat(entry)}</span>
                  {merged ? (
                    <span
                      data-testid="audit-merged"
                      style={{ fontSize: 12, fontWeight: 600, color: C.amber, background: "#fff4e0", borderRadius: 6, padding: "2px 8px", alignSelf: "flex-start" }}
                    >
                      gộp {entry.merged_count} lần đổi trong 10 phút
                    </span>
                  ) : null}
                </span>
              </div>
            );
          })}
        </section>
        <section className="ops-kpis" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 12 }}>
          <div style={{ background: "#ffffff", border: `1px solid ${C.line}`, borderRadius: 14, padding: "14px 16px", fontSize: 13, display: "flex", flexDirection: "column", gap: 4 }}>
            <b style={{ fontSize: 14 }}>Thời gian lưu</b>
            <span style={{ color: C.body }}>Thay đổi cấu hình: 365 ngày. Xem như shop và việc hệ thống tự chạy: 90 ngày. Job mỗi đêm xoá dòng quá hạn.</span>
          </div>
        </section>
      </main>
    </OpsPage>
  );
}
