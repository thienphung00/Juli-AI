/**
 * U7: where an answer's links go. Reuses the seller app's own link builders so Juli never writes a
 * route twice. A page that cannot take the window opens on its default (follow-up for the page owner).
 */
import type { JuliLink } from "@juli/contracts";

import { sellerLinks } from "../shopee-analytics/links";
import type { WindowState } from "../shopee-analytics/params";

function windowOf(link: JuliLink): WindowState | undefined {
  if (!link.from || !link.to) return undefined;
  return { query: { period: "custom", from: link.from, to: link.to }, compare: true };
}

export function juliHref(link: JuliLink, platform: "shopee" | "tiktok" = "shopee"): string {
  if (platform === "tiktok" && link.kind !== "card") {
    // TikTok has no Shopee Phân tích / product pages; its single analytics page takes no parameters.
    return "/analytics";
  }
  switch (link.kind) {
    case "metric":
      return sellerLinks.analysis({ metric: link.metric }, windowOf(link));
    case "channel":
      return sellerLinks.analysis({ metric: link.metric, channel: link.channel }, windowOf(link));
    case "product":
      return link.item_id ? sellerLinks.product(link.item_id, {}, windowOf(link)) : sellerLinks.products(windowOf(link));
    case "ads":
      return sellerLinks.dashboard("quang-cao");
    case "card":
      return link.card_code ? sellerLinks.card(link.card_code, "juli") : "/decisions";
  }
}

/** Quyết định detail of a sent card (JC code). */
export function cardHref(code: string): string {
  return sellerLinks.card(code, "juli");
}
