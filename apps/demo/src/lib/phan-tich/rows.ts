/**
 * The ranking table under an open stream (ADR-109 Amendment 2 d.3, PtProduct /
 * PtContent / PtMobile) — pure. Rows come from one stored ranking
 * (`GET /v1/demo/analysis/rankings`, decision 5's maths unchanged); the card
 * join and the row detail's facts from the decisions list and the report.
 */

import type { ShopDiagnosisReport } from "../shop-analysis/types";
import type { CardIndex, CardRef } from "./cards";
import { count, dayMonth, kMoney, percent, perDay, signedKMoney } from "./format";
import { METRIC_COLS, specOf, type CellMetric, type Direction } from "./model";
import type { RankingPayload, RankingRow, RankedStream } from "./types";

export interface Fact {
  readonly k: string;
  readonly v: string;
}

export interface RowView {
  readonly id: string;
  /** Product rows: the seller SKU chip; `null` when nobody knows it. */
  readonly sku: string | null;
  /** Product name / video title / LIVE title. */
  readonly name: string;
  /** Content rows: "Đăng 21/09 · gắn SM-012" / "04/10 · 9 sản phẩm". */
  readonly meta: string | null;
  readonly before: string;
  readonly now: string;
  readonly gmv: string;
  readonly negative: boolean;
  /** Bar width, % of the largest row in the list. */
  readonly width: number;
  readonly confidence: "Rõ" | "Tham khảo" | null;
  readonly card: CardRef | null;
  /** Content rows: the first product it featured (for "Xem sản phẩm được gắn ›"). */
  readonly taggedProduct: string | null;
  readonly facts: readonly Fact[];
}

export interface RestLine {
  readonly k: string;
  readonly v: string;
}

export interface TableView {
  readonly title: string;
  /** "CTOR" — the column caption and the "Tổng · bằng số của ô CTOR" line. */
  readonly col: string;
  readonly rows: readonly RowView[];
  readonly rest: readonly RestLine[];
  readonly restSum: string;
  /** Content streams: "12 video ít lượt xem". */
  readonly restLabel: string;
  /** = the cell's ₫/day figure (`stream_factor_gmv`). */
  readonly total: string;
}

export interface TableContext {
  readonly report: ShopDiagnosisReport;
  readonly stream: RankedStream;
  readonly metric: CellMetric;
  readonly direction: Direction;
  readonly cards: CardIndex;
}

function formatValue(metric: CellMetric, value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (metric === "impressions") return count(value);
  if (metric === "aov") return kMoney(value);
  return percent(value, 1);
}

const CHANNEL_SHORT: Readonly<Record<string, string>> = {
  product_card: "Thẻ sản phẩm",
  shop_tab: "Tab cửa hàng",
  seller_video: "Video",
  seller_live: "LIVE",
  affiliate: "Liên kết",
};

/** "Video tăng · LIVE giảm" from the product's 5-channel profile (heroes only). */
function otherChannels(report: ShopDiagnosisReport, productId: string, stream: RankedStream): string | null {
  const profile = report.profiles?.find((p) => p.product_id === productId);
  if (!profile) return null;
  const moves: string[] = [];
  for (const row of profile.channels ?? []) {
    if (row.channel === stream || !CHANNEL_SHORT[row.channel]) continue;
    const prior = row.comparison.prior.gmv;
    const last = row.comparison.last.gmv;
    if (!prior && !last) continue;
    const ratio = prior ? last / prior - 1 : 1;
    if (Math.abs(ratio) < 0.1) continue;
    moves.push(`${CHANNEL_SHORT[row.channel]} ${ratio > 0 ? "tăng" : "giảm"}`);
  }
  return moves.length > 0 ? moves.join(" · ") : "Ổn định";
}

const ADVICE: Readonly<Record<CellMetric, string>> = {
  impressions: "Kiểm tra từ khoá tìm kiếm",
  ctr: "Kiểm tra ảnh bìa và tiêu đề",
  ctor: "Kiểm tra mô tả và giá",
  aov: "Thử mua nhiều giảm nhiều",
};

function proposalFact(row: RankingRow, card: CardRef | null, metric: CellMetric, negative: boolean): Fact | null {
  if (card?.proposal) return { k: "Đề xuất", v: card.proposal };
  if (!negative) return null;
  if (row.confidence !== "Rõ") return { k: "Gợi ý", v: "Theo dõi thêm" };
  return { k: "Gợi ý", v: ADVICE[metric] };
}

function productFacts(ctx: TableContext, row: RankingRow, card: CardRef | null, negative: boolean): Fact[] {
  const { metric, stream, report } = ctx;
  const facts: Fact[] = [];
  const window = (label: string) => ({ k: `${label} 30 ngày`, v: `${count(row.quantity_prior)} → ${count(row.quantity_last)}` });
  if (metric === "impressions") {
    facts.push(window("Lượt hiển thị"));
    const others = otherChannels(report, row.id, stream);
    if (others) facts.push({ k: "Kênh khác", v: others });
  } else if (metric === "ctr") {
    facts.push(window("Lượt bấm"));
    if (card) facts.push({ k: "Mã TikTok", v: card.codes.length > 0 ? card.codes.join(", ") : "Không có" });
  } else {
    const steps = metric === "ctor" ? row.steps : undefined;
    if (steps && (steps.add_to_cart_rate !== undefined || steps.orders_per_cart !== undefined)) {
      facts.push({
        k: "Hai bước của CTOR",
        v: `Thêm giỏ/bấm ${signedKMoney(steps.add_to_cart_rate ?? 0)} · Đơn/thêm giỏ ${signedKMoney(steps.orders_per_cart ?? 0)}`,
      });
    }
    facts.push(window("Đơn hàng SKU"));
  }
  const proposal = proposalFact(row, card, metric, negative);
  if (proposal) facts.push(proposal);
  return facts;
}

const CONTENT_QUANTITY: Readonly<Record<CellMetric, string>> = {
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "Lượt bấm sản phẩm",
  ctor: "Đơn trong phiên",
  aov: "Đơn",
};

function contentFacts(ctx: TableContext, row: RankingRow, negative: boolean): Fact[] {
  const facts: Fact[] = [{ k: `${CONTENT_QUANTITY[ctx.metric]} 30 ngày`, v: count(row.quantity_last) }];
  const products = row.product_ids ?? [];
  if (products.length > 0) {
    const first = products[0];
    const sku = ctx.report.seller_skus?.[first];
    const title = ctx.report.titles?.[first];
    const name = [sku, title].filter(Boolean).join(" ") || first;
    facts.push({ k: products.length > 1 ? `Sản phẩm (${products.length})` : "Sản phẩm", v: name });
  }
  if (negative) facts.push({ k: "Gợi ý", v: row.confidence === "Rõ" ? ADVICE[ctx.metric] : "Theo dõi thêm" });
  return facts;
}

function contentMeta(ctx: TableContext, row: RankingRow): string | null {
  const products = row.product_ids ?? [];
  const day = row.date ? dayMonth(row.date) : null;
  if (ctx.stream === "seller_live") {
    return [day, products.length > 0 ? `${products.length} sản phẩm` : null].filter(Boolean).join(" · ") || null;
  }
  const first = products[0];
  const tag = first ? `gắn ${ctx.report.seller_skus?.[first] ?? ctx.report.titles?.[first] ?? first}` : null;
  return [day ? `Đăng ${day}` : null, tag].filter(Boolean).join(" · ") || null;
}

/** LIVE names arrive as "<title> · dd/mm/yyyy": the date moves to the meta line. */
function contentTitle(row: RankingRow): string {
  return row.name.replace(/ · \d{2}\/\d{2}\/\d{4}$/, "");
}

export function tableView(ctx: TableContext, payload: RankingPayload): TableView {
  const spec = specOf(ctx.stream);
  const col = METRIC_COLS[ctx.metric];
  const product = spec.rowKind === "product";
  const source = product
    ? ctx.direction === "down"
      ? payload.down
      : payload.up
    : [...payload.down, ...payload.up].sort((a, b) => Math.abs(b.gmv_per_day) - Math.abs(a.gmv_per_day));
  const max = Math.max(1, ...source.map((r) => Math.abs(r.gmv_per_day)));
  const rows: RowView[] = source.map((row) => {
    const negative = row.gmv_per_day < 0;
    const card = product ? ctx.cards.find(row.id, ctx.metric) : null;
    const known = product ? ctx.cards.anyFor(row.id) : null;
    return {
      id: row.id,
      sku: product ? (row.seller_sku ?? ctx.report.seller_skus?.[row.id] ?? known?.sku ?? null) : null,
      name: product ? row.name : contentTitle(row),
      meta: product ? null : contentMeta(ctx, row),
      before: formatValue(ctx.metric, row.prior),
      now: formatValue(ctx.metric, row.last),
      gmv: signedKMoney(row.gmv_per_day),
      negative,
      width: Math.max(2, Math.round((Math.abs(row.gmv_per_day) / max) * 100)),
      confidence: row.confidence,
      card,
      taggedProduct: product ? null : (row.product_ids?.[0] ?? null),
      facts: product ? productFacts(ctx, row, card, negative) : contentFacts(ctx, row, negative),
    };
  });
  const closing = [payload.closing.few, payload.closing.others, payload.closing.mix];
  const restTotal = closing.reduce((sum, c) => sum + (c?.gmv_per_day ?? 0), 0);
  const noun = spec.rowKind === "product" ? "sản phẩm" : spec.rowKind === "video" ? "Video" : "Phiên LIVE";
  return {
    title: product
      ? `${rows.length} sản phẩm kéo ${col} ${ctx.direction === "down" ? "xuống" : "lên"}`
      : `${noun} tác động ${col} nhiều nhất`,
    col,
    rows,
    rest: closing.filter(Boolean).map((c) => ({ k: c.label, v: signedKMoney(c.gmv_per_day) })),
    restSum: signedKMoney(restTotal),
    restLabel: payload.closing.few?.label ?? "",
    total: perDay(payload.stream_factor_gmv),
  };
}
