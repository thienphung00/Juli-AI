"use client";

import { useCallback, useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import type { AuditEntry, OpsMe } from "../../lib/ops/types";
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

export function OpsAudit({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Pick<OpsApi, "audit"> }) {
  const [rows, setRows] = useState<AuditEntry[] | null>(null);
  useEffect(() => {
    api
      .audit(null)
      .then((r) => setRows(r.data))
      .catch(() => setRows([]));
  }, [api]);
  return (
    <OpsPage>
      <OpsHeader active="audit" me={me} />
      <main style={{ padding: "24px 28px", display: "flex", flexDirection: "column", gap: 16, maxWidth: 900 }}>
        <h1 style={{ margin: 0, fontSize: 26, fontWeight: 700 }}>Nhật ký</h1>
        <div style={{ ...card, gap: 8 }}>
          {rows?.length === 0 ? <span style={{ color: C.muted2 }}>Chưa có thao tác nào.</span> : null}
          {(rows ?? []).map((entry) => (
            <div data-testid="ops-audit-row" key={entry.id} style={{ display: "grid", gridTemplateColumns: "92px minmax(0, 1fr)", gap: 8, fontSize: 13, borderTop: `1px solid ${C.lineSoft}`, paddingTop: 6 }}>
              <span style={{ color: C.muted2 }}>{auditWhen(entry.at)}</span>
              <span>
                <b>{auditWho(entry)}</b> {auditWhat(entry)}
              </span>
            </div>
          ))}
        </div>
      </main>
    </OpsPage>
  );
}
