"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  CONNECTOR_DATASETS,
  type ConnectorDatasetStatus,
  PairingRequestError,
  createSellerPairingCode,
  sellerConnectorStatus,
  listSellerIngestTokens,
  revokeSellerIngestToken,
  type SellerIngestToken,
  type SellerPairingCode,
} from "../../lib/connector-pairing";
import { AppPageHeader } from "../app-shell/page-header";

/** Cài đặt › Juli Connector (P96, owner 2026-11-06): the seller pairs their own Chrome with the shop. */
export function ConnectorSettings({
  auth,
  shopName,
  tabs,
}: {
  readonly auth: { readonly token: string; readonly shopId: string; readonly fetchImpl?: typeof fetch };
  readonly shopName: string;
  readonly tabs?: ReactNode;
}) {
  const { token, shopId, fetchImpl } = auth;
  // The page builds `auth` inline on every render: depend on its fields, not the object.
  const client = useMemo(() => ({ token, shopId, fetchImpl }), [token, shopId, fetchImpl]);
  const [code, setCode] = useState<SellerPairingCode | null>(null);
  const [tokens, setTokens] = useState<readonly SellerIngestToken[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [received, setReceived] = useState<readonly ConnectorDatasetStatus[] | null>(null);

  const reload = useCallback(() => {
    listSellerIngestTokens(client)
      .then(setTokens)
      .catch(() => setError("Không tải được danh sách trình duyệt đã kết nối."));
    sellerConnectorStatus(client)
      .then(setReceived)
      .catch(() => setReceived(null));
  }, [client]);

  useEffect(() => {
    const timer = window.setTimeout(reload, 0);
    return () => window.clearTimeout(timer);
  }, [reload]);

  const issue = async () => {
    setBusy(true);
    setError(null);
    try {
      setCode(await createSellerPairingCode(client));
    } catch (e) {
      const status = e instanceof PairingRequestError ? e.status : 0;
      setError(status === 429 ? "Đã có 5 mã chưa dùng. Đợi mã cũ hết hạn (10 phút)." : "Không tạo được mã. Thử lại sau.");
    } finally {
      setBusy(false);
    }
  };

  const revoke = async (tokenId: string) => {
    setError(null);
    try {
      await revokeSellerIngestToken(client, tokenId);
      reload();
    } catch {
      setError("Không ngắt được kết nối. Thử lại sau.");
    }
  };

  const active = tokens.filter((t) => t.active);
  return (
    <section aria-labelledby="connector-title" className="qd-page">
      <AppPageHeader
        eyebrow="Cài đặt › Juli Connector"
        lede="Juli Connector là tiện ích Chrome đọc báo cáo Seller Centre của shop (chỉ đọc) và gửi về Juli mỗi ngày."
        title={
          <>
            Kết nối Juli Connector <span className="sx-shop">Shopee · {shopName}</span>
          </>
        }
        titleId="connector-title"
      />
      {tabs}
      <div style={{ display: "flex", flexDirection: "column", gap: 12, maxWidth: 640 }}>
        <ol style={{ margin: 0, paddingLeft: 20, fontSize: 14, lineHeight: 1.6 }}>
          <li>Cài tiện ích Juli Connector trên Chrome.</li>
          <li>Bấm “Tạo mã kết nối” bên dưới, rồi dán mã vào tiện ích.</li>
          <li>
            Mở Seller Centre, đăng nhập shop, vào <strong>Phân Tích Bán Hàng › Truy cập</strong> rồi bấm “Đồng bộ hôm qua” trong tiện ích.
            Sau đó mỗi ngày tiện ích tự mở lần lượt các trang báo cáo trong một tab nền (chỉ đọc, không sửa gì); bấm biểu tượng tiện ích để
            xem đang đọc trang nào và cần mở trang nào.
          </li>
        </ol>
        <div>
          <button className="juli-btn juli-btn--primary juli-btn--default" disabled={busy} onClick={() => void issue()} type="button">
            {busy ? "Đang tạo…" : "Tạo mã kết nối"}
          </button>
        </div>
        {code ? (
          <p aria-label="Mã kết nối" style={{ margin: 0, fontSize: 14 }}>
            <strong style={{ fontSize: 22, letterSpacing: 2, fontFamily: "ui-monospace, monospace" }}>{code.code}</strong>
            <span> · dùng một lần, hết hạn sau {Math.round(code.ttl_seconds / 60)} phút</span>
          </p>
        ) : null}
        {received ? <ReceivedData received={received} /> : null}
        <h2 style={{ margin: "8px 0 0", fontSize: 16 }}>Trình duyệt đã kết nối</h2>
        {active.length ? (
          <ul style={{ margin: 0, padding: 0, listStyle: "none", display: "flex", flexDirection: "column", gap: 8 }}>
            {active.map((t) => (
              <li key={t.id} style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 14 }}>
                <span>{t.client_label ?? "Trình duyệt không tên"}</span>
                <span className="sa-hint">dùng lần cuối: {t.last_used_at ? new Date(t.last_used_at).toLocaleString("vi-VN") : "chưa"}</span>
                <button className="juli-btn juli-btn--default" onClick={() => void revoke(t.id)} style={{ marginLeft: "auto" }} type="button">
                  Ngắt kết nối
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p style={{ margin: 0, fontSize: 14 }}>Chưa có trình duyệt nào kết nối.</p>
        )}
        {error ? (
          <p role="alert" style={{ margin: 0 }}>
            {error}
          </p>
        ) : null}
      </div>
    </section>
  );
}

const day = (iso: string | null): string | null => (iso ? new Date(iso).toLocaleDateString("vi-VN") : null);

/** What Juli has received from the Connector, page by page (0.3.17). */
function ReceivedData({ received }: { readonly received: readonly ConnectorDatasetStatus[] }) {
  const byName = new Map(received.map((d) => [d.dataset, d]));
  return (
    <section aria-label="Juli đã nhận gì" data-testid="connector-received">
      <h2 style={{ margin: "8px 0 4px", fontSize: 16 }}>Juli đã nhận gì</h2>
      <table className="sa-table" style={{ fontSize: 13, width: "100%" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>Số liệu</th>
            <th style={{ textAlign: "left" }}>Số liệu đến ngày</th>
            <th style={{ textAlign: "left" }}>Trạng thái</th>
          </tr>
        </thead>
        {CONNECTOR_DATASETS.map((group) => (
          <tbody key={group.page}>
            <tr>
              <th colSpan={3} style={{ textAlign: "left", paddingTop: 8 }}>{group.page}</th>
            </tr>
            {group.items.map(([key, label]) => {
              const d = byName.get(key);
              const through = day(d?.last_period_end ?? null);
              const state =
                d?.drift === "drift"
                  ? "Tạm dừng: Seller Centre đã thay đổi, Juli đang cập nhật"
                  : d?.last_ingest_at
                    ? `Nhận lúc ${new Date(d.last_ingest_at).toLocaleString("vi-VN")}`
                    : "Chưa nhận";
              return (
                <tr data-testid={`received-${key}`} key={key}>
                  <td>{label}</td>
                  <td>{through ?? "—"}</td>
                  <td className={d?.drift === "drift" ? "sa-tone--warn" : d?.last_ingest_at ? undefined : "sa-hint"}>{state}</td>
                </tr>
              );
            })}
          </tbody>
        ))}
      </table>
    </section>
  );
}
