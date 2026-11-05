"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { BuilderApi, ExclusionList, ExclusionRow, PickerProduct } from "../../lib/shopee-decisions/builder-api";
import { READ_ONLY_TITLE } from "../seller-view-context";

/**
 * Cài đặt › Loại trừ sản phẩm (P92 B-1), artboard `CaiDatLoaiTru.dc.html`: the listings the shop
 * takes out of the optimisation (ngừng bán · quà tặng · hàng phân phối · khác), each with a reason
 * and Hoàn tác; add by search; the note that the shop totals still include their sales; the
 * Tổng quan preview. One component for the seller's Settings, Juli Ops' Cài đặt shop and the
 * read-only "Xem như shop" (no add, no undo, no reason change there).
 */

export type ExclusionsApi = Pick<BuilderApi, "exclusions" | "exclude" | "undoExclusion" | "products">;

/** What the Tổng quan preview shows: the 30-day GMV and the part of it from excluded listings. */
export interface ExclusionPreview {
  readonly gmv: number | null;
  readonly excludedGmv: number | null;
}

export const EXCLUSIONS_TITLE = "Loại trừ sản phẩm";
export const EXCLUSIONS_LEDE =
  "Sản phẩm không còn là một phần của việc tối ưu: đã ngừng bán, quà tặng, hàng phân phối… Juli sẽ không đề xuất gì cho chúng.";
export const TOTALS_NOTE_HEAD = "Tổng vẫn gồm đơn của các sản phẩm này.";
export const TOTALS_NOTE_BODY =
  "GMV và lợi nhuận toàn shop vẫn tính cả đơn của sản phẩm đã loại trừ, để khớp Seller Centre. Sản phẩm đã loại trừ chỉ không có thẻ đề xuất, không có dòng ở danh sách sản phẩm, không có trong Tự tạo phương án và không có cờ Phân tích.";

const DEFAULT_REASONS = [
  { key: "ngung_ban", label: "Ngừng bán" },
  { key: "qua_tang", label: "Quà tặng" },
  { key: "phan_phoi", label: "Hàng phân phối" },
  { key: "khac", label: "Khác" },
] as const;

const lower = (s: string) => s.toLocaleLowerCase("vi-VN");
const dot = (n: number) => Math.round(n).toLocaleString("vi-VN");
const vnd = (n: number | null | undefined) => (n === null || n === undefined ? "—" : `${dot(n)}đ`);

function dmy(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : null;
}

function failure(e: unknown): string {
  const status = (e as { status?: number }).status;
  const code = (e as { code?: string }).code;
  if (status === 409 || code === "not_a_shopee_shop") return "Loại trừ sản phẩm chỉ có cho shop Shopee.";
  if (status === 403) return "Bạn không có quyền thay đổi loại trừ sản phẩm.";
  if (status === 404) return "Sản phẩm này chưa được loại trừ.";
  if (status === 422) return "Không loại trừ được sản phẩm này. Kiểm tra lại sản phẩm và lý do.";
  return "Không tải được hoặc không lưu được. Thử lại sau.";
}

type Notice = { readonly kind: "added"; readonly row: { readonly item_id: string; readonly name: string; readonly label: string } } | { readonly kind: "undone"; readonly name: string } | { readonly kind: "changed"; readonly name: string; readonly label: string };

export function ExclusionsPanel({
  api,
  readOnly = false,
  loadPreview,
}: {
  readonly api: ExclusionsApi;
  /** Juli Ops "Xem như shop": reading only. */
  readonly readOnly?: boolean;
  /** Optional: the Tổng quan figures for the preview block. */
  readonly loadPreview?: () => Promise<ExclusionPreview>;
}) {
  const [list, setList] = useState<ExclusionList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<ExclusionPreview | null>(null);

  const load = useCallback(async () => {
    try {
      const next = await api.exclusions();
      setList(next);
      setError(null);
    } catch (e) {
      setError(failure(e));
    }
    if (loadPreview) {
      try {
        setPreview(await loadPreview());
      } catch {
        setPreview(null);
      }
    }
  }, [api, loadPreview]);

  useEffect(() => {
    // Initial fetch: the loader sets state once the response arrives.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  const reasons = list && list.reasons.length > 0 ? list.reasons : DEFAULT_REASONS;
  const labelOf = (key: string, fallback?: string) => lower(reasons.find((r) => r.key === key)?.label ?? fallback ?? key);

  const write = async (work: () => Promise<void>) => {
    setBusy(true);
    try {
      await work();
      setError(null);
      await load();
    } catch (e) {
      setError(failure(e));
    } finally {
      setBusy(false);
    }
  };

  const add = (product: PickerProduct, reason: string) =>
    write(async () => {
      const row = await api.exclude(product.item_id, reason);
      setNotice({ kind: "added", row: { item_id: product.item_id, name: row?.name ?? product.name, label: labelOf(reason, row?.reason_label) } });
    });
  const undo = (row: { item_id: string; name: string }) =>
    write(async () => {
      await api.undoExclusion(row.item_id);
      setNotice({ kind: "undone", name: row.name });
    });
  const change = (row: ExclusionRow, reason: string) =>
    write(async () => {
      await api.exclude(row.item_id, reason);
      setNotice({ kind: "changed", name: row.name, label: labelOf(reason) });
    });

  const rows = list?.excluded ?? [];
  return (
    <div className="sx-panel" data-testid="sx-panel">
      {error ? (
        <p className="sx-error" data-testid="sx-error" role="alert">
          {error}
        </p>
      ) : null}
      {!readOnly && list ? <AddForm busy={busy} onAdd={(p, r) => void add(p, r)} reasons={reasons} api={api} excludedIds={rows.map((r) => r.item_id)} /> : null}
      {notice ? (
        <p className="sx-notice" data-testid={`sx-notice-${notice.kind}`} role="status">
          {notice.kind === "added" ? (
            <>
              Đã loại trừ {notice.row.name} ({notice.row.label}). Thẻ, dòng sản phẩm và cờ Phân tích của sản phẩm này đã ẩn.
              {readOnly ? null : (
                <button className="sx-link" disabled={busy} onClick={() => void undo(notice.row)} type="button">
                  Hoàn tác
                </button>
              )}
            </>
          ) : notice.kind === "undone" ? (
            <>Đã hoàn tác. {notice.name} trở lại danh sách; thẻ và cờ Phân tích sẽ được tính lại ở lần cập nhật dữ liệu tới.</>
          ) : (
            <>
              Đã đổi lý do của {notice.name} thành {notice.label}.
            </>
          )}
        </p>
      ) : null}
      {list && rows.length === 0 ? (
        <div className="sx-empty" data-testid="sx-empty">
          <b>Chưa loại trừ sản phẩm nào</b>
          <span>Mọi sản phẩm đang bán đều nằm trong thẻ, danh sách và Tự tạo phương án.</span>
        </div>
      ) : null}
      {rows.length > 0 ? (
        <section aria-label="Sản phẩm đã loại trừ" className="sx-card" data-testid="sx-list">
          <h2 className="sx-h2">Đã loại trừ ({rows.length})</h2>
          <ul className="sx-rows">
            {rows.map((r) => (
              <li className="sx-row" data-testid={`sx-row-${r.item_id}`} key={r.item_id}>
                <div className="sx-row__main">
                  <b className="sx-row__name">{r.name}</b>
                  <span className="sx-muted">
                    {r.item_id}
                    {dmy(r.set_at) ? ` · loại trừ từ ${dmy(r.set_at)}` : ""}
                  </span>
                  {r.gmv_30d !== undefined && r.gmv_30d !== null ? (
                    <span className="sx-muted">
                      GMV 30 ngày {vnd(r.gmv_30d)}
                      {r.gmv_90d !== undefined && r.gmv_90d !== null ? ` · 90 ngày ${vnd(r.gmv_90d)}` : ""}
                    </span>
                  ) : null}
                </div>
                <span className="sx-chip">vẫn nằm trong tổng</span>
                <select
                  aria-label={`Lý do loại trừ ${r.name}`}
                  className="sx-select"
                  disabled={readOnly || busy}
                  onChange={(e) => void change(r, e.target.value)}
                  title={readOnly ? READ_ONLY_TITLE : undefined}
                  value={r.reason}
                >
                  {reasons.map((o) => (
                    <option key={o.key} value={o.key}>
                      {lower(o.label)}
                    </option>
                  ))}
                </select>
                {readOnly ? null : (
                  <button className="sx-btn sx-btn--ghost" disabled={busy} onClick={() => void undo(r)} type="button">
                    Hoàn tác
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {list ? (
        <p className="sx-totals" data-testid="sx-totals-note">
          <b>{TOTALS_NOTE_HEAD}</b> {TOTALS_NOTE_BODY}
        </p>
      ) : null}
      {list && preview && preview.gmv !== null ? (
        <section aria-label="Hiển thị ở Tổng quan" className="sx-card" data-testid="sx-preview">
          <h2 className="sx-h2">
            Hiển thị ở Tổng quan <span className="sx-muted">xem trước</span>
          </h2>
          <p className="sx-preview__line">
            <span>GMV 30 ngày</span> <b>{vnd(preview.gmv)}</b>
            {preview.excludedGmv !== null && preview.excludedGmv > 0 ? (
              <span className="sx-muted" data-testid="sx-preview-excluded">
                {" "}
                trong đó {vnd(preview.excludedGmv)} từ sản phẩm đã loại trừ
              </span>
            ) : null}
          </p>
          <p className="sx-muted">Một dòng nhỏ dưới số tổng; bấm dòng mở danh sách này.</p>
        </section>
      ) : null}
      {list ? (
        <section aria-label="Quy tắc shop" className="sx-card" data-testid="sx-rule">
          <h2 className="sx-h2">
            Quy tắc shop <span className="sx-muted">lưu theo phiên bản như Thông số shop</span>
          </h2>
          <p className="sx-muted">
            Mỗi lần thêm, đổi lý do hoặc hoàn tác ghi một dòng kiểm toán. Cũng nhận trong file Thông số shop (cột “loại trừ” và “lý do”), khi áp dụng sẽ có bước so sánh cũ → mới như các cột khác.
          </p>
        </section>
      ) : null}
      {!list && !error ? <p className="sx-muted">Đang tải…</p> : null}
    </div>
  );
}

function AddForm({
  api,
  reasons,
  busy,
  onAdd,
  excludedIds,
}: {
  readonly api: ExclusionsApi;
  readonly reasons: readonly { readonly key: string; readonly label: string }[];
  readonly busy: boolean;
  readonly onAdd: (product: PickerProduct, reason: string) => void;
  readonly excludedIds: readonly string[];
}) {
  const [q, setQ] = useState("");
  const [results, setResults] = useState<readonly PickerProduct[]>([]);
  const [picked, setPicked] = useState<PickerProduct | null>(null);
  const [reason, setReason] = useState(reasons[0]?.key ?? "ngung_ban");
  const [searchError, setSearchError] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    const text = q.trim();
    if (!text || (picked && picked.name === q)) {
      // Nothing to look up (or the text is the product just picked): clear the suggestions.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setResults([]);
      return;
    }
    const mine = ++seq.current;
    const timer = window.setTimeout(() => {
      api
        .products({ q: text, includeExcluded: false, limit: 8, sort: "gmv_90d" })
        .then((r) => {
          if (mine !== seq.current) return;
          setSearchError(false);
          setResults(r.products.filter((p) => !p.excluded && !excludedIds.includes(p.item_id)));
        })
        .catch(() => mine === seq.current && setSearchError(true));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [q, api, picked, excludedIds]);

  return (
    <section aria-label="Thêm sản phẩm loại trừ" className="sx-card" data-testid="sx-add">
      <h2 className="sx-h2">Thêm sản phẩm loại trừ</h2>
      <div className="sx-add">
        <label className="sx-field sx-field--grow">
          <span>Sản phẩm cần loại trừ</span>
          <input
            autoComplete="off"
            className="sx-input"
            onChange={(e) => {
              setQ(e.target.value);
              setPicked(null);
            }}
            placeholder="Tìm theo tên hoặc mã sản phẩm"
            type="search"
            value={q}
          />
          {results.length > 0 && !picked ? (
            <ul aria-label="Kết quả tìm" className="sx-results" role="listbox">
              {results.map((p) => (
                <li key={p.item_id} role="option" aria-selected={false}>
                  <button
                    className="sx-result"
                    onClick={() => {
                      setPicked(p);
                      setQ(p.name);
                      setResults([]);
                    }}
                    type="button"
                  >
                    <b>{p.name}</b> <span className="sx-muted">{p.item_id}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {searchError ? <span className="sx-muted">Không tìm được sản phẩm. Thử lại sau.</span> : null}
        </label>
        <label className="sx-field">
          <span>Lý do</span>
          <select className="sx-select" onChange={(e) => setReason(e.target.value)} value={reason}>
            {reasons.map((o) => (
              <option key={o.key} value={o.key}>
                {lower(o.label)}
              </option>
            ))}
          </select>
        </label>
        <button
          className="sx-btn"
          disabled={!picked || busy}
          onClick={() => {
            if (!picked) return;
            onAdd(picked, reason);
            setPicked(null);
            setQ("");
          }}
          type="button"
        >
          Loại trừ
        </button>
      </div>
      <p className="sx-muted">
        Lý do chọn một trong: {reasons.map((r) => lower(r.label)).join(" · ")}. Có thể đổi lý do bất cứ lúc nào; Hoàn tác đưa sản phẩm lại vào thẻ, danh sách và cờ Phân tích.
      </p>
    </section>
  );
}
