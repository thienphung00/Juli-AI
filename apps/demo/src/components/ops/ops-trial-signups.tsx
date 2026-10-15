"use client";

import { useCallback, useEffect, useState, type CSSProperties } from "react";

import { OpsApiError, opsApi, type OpsApi } from "../../lib/ops/api";
import type { OpsMe, TrialSignup, TrialSignupStatus, TrialSignupsPage } from "../../lib/ops/types";
import { auditWhen, SIGNUP_STATUS_LABELS } from "./audit-text";
import { Toast } from "./ops-confirm";
import { C, OpsHeader, OpsPage, card } from "./ops-shell";
import { OpsSkeleton } from "./ops-skeleton";

/**
 * Tab "Đăng ký dùng thử" (P33-F, D43): the sign-ups from app-juli.com/dang-ky,
 * newest first. Vận hành / Admin see the contact details (the prospect asked to
 * be called) and set the status; every change is one audit row. Xem gets a
 * plain "cần quyền Vận hành" — the API answers 403.
 */

type Api = Pick<OpsApi, "trialSignups" | "setTrialSignupStatus">;
type Filter = TrialSignupStatus | "all";

const STATUSES: readonly TrialSignupStatus[] = ["new", "contacted", "converted", "spam"];

const PILL_ON: CSSProperties = { color: "#ffffff", background: C.ink, border: `1px solid ${C.ink}` };
const PILL_OFF: CSSProperties = { color: C.body, background: "#ffffff", border: `1px solid ${C.line}` };

const STATUS_STYLE: Record<TrialSignupStatus, CSSProperties> = {
  new: { color: "#1d4f91", background: "#e6f0fd" },
  contacted: { color: C.amber, background: "#fff4e0" },
  converted: { color: C.green, background: "#e3f5e8" },
  spam: { color: C.body, background: "#f0f0f3" },
};

const GRID = "110px minmax(0, 1.1fr) minmax(0, 1.3fr) minmax(0, 1.2fr) minmax(0, 1.2fr) 170px";

/** A Zalo chat link for a Vietnamese mobile number (`0912…` → `zalo.me/0912…`). */
export function zaloHref(phone: string): string {
  return `https://zalo.me/${encodeURIComponent(phone)}`;
}

function sourceText(source: Readonly<Record<string, string>>): string {
  const utm = [source.utm_source, source.utm_medium, source.utm_campaign].filter(Boolean).join(" / ");
  return utm || (source.referrer ? `từ ${source.referrer}` : "trực tiếp");
}

function Row({
  row,
  canEdit,
  onChange,
}: {
  readonly row: TrialSignup;
  readonly canEdit: boolean;
  readonly onChange: (row: TrialSignup, status: TrialSignupStatus) => void;
}) {
  return (
    <div
      data-testid="signup-row"
      style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, fontSize: 14, borderTop: `1px solid ${C.lineSoft}`, padding: "10px 0", alignItems: "start", minWidth: 980 }}
    >
      <span style={{ color: C.muted }}>{auditWhen(row.created_at)}</span>
      <span style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
        <b style={{ overflowWrap: "anywhere" }}>{row.full_name}</b>
        <span style={{ fontSize: 12, color: C.muted2 }}>{row.role_label}</span>
      </span>
      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <a href={`tel:${row.phone}`} style={{ color: C.ink }}>
          {row.phone}
        </a>
        <a href={zaloHref(row.phone)} rel="noreferrer" style={{ color: C.pink, fontSize: 12 }} target="_blank">
          Nhắn Zalo
        </a>
        <a href={`mailto:${row.email}`} style={{ color: C.body, fontSize: 13, overflowWrap: "anywhere" }}>
          {row.email}
        </a>
      </span>
      <span style={{ overflowWrap: "anywhere" }}>{row.shop}</span>
      <span style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 0 }}>
        <span style={{ color: C.body, overflowWrap: "anywhere" }}>{row.note ?? "—"}</span>
        <span style={{ fontSize: 12, color: C.muted2, overflowWrap: "anywhere" }}>Nguồn: {sourceText(row.source)}</span>
      </span>
      <span style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {canEdit ? (
          <select
            aria-label={`Trạng thái của ${row.full_name}`}
            onChange={(e) => onChange(row, e.target.value as TrialSignupStatus)}
            style={{ font: "inherit", fontSize: 13, fontWeight: 600, borderRadius: 8, minHeight: 36, padding: "0 8px", border: `1px solid ${C.line}`, ...STATUS_STYLE[row.status] }}
            value={row.status}
          >
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {SIGNUP_STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        ) : (
          <span style={{ fontSize: 12, fontWeight: 700, borderRadius: 999, padding: "4px 10px", justifySelf: "start", ...STATUS_STYLE[row.status] }}>
            {row.status_label}
          </span>
        )}
        {row.handled_by ? (
          <span style={{ fontSize: 12, color: C.muted2 }}>
            {row.handled_by.split("@")[0]} · {auditWhen(row.handled_at)}
          </span>
        ) : null}
      </span>
    </div>
  );
}

export function OpsTrialSignups({ me, api = opsApi }: { readonly me: OpsMe; readonly api?: Api }) {
  const [page, setPage] = useState<TrialSignupsPage | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "forbidden" | "failed">("loading");
  const [filter, setFilter] = useState<Filter>("all");
  const [toast, setToast] = useState<string | null>(null);
  const canEdit = me.role === "operator" || me.role === "admin";

  const load = useCallback(() => {
    api
      .trialSignups(filter === "all" ? null : filter)
      .then((body) => {
        setPage(body);
        setState("ready");
      })
      .catch((error: unknown) => {
        setState(error instanceof OpsApiError && error.status === 403 ? "forbidden" : "failed");
      });
  }, [api, filter]);

  useEffect(() => {
    load();
  }, [load]);

  const change = (row: TrialSignup, status: TrialSignupStatus) => {
    if (status === row.status) return;
    api
      .setTrialSignupStatus(row.id, status)
      .then(() => {
        setToast(`${row.full_name}: ${SIGNUP_STATUS_LABELS[row.status]} → ${SIGNUP_STATUS_LABELS[status]} · ghi 1 dòng nhật ký`);
        load();
      })
      .catch(() => setToast("Không lưu được trạng thái. Thử lại."));
  };

  const total = page ? STATUSES.reduce((sum, s) => sum + (page.counts[s] ?? 0), 0) : 0;
  const filters: readonly [Filter, string][] = [
    ["all", `Tất cả${page ? ` · ${total}` : ""}`],
    ...STATUSES.map((s): [Filter, string] => [s, `${SIGNUP_STATUS_LABELS[s]}${page ? ` · ${page.counts[s] ?? 0}` : ""}`]),
  ];

  return (
    <OpsPage>
      <OpsHeader active="signups" me={me} />
      <main style={{ padding: "22px 28px", display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 700 }}>Đăng ký dùng thử</h1>
          <div role="group" aria-label="Lọc theo trạng thái" style={{ display: "inline-flex", gap: 6, flexWrap: "wrap" }}>
            {filters.map(([id, label]) => (
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
        <p style={{ margin: 0, fontSize: 13, color: C.muted }}>
          Từ app-juli.com/dang-ky. Gọi hoặc nhắn Zalo, kết nối shop cùng khách rồi “Mời seller” nhận shop; đổi trạng thái để cả đội biết.
        </p>
        {state === "loading" ? <OpsSkeleton rows={6} /> : null}
        {state === "forbidden" ? (
          <p role="status" style={{ ...card, maxWidth: 520 }}>
            Cần quyền Vận hành để xem danh sách đăng ký dùng thử.
          </p>
        ) : null}
        {state === "failed" ? <p role="alert">Không tải được danh sách đăng ký.</p> : null}
        {state === "ready" && page ? (
          <div style={{ ...card, padding: "8px 18px 14px", gap: 0, overflowX: "auto" }}>
            <div style={{ display: "grid", gridTemplateColumns: GRID, gap: 10, fontSize: 12, fontWeight: 600, color: C.muted, padding: "8px 0", minWidth: 980 }}>
              <span>Thời điểm</span>
              <span>Họ tên · vai trò</span>
              <span>Liên hệ</span>
              <span>Shop</span>
              <span>Ghi chú · nguồn</span>
              <span>Trạng thái</span>
            </div>
            {page.data.length === 0 ? <p style={{ fontSize: 14, color: C.muted }}>Chưa có đăng ký nào.</p> : null}
            {page.data.map((row) => (
              <Row canEdit={canEdit} key={row.id} onChange={change} row={row} />
            ))}
          </div>
        ) : null}
      </main>
      {toast ? <Toast onDone={() => setToast(null)} text={toast} /> : null}
    </OpsPage>
  );
}
