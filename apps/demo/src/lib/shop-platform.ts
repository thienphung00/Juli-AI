/**
 * Which marketplace a shop is on (`shops.platform`, ADR-118). Juli Ops shows it
 * beside every shop; a missing value is a TikTok shop (every shop before the
 * Shopee contract clients).
 */

export type ShopPlatform = "tiktok" | "shopee";

export function platformOf(value: string | null | undefined): ShopPlatform {
  return value === "shopee" ? "shopee" : "tiktok";
}

/** The shop's kind, as a label: "TikTok Shop" / "Shopee". */
export const PLATFORM_LABEL: Readonly<Record<ShopPlatform, string>> = Object.freeze({ tiktok: "TikTok Shop", shopee: "Shopee" });

/** The platform's name in a sentence: "TikTok không cung cấp…" / "Shopee không cung cấp…". */
export const PLATFORM_NAME: Readonly<Record<ShopPlatform, string>> = Object.freeze({ tiktok: "TikTok", shopee: "Shopee" });
