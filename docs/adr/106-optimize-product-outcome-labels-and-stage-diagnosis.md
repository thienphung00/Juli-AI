# ADR-106: Optimize Product optimises a funnel factor — outcome labels, stage diagnosis, and a per-product cycle

**Status:** Proposed
**Date:** 2026-10-06
**Deciders:** grill-with-docs (Architect) with the owner, grounded in the TikTok Academy VN
corpus (≈ 25 pages read: product-card diagnosis, product traffic, Product Optimizer, promotion
tools, GMV Max), the Partner API OpenAPI spec (`tts-openapi-guide`, 405 paths) and the
Partner Center listing-quality code reference.

**Amends:** [ADR-055](055-decision-plan-review.md) d.15 (one Main KPI per workflow → a Main
KPI *set* per workflow, one member per card); [ADR-090](090-optimize-product-realignment.md)
d.3–d.4 (diagnosis-first and one-lever stay; the lever is now *selected* by a deterministic
stage diagnosis, and the lever set gains a one-tier BMSM for AOV); the v1 spec
[`v1-workflow-spec.md`](../product/agent-workflow-execution/v1-workflow-spec.md) §2
(OP-NFR-3's "CTOR is not a metric anywhere in the codebase" becomes a defect to fix, not a
limitation to accept).
**Does not change:** ADR-090 d.1 (discount-only reprice), d.2 (fail-safe lock detection),
d.5 (single proposal), d.6 (no repeat consent), d.7 (honest end states, extended below);
[ADR-077](077-incremental-impact-measurement.md)'s method; [`ml_layer.md`](../ml/ml_layer.md)'s technique selection
(deterministic T7 ranker; learned-to-rank rejected).
**Scope:** W9-A follow-on; the Optimize Product lane. Ads, platform campaigns and traffic
acquisition are **out of scope** — they live on the TikTok Business API, which Juli does not
hold, and on human-only Seller Center journeys.

## Context

**The owner's draft said GMV = Traffic × CR × AOV and planned four calendar weeks per
product.** Checked against the corpus, two of its load-bearing terms do not exist on the
platform and one of its mechanics breaks Juli's own measurement:

1. TikTok has **no product-level "conversion rate"**. The product-traffic module (La bàn dữ
   liệu, 06/2026) states that *"Tỷ lệ chuyển đổi"* was **renamed CTOR** — SKU orders ÷ product
   clicks — "because every platform computes CVR differently". The per-product list endpoint
   (A-34, `GET /analytics/202605/shop_products/performance`) returns exactly that as
   `click_order_rate`, beside `ctr`, `gmv` and `sku_orders`. The only field literally named a
   conversion rate (`avg_conversation_rate`, A-36) is **shop-grain**, page-view → buyer.
2. TikTok attributes every impression, click and order to one of three **content types** —
   `PRODUCT_CARD`, `VIDEO`, `LIVE` — and the detail endpoint (A-33,
   `GET /analytics/202509/shop_products/{id}/performance`, `granularity=1D`) returns
   `impressions`, `page_views`, `ctr` and `avg_conversion_rate` **per content type**, plus a
   `cancel_and_refunds` block. Listing levers (first image, title, description) act on the
   PRODUCT_CARD funnel only; a product sold mostly through LIVE has an all-channel CTR that
   says nothing about its listing. Juli's backfill fetches A-34 only; the A-33 mapper exists
   but reads one `ctr` and is never scheduled.
3. The Academy prescribes **no field order**. Across the Product Optimizer, Title Optimizer,
   Smart Suggestions, Price Diagnostics and the four-part product-card diagnosis series, the
   one rule is *"find the stage where the card loses customers, then fix that stage"*:
   impression → click weak ⇒ images and title; click → add-to-cart weak ⇒ description and
   price; add-to-cart → payment weak ⇒ promotion tools. The draft's fixed sequence (ảnh bìa →
   tiêu đề → mô tả → đánh giá → ảnh chi tiết → giá) has no source.
4. **Weekly lever rotation on one product defeats ADR-077.** Its ratio-form DiD needs a
   14-day pre window and 7/14-day post windows, and marks any reading `confounded` when a
   second Juli run touches the product inside either window. Four levers in four weeks yields
   four confounded readings and zero outcome labels — the opposite of what the owner wants
   the labels for (training data for a later scorer).
5. **The impact reader cannot read the metric it needs.** `METRIC_MAP` scores a description
   edit on `conversion_rate` and a title edit on `impressions`, and `load_daily_series` reads
   those two columns at product grain — where the product mapper never writes them (it
   writes `ctr` and `click_order_rate`). Every content reading today lands on "Chưa đủ dữ
   liệu" regardless of the data.
6. **AOV is tied to the wrong workflow.** ADR-055 d.15 gives Clear Excess the AOV Main KPI,
   but CE-NFR-3 records that the backend catalog ties it to `inventory_turnover`/`dsi` and that
   its v1 measure is days of supply and goal progress. Clear Excess exists to draw down stock;
   nothing in it raises basket size. The only basket lever with a Partner API surface is
   Buy More Save More (`activity_type: BUY_MORE_SAVE_MORE` on `POST /promotion/202309/activities`,
   ≤ 2 tiers, `MINIMAL_ITEM_QUANTITY` or `MINIMAL_ORDER_AMOUNT`, `PERCENTAGE_OFF` or
   `AMOUNT_OFF`). Bundle deals (Ưu Đãi Theo Gói) have no `activity_type`; vouchers are
   read-only (`coupons/search`); gift-with-purchase (`gift_discount`) exists but cannot
   coexist with BMSM or a bundle on the same product in the same window.
7. **Partner API evidence for VN content levers is concrete.** `GET /product/202405/products/diagnoses`
   returns per-field codes for `TITLE`, `DESCRIPTION`, `IMAGE`, `ATTRIBUTE`, `SIZE_CHART` with
   `how_to_solve` and auto-suggestions (`seo_words`, `smart_texts`, an optimised first image);
   the "Rest of World" code table applicable to VN is `TITLE_LESS_THAN_40_CHARACTERS`,
   `SEO_DIAGNOSTIC_ITEM`, `DESC_LESS_THAN_FIVE_HUNDRED_CHARS`, `DESC_NO_NEW_LINE`, thirteen
   `MAIN_IMG_FIRST_IMG_*` codes, `MAIN_IMG_DUPLICATE`, `MAIN_IMG_NUMBER_LESS_THAN_FIVE`.
   `POST /product/202411/products/diagnose_optimize` diagnoses a *proposed* rewrite before it
   is written. `POST /product/202509/products/{id}/partial_edit` edits one top-level field and
   leaves the rest untouched (Juli's tool today calls the full `EditProduct` with passthrough of
   every other field, which is the right intent on the wrong endpoint). Listing-quality
   *tiers* remain US-only, as ADR-090 d.3 already states. Neither diagnosis endpoint has been
   captured on the sandbox yet; `seo_words` and `suggestions` were, and returned empty arrays.

## Decisions

1. **The funnel identity is TikTok's: GMV = Impressions × CTR × CTOR × AOV, scoped by content
   type.** Juli uses TikTok's metric names and definitions — CTOR = `click_order_rate`,
   AOV = `gmv ÷ sku_orders` — and never a standalone "CR" or "Traffic". Content levers are
   diagnosed and measured on the **PRODUCT_CARD** series from A-33; price and basket levers on
   the all-channel A-34 aggregate, since a discount or BMSM applies everywhere. Video and LIVE
   funnels belong to content workflows, not to Optimize Product. **The measurement formula of
   Optimize Product is this identity applied to one product** — `GMV_sp = Impressions_sp ×
   CTR_sp × CTOR_sp × AOV_sp` (owner, 2026-10-06): the workflow exists to optimise the product,
   raise its conversion, and thereby raise its GMV, so the run's GMV is always read through the
   four factors, never as a bare revenue delta. The workflow owns CTOR and AOV (decision 2);
   CTR moves through the image and title levers under the CTOR label; Impressions is the
   factor the workflow does not own and is reported so a traffic swing is never mistaken for
   a listing effect. **The same identity is the
   workflow's measurement formula** — there is no separate `GMV_sp`; product clicks are
   `Impressions × CTR`, so a three-factor form `clicks × CTOR × AOV` is the same number, and
   impressions never appear as an extra factor beside clicks (owner, 2026-10-06). Impressions
   and CTR are reported beside the reading as the decomposition of traffic the workflow does not
   own. *Rejected:* keeping three
   factors with CR = CTR × CTOR — arithmetically fine, but a number the seller cannot find on
   Seller Center, which OP-NFR-2 forbids Juli from asserting.

2. **Two outcome labels, which are the workflow's two Main KPIs; diagnostic KPIs branch the
   lever.** Each card carries exactly one label, **Increase CTOR** or **Increase AOV**, and that
   label is the card's Main KPI (ADR-055 d.15 amended: a workflow has a Main KPI *set*,
   Optimize Product's is {CTOR, AOV}; Clear Excess's v1 measure stays as CE-NFR-3 wrote it and
   AOV leaves it). **Impressions and CTR are diagnostic KPIs**: a weak PRODUCT_CARD CTR under
   the CTOR label routes to the first image or the title, a weak CTOR with healthy CTR routes to
   the description or a Product Discount. They never appear as a card KPI. The impact reading's
   primary metric is the label's KPI; the diagnostic KPI the lever targeted (CTR for an image or
   title edit) is the secondary metric. "Increase GMV" is the objective, not a label.
   *Rejected:* AOV kept in Clear Excess (no basket lever there, and the tie is already
   contradicted by the catalog); a twelfth "Optimize Basket" workflow (a whole playbook for one
   lever, against the owner's one-structure rule); deferring AOV to v2 (loses one of the three
   pillars of the draft and one label class of training data).

3. **The cadence belongs to the product, not the calendar.** After one lever the product
   leaves the diagnosis queue until its **final impact reading (T+14) is written or
   `suppressed`**; only then is it re-diagnosed. The nightly scoring pass still emits new cards
   every night, on other products, so "5 SKU" means five parallel cards on five products, never
   five successive steps on one. A Product Discount occupies its product for its 30-day window
   and cooldown (OP-FR-4) but does not block a content lever after T+14 — the discount is a
   constant across that lever's pre and post windows, so the DiD stays valid. The draft's
   "week 4: measure and re-optimise" becomes automatic: the preliminary reading (T+7) shows on
   the card, the final reading re-opens the queue. *Rejected:* weekly rotation (every reading
   confounded); re-diagnosis at T+7 on the preliminary reading alone (kept as a seller-selectable
   v2 "fast mode", off in v1); bundling fields to move faster (ADR-090 d.4 and the
   listing-repurposing fingerprint).

4. **Stage diagnosis is a deterministic rule with every parameter in the T7 config.**
   Over the last 14 days: **volume floors** reuse ADR-077 d.4 (≥ 50 PRODUCT_CARD
   impressions/day for CTR, ≥ 20 clicks/day for CTOR, ≥ 1 order/day for AOV) — a factor below
   its floor is neither diagnosed nor acted on, because it could not be measured afterwards.
   **Two gaps per factor**: `gap_median = 1 − value_14d ÷ shop_median_14d` (the median over
   products above the floor, requiring ≥ 5 of them) and `gap_trend = 1 − value_14d ÷
   value_prior_28d` (the 28 days before the window; not computable, hence ignored, under 42 days
   of product age). `gap = max(gap_median, gap_trend)`, with **the trigger that fired recorded on
   the card** so copy says "thấp hơn X % so với trung bình shop" *or* "giảm X % so với 4 tuần
   trước", never a blend. Act only at gap ≥ 0.20 (config, one threshold per gap kind).
   **Label** = the larger gap of {CTOR, AOV}, AOV only when CTOR's gap < 0.20. **Branch under
   CTOR**: CTR gap ≥ CTOR gap → card branch, else page branch. **Lever order inside a branch is
   fixed**: card branch `MAIN_IMG_FIRST_IMG_*` → `MAIN_IMG_NUMBER_LESS_THAN_FIVE` /
   `MAIN_IMG_DUPLICATE` → `TITLE_LESS_THAN_40_CHARACTERS` / `SEO_DIAGNOSTIC_ITEM` (the first
   image is the card's largest element and its fix is mechanical and verifiable by the code
   disappearing; the title carries a character gate and `seo_words` returned empty on the
   sandbox); page branch `DESC_*` first, a Product Discount only when **no description code
   remains** (content costs no margin) **and** the seller's maximum discount is set, otherwise
   `completed` with a new cause `discount_cap_unset`; AOV branch = one-tier BMSM. A branch with
   no code falls to the other branch if that one has a code; neither → `no_diagnosis_codes`
   (ADR-090 d.7). Ranking among eligible products: `gap × GMV_28d` — this is what the T7
   ranker sorts on. *Rejected:* choosing the field with the most codes (count ≠ impact, and
   unexplainable to a seller); shop median alone (misses a product that is falling); own trend
   alone (misses a product that was always weak); FastMoss category benchmarks as the trigger
   (no CTR/CTOR there — deferred to the benchmark role the feature catalog already gives it).

5. **The AOV lever is a one-tier BMSM computed by rule.** `activity_type: BUY_MORE_SAVE_MORE`,
   `product_level: PRODUCT`, one `tier`, `threshold_type: MINIMAL_ITEM_QUANTITY`,
   `type: PERCENTAGE_OFF`, 30-day window, `participation_limit: BUYER_NO_LIMIT`,
   `target_user_info: ALL_USER`. Threshold = the product's mean items per SKU order over 14
   days, rounded up, plus one; percentage ≤ the seller's maximum discount (OP-FR-4); the model
   chooses neither number. Precheck: no Juli-created activity on the product in the window
   (Juli's ledger; `activities/search` becomes the primary check if it captures live, per
   ADR-090 d.2), and the vendor's rejection — including the bundle/GWP collision TikTok
   enforces — is the authoritative lock signal, ending the run `completed` with cause
   `aov_lever_locked`. If the sandbox capture of BMSM fails, the AOV label degrades for v1 to a
   checklist item ("tạo Ưu Đãi Theo Gói trên Seller Center") and the other decisions hold
   unchanged — the unverified fact is isolated to this one decision, as ADR-090 isolated the
   diagnosis scope.

6. **Throughput: at most 5 open Optimize Product cards per shop**, a workflow-config value.
   The sixth-ranked product waits in the nightly queue; a freed slot refills on the next
   nightly pass, never mid-day. The per-product A-33 daily series is backfilled for every
   product that held a card or run in the last 60 days **plus the shop's top 20 by 28-day
   GMV**, so a newly selected candidate already has its 14-day PRODUCT_CARD pre-window when
   its first card is emitted. *Rejected:* uncapped emission and whole-catalog A-33 (500
   calls/day on a 500-SKU shop against an unknown rate limit); carded-products-only backfill
   (the first card of every product would be diagnosed on the all-channel aggregate, against
   decision 1).

## Consequences

- **Outcome labels are the training set.** Each run records `(outcome_label, trigger,
  branch, lever, diagnosis codes cleared)`; `impact_readings` records the control-adjusted
  delta on the label's KPI and on the diagnostic KPI. That pair is the labelled example a
  future scorer would learn from. Per `ml_layer.md`'s technique selection nothing is trained now — T7 stays a weighted
  deterministic sort — and a learned model, if ever, arrives through its own ADR once a few
  hundred clean readings exist.
- **Impact reader fix (defect, not feature):** `METRIC_MAP` → DESCRIPTION and PRICE primary
  on `click_order_rate`, IMAGE and TITLE primary on `ctr` with `click_order_rate` secondary,
  AOV on `gmv ÷ sku_orders`; `load_daily_series` reads `click_order_rate`, `ctr`,
  `impressions`, `page_views` at product grain. OP-NFR-3's "CTOR reading is v2" is withdrawn.
- **Backfill:** schedule `expand_analytics_product_detail` (A-33, `granularity=1D`) for the
  decision-6 set; extend the mapper to `impressions`, `page_views`, `avg_conversion_rate` per
  content type and the `cancel_and_refunds` block. Store the content type on the row (new
  column or the existing `grain` convention — data-platform decides).
- **Tool-set delta (extends ADR-090's):** `update_product_listing` moves from `EditProduct`
  to `POST /product/202509/products/{id}/partial_edit` with one field per call;
  `get_product_diagnosis` and `check_listing_rewrite` as ADR-090 named them; new
  `optimize_product_image` (`POST /product/202404/images/optimize`, `WHITE_BACKGROUND`,
  READ/AUTO — it stages a URI, writes nothing); new `create_bmsm_activity` (WRITE/CONFIRM).
- **Captures required before the first real run:** `diagnoses`, `diagnose_optimize`,
  `partial_edit`, `DIRECT_DISCOUNT` create, `BUY_MORE_SAVE_MORE` create, one `A-33` with a
  non-empty PRODUCT_CARD breakdown, and an attempt at `activities/search`. The owner confirms
  the app holds `seller.product.optimize`.
- **End-state causes added to ADR-090 d.7's table:** `audit_rejected` (partial_edit's v2
  failed TikTok's re-audit; v1 stays live), `discount_cap_unset`, `aov_lever_locked`,
  `below_volume_floor` (card emission should prevent it; if reached, say so).
- **Card copy:** the label's KPI with its real current value and directional goal (ADR-055),
  the trigger sentence (median or trend, never both), the code(s) the lever clears, and for
  BMSM the threshold and percentage with the 30-day window. All through the ADR-070
  banned-pattern guard.
- **Title gate:** the diagnosis targets ≥ 40 characters (`TITLE_LESS_THAN_40_CHARACTERS`),
  policy enforces ≥ 25 on the next edit, the API bounds VN titles to [25, 255]; Juli writes
  toward 40 and never below 25.
- **Out of scope, recorded so nobody re-derives it:** GMV Max is the only Shop Ads campaign
  type since July 2025 and has no keyword control; it and campaign registration live on the
  Business API and Seller Center respectively. Bundle deals, all vouchers (including the
  review voucher), review replies and the Price Diagnostics tier have no Partner API write or
  read; they appear only as seller checklist items.
- **Risk.** Five endpoints are uncaptured. Decision 5 isolates BMSM; decision 4's content
  branches depend on the diagnosis scope exactly as ADR-090 d.3 already does, with the same
  degraded mode. Decisions 1–3 and 6 depend on nothing unverified.
