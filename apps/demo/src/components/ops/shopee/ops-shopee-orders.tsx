"use client";

import { useCallback, useState, type CSSProperties } from "react";

import { OpsApiError, opsApi, type OpsApi } from "../../../lib/ops/api";
import { fmtDate } from "../../../lib/ops/format";
import { UnknownColumnError, OrderLayoutError, UnknownStatusError, previewOf, type OrderPreview, type OrderStatusName, type ParsedOrders } from "../../../lib/ops/orders/parse-orders";
import { postOrderLines, prepareOrderUpload, type PostProgress } from "../../../lib/ops/orders/upload";
import type { OpsMe } from "../../../lib/ops/types";
import { C, OpsHeader, OpsPage } from "../ops-shell";
import { PageTitle, Section, TD, TD_LEFT, TH, TH_LEFT, TableWrap, errorText, fmtCount } from "./shopee-ui";

/**
 * Đơn hàng (P90 step 2): the order export (Seller Centre › Đơn hàng › Xuất) is read in the
 * browser. Buyer name, phone, address, comment, note and tracking id are never read or sent;
 * the order id is replaced by a keyed hash with the shop's key (fetched for this upload only and
 * dropped). The page shows COUNTS, never a line.
 */

type Api = Pick<OpsApi, "orderRefKey" | "uploadOrderLines">;

const STATUS_LABEL: Record<OrderStatusName, string> = {
  delivered: "Đã giao",
  cancelled: "Đã hủy",
  in_transit: "Đang xử lý / vận chuyển",
  refunded_accepted: "Hoàn tiền đã chấp thuận (đã nhận hàng)",
  refunded_not_received: "Hoàn tiền đã chấp thuận (chưa nhận hàng)",
};

const BUTTON: CSSProperties = { font: "inherit", fontSize: 13, fontWeight: 600, padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.line}`, background: "#ffffff", cursor: "pointer" };

/** FileReader rather than `Blob.arrayBuffer()`, which jsdom lacks. */
function readBytes(file: File): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result as ArrayBuffer));
    reader.onerror = () => reject(new Error("Không đọc được tệp."));
    reader.readAsArrayBuffer(file);
  });
}

/** Vietnamese text for a failure; it names a column or a status, never a cell value. */
export function failureText(e: unknown): string {
  if (e instanceof UnknownColumnError) return `Tệp có cột chưa được duyệt: "${e.column}". Shopee có thể đã đổi mẫu xuất; chưa đọc gì từ tệp.`;
  if (e instanceof UnknownStatusError) return `Tệp có trạng thái đơn hàng chưa biết: "${e.status}".`;
  if (e instanceof OrderLayoutError) return `Tệp không đúng bố cục đã kiểm: ${e.message}`;
  if (e instanceof OpsApiError) {
    if (e.status === 503) return "Chưa cấu hình khóa băm mã đơn hàng trên máy chủ.";
    if (e.status === 403) return "Bạn không có quyền tải đơn hàng (cần vai trò Vận hành) hoặc shop chưa đồng ý dùng dữ liệu.";
    if (e.status === 422) return `Máy chủ từ chối dòng dữ liệu: ${e.detail}`;
    return errorText(e);
  }
  if (e instanceof Error) return e.message;
  return errorText(e);
}

export function OpsShopeeOrders({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  const canEdit = me.role !== "viewer";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [parsed, setParsed] = useState<ParsedOrders | null>(null);
  const [progress, setProgress] = useState<PostProgress | null>(null);

  const choose = useCallback(
    async (file: File) => {
      setBusy(true);
      setError(null);
      setProgress(null);
      setPreview(null);
      setParsed(null);
      try {
        const next = await prepareOrderUpload(await readBytes(file), shopId, api);
        setParsed(next);
        setPreview(previewOf(next));
      } catch (e) {
        setError(failureText(e));
      } finally {
        setBusy(false);
      }
    },
    [api, shopId],
  );

  const send = useCallback(async () => {
    if (!parsed) return;
    setBusy(true);
    setError(null);
    try {
      setProgress(await postOrderLines(parsed, shopId, api, setProgress));
    } catch (e) {
      setError(failureText(e));
    } finally {
      setBusy(false);
    }
  }, [api, parsed, shopId]);

  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="don-hang" shopId={shopId} title="Shopee · Đơn hàng" />
        {error ? (
          <p role="alert" style={{ margin: 0, color: C.red }}>
            {error}
          </p>
        ) : null}
        <Section hint="Tệp Order.all.*.xlsx từ Seller Centre › Đơn hàng › Xuất" title="Tải lên đơn hàng">
          <p style={{ margin: 0, fontSize: 13, color: C.muted }}>
            Tệp được đọc ngay trong trình duyệt này. Tên, số điện thoại, địa chỉ, mã vận đơn, nhận xét và ghi chú của người mua không bao giờ được đọc hay gửi đi. Mã đơn hàng được băm bằng khóa riêng của shop trước khi gửi.
          </p>
          {canEdit ? (
            <label style={{ display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600 }}>
              Chọn tệp đơn hàng (.xlsx)
              <input
                accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void choose(file);
                  e.target.value = "";
                }}
                style={{ fontSize: 13 }}
                type="file"
              />
            </label>
          ) : (
            <p style={{ margin: 0, fontSize: 13 }}>Chỉ vai trò Vận hành trở lên được tải đơn hàng.</p>
          )}
        </Section>
        {preview ? <PreviewSection busy={busy} canSend={canEdit && progress === null} onSend={() => void send()} preview={preview} /> : null}
        {progress ? (
          <p role="status" style={{ margin: 0, color: C.green, fontSize: 14 }}>
            Đã gửi {fmtCount(progress.posted)} / {fmtCount(progress.total)} dòng
            {progress.duplicates ? ` (${progress.duplicates} lô đã có sẵn, không ghi lại)` : ""}.
          </p>
        ) : null}
      </main>
    </OpsPage>
  );
}

function PreviewSection({ preview, canSend, busy, onSend }: { readonly preview: OrderPreview; readonly canSend: boolean; readonly busy: boolean; readonly onSend: () => void }) {
  return (
    <Section hint={`${fmtDate(preview.firstDay)} – ${fmtDate(preview.lastDay)}`} title="Đã đọc tệp">
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 14 }} data-testid="orders-preview">
        <span>
          <b>{fmtCount(preview.lines)}</b> dòng
        </span>
        <span>
          <b>{fmtCount(preview.orders)}</b> đơn
        </span>
        <span>
          <b>{fmtCount(preview.chunks)}</b> lô gửi
        </span>
      </div>
      <TableWrap label="Đơn theo trạng thái">
        <thead>
          <tr>
            <th style={TH_LEFT}>Trạng thái</th>
            <th style={TH}>Số đơn</th>
          </tr>
        </thead>
        <tbody>
          {(Object.keys(STATUS_LABEL) as OrderStatusName[]).map((status) => (
            <tr key={status}>
              <td style={TD_LEFT}>{STATUS_LABEL[status]}</td>
              <td style={TD}>{fmtCount(preview.statusCounts[status])}</td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
      {canSend ? (
        <div>
          <button disabled={busy} onClick={onSend} style={BUTTON} type="button">
            Tải lên {fmtCount(preview.lines)} dòng
          </button>
        </div>
      ) : null}
    </Section>
  );
}
