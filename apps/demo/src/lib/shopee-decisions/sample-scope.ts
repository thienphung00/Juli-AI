import type { Kind92 } from "./builder-p92";
import type { CardSummary } from "./types";

/**
 * P100 S2-C (owner, 2026-11-11): what Quyết định offers on the reviewer's sample shop ("Dữ liệu
 * mẫu"). ONE allowlist of the strategies that work there end to end: Tiêu đề, Ảnh bìa, Voucher (S2-C),
 * and since S2-D2 Combo Khuyến Mãi, Deal Sốc, Affiliate and (its own tab) a new Dịch vụ hiển thị Sản
 * phẩm campaign. Tự tạo shows only these, and Đề xuất / Đang thực hiện / Đo lường / Sản phẩm › Đề xuất
 * list only cards of these kinds.
 * Presentation only: the API refuses everything else for a sample pin (S2-F allowlist).
 */
export const SAMPLE_SHOP_STRATEGIES: readonly { readonly builder: Kind92; readonly cardKinds: readonly string[] }[] = [
  { builder: "title", cardKinds: ["title"] },
  { builder: "cover_image", cardKinds: ["cover_image"] },
  // the builder's voucher form saves a `min_spend_voucher` card; the engine also makes these two
  { builder: "voucher", cardKinds: ["min_spend_voucher", "review_voucher", "voucher_cap"] },
  // P100 S2-D2 (owner, 2026-11-13): the offers, Dịch vụ hiển thị Sản phẩm and Affiliate.
  { builder: "combo", cardKinds: ["bundle_deal"] },
  { builder: "deal_soc", cardKinds: ["add_on", "gift"] },
  { builder: "affiliate", cardKinds: ["affiliate_commission", "affiliate_target_campaign"] },
];

export const SAMPLE_SHOP_BUILDER_KINDS: ReadonlySet<Kind92> = new Set(SAMPLE_SHOP_STRATEGIES.map((s) => s.builder));

/**
 * The Tự tạo tool tabs on the sample shop (S2-D2): "Từng phương án" and "Dịch vụ hiển thị" — a NEW
 * Hiển thị Sản phẩm campaign (`/builder/ads/setup`, saved as `ads_new_campaign`). The single
 * builder's "Dịch vụ hiển thị" kind edits a running campaign, which the server refuses for every shop
 * (`ads_edit_hidden`), so it is not offered. No Combo nhiều SKU / KOL tabs.
 */
export const SAMPLE_SHOP_MODES: ReadonlySet<string> = new Set(["single", "ads"]);

/** Card kinds besides the builder kinds': the Dịch vụ hiển thị tab's new campaign. */
const SAMPLE_SHOP_EXTRA_CARD_KINDS: readonly string[] = ["ads_new_campaign"];

export const SAMPLE_SHOP_CARD_KINDS: ReadonlySet<string> = new Set([...SAMPLE_SHOP_STRATEGIES.flatMap((s) => s.cardKinds), ...SAMPLE_SHOP_EXTRA_CARD_KINDS]);

/** The cards a sample-shop reviewer sees: only these kinds; everything else as given. */
export function sampleShopCards<C extends Pick<CardSummary, "change_kind">>(cards: readonly C[], sampleShop: boolean): readonly C[] {
  return sampleShop ? cards.filter((c) => SAMPLE_SHOP_CARD_KINDS.has(c.change_kind)) : cards;
}
