/**
 * A product image the browser can load, from what the item row stores (P100 S2-D3).
 *
 * The Connector stores Seller Centre's `cover_image` as it reads it: a bare image id such as
 * `vn-11134207-7r98o-…`, not a URL, so using it as `src` shows a broken image. A full URL and a
 * same-origin path (the sample shop's covers under `/sample-shop/`) pass through; anything else
 * gives null and the card keeps its plain tile.
 */

export const SHOPEE_IMAGE_CDN = "https://down-vn.img.susercontent.com/file/";

const SHOPEE_IMAGE_ID = /^[a-z]{2}-[0-9]{8,}(?:-[A-Za-z0-9]+)+$/;

export function shopeeImageSrc(value: string | null | undefined): string | null {
  const v = value?.trim();
  if (!v) return null;
  if (/^https:\/\//.test(v)) return v;
  if (v.startsWith("/") && !v.startsWith("//")) return v;
  if (SHOPEE_IMAGE_ID.test(v)) return `${SHOPEE_IMAGE_CDN}${v}`;
  return null;
}
