# P12 contract — Phân tích redesign (ADR-109 Amendment 2)

Additive to `GET /v1/demo/analysis` (the ADR-108 report, P7-A) and
`GET /v1/demo/analysis/rankings` (ADR-109 d.5, P8-A). Same auth + `X-Shop-Id`
guards, no new route, **no migration**: both payloads are stored as JSON
(`shop_diagnosis_reports.report`, `shop_metric_rankings.ranking`, migrations
076/077) and the daily job writes the new keys from its next run. A report or
ranking stored before P12 lacks them; the UI degrades (noted per field).
UI copy comes from the artboards in `docs/product/design/phan-tich/`.

## 1. Report — new top-level keys (`services/shop_diagnosis/report.py`)

```json
"daily_gmv": { "2026-08-08": 5580000, "…": 0 },   // GMV per PRESENT day of the 60, all channels (A-34 "total")
"seller_skus": { "1729000012": "SM-012" },        // product id → first non-blank skus[].seller_sku (catalogue)
"promo_products": [                                // at most 10, by gmv_in desc
  {
    "product_id": "1729000021",
    "kind": "Flash sale",        // PromoKind value: Flash sale | Giảm giá sản phẩm | Mua nhiều giảm nhiều
    "days": 5,                   // days a known-list promotion covered ≥ flash_day_coverage (0.5) of the day
    "depth": 0.12,               // flash: median true depth (flash price vs already-discounted price);
                                 // discount: median depth vs list price; null when unknown
    "gmv_in": 1100000,           // mean daily GMV (all channels) on those days; null when none
    "gmv_out": 700000            // … on the other present days of the 60; null when none
  }
]
```
`shop_bands[]` (and each profile's `bands[]`) gain `"product_count": 3 | null`
(products in the promotion; null for vouchers and promotions whose product list
was not fetched).

UI without them: Lịch sale shows "chưa có GMV từng ngày"; the Khuyến mãi rows
are empty and the Flash-sale product count says it is not in the report; SKU
chips fall back to the ranking row's `seller_sku`, then the card's.

## 2. Ranking rows — new optional fields (`services/shop_diagnosis/rankings.py`)

```json
// product rows (Thẻ sản phẩm, Tab cửa hàng)
{ "id": "1729000012", "seller_sku": "SM-012", … }      // omitted when the catalogue has none
// content rows (LIVE sessions, videos)
{ "id": "v1", "product_ids": ["1729000015"], … }        // products featured, order kept, de-duplicated
```
`product_ids` come from the snapshot's `live/products/<id>.json`, the video
list's `products[]` and `videos/products/<id>.json`; `[]` when none is known.
"Xem sản phẩm được gắn ›" opens Sản phẩm on the first one; without any the
link is not shown.

## 3. What is NOT new (read as before)

- Per-cell ₫/day impact = `channels[].comparison.factors[].contribution`
  (ADR-108 log-share), the weakest metric = the most negative contribution among
  the stream's clickable cells (ADR-109 d.4) — computed in the UI.
- Row → card join: `GET /v1/demo/decisions` item
  `recommendation.diagnosis.tiktok_product_id` = row `id`, and the card's stage
  (`card` → CTR, `page` → CTOR, `basket` → AOV) = the selected cell. Impressions
  rows never have a card.

## 4. URLs (UI only)

- Phân tích: `/analytics?tab=san-pham|noi-dung&stream=the-san-pham|tab-cua-hang|video|live|dong&metric=hien-thi|ctr|ctor|aov&huong=len&row=<id>`
  (`them-gio` / `don-them-gio` from older links open CTOR).
- Đề xuất: `/decisions?tab=de-xuat&the=<card id>` (scroll + 3 s pink outline) and
  `&nhom=ctr|ctor|aov` (the metric's card group).
