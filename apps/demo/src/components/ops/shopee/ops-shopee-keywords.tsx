"use client";

import { Fragment, useCallback, useEffect, useState, type CSSProperties } from "react";

import { OpsApiError, opsApi, type OpsApi } from "../../../lib/ops/api";
import { fmtDate } from "../../../lib/ops/format";
import type { KeywordCoverage, KeywordPattern, OpsMe, ShopeeKeyword, ShopeeKeywordBoard } from "../../../lib/ops/types";
import { C, OpsHeader, OpsPage } from "../ops-shell";
import { OpsSkeleton } from "../ops-skeleton";
import { Lines } from "./shopee-charts";
import { Empty, PageTitle, Section, TD, TD_LEFT, TH, TH_LEFT, TableWrap, errorText, fmtCount } from "./shopee-ui";

/**
 * Từ khóa (ADR-119, D81.4–D81.8): keyword combinations decomposed from the shop's own titles,
 * with the search volume / CPC / difficulty the owner looks up on shopeeanalytics.com in their
 * own browser and uploads weekly (public data). A keyword never looked up says "chưa tra",
 * never 0. Products with no keyword above the threshold are title-proposal candidates.
 */

type Api = Pick<OpsApi, "shopeeKeywords" | "generateKeywordSeeds" | "setKeywordSeed" | "uploadKeywordMetrics">;
/** What the board needs: the seller's Demo can only read (`canEdit` false never calls a write). */
export type ShopeeKeywordsApi = Pick<OpsApi, "shopeeKeywords"> & Partial<Omit<Api, "shopeeKeywords">>;

export const PATTERN_LABEL: Record<KeywordPattern, string> = {
  brand_type: "Thương hiệu + loại",
  brand_function: "Thương hiệu + công dụng",
  brand_material: "Thương hiệu + chất liệu",
  type_function_material: "Loại + công dụng + chất liệu",
  type_function: "Loại + công dụng",
  type_material: "Loại + chất liệu",
  function_material: "Công dụng + chất liệu",
  function_size: "Công dụng + dung tích",
  type_size: "Loại + dung tích",
  common_phrase: "Cụm chung nhiều tiêu đề",
};

export const COVERAGE_LABEL: Record<KeywordCoverage, string> = {
  da_tra: "Đã tra",
  khong_khop: "Không khớp",
  bi_chan: "Bị chặn",
  chua_tra: "Chưa tra",
};

const COVERAGE_COLOR: Record<KeywordCoverage, string> = { da_tra: C.green, khong_khop: C.muted, bi_chan: C.amber, chua_tra: C.muted2 };

const PRODUCT_STATUS: Record<ShopeeKeywordBoard["products"][number]["status"], string> = {
  de_xuat_tieu_de: "Đề xuất sửa tiêu đề",
  chua_du_du_lieu: "Chưa đủ dữ liệu",
  co_tu_khoa: "Có từ khóa",
};

const BUTTON: CSSProperties = { font: "inherit", fontSize: 13, fontWeight: 600, padding: "6px 14px", borderRadius: 8, border: `1px solid ${C.line}`, background: "#ffffff", cursor: "pointer" };
const INPUT: CSSProperties = { font: "inherit", fontSize: 13, padding: "5px 8px", borderRadius: 8, border: `1px solid ${C.line}` };
const LABEL: CSSProperties = { display: "flex", flexDirection: "column", gap: 3, fontSize: 12, fontWeight: 600 };

/** The volume cell: what was looked up shows its number; what was not says why. */
export function volumeText(k: ShopeeKeyword): string {
  if (k.coverage !== "da_tra") return COVERAGE_LABEL[k.coverage].toLowerCase();
  return fmtCount(k.latest?.volume);
}

function cpcText(k: ShopeeKeyword): string {
  const l = k.latest;
  if (!l || (l.cpc_min === null && l.cpc_max === null)) return "—";
  return `${fmtCount(l.cpc_min)} – ${fmtCount(l.cpc_max)}`;
}

/** Collection lines (JSON Lines) → records; a bad line is named, nothing is sent. */
export function parseCollection(text: string): { records: unknown[] } | { error: string } {
  const records: unknown[] = [];
  const lines = text.split(/\r?\n/);
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i].trim();
    if (!line) continue;
    try {
      records.push(JSON.parse(line));
    } catch {
      return { error: `Dòng ${i + 1} không phải JSON.` };
    }
  }
  if (records.length === 0) return { error: "Tệp không có dòng nào." };
  if (records.length > 500) return { error: "Tối đa 500 lượt tra mỗi lần tải lên." };
  return { records };
}

/** FileReader rather than `Blob.text()`, which older browsers (and jsdom) lack. */
function readText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Không đọc được tệp."));
    reader.readAsText(file, "utf-8");
  });
}

function apiMessage(e: unknown): string {
  if (e instanceof OpsApiError && e.status === 422) return `Tệp không đúng định dạng: ${e.detail}`;
  if (e instanceof OpsApiError && e.status === 403) return "Bạn không có quyền thực hiện thao tác này.";
  if (!(e instanceof OpsApiError) && e instanceof Error) return e.message;
  return errorText(e);
}

export function OpsShopeeKeywords({ me, shopId, api = opsApi }: { readonly me: OpsMe; readonly shopId: string; readonly api?: Api }) {
  return (
    <OpsPage>
      <OpsHeader me={me} shopId={shopId} />
      <main style={{ padding: "22px 28px 40px", display: "flex", flexDirection: "column", gap: 16 }}>
        <PageTitle active="tu-khoa" shopId={shopId} title="Shopee · Từ khóa" />
        <ShopeeKeywordsBody api={api} canEdit={me.role !== "viewer"} shopId={shopId} />
      </main>
    </OpsPage>
  );
}

/**
 * The page's content without Ops' chrome. Juli Ops (Vận hành+ edits) and the seller's Demo
 * (P92 B-8, `canEdit` false: no seed generation, no metrics upload, no "Giữ" boxes) both draw it.
 */
export function ShopeeKeywordsBody({
  shopId,
  api,
  canEdit,
  seller = false,
}: {
  readonly shopId: string;
  readonly api: ShopeeKeywordsApi;
  readonly canEdit: boolean;
  /** The seller's own view: hides the team's look-up worklist and the "Tạo từ khóa" hint. */
  readonly seller?: boolean;
}) {
  const [minVolume, setMinVolume] = useState<number | undefined>(undefined);
  const [draftMin, setDraftMin] = useState<string>("");
  const [board, setBoard] = useState<ShopeeKeywordBoard | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [brand, setBrand] = useState("");
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let live = true;
    api
      .shopeeKeywords(shopId, minVolume)
      .then((b) => {
        if (!live) return;
        setError(null);
        setBoard(b);
      })
      .catch((e) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [api, shopId, minVolume, reload]);

  const run = useCallback(async (work: () => Promise<string>) => {
    setBusy(true);
    setNotice(null);
    try {
      setNotice(await work());
      setError(null);
      setReload((n) => n + 1);
    } catch (e) {
      setError(apiMessage(e));
    } finally {
      setBusy(false);
    }
  }, []);

  const generate = () =>
    run(async () => {
      if (!api.generateKeywordSeeds) throw new Error("Chỉ xem.");
      const r = await api.generateKeywordSeeds(shopId, brand.trim() || null);
      return `Đã đọc ${r.titles} tiêu đề: ${r.created} từ khóa mới, ${r.updated} từ khóa cập nhật.`;
    });

  const upload = (file: File) =>
    run(async () => {
      const parsed = parseCollection(await readText(file));
      if ("error" in parsed) throw new Error(parsed.error);
      if (!api.uploadKeywordMetrics) throw new Error("Chỉ xem.");
      const r = await api.uploadKeywordMetrics(parsed.records);
      const s = r.by_status;
      const days = r.collected_on.map(fmtDate).join(", ");
      return `Đã lưu ${r.records} lượt tra ngày ${days}: ${s.ok ?? 0} có kết quả, ${s.blocked ?? 0} bị chặn, ${s.no_match ?? 0} không khớp.`;
    });

  const toggle = (k: ShopeeKeyword) =>
    run(async () => {
      if (!api.setKeywordSeed) throw new Error("Chỉ xem.");
      await api.setKeywordSeed(shopId, k.id, !k.enabled);
      return k.enabled ? `Đã bỏ "${k.keyword}".` : `Đã giữ lại "${k.keyword}".`;
    });

  return (
    <>
        {error ? (
          <p role="alert" style={{ margin: 0, color: C.red }}>
            {error}
          </p>
        ) : null}
        {notice ? (
          <p role="status" style={{ margin: 0, color: C.green, fontSize: 14 }}>
            {notice}
          </p>
        ) : null}
        {canEdit ? (
          <Section hint="Từ khóa ghép từ tiêu đề sản phẩm của shop; số liệu tra trên shopeeanalytics.com" title="Thu thập">
            <div style={{ display: "flex", gap: 12, alignItems: "flex-end", flexWrap: "wrap" }}>
              <label style={LABEL}>
                Thương hiệu (không bắt buộc)
                <input maxLength={100} onChange={(e) => setBrand(e.target.value)} style={INPUT} value={brand} />
              </label>
              <button disabled={busy} onClick={generate} style={BUTTON} type="button">
                Tạo từ khóa từ tiêu đề
              </button>
              <label style={LABEL}>
                Tải lên kết quả tra cứu (.jsonl)
                <input
                  accept=".jsonl,.json,application/json,text/plain"
                  disabled={busy}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void upload(file);
                    e.target.value = "";
                  }}
                  style={{ fontSize: 13 }}
                  type="file"
                />
              </label>
            </div>
          </Section>
        ) : null}
        {!error && !board ? <OpsSkeleton /> : null}
        {board ? (
          <>
            <CoverageSection board={board} seller={seller} />
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
              <label style={LABEL}>
                Ngưỡng lượt tìm/tháng
                <input inputMode="numeric" onChange={(e) => setDraftMin(e.target.value)} placeholder={String(board.min_volume)} style={{ ...INPUT, width: 120 }} value={draftMin} />
              </label>
              <button
                disabled={!/^\d+$/.test(draftMin)}
                onClick={() => setMinVolume(Number(draftMin))}
                style={BUTTON}
                type="button"
              >
                Áp dụng
              </button>
            </div>
            <KeywordsSection board={board} busy={busy} canEdit={canEdit} seller={seller} onToggle={toggle} open={open} setOpen={setOpen} />
            <ProductsSection board={board} />
          </>
        ) : null}
    </>
  );
}

function CoverageSection({ board, seller }: { readonly board: ShopeeKeywordBoard; readonly seller: boolean }) {
  const [copied, setCopied] = useState(false);
  const dates = board.collection_dates;
  return (
    <Section hint={dates.length ? `Ngày tra: ${dates.map(fmtDate).join(", ")}` : "Chưa có lượt tra nào"} title="Độ phủ">
      <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 14 }} data-testid="keyword-coverage">
        {(Object.keys(COVERAGE_LABEL) as KeywordCoverage[]).map((c) => (
          <span key={c}>
            <b style={{ color: COVERAGE_COLOR[c] }}>{COVERAGE_LABEL[c]}</b> {board.coverage[c]}
          </span>
        ))}
      </div>
      {!seller && board.to_look_up.length ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <span style={{ fontSize: 13, color: C.muted }}>Cần tra ({board.to_look_up.length}) — chưa tra hoặc bị chặn lần trước:</span>
          <textarea aria-label="Danh sách cần tra" readOnly rows={Math.min(6, board.to_look_up.length)} style={{ ...INPUT, fontFamily: "inherit", resize: "vertical" }} value={board.to_look_up.join("\n")} />
          <div>
            <button
              onClick={() => {
                void navigator.clipboard?.writeText(board.to_look_up.join("\n")).then(() => setCopied(true));
              }}
              style={BUTTON}
              type="button"
            >
              {copied ? "Đã chép" : "Chép danh sách"}
            </button>
          </div>
        </div>
      ) : null}
    </Section>
  );
}

function KeywordsSection({
  board,
  canEdit,
  seller,
  busy,
  onToggle,
  open,
  setOpen,
}: {
  readonly seller: boolean;
  readonly board: ShopeeKeywordBoard;
  readonly canEdit: boolean;
  readonly busy: boolean;
  readonly onToggle: (k: ShopeeKeyword) => void;
  readonly open: string | null;
  readonly setOpen: (id: string | null) => void;
}) {
  if (board.keywords.length === 0) {
    return (
      <Section title="Từ khóa">
        <Empty>
          {seller
            ? "Chưa có từ khóa cho shop này. Từ khóa được ghép từ tiêu đề sản phẩm và hiện ở đây khi đã tạo."
            : "Chưa có từ khóa. Bấm “Tạo từ khóa từ tiêu đề” để ghép từ khóa từ tiêu đề sản phẩm."}
        </Empty>
      </Section>
    );
  }
  return (
    <Section hint="Lượt tìm/tháng, CPC và độ khó theo shopeeanalytics.com, lần tra gần nhất" title="Từ khóa">
      <TableWrap label="Từ khóa">
        <thead>
          <tr>
            <th style={TH_LEFT}>Từ khóa</th>
            <th style={TH_LEFT}>Kiểu kết hợp</th>
            <th style={TH_LEFT}>Sản phẩm nguồn</th>
            <th style={TH}>Lượt tìm/tháng</th>
            <th style={TH}>CPC (₫)</th>
            <th style={TH}>Độ khó</th>
            <th style={TH}>Lần tra</th>
            {canEdit ? <th style={TH}>Giữ</th> : null}
          </tr>
        </thead>
        <tbody>
          {board.keywords.map((k) => (
            <Fragment key={k.id}>
              <tr style={{ opacity: k.enabled ? 1 : 0.5 }}>
                <td style={TD_LEFT}>
                  <button aria-expanded={open === k.id} onClick={() => setOpen(open === k.id ? null : k.id)} style={{ font: "inherit", fontSize: 13, background: "none", border: "none", padding: 0, color: C.pink, cursor: "pointer", textAlign: "left" }} type="button">
                    {k.keyword}
                  </button>
                </td>
                <td style={TD_LEFT}>{PATTERN_LABEL[k.pattern]}</td>
                <td style={TD_LEFT}>{k.products.length} sản phẩm</td>
                <td style={{ ...TD, color: k.coverage === "da_tra" ? C.ink : COVERAGE_COLOR[k.coverage] }}>{volumeText(k)}</td>
                <td style={TD}>{cpcText(k)}</td>
                <td style={TD}>{fmtCount(k.latest?.difficulty)}</td>
                <td style={TD}>{k.latest ? fmtDate(k.latest.collected_on) : "—"}</td>
                {canEdit ? (
                  <td style={TD}>
                    <input aria-label={`Giữ từ khóa ${k.keyword}`} checked={k.enabled} disabled={busy} onChange={() => onToggle(k)} type="checkbox" />
                  </td>
                ) : null}
              </tr>
              {open === k.id ? (
                <tr>
                  <td colSpan={canEdit ? 8 : 7} style={{ ...TD_LEFT, background: "#faf9fb" }}>
                    <KeywordDetail k={k} />
                  </td>
                </tr>
              ) : null}
            </Fragment>
          ))}
        </tbody>
      </TableWrap>
    </Section>
  );
}

function KeywordDetail({ k }: { readonly k: ShopeeKeyword }) {
  const trend = k.history.map((p) => ({ label: fmtDate(p.collected_on).slice(0, 5), volume: p.volume }));
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)", gap: 16, padding: "6px 0" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <b style={{ fontSize: 13 }}>Sản phẩm nguồn</b>
        <ul style={{ margin: 0, paddingLeft: 18, fontSize: 13 }}>
          {k.products.map((p) => (
            <li key={p.item_id}>{p.name ?? `Mã sản phẩm ${p.item_id}`}</li>
          ))}
        </ul>
        <b style={{ fontSize: 13 }}>Lượt tìm theo tuần</b>
        {trend.length >= 2 ? <Lines data={trend} label={`Lượt tìm theo tuần: ${k.keyword}`} series={[{ key: "volume", label: "Lượt tìm/tháng" }]} /> : <Empty>{trend.length === 1 ? `Mới có một lần tra (${fmtCount(trend[0].volume)}).` : "Chưa có số liệu theo tuần."}</Empty>}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <b style={{ fontSize: 13 }}>Từ khóa liên quan / ngách</b>
        {k.related.length === 0 ? (
          <Empty>Chưa có từ khóa liên quan (từ khóa này chưa được tra trực tiếp).</Empty>
        ) : (
          <TableWrap label={`Từ khóa liên quan: ${k.keyword}`}>
            <thead>
              <tr>
                <th style={TH_LEFT}>Từ khóa</th>
                <th style={TH}>Lượt tìm/tháng</th>
                <th style={TH}>Độ khó</th>
              </tr>
            </thead>
            <tbody>
              {k.related.map((r) => (
                <tr key={r.keyword}>
                  <td style={TD_LEFT}>{r.keyword}</td>
                  <td style={TD}>{fmtCount(r.volume)}</td>
                  <td style={TD}>{fmtCount(r.difficulty)}</td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </div>
    </div>
  );
}

function ProductsSection({ board }: { readonly board: ShopeeKeywordBoard }) {
  if (board.products.length === 0) {
    return (
      <Section title="Sản phẩm">
        <Empty>Chưa có danh sách sản phẩm từ tệp xuất Shopee.</Empty>
      </Section>
    );
  }
  return (
    <Section hint={`Đề xuất sửa tiêu đề: không có từ khóa nào từ ${fmtCount(board.min_volume)} lượt tìm/tháng`} title="Sản phẩm">
      <TableWrap label="Sản phẩm theo từ khóa">
        <thead>
          <tr>
            <th style={TH_LEFT}>Sản phẩm</th>
            <th style={TH}>Số từ khóa</th>
            <th style={TH}>Lượt tìm cao nhất</th>
            <th style={TH_LEFT}>Trạng thái</th>
          </tr>
        </thead>
        <tbody>
          {board.products.map((p) => (
            <tr key={p.item_id}>
              <td style={TD_LEFT}>{p.name}</td>
              <td style={TD}>{fmtCount(p.keywords)}</td>
              <td style={TD}>{fmtCount(p.best_volume)}</td>
              <td style={{ ...TD_LEFT, fontWeight: p.status === "de_xuat_tieu_de" ? 700 : 400, color: p.status === "de_xuat_tieu_de" ? C.pinkStrong : C.body }}>{PRODUCT_STATUS[p.status]}</td>
            </tr>
          ))}
        </tbody>
      </TableWrap>
    </Section>
  );
}
