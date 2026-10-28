/**
 * Phân tích ↔ Đề xuất (ADR-109 Amendment 2 d.3–4, `PtFlow.dc.html`) — pure.
 *
 * A ranking row has a card when a `GET /v1/demo/decisions` item names the
 * same product (`recommendation.diagnosis.tiktok_product_id` = the row's
 * product id) for the same metric (the diagnosis' weak stage: card → CTR,
 * page → CTOR, basket → AOV). Lượt hiển thị has no card. The two links:
 *
 * - row "Xem đề xuất ›" → `/decisions?tab=de-xuat&the=<card id>` (scrolled
 *   to, pink 3 s);
 * - header "Xem N đề xuất ›" → `/decisions?tab=de-xuat&nhom=<metric>`;
 * - card "Xem phân tích ›" → `/analytics?tab=san-pham&stream=…&metric=…&row=<product id>`.
 */

import type { DemoDecisionItem } from "@juli/contracts";

import type { P10DecisionItem } from "../quyet-dinh/p10-types";
import { signedKMoney } from "./format";
import { analysisHref, type CellMetric } from "./model";
import type { RankedStream } from "./types";

const STAGE_METRIC: Readonly<Record<string, CellMetric>> = { card: "ctr", page: "ctor", basket: "aov" };
const KPI_METRIC: Readonly<Record<string, CellMetric>> = { ctr: "ctr", ctor: "ctor", aov: "aov" };

export interface CardRef {
  readonly id: string;
  readonly productId: string;
  readonly metric: CellMetric;
  readonly sku: string | null;
  readonly title: string | null;
  /** "Mô tả · +2,1 tr ₫/tháng" (the row detail's Đề xuất). */
  readonly proposal: string | null;
  /** TikTok's own diagnosis codes on the card (`card.tiktok_codes`). */
  readonly codes: readonly string[];
  readonly stream: RankedStream;
}

function text(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value.trim() : null;
}

/** The metric a card is about, `null` for a card without a P7-B diagnosis. */
export function cardMetric(item: DemoDecisionItem): CellMetric | null {
  const diagnosis = item.recommendation.diagnosis;
  if (!diagnosis) return null;
  return STAGE_METRIC[diagnosis.stage?.code ?? ""] ?? KPI_METRIC[diagnosis.main_kpi?.key ?? ""] ?? null;
}

function cardStream(item: DemoDecisionItem): RankedStream {
  return item.recommendation.diagnosis?.channel_scope === "SHOP_TAB" ? "shop_tab" : "product_card";
}

export function toCardRef(raw: DemoDecisionItem): CardRef | null {
  const item = raw as P10DecisionItem;
  const productId = text(item.recommendation.diagnosis?.tiktok_product_id);
  const metric = cardMetric(item);
  if (!productId || !metric) return null;
  const card = item.recommendation.card ?? null;
  const lever = text(card?.lever?.label) ?? text(item.recommendation.diagnosis?.lever?.label);
  const gmvMonth =
    typeof card?.expected_gmv_per_month === "number"
      ? card.expected_gmv_per_month
      : typeof item.recommendation.diagnosis?.recoverable_gmv_per_day === "number"
        ? item.recommendation.diagnosis.recoverable_gmv_per_day * 30
        : null;
  return {
    id: item.id,
    productId,
    metric,
    sku: text(card?.seller_sku),
    title: text(card?.product_title) ?? text(item.recommendation.diagnosis?.product_title),
    proposal: lever ? (gmvMonth !== null ? `${lever} · ${signedKMoney(gmvMonth)}/tháng` : lever) : null,
    codes: card?.tiktok_codes ?? [],
    stream: cardStream(item),
  };
}

/**
 * P71: any open card, whatever it is about -- an orders-sourced quick scan, a
 * promotion, a new product -- for Phân tích's "Có N đề xuất cho shop" block and a
 * product row's link to a card about no metric.
 */
export interface ShopCard {
  readonly id: string;
  /** `null` for a card about no product. */
  readonly productId: string | null;
  /** The card's heading ("Tạo khuyến mãi giảm giá cho …"). */
  readonly title: string;
}

export interface CardIndex {
  /** The card for `productId` × `metric`, if any. */
  readonly find: (productId: string, metric: CellMetric) => CardRef | null;
  /** Any card naming the product (its SKU / title when the report has none). */
  readonly anyFor: (productId: string) => CardRef | null;
  /** How many cards are about `metric` (the header's "Xem N đề xuất ›"). */
  readonly countFor: (metric: CellMetric) => number;
  /**
   * P71: a card about the product that is about no metric (a promotion, a new
   * product): its row links to it in every metric's table. A card about another
   * metric stays in that metric's table only.
   */
  readonly anyCardId: (productId: string) => string | null;
  /** P71: every open card of the shop, in the decisions' order. */
  readonly all: readonly ShopCard[];
  readonly total: number;
}

function toShopCard(raw: DemoDecisionItem): ShopCard | null {
  const item = raw as P10DecisionItem;
  const title = text(item.recommendation.card?.product_title) ?? text(item.title);
  if (!title) return null;
  return { id: item.id, productId: text(item.recommendation.diagnosis?.tiktok_product_id), title };
}

export function indexCards(items: readonly DemoDecisionItem[]): CardIndex {
  const refs = items.map(toCardRef).filter((ref): ref is CardRef => ref !== null);
  const shopCards = items.map(toShopCard).filter((card): card is ShopCard => card !== null);
  return {
    find: (productId, metric) => refs.find((r) => r.productId === productId && r.metric === metric) ?? null,
    anyFor: (productId) => refs.find((r) => r.productId === productId) ?? null,
    countFor: (metric) => refs.filter((r) => r.metric === metric).length,
    anyCardId: (productId) =>
      shopCards.find((c) => c.productId === productId && !refs.some((r) => r.id === c.id))?.id ?? null,
    all: shopCards,
    total: shopCards.length,
  };
}

/** P71: Quyết định's Đề xuất tab, all of the shop's cards. */
export const SHOP_DECISIONS_HREF = "/decisions?tab=de-xuat";

/** P71: "Có 2 đề xuất cho shop". */
export function shopCardsLine(count: number): string {
  return `Có ${count} đề xuất cho shop`;
}

export const EMPTY_CARDS: CardIndex = indexCards([]);

/** Row "Xem đề xuất ›": Đề xuất scrolled to that card, highlighted. */
export function decisionCardHref(cardId: string): string {
  return `/decisions?${new URLSearchParams({ tab: "de-xuat", the: cardId }).toString()}`;
}

/** Header "Xem N đề xuất ›": Đề xuất at the weakest metric's card group. */
export function decisionGroupHref(metric: CellMetric): string {
  return `/decisions?${new URLSearchParams({ tab: "de-xuat", nhom: metric }).toString()}`;
}

/** Card "Xem phân tích ›": Phân tích on that stream, metric and row (expanded); `null` without a product. */
export function analysisHrefForDecision(item: DemoDecisionItem): string | null {
  // P14-E content cards: Phân tích › Nội dung on the stream × metric the card came from.
  const content = (item as P10DecisionItem).recommendation.card?.content;
  if (content) {
    return content.kind === "live"
      ? analysisHref({ tab: "noi-dung", stream: "seller_live", metric: "ctor" })
      : analysisHref({ tab: "noi-dung", stream: "seller_video", metric: "ctr" });
  }
  const ref = toCardRef(item);
  if (!ref) return null;
  return analysisHref({ tab: "san-pham", stream: ref.stream, metric: ref.metric, row: ref.productId });
}
