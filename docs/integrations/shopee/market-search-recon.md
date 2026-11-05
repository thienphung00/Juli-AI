# Market search reader (Connector 0.3.5, P92 B-10) — what is assumed

Status: **no real capture yet.** Everything marked *to verify* is a recon guess from Shopee's public
web app and must be confirmed on the first live run on ORY before the numbers are trusted. Tests use
synthetic fixtures of this shape (`apps/connector/test/fixtures/market/search_items.json`).

## What the reader does
Weekly per keyword (server list `GET /v1/ingest/market/keywords`, 1–3 main keywords per product,
de-duplicated, max 12 per run, never the same keyword twice in 6 days), the Connector opens
`https://shopee.vn/search?keyword=<kw>` in a background tab, keeps the page's own page-1 answer,
posts it to `shopee/market_search` and closes the tab. One tab at a time, 20–45 s between tabs.

## Relied on (all *to verify on a real capture*)
| Item | Assumed |
|---|---|
| Page | `https://shopee.vn/search?keyword=...` loads without login |
| Answer | `GET /api/v4/search/search_items?by=relevancy&keyword=...&limit=60&newest=0&page_type=search` (JSON); `newest>0` (page 2+) is ignored |
| List | `items[]`, each `{ item_basic: {...}, adsid?, campaignid?, ads_keyword? }` |
| Fields in `item_basic` | `itemid`, `shopid`, `name`, `shop_name`, `price`, `price_min`, `price_max`, `price_before_discount`, `raw_discount`, `historical_sold` (lifetime), `sold` (assumed recent/monthly), `image` (image id), `item_rating.rating_star` |
| Optional sold display | `item_card_display_sold_count.monthly_sold_count` and `.display_sold_count_text` |
| Money unit | VND × 100 000 (`12900000000` = 129 000 đ); `MARKET_PRICE_DIVISOR` |
| Ad flag | a card with `adsid` / `campaignid` / `ads_keyword` is an ad: kept with `is_ad = true`, position stays true |
| Position | `pos` = 1-based index in `items[]` (ads included) |
| Pagination | page 1 only (60 cards); no scrolling |
| Block | HTTP 403/429 or `error: 90309999`, a `/verify/*` page, or a redirect to `/buyer/login` |

Ingest row (snake_case, contract fields only): `keyword, sort, page, pos, is_ad, item_id, shop_id,
shop_title, title, price, price_min, price_max, price_before_discount, discount_pct, rating,
sold_monthly, sold_lifetime, sold_text, image_id`. (`title` / `shop_title`, not `name`.)

## Drift (dataset paused for this extension version, nothing posted)
No card list; a card without item id / title / price; median price < 100 đ or any price above
`MAX_PLAUSIBLE_PRICE_VND` (wrong scale). Reported through the usual `/v1/ingest/status` drift call.

## First live run checklist (ORY)
1. Open `shopee.vn/search?keyword=<one real keyword>` in Chrome, DevTools → Network → Fetch/XHR.
2. Find the search-items call: path, query (`newest`, `limit`, `by`), status; save the JSON (not committed).
3. Confirm: list key, `item_basic` field names above, price unit (compare one price with the screen),
   which of `sold` / `historical_sold` is the "Đã bán" shown (monthly or lifetime), the ad marker field
   on a "Quảng cáo" card, image id format, and that `shop_name` is present (else shop name needs the
   shop page / is omitted).
4. Look for anti-bot: does a background (inactive) tab get a CAPTCHA / `/verify` page? Does the answer
   load at all without scrolling? Is the call made by `fetch` or XHR (both are wrapped)?
5. Then adjust `src/shopee/market.ts` constants / names, keep the fixtures in step, bump the version.

## Constraints
Public search pages only; no login, no cookies read, no buyer data (a search card has none; the hook
keeps only the fields above and drops everything else before leaving the page); never clicks, scrolls,
solves a CAPTCHA or logs in; assisted only; ORY pilot only (`marketActive` needs the explicit shop id,
the `"*"` wildcard does not count); a block closes the tab, stops the run and cools down 6–72 h.
Host permission added: `https://shopee.vn/*` (content scripts only on `https://shopee.vn/search*`).
