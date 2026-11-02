"use client";

import { useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { fmtWhen } from "../../lib/ops/format";
import type { IngestTokenRow, PairingCode, ShopConsent } from "../../lib/ops/types";
import { C, card } from "./ops-shell";

/**
 * Contract-client shops (owner decisions 2026-11-02, ADR-118): a Shopee shop with no
 * seller login, managed only in Ops. "Thêm shop hợp đồng" asks for the name and the
 * Seller Centre shop id; "Bật" turns the shop's data-use consent on with no fields;
 * then "Tạo mã kết nối" gives the Juli Connector (or the export loader) a 10-minute
 * code, and the connected sources can be revoked ("Thu hồi").
 */

const BUTTON = {
  font: "inherit",
  fontSize: 14,
  fontWeight: 600,
  color: "#ffffff",
  background: C.pinkStrong,
  border: 0,
  borderRadius: 10,
  minHeight: 40,
  padding: "0 16px",
  cursor: "pointer",
} as const;

const SECONDARY = { ...BUTTON, color: C.ink, background: "#ffffff", border: `1px solid ${C.line}` } as const;

const INPUT = {
  font: "inherit",
  fontSize: 14,
  border: `1px solid ${C.line}`,
  borderRadius: 8,
  padding: "8px 10px",
  minWidth: 220,
} as const;

type AddApi = Pick<OpsApi, "createContractShop">;

export function OpsAddContractShop({ api = opsApi, onCreated }: { readonly api?: AddApi; readonly onCreated: () => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [shopeeId, setShopeeId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reset = () => {
    setOpen(false);
    setName("");
    setShopeeId("");
    setError(null);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.createContractShop(name.trim(), shopeeId.trim() || null);
      reset();
      onCreated();
    } catch (e) {
      const status = (e as { status?: number }).status;
      setError(status === 409 ? "Mã shop Shopee này đã có trong Juli." : "Không tạo được shop. Kiểm tra tên và mã shop.");
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <div>
        <button onClick={() => setOpen(true)} style={SECONDARY} type="button">
          + Thêm shop hợp đồng
        </button>
      </div>
    );
  }
  return (
    <form
      aria-label="Thêm shop hợp đồng"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
      style={{ ...card, gap: 10 }}
    >
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Thêm shop hợp đồng</h2>
      <p style={{ margin: 0, fontSize: 13, color: C.muted }}>Shop Shopee không có tài khoản seller; đội ngũ quản lý trong Ops.</p>
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, fontWeight: 600 }}>
          Tên shop
          <input onChange={(e) => setName(e.target.value)} required style={INPUT} value={name} />
        </label>
        <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 13, fontWeight: 600 }}>
          Mã shop Shopee (không bắt buộc)
          <input inputMode="numeric" onChange={(e) => setShopeeId(e.target.value)} style={INPUT} value={shopeeId} />
        </label>
      </div>
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red, fontSize: 13 }}>
          {error}
        </p>
      ) : null}
      <div style={{ display: "flex", gap: 8 }}>
        <button disabled={busy || !name.trim()} style={BUTTON} type="submit">
          {busy ? "Đang tạo…" : "Tạo shop"}
        </button>
        <button onClick={reset} style={SECONDARY} type="button">
          Hủy
        </button>
      </div>
    </form>
  );
}

type ConsentApi = Partial<Pick<OpsApi, "consent" | "enableConsent" | "createPairingCode" | "ingestTokens" | "revokeIngestToken">>;

export function OpsShopConsent({
  shopId,
  canEdit,
  api = opsApi,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly api?: ConsentApi;
}) {
  const [state, setState] = useState<ShopConsent | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    if (!api.consent) return;
    api
      .consent(shopId)
      .then((s) => live && setState(s))
      .catch(() => live && setError("Không tải được trạng thái đồng ý."));
    return () => {
      live = false;
    };
  }, [api, shopId]);

  const enable = async () => {
    if (!api.enableConsent) return;
    setBusy(true);
    setError(null);
    try {
      setState(await api.enableConsent(shopId));
    } catch {
      setError("Không bật được. Thử lại sau.");
    } finally {
      setBusy(false);
    }
  };

  if (!state) return error ? <p role="alert">{error}</p> : null;
  if (!state.contract_client) return null;
  return (
    <div style={{ ...card, gap: 10 }}>
      <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700 }}>Đồng ý xử lý dữ liệu</h2>
      {state.enabled ? (
        <>
          <p role="status" style={{ margin: 0, fontSize: 14, color: C.green, fontWeight: 600 }}>
            Đã bật
          </p>
          <OpsShopConnector api={api} canEdit={canEdit} shopId={shopId} />
        </>
      ) : (
        <>
          <p style={{ margin: 0, fontSize: 13, color: C.muted }}>Shop hợp đồng: bật để Juli nhận và phân tích dữ liệu của shop.</p>
          {canEdit ? (
            <div>
              <button disabled={busy} onClick={() => void enable()} style={BUTTON} type="button">
                {busy ? "Đang bật…" : "Bật"}
              </button>
            </div>
          ) : null}
        </>
      )}
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red, fontSize: 13 }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

function OpsShopConnector({ shopId, canEdit, api }: { readonly shopId: string; readonly canEdit: boolean; readonly api: ConsentApi }) {
  const [code, setCode] = useState<PairingCode | null>(null);
  const [tokens, setTokens] = useState<readonly IngestTokenRow[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [epoch, setEpoch] = useState(0);

  useEffect(() => {
    let live = true;
    if (!api.ingestTokens) return;
    api
      .ingestTokens(shopId)
      .then((r) => live && setTokens(r.data))
      .catch(() => live && setError("Không tải được danh sách kết nối."));
    return () => {
      live = false;
    };
  }, [api, shopId, epoch]);

  const issue = async () => {
    if (!api.createPairingCode) return;
    setBusy(true);
    setError(null);
    try {
      setCode(await api.createPairingCode(shopId));
    } catch (e) {
      const status = (e as { status?: number }).status;
      setError(status === 429 ? "Đã có 5 mã chưa dùng. Đợi mã cũ hết hạn (10 phút)." : "Không tạo được mã. Thử lại sau.");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (tokenId: string) => {
    if (!api.revokeIngestToken) return;
    setError(null);
    try {
      await api.revokeIngestToken(shopId, tokenId);
      setEpoch((n) => n + 1);
    } catch {
      setError("Không thu hồi được. Thử lại sau.");
    }
  };

  const active = tokens.filter((t) => t.active);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, borderTop: `1px solid ${C.line}`, paddingTop: 10 }}>
      <h3 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>Kết nối dữ liệu</h3>
      <p style={{ margin: 0, fontSize: 13, color: C.muted }}>Nhập mã vào Juli Connector (hoặc công cụ tải file xuất) để gửi dữ liệu Seller Centre của shop này.</p>
      {canEdit ? (
        <div>
          <button disabled={busy} onClick={() => void issue()} style={SECONDARY} type="button">
            {busy ? "Đang tạo…" : "Tạo mã kết nối"}
          </button>
        </div>
      ) : null}
      {code ? (
        <p aria-label="Mã kết nối" style={{ margin: 0, fontSize: 13 }}>
          <strong style={{ fontSize: 20, letterSpacing: 2, fontFamily: "ui-monospace, monospace" }}>{code.code}</strong>
          <span style={{ color: C.muted }}> · dùng một lần, hết hạn sau {Math.round(code.ttl_seconds / 60)} phút</span>
        </p>
      ) : null}
      <p style={{ margin: 0, fontSize: 13 }}>{active.length ? `${active.length} nguồn đang kết nối` : "Chưa có nguồn nào kết nối."}</p>
      {active.length ? (
        <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 6 }}>
          {active.map((t) => (
            <li key={t.id} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13 }}>
              <span>{t.client_label ?? "Nguồn không tên"}</span>
              <span style={{ color: C.muted2 }}>dùng lần cuối: {t.last_used_at ? fmtWhen(t.last_used_at) : "chưa"}</span>
              {canEdit ? (
                <button onClick={() => void revoke(t.id)} style={{ ...SECONDARY, minHeight: 32, fontSize: 13, marginLeft: "auto" }} type="button">
                  Thu hồi
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <p role="alert" style={{ margin: 0, color: C.red, fontSize: 13 }}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
