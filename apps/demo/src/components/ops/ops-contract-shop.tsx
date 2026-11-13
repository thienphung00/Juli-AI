"use client";

import { useEffect, useState } from "react";

import { opsApi, type OpsApi } from "../../lib/ops/api";
import { fmtWhen } from "../../lib/ops/format";
import type { IngestTokenRow, PairingCode } from "../../lib/ops/types";
import { C, card } from "./ops-shell";

/**
 * "Kết nối dữ liệu" on every shop's Ops page. "Tạo mã kết nối" gives the Juli
 * Connector (or the export loader) a 10-minute code. Connected sources can be
 * revoked ("Thu hồi"). Contract shops are no longer created from Ops.
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

type ConsentApi = Partial<Pick<OpsApi, "createPairingCode" | "ingestTokens" | "revokeIngestToken">>;

export function OpsShopConsent({
  shopId,
  canEdit,
  api = opsApi,
}: {
  readonly shopId: string;
  readonly canEdit: boolean;
  readonly api?: ConsentApi;
}) {
  return (
    <div style={{ ...card, gap: 10 }}>
      <OpsShopConnector api={api} canEdit={canEdit} shopId={shopId} />
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
      setError(
        status === 429
          ? "Đã có 5 mã chưa dùng. Đợi mã cũ hết hạn (10 phút)."
          : status === 409
            ? "Shop chưa có đồng ý xử lý dữ liệu, nên mã kết nối chưa dùng được."
            : "Không tạo được mã. Thử lại sau.",
      );
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
