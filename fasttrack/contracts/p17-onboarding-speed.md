# P17 contract — onboarding speed: quick scan, progress, history to 180 days

Owner decisions: DECISIONS **D26** (quick scan right after connect), **D25.12**
(history to 180 days in the background, 429 fix), **D24.17 / D24.21** (card
limits, fixed daily slots 3 Juli / 1 Seller Center / 1 nội dung), D24.1 (no
LLM before approval), D22 (expected GMV formula).

One migration, **`084_onboarding_speed`** (chained after `081_order_cost_data`
on this branch; the orchestrator re-chains it after 083; the deferred
phone-cleanup step stays the tail). It adds five nullable columns to
`shop_ingestion_state` and nothing else.

## 1. Quick scan (D26)

Task `juli_backend.shop_quick_scan(shop_id)`, queue **`ingest_priority`**,
enqueued by `bootstrap_shop` as it starts (de-duplicated by a
`quick_scan_queued` marker), so it runs **in parallel** with the fast phase
(another worker process; Celery's prefork pool has one per CPU). Its own
per-shop lock `quick_scan` — never the `cycle` lock.

TikTok reads (read-only, every call through the poll path's Redis
per-endpoint window, `pacing.RateLimitedResources`):

| # | Read | Calls |
|---|---|---|
| 1 | A-34 `GET /analytics/202605/shop_products/performance`, `start_date_ge` = D−14, `end_date_lt` = D (D = today UTC+7, so the window is the last 14 full local days), `page_size` 100, sorted by GMV desc | 1–2 (≤ 200 products) |
| 2 | `GET /product/202405/products/diagnoses` for the top `QUICK_SCAN_TOP_PRODUCTS` (10) products by 14-day GMV | 1 |
| 3 | `GET /product/202309/products/{id}` only for a chosen product the `products` table does not hold yet (the fast phase may not have synced the catalog) | 0–3 |

Selection (pure, `services/onboarding/quick_scan.py`):

1. Funnel per product from A-34 `total_performance` over 14 days
   (`FunnelWindow.from_a34_total_performance(days=14)`), shop medians over
   every product above the volume floor (`ShopMedians.from_products`).
2. For each of the top 10 by GMV, ADR-106 decision 4 (`diagnose_product`) with
   **TikTok's own codes** as evidence (`diagnoses_asked=True`), no prior window
   (median trigger only), no discount cap (so no price lever).
3. Keep only `cover_image` / `title` / `description` (Juli tự làm); price the
   proposal with the D22 formula on the **14-day** window
   (`recoverable_gmv_per_day`, `recoverable_gmv_basis.window_days = 14`);
   rank by it (ties: gap × 14-day GMV); keep **1–3** (`QUICK_SCAN_MAX_CARDS`, 3).

Cards: workflow `optimize_product_2`, subject = the product (same ladder as the
full pipeline, `emit_optimize_product_cards`), then `apply_emission_budget`, so
they take the day-1 **Juli** slots (3) and surface at once. No LLM call.

Card payload additions (`recommendation_payload.diagnosis.quick_scan`, allowlisted
in the masked read):

```json
{"label": "Đề xuất nhanh · dựa trên 14 ngày", "confidence": "Tham khảo",
 "window_days": 14, "scanned_at": "2026-10-10T08:01:00+00:00",
 "basis": "GMV dự kiến theo công thức D22 trên 14 ngày gần nhất (trung bình/ngày), mã chẩn đoán TikTok"}
```

and `expected_impact.confidence = "reference"` (instead of
`rule_based_estimate`). The Quyết định card block (`recommendation.card`) gains

| Field | Type | Meaning |
|---|---|---|
| `quick_scan` | `{label, confidence, window_days, basis}` \| `null` | a quick card; the UI shows the label as a chip and "Độ tin cậy: Tham khảo" |

and its `gmv_method` says "trung bình 14 ngày" for a quick card.

**Upgrade to full cards.** When the full diagnosis runs (end of the fast phase,
then daily), for each product with an open quick card:

- the full plan proposes the **same lever** → the **same card row** is
  re-scored in place: numbers, rank, evidence and `computed_at` from the full
  diagnosis, `quick_scan` removed, `surfaced_at` kept (its 3-day stay / 7-day
  validity run from the quick surfacing); the TikTok codes the quick scan read
  are fed to the full diagnosis as evidence, so a cover-image or description
  card stays confirmed;
- otherwise (another lever, or no proposal) → the quick card is **withdrawn**
  at once (`quick_scan_not_confirmed`; the 3-day stay does not protect a quick
  card), and a different lever for that product is a new revision for the
  budget to place.

Full cards then fill the slots the quick cards left (Juli 3 − quick, Seller
Center 1, nội dung 1) under the unchanged D24.17 limits.

State (`shop_ingestion_state`, migration 084): `quick_scan_status`
(`running` | `done` | `skipped` | `failed`), `quick_scan_started_at`,
`quick_scan_done_at`, `quick_scan_cards` (cards written). Log event
`shop_quick_scan_done` carries `seconds_since_connect` (= time to first card).
A shop whose full cards already exist is `skipped` (no TikTok call).

## 2. Onboarding status — `GET /v1/shops/me/onboarding`

Bearer + `X-Shop-Id` (the `/v1/shops/me` resolver). Read-only; no TikTok call.

```json
{
  "shop_id": "…",
  "active": true,
  "current_step": 2,
  "total_steps": 3,
  "label": "Juli đang đọc dữ liệu shop · bước 2/3",
  "poll_interval_seconds": 15,
  "steps": [
    {"key": "quick_scan", "label": "Quét nhanh 14 ngày", "status": "done",
     "percent": 100, "eta_seconds": null, "detail": "2 đề xuất nhanh"},
    {"key": "backfill_diagnosis", "label": "Đọc 60 ngày và chẩn đoán đầy đủ",
     "status": "running", "percent": 40, "eta_seconds": 540, "detail": "24/60 ngày"},
    {"key": "history", "label": "Tải lịch sử nền", "status": "pending",
     "percent": 13, "eta_seconds": null, "detail": "Đang tải lịch sử · còn 156 ngày"}
  ],
  "history_days_available": 24,
  "history_target_days": 180,
  "history_days_remaining": 156,
  "history_complete": false,
  "window_90d_available": false
}
```

- `steps[].status`: `pending` | `running` | `done` | `skipped` | `failed`.
- `quick_scan` is `done` / `skipped` / `failed` from state; `running` once
  started; `pending` before.
- `backfill_diagnosis` is `done` when the fast phase is done, 60 days of
  history are available (or the history walk has ended), and the shop's first
  diagnosis report exists; `percent` = 70 % × min(days, 60)/60 + 30 % if the
  report exists; `eta_seconds` = a typical-duration estimate
  (`ONBOARDING_FULL_DIAGNOSIS_TYPICAL_SECONDS`, 900 s from the fast phase's
  start) while running, `null` otherwise.
- `history` is `done` when `history_complete`; `running` once step 2 is done;
  `percent` = days ÷ target.
- `active` is `true` while step 1 or 2 is not finished (`done`/`skipped`/
  `failed`): the client shows the strip "Juli đang đọc dữ liệu shop · bước
  N/3" and polls every `poll_interval_seconds` (15). Once only the history
  step remains, `active` is `false`, `current_step` 3, `label` = "Đang tải
  lịch sử · còn N ngày", `poll_interval_seconds` 300: the client may show a
  quiet note but no longer polls fast. All done → `current_step` `null`,
  `label` `null`, `poll_interval_seconds` `null`.

### `history_days_available` (read by P16's simulation)

`history_days_available` = number of local days with analytics stored
contiguously, `analytics_through_date − history_earliest_date + 1` (0 before
the fast phase). `history_target_days` = `min(180, SHOP_HISTORY_MAX_LOOKBACK_DAYS)`
while the walk runs; once the walk has ended early (TikTok refused older
dates, or two empty chunks) the target becomes the days available and
`history_complete` is `true`. `history_days_remaining` = target − available
(≥ 0). `window_90d_available` = `history_days_available ≥ 180` (D25.12: the
90-day window needs 2 × 90 days). P16 greys the 90-day window with "Đang tải
lịch sử · còn {history_days_remaining} ngày" until `window_90d_available`.
Python accessor: `services.onboarding.history_days_available(state)`.

## 3. History to 180 days (D25.12)

- **API look-back**: the Partner docs for the shop analytics reads used here
  (A-34 202605 product list, 202509 shop / product / SKU / video / LIVE) state
  **no maximum look-back**; the only documented limit in
  `api-reference/analytics/` is **180 days** ("start_time must be within the
  last 180 days", Get Video Performances 202403); the hourly shop read is 30
  days. The walk therefore targets 180 days and ends earlier at TikTok's real
  limit when TikTok refuses a window (`28001022` "start time or end time is
  invalid" → existing halving to the exact limit) or returns two empty chunks.
- At connect the history chain runs on `ingest_backfill` only until **60
  days** exist (`SHOP_HISTORY_CONNECT_DAYS`); it then stops
  (`connect_window_done`, not done) and the 15-minute poll no longer revives
  it.
- **Nightly** beat `shop-history-extend` (19:43 UTC = 02:43 UTC+7) enqueues one
  `shop_history_backfill(nightly=True)` per shop whose walk is not done:
  `SHOP_HISTORY_NIGHTLY_CHUNKS` (2) chunks of `SHOP_HISTORY_NIGHTLY_CHUNK_DAYS`
  (15) days, rate-limited by the shared limiter, under the per-shop `history`
  lock, resumable from `history_earliest_date` (a refused/limited chunk is not
  recorded and is retried next night). 60 → 180 days in 4 nights.
- `SHOP_HISTORY_MAX_LOOKBACK_DAYS` default **180** (was 1095).

## 4. 429 handling in the daily shop diagnosis (D25.12)

`services/shop_diagnosis_daily/fetch.with_backoff`: on a throttle (HTTP 429,
TikTok `36009002` / `100005`, "Too many requests") it waits exponentially with
full jitter — base `SHOP_DIAGNOSIS_BACKOFF_BASE_SECONDS` (2), × 2 per retry,
capped at `SHOP_DIAGNOSIS_BACKOFF_CAP_SECONDS` (60), `SHOP_DIAGNOSIS_BACKOFF_RETRIES`
(5) retries — and then raises `ThrottledError`. In `video_windows`, a throttle
that survives the backoff no longer falls back to whole-window
(`posted_in_window`) totals: the video tables are **skipped for this cycle**
(the other streams' tables are stored), counter `video_windows_throttled_skips`
in the `shop_video_windows_skipped` log event. Non-throttle failures keep the
existing fallback.

## 5. Faster cost reads (P14-C)

`sync_order_costs`: orders created in the last `ORDER_COSTS_FAST_WINDOW_DAYS`
(30) are read up to `ORDER_COSTS_FAST_PER_CYCLE` (60) per pass per cycle;
older orders (31–60 days) at `ORDER_COSTS_PRICE_PER_CYCLE` /
`ORDER_COSTS_FINANCE_PER_CYCLE` (10). In the fast tier an empty rate-limit
bucket **waits** for the window instead of ending the pass, at most
`ORDER_COSTS_MAX_WAIT_SECONDS` (600) per cycle and within the cycle deadline;
a vendor 429 or a permission error still ends the pass at once.
