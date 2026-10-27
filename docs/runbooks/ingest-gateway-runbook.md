# Ingest gateway and Juli Connector (fast track P24) — operation

Decisions: `fasttrack/DECISIONS.md` D31.3 (one ingest gateway) and D31.4 (Juli
Connector). Code: `backend/src/juli_backend/services/ingest/`, routes
`api/routes/ingest.py`, migration `088_ingest_gateway`, extension `apps/connector/`.

## Gateway

| Route | Caller | What |
|---|---|---|
| `POST /v1/shops/shopee` | seller (Supabase JWT) | create a `platform='shopee'` shop (`{shop_name, shopee_shop_id?}`) |
| `POST /v1/ingest/pairing-codes` | seller (JWT + `X-Shop-Id`) | 10-char code, 10 min, single use (≤ 5 live per shop) |
| `GET /v1/ingest/tokens` · `DELETE /v1/ingest/tokens/{id}` | seller | list / revoke the shop's connector tokens (revokes the rotated chain too) |
| `POST /v1/ingest/pair` | extension, no token | `{code, platform, platform_shop_id?, client_label?}` → token (`jci_<shop hex>_<secret>`, 90 days) |
| `POST /v1/ingest/token/rotate` | extension token | new token; the old one works 10 more minutes |
| `GET /v1/ingest/status` | extension token | last ingest + drift per dataset, token expiry |
| `POST /v1/ingest/status` | extension token | drift report `{platform, dataset, state: drift\|ok, source_version, endpoint, unexpected[], missing[]}` |
| `POST /v1/ingest/{platform}/{dataset}` | extension token | one dataset post (see the contract below) |

Datasets now (`platform=shopee`): `traffic_overview`, `item_by_source`,
`item_performance`, `shop_traffic`. The row models are in
`services/ingest/schemas.py`; rows carry Seller Centre's own field names, the
server maps them (`mapping.py`) onto Juli streams (`product_card`,
`seller_video`, `seller_live`, `affiliate`, overlay `ads`, `total`) and KPI
columns in `platform_daily_metrics`. Everything else lands in `extra`.

Body: `{source: extension|file|api|vendor, source_version, captured_at (with
offset), period: {start, end, granularity: "day"} (≤ 31 days, not in the future),
order_type: placed|paid|confirmed (null for shop_traffic), platform_shop_id?,
rows[] (≤ 2,000)}`; ≤ 1,000,000 bytes (under nginx's default 1 MiB, so no
nginx change). Rates are fractions in [0, 1]; a percentage is refused.

Answers: `200 {raw_payload_id, duplicate, rows, content_hash}`; errors are
`{"detail": {"code": ...}}`: `401 missing_token | invalid_token`, `403
platform_not_allowed`, `404 unknown_dataset`, `409 dataset_in_drift |
shop_mismatch`, `413 body_too_large`, `422 invalid_body | invalid_rows |
order_type_required | ...` (with `errors[]`), `429 rate_limited` (+ `Retry-After`).

Behaviour to know when reading the data:

- **Idempotent.** The raw body is kept in `ingest_raw_payloads`, unique per
  (shop, sha256 of platform + dataset + period + order type + rows). A re-post
  answers `duplicate: true` and changes nothing.
- **Source precedence.** A normalized row is replaced only by a source of the
  same or higher rank: vendor (`estimated`) < extension = file (`high`) < api.
- **Order types are separate rows.** "Doanh số" includes orders later
  cancelled / returned; `orders` can be fractional (multi-item orders).
- **Drift.** After a drift report the dataset is refused (409) for that
  `source_version` until a new extension version posts or the extension reports
  `ok`. Find drift: `SELECT shop_id, dataset, drift_detail, drift_at FROM
  ingest_dataset_status WHERE drift_state = 'drift';` (owner connection).

Rate limits (env, per API process group via Redis; in-process without
`REDIS_URL`): `INGEST_RATE_LIMIT_PER_SHOP` (120) per `INGEST_RATE_WINDOW_SECONDS`
(600) across the token routes; `INGEST_PAIR_LIMIT_PER_CLIENT` (10) per
`INGEST_PAIR_WINDOW_SECONDS` (600) on `/pair`, and 30× that overall. A Redis
error fails closed (429).

Logs (one line each, the audit trail): `ingest_accepted`, `ingest_rejected`,
`ingest_drift_reported`, `ingest_pairing_code_created`, `ingest_paired`,
`ingest_pairing_refused`, `ingest_token_rotated`, `ingest_token_revoked(_by_seller)`,
`ingest_shop_mismatch`, `ingest_rate_limited`, `shopee_shop_connected`.

Tenancy: the five tables are tenant-direct (RLS through `app_current_shop_id()`).
A token embeds its shop id and is resolved under that shop's scope; the pairing
redeem sets `app.pairing_code_hash`, and `ingest_pairing_codes`' SELECT policy
admits only the row with that hash. Proof: `tests/integration/test_ingest_two_tenant.py`.

CORS: none needed. The extension's service worker calls the API with a host
permission for `https://api.app-juli.com/*`, which Chrome exempts from CORS.

## Juli Connector (Chrome extension)

Build: `pnpm --filter @juli/connector build` → `apps/connector/dist/` (load
unpacked via chrome://extensions › Developer mode, or zip `dist/` for the Web
Store). `JULI_API_ORIGIN=https://api.app-juli.com` by default; it is baked into
the code and the manifest's host permission. Tests: `pnpm --filter
@juli/connector test` (and `type-check`).

How it works:

1. The seller creates a code in Juli and types it in the popup; the service
   worker calls `/v1/ingest/pair` and keeps only the ingest token
   (`chrome.storage.local`).
2. On `banhang.shopee.vn`, `hook.js` (page world) wraps fetch / XHR and passes
   the page's own responses from four `/api/mydata/...` endpoints to
   `content.js` (window.postMessage, origin + channel checked), which relays them
   to the service worker. Only exactly-one-finished-day responses are mapped;
   `real_time`, 7 / 30-day aggregates are ignored. Recorded day shapes
   (2026-10-26): "Hôm qua" `period=yesterday`, end = start + 86399; a picked day
   `period=day`, end = start + 86400 (+ 86399 → Shopee code 10006); the traffic
   dashboard `period=day&dt=YYYYMMDD`.
3. Once a day (alarm, random start) — and only while a Seller Centre tab is
   open — the service worker asks that tab to re-issue yesterday's same GETs, at
   ≥ 2 s + jitter apart, with the session params the page itself used (never
   stored, never sent to Juli). No tab → it waits for one.
4. Unexpected / missing fields, a renamed source enum or a percentage where a
   fraction belongs → drift report, that dataset stops for this version.
5. The token rotates after 30 days; a 401 clears it (the seller pairs again).
6. **30-day backfill (v0.2.0):** once per shop (kept across re-pairing the same
   shop), the last 30 finished GMT+7 days, newest first, one day per round trip
   to the tab (traffic overview + shop traffic; item datasets while
   `ITEM_READERS_ACTIVE` is false are skipped), same ≥ 2 s + jitter pacing across
   all requests. Progress lives in `chrome.storage.local` (`backfill`: done days,
   per-day accepted datasets, in-flight day); a closed browser resumes there.
   Stops: Seller Centre 401/403 or a login page (resumes once the page loads data
   again), code 10006 or another error code / 3 transient failures (until a new
   extension version), Juli 401 (until paired again), `consent_required`.
7. **`403 consent_required`** (gateway, PR #2199): the extension stops sending
   anything (no queue, no daily sync, no backfill) and the popup says the shop is
   not yet allowed to sync; "Đồng bộ hôm qua" or pairing again lifts it.

Seller UI still needed (not built): in Juli "Cài đặt › Kết nối Shopee" — create
the Shopee shop (`POST /v1/shops/shopee`), "Tạo mã kết nối" (show the code and
its 10-minute countdown), the connected-browser list with "Ngắt kết nối"
(`GET`/`DELETE /v1/ingest/tokens`), and the per-dataset freshness / "Seller
Centre đã thay đổi" state. Ops: a column for connector status per Shopee shop.

Release: Chrome Web Store, **Unlisted**, to pilot shops first (D31.4). Drafts:
`apps/connector/STORE_LISTING.md`, `apps/connector/PRIVACY.md`. Icons
(16/48/128 PNG) and screenshots are still to be made.
