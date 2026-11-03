# ADR-119: Shopee keywords come from the shop's own titles; their market numbers are public data the owner collects in their own browser and uploads through Ops

**Status:** Accepted (owner grill D81.4–D81.8, 2026-11-03)
**Date:** 2026-11-03
**Related ADRs / decisions:** ADR-116 (client / public lanes), ADR-117 (Shopee files through the
ingest gateway; `platform_items`; public market lane `market_*_snapshots`), ADR-118 (proposals —
a title change is a `title` proposal), D25 (Juli Ops).

## Context

The owner wants a "Từ khóa" page per Shopee shop in Juli Ops: which search phrases the shop's
products can be found by, how much demand each has, and which products have none worth having
(candidates for a title proposal). Demand numbers (monthly volume, CPC min / max, difficulty,
competition, opportunity, related keywords) come from shopeeanalytics.com, a public third-party
site. Anonymous visitors get 5 lookups a day; after that the site shows a login box and an empty
table reading "Không có từ khóa khớp bộ lọc" — which looks exactly like "no demand".

`market_keyword_snapshots` (108) is a different thing: Shopee search-result pages (cards, shops,
prices) per keyword. It is not reused.

## Decision

### 1. Keywords are combinations decomposed from the shop's titles (D81.4, D81.6)

A pure, deterministic decomposer (`services/shop_keywords/decompose.py`) reads the shop's
item-level titles from `platform_items` and returns combinations a buyer would type — never single
words: brand + type / function / material, type + function (+ material), type + material,
function + material, function + size, type + size, and shared 2–4 word phrases. Vietnamese text is
lower-cased and NFC-normalised; diacritics are stripped only for matching (a token written with
diacritics must match a lexicon entry exactly, so "dầu" never matches "đầu"); the display form
keeps them. Size / volume tokens (`500ml`, `1,5l`, `1kg`, `30 viên`) are one facet. The brand is
what the operator types (or nothing), else the leading words ≥ 60 % of titles share when they are
not a product word. A combination is kept when ≥ 2 titles produce it, or it pairs the brand with
another facet; each keeps the item ids it came from. The operator trims (`enabled`); re-generating
never re-enables a trimmed combination.

Synthetic example — titles "Miếng rửa chén xơ mướp Lumi tự nhiên", "Lumi Miếng rửa chén xơ mướp
loại lớn", "Nước rửa chén Lumi tinh dầu sả 500ml", "Nước rửa chén sinh học hương sả 500ml", brand
"Lumi" → `miếng rửa chén xơ mướp` (type + function + material, items 1, 2), `nước rửa chén`
(type + function, 3, 4), `nước rửa chén 500ml` (type + size, 3, 4), `lumi rửa chén`
(brand + function, 1–3), `rửa chén` (shared phrase, 1–4), …

### 2. Two tables, two lanes (D81.5) — migration `111_shopee_keywords`

- **`market_keyword_metrics`** — public lane (ADR-116 §1), no `shop_id`, `ops_only` like 108's
  market tables (`juli_ops` SELECT / INSERT / UPDATE). One row per (`source`, `keyword`, `seed`,
  `collected_on`): `seed` is the keyword looked up, `keyword` one row of its result. `status` ∈
  {`ok`, `blocked`, `no_match`}; a non-`ok` row is `keyword = seed` with every number NULL (CHECK).
  The seed's own row carries `extra.total_volume`; when the site did not list the seed itself, its
  row exists with NULL numbers (`extra.listed = false`). A `blocked` / `no_match` upload never
  overwrites an `ok` row of the same day.
- **`shop_keyword_seeds`** — client lane, `tenant_direct` (RLS on `app_current_shop_id()`,
  `juli_app` SELECT / INSERT / UPDATE, no DELETE): `shop_id`, `platform`, `keyword`, `pattern`,
  `item_ids` (JSONB), `enabled`, `created_by` (plain staff uuid, as 109), timestamps; unique
  (`shop_id`, `platform`, `keyword`). Which of a client's products a keyword came from is client
  data: it is deleted with the shop by the account purge (094's `privacy_purge_account` deletes
  every table carrying a uuid `shop_id`), and it is registered in `TABLE_CLASSIFICATION_MAP`.

### 3. Collection is the owner's, in their own browser (D81.8)

Juli's servers and Claude never fetch shopeeanalytics.com. The owner looks seeds up while logged in
to a free account and uploads the result weekly from their laptop. **Collection format** — JSON
Lines, one object per looked-up seed keyword (`services/shop_keywords/collection.py` validates it):

```json
{"source": "shopeeanalytics", "collected_on": "YYYY-MM-DD", "seed": "...",
 "status": "ok" | "blocked" | "no_match", "total_volume": 1250 | null,
 "rows": [{"keyword": "...", "volume": 70, "cpc_min": 422, "cpc_max": 2203,
           "difficulty": 56, "competition": 90, "opportunity": 1}]}
```

Numbers are plain JSON numbers; a quoted number is refused. `ok` needs ≥ 1 row; `blocked` and
`no_match` carry no rows and no `total_volume`. **An empty result is `blocked` unless the owner
marks it `no_match` — never zero demand.** `scripts/shopeeanalytics_keywords.py` converts the
current browser capture (`{kw, sum: "1.250", n, rows: ["keyword | volume | trend | min CPC |
max CPC | difficulty | competition | opportunity"]}`) into this format (`--no-match SEED` marks a
real empty result).

### 4. Upload through an Ops route, not the ingest gateway

`POST /v1/ops/market/keyword-metrics` (Vận hành, audited `keyword_metrics_upload` with counts
only): the Từ khóa page reads the file in the owner's browser and posts its lines. The pairing-token
gateway (`/v1/ingest/{platform}/{dataset}`, ADR-117 §1) was not extended because every step of it
is per shop: the token is one shop's, `service` consent is required for that shop,
`ingest_raw_payloads` and every target table are tenant-direct, and the session is `juli_app`
under the shop's scope — which has no grant on an `ops_only` public table. A public dataset there
would need a shop-less token, a consent bypass and a role switch: a second security model inside
the gateway. The Ops path already has the right one (Cloudflare Access → staff role → `juli_ops`,
`ops_audit_log`) and costs one route.

Seeds are written by `POST /v1/ops/shops/{id}/shopee/keywords/seeds/generate` ("Tạo từ khóa từ
tiêu đề", Vận hành, audited `keyword_seeds_generate`) under the shop's scope; one combination is
kept / dropped by `PUT …/seeds/{seed_id}` (audited `keyword_seed_toggle`).

### 5. The page

`/ops/shops/[shopId]/shopee/tu-khoa`, a third tab beside Sản phẩm + luồng and Quảng cáo + khuyến
mãi. Per combination: pattern, source products, latest volume / CPC / difficulty, volume per
collection day (weekly line), related keywords from the latest lookup. Coverage: đã tra / không
khớp / bị chặn / **chưa tra** (never shown as 0); the list still to look up can be copied. Products
whose enabled combinations were all looked up with none reaching the volume threshold (default 100,
adjustable) are flagged "Đề xuất sửa tiêu đề"; while some combination is still chưa tra / bị chặn
the product says "Chưa đủ dữ liệu".

## Consequences

- One expand-only migration (`111_shopee_keywords`); the deferred tail (101 → 074) is re-parented
  onto it.
- Volume is the site's estimate for Shopee VN search, not Juli's measurement; the page names the
  source and the collection day.
- A title change suggested from this page is an ADR-118 `title` proposal; nothing here writes to
  the shop.

## Alternatives rejected

- **Reuse `market_keyword_snapshots`** — another grain (search-result cards per sort), no CPC or
  difficulty columns.
- **Server-side or Claude-driven scraping of shopeeanalytics.com** — the site's terms and its login
  wall; the owner's own logged-in lookups are the agreed source (D81.8).
- **A public-lane dataset in the ingest gateway** — §4.
- **Single-word keywords** — buyers search combinations (D81.4).
