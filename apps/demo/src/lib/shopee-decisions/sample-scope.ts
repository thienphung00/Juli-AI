import type { Kind92 } from "./builder-p92";
import type { CardSummary } from "./types";

/**
 * P100 S2-C (owner, 2026-11-11): what Quyết định offers on the reviewer's sample shop ("Dữ liệu
 * mẫu"). ONE allowlist: the three strategies that work there end to end — Tiêu đề, Ảnh bìa, Voucher.
 * Tự tạo shows only these builder kinds (no Combo Khuyến Mãi, no P98 Combo nhiều SKU / KOL / Quảng
 * cáo), and Đề xuất / Đang thực hiện / Đo lường / Sản phẩm › Đề xuất list only cards of these kinds.
 * Presentation only: the API refuses everything else for a sample pin (S2-F allowlist).
 */
export const SAMPLE_SHOP_STRATEGIES: readonly { readonly builder: Kind92; readonly cardKinds: readonly string[] }[] = [
  { builder: "title", cardKinds: ["title"] },
  { builder: "cover_image", cardKinds: ["cover_image"] },
  // the builder's voucher form saves a `min_spend_voucher` card; the engine also makes these two
  { builder: "voucher", cardKinds: ["min_spend_voucher", "review_voucher", "voucher_cap"] },
];

export const SAMPLE_SHOP_BUILDER_KINDS: ReadonlySet<Kind92> = new Set(SAMPLE_SHOP_STRATEGIES.map((s) => s.builder));

export const SAMPLE_SHOP_CARD_KINDS: ReadonlySet<string> = new Set(SAMPLE_SHOP_STRATEGIES.flatMap((s) => s.cardKinds));

/** The cards a sample-shop reviewer sees: only the three kinds; everything else as given. */
export function sampleShopCards<C extends Pick<CardSummary, "change_kind">>(cards: readonly C[], sampleShop: boolean): readonly C[] {
  return sampleShop ? cards.filter((c) => SAMPLE_SHOP_CARD_KINDS.has(c.change_kind)) : cards;
}
