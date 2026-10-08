# ADR-108: Shop diagnosis report — GMV split into TikTok's five channels, each channel's funnel from Lượt hiển thị sản phẩm to GMV, hero-product profiles and a daily event timeline, built by hand first

**Status:** Proposed
**Date:** 2026-10-08
**Deciders:** grill-with-docs (Architect) with the owner, fourteen questions plus one
consolidation round.

**Replaces:** the planned ADR-106 Amendment 6 (top-5 focus, 30-day decision tree, no
TikTok-diagnosis gate), which was never written; its three points are decisions 5 and 6 here.
**Builds on:** [ADR-106](106-optimize-product-outcome-labels-and-stage-diagnosis.md) (the
funnel identity GMV = Impressions × CTR × CTOR × AOV, A-34 channel blocks — Amendment 2);
[ADR-077](077-incremental-impact-measurement.md) (volume floors); ADR-107's significance
discipline for decision 11.
**Does not change:** the ADR-106 card report (`scripts/shop_optimization_report.py`), the card
rules, or [ADR-107](107-card-journey-log-and-measurement-plan.md). This report renders **no
cards**.
**Scope:** any connected shop. Phase 1 is an operator-run script; Juli automates it later.

## Context

The Fujiwa work (2026-10-06 → 10-08) answered the owner's real questions only after a chain of
hand analyses outside the card report: a 30-day vs prior-30-day channel split, per-channel
funnels, daily flash-sale and voucher checks, and per-product profiles. Three findings could
not have come from the card report:

- **The shop-wide CTOR hid the problem.** All-channel CTOR was flat (5.11 % → 5.10 %) while
  the product-card CTOR fell 4.63 % → 3.19 % and, for the top five products, 5.40 % → 3.23 %.
  Affiliate (~70 % of clicks, flat CTOR) and a seller LIVE whose clicks doubled masked it.
- **GMV grew for a different reason than the seller assumed.** Shop GMV rose 6.6 %/day, almost
  entirely from Lượt hiển thị sản phẩm (+445k ₫/day of +349k ₫/day; CTR, CTOR and AOV were
  each slightly negative). For the top five, the two self-search channels lost ~700k ₫/day
  through CTOR alone.
- **Timing explained it.** Flash sales started 07/09 and covered 56 % of the next 30 days
  (97 % in the week of 28/09) at only 2–4 % below an already-running product discount;
  the product-card order/add-to-cart rate fell from 50.6 % to 39.5 % on flash days and 25.7 %
  on non-flash days. The two shop vouchers had lapsed 01/09 and returned 22/09 — their effect
  cannot be separated from the flash sales with the days available.

Two process errors also surfaced: two data paths (one 30-day aggregate call, sums of daily
files) gave different numbers, and the Shop Tab block — whose fields carry a `shop_tab_` prefix
— was silently read as zero in one shop-wide table. And the hand CTOR used orders, not
TikTok's SKU orders.

## Decisions

1. **Output: two layers from one set of numbers.** An internal HTML page per shop and a draft
   message to the seller, both generated from the same computed snapshot so they cannot
   disagree. The page is **Vietnamese only** and contains **no backend field names, endpoints or
   code identifiers — not even in footnotes**; its notes explain each calculation in words. KPI
   and channel names are **TikTok's own Vietnamese wording** (TikTok Academy, *Lưu lượng truy cập
   sản phẩm*):

   | Report term | Data source |
   |---|---|
   | Lượt hiển thị sản phẩm | `product_impressions` |
   | CTR (Tỷ lệ nhấp) | clicks ÷ impressions |
   | Lượt nhấp vào sản phẩm | `product_clicks` |
   | Tỷ lệ thêm vào giỏ hàng | add-to-carts ÷ clicks |
   | Số lượt thêm vào giỏ hàng | `add_cart_count` |
   | Đơn hàng SKU | `attributed_sku_orders` / `sku_orders` |
   | CTOR | SKU orders ÷ clicks |
   | AOV (SKU) | GMV ÷ SKU orders |
   | GMV, Hoàn tiền | `attributed_gmv` / `gmv`, `refunds` |
   | Thẻ sản phẩm của người bán · Tab Cửa hàng · Video của người bán · LIVE của người bán · Liên kết (Video liên kết, LIVE liên kết) | the five A-34 channel blocks |

   **Every KPI uses TikTok's own calculation** (owner directive 2026-10-08):
   - CTR = clicks ÷ impressions. Tỷ lệ thêm vào giỏ hàng = add-to-carts ÷ clicks, per TikTok's
     2026 redefinition, which uses clicks rather than unique visitors.
   - CTOR = **SKU orders** ÷ clicks. AOV (SKU) = GMV ÷ SKU orders.
   - GMV is TikTok's GMV, which includes cancelled and refunded orders. Nothing is netted out.
   - A rate over a window is the ratio of the window's totals, as Seller Center computes it
     for a date range. It is never an average of daily rates.

   Verified on Fujiwa, 07/09–06/10:
   - Summing the 30 daily files reproduces TikTok's 30-day aggregate exactly for the top five
     products: impressions, clicks, SKU orders, GMV and `click_order_rate`.
   - TikTok's `aov` equals GMV ÷ SKU orders.
   - SKU orders and orders are equal at product grain on the product-card channel. They differ
     by ~1 % on the all-channel total (808 vs 799). Hand figures built on orders therefore
     move by at most about 1 %.

   A test pins the equality of daily sums and the aggregate on a synthetic fixture.

2. **Data: daily A-34 for 60 days is the only source.** One file per day, ending **yesterday
   (UTC+7) by default, with an operator-chosen end date** (to step around a sale season). Days
   already on disk are not refetched. "30 ngày gần đây" and "30 ngày trước" are sums of the
   daily files; only additive counts are summed (impressions, clicks, add-to-carts, SKU
   orders, GMV) and every rate is recomputed from the sums — the "unique" fields are never
   used. Orders are fetched by **create time** for the same 60 days; promotions and vouchers
   with their full history. Days of a platform sale (9.9, 10.10, …) are **marked, not
   dropped**. Every figure in a table is a **daily average** over its 30-day window.
   Rejected: one aggregate call per window (disagreed with the daily path on Fujiwa).

3. **Refresh: once a day.** In phase 1 the operator runs the fetch each morning (it adds only
   yesterday) and rebuilds; the page is republished to the **same link per shop**, which serves
   as the shop's dashboard. Under automation Juli schedules the daily run, stores the series in
   the database and moves the dashboard into the app. Rejected: weekly (too slow for flash
   sales); no manual phase.

4. **Step 1 — split shop GMV into the five channels.** For each channel: average daily GMV in
   the last 30 days and the prior 30 days, the change, and its contribution to the change in
   total GMV. Channels form two groups:
   - **Nhóm khách tự tìm đến** — Thẻ sản phẩm của người bán + Tab Cửa hàng. Listing, price and
     voucher work acts here; **CTOR is this group's main KPI**.
   - **Nhóm nội dung** — Video của người bán, LIVE của người bán, Liên kết. Lượt hiển thị sản
     phẩm and GMV are the main KPIs; CTOR is shown for reference only.

5. **Step 2 — each channel's funnel, Lượt hiển thị sản phẩm → GMV.** Chain: Lượt hiển thị sản
   phẩm, CTR, Lượt nhấp vào sản phẩm, Tỷ lệ thêm vào giỏ hàng, Số lượt thêm vào giỏ hàng, Đơn
   hàng SKU, CTOR, AOV, GMV. The GMV change is split into four contributions — Impressions,
   CTR, CTOR, AOV — by log shares: for factor *f*, `ΔGMV × ln(f₁/f₀) ÷ ln(GMV₁/GMV₀)`.
   - **Tab Cửa hàng** has no add-to-cart data; those cells read *"TikTok không cung cấp"*. Its
     SKU orders are derived as CTOR × clicks and labelled *ước tính*. The block's fields carry
     a `shop_tab_` prefix; the reader must map them explicitly (the Fujiwa shop-wide table lost
     this channel by reading it as zero).
   - **Video and LIVE của người bán**: buyers often order without a cart, so "đơn trên thêm
     giỏ" reads *"khách mua ngay"* and CTOR carries the note *"gồm khách mua thẳng"*.
   - **Liên kết** is shown for understanding the whole shop and never drives a product
     conclusion. Its Video/LIVE branches have impressions, clicks, CTR and GMV but no orders,
     so they appear as sub-rows without CTOR.

6. **Step 4 — hero products.** Five products by GMV (all channels). The script **asks the
   operator** which ranking to use and the page states it: (a) GMV over the 60 days combined —
   the default, because ranking on the last 30 days drops exactly the products whose CTOR
   collapsed — or (b) GMV over the last 30 days. Products in the top five of one window but not
   the chosen ranking are listed as *"vào top"* / *"rơi khỏi top"*. If the five carry under
   50 % of shop GMV the page says *"shop phân tán, top 5 chưa đại diện"*.

7. **Decision tree per hero product, on its Nhóm khách tự tìm đến.**
   1. GMV change under 10 % either way, or under 30 SKU orders in a window → *Ổn định* /
      *Chưa đủ dữ liệu*.
   2. Otherwise the largest contribution (negative if GMV fell, positive if it rose) is the main
      story — **only among factors labelled Rõ** (decision 11); if none is, the conclusion is
      *Chưa rõ nguyên nhân* with the largest factor shown for reference.
   3. If the largest factor is Impressions, fall back to the second (listing work barely moves
      impressions); impressions still appear in the profile.
   4. If the story is CTOR, split it: Tỷ lệ thêm vào giỏ hàng falling → **trước giỏ** (price,
      images, description, reviews); orders per add-to-cart falling → **sau giỏ** (vouchers,
      shipping fee, buyers waiting for a flash sale).
   5. Nhóm nội dung gets its impressions and GMV change stated, no separate story.

   The owner's rule "CTR up and AOV up but GMV down → the story is CTOR" is the special case
   of 2. Thresholds (10 %, 30 orders) live in config. The TikTok product-diagnosis endpoint is
   **not** a gate.

8. **Hero-product profile, in this order.**
   1. Conclusion from decision 7 plus one line *"Cần xem tiếp"* naming where to look, not what
      to do (trước giỏ → ảnh bìa, giá, đánh giá; sau giỏ → voucher, phí vận chuyển, lịch flash
      sale).
   2. KPI table, 30 vs prior 30 days, including số món trên đơn, Hoàn tiền ÷ GMV, and GMV share
      by channel.
   3. Funnel per channel for **all five channels** (Liên kết included, decision 5), each
      channel tagged (*"CTR giảm rõ"*, *"ít lượt hiển thị"* …) with the reading rule: CTR down in
      nearly every channel → the cause is the product; down only in the channel that just
      received a surge of impressions → diluted traffic, do not edit the listing.
   4. Promotions on this product (flash sales, product discounts, vouchers in scope) as date
      bars, filtered from decision 9.
   5. Giảm giá trên đơn: share of items carrying a platform discount and a seller discount,
      both windows.
   6. The five LIVE sessions and five videos with the most orders, plus the count of sessions
      with none.

   Shop-level sections kept: chỉ số trung bình của shop, phần còn lại ngoài top 5, sản phẩm cần
   theo dõi. The old *"TikTok chỉ ra lỗi gì"* section is dropped.

9. **Step 3 — event timeline, the only daily view.** Per channel, four lines — Lượt hiển thị
   sản phẩm, CTR, CTOR, AOV — as **7-day rolling averages** (a small shop has 2–4 product-card
   orders a day; raw daily lines are noise). Flash sales, product discounts and vouchers are
   drawn as date bands on the same axis, each with its type and the number of its days inside
   each 30-day window. Tables everywhere else stay 30 vs 30; no day-by-day change tables.

10. **Promotions analysis.**
    - **Vouchers** are classified from their configuration, not their seller-written title,
      against the **giá một món phổ biến** (median value of single-item orders, last 30 days):
      *Chốt đơn* (no threshold, or below the value of 75 % of single-item orders) · *Nâng giá
      trị đơn* (between that and 1.8×) · *Đơn nhiều món* (≥ 1.8×) · *Cá nhân / bù khách* (total
      claims 1–3) · *Riêng sản phẩm* (specific-product scope, plus its threshold class).
      Vouchers live in the 60 days are analysed — discount as % of the common single-item price,
      share of orders within 15 % below the threshold, order-value mix before vs after the start
      date, labelled *"chưa tách được khỏi flash sale"* when the two overlap; older vouchers are
      summarised by month. Actual redemptions and cost are used if the order data identifies the
      voucher, otherwise an upper-bound estimate is labelled as such.
    - **Flash sales**, per hero product and shop-wide: coverage per day and week (a day is a
      flash day at ≥ 50 % coverage); **true depth** = flash price vs the already-discounted
      price, not vs list price; CTOR and order-per-add-to-cart on pre-flash days, flash days and
      non-flash days (cells under 5 days or 30 orders read *Chưa đủ dữ liệu*). Three flags:
      *Flash gần như liên tục* (30-day coverage > 50 % or any week > 80 %), *Flash quá nông*
      (true depth < 5 %), *Khách chờ flash* (non-flash order-per-add-to-cart below both flash days
      and pre-flash). Flags are shown; **no recommendation is generated** (decision 12).

11. **Confidence label on every comparison.** *Rõ* — ≥ 30 orders on each side and the 90 %
    interval of the difference excludes 0 (two-proportion test for rates; daily-series interval
    for GMV and AOV). *Tham khảo* — 10–29 orders a side, or a difference inside the noise band.
    *Chưa đủ dữ liệu* — under 10 orders on a side. The seller message uses only *Rõ* numbers;
    *Tham khảo* numbers must carry the word *"dấu hiệu"*. Rejected: order floors without a test
    (labels chance as Rõ); ADR-107's 30 % MDE (nearly every small shop would read Chưa đủ).

12. **Analysis only.** The report ends each hero profile with its conclusion and *Cần xem tiếp*.
    The existing card code is untouched but not rendered here — its product selection and
    diagnosis follow the older rules, and two contradictory sets on one page is what produced
    two different "5 cards" for Fujiwa. Mapping conclusions to cards (and to ADR-107's journey)
    is a separate grill when Juli automates.

13. **Code and run order.**
    - A new pure package `backend/src/juli_backend/services/shop_diagnosis/` beside
      `optimize_product/`, reusing its order-window helpers; one module per step (channels and
      funnel, decomposition and decision tree, hero products, promotions, timeline, confidence,
      rendering) and one config file for every threshold above. No live I/O (import boundary).
    - Two scripts: a **read-only fetch** (production-read client, transport guard) writing a
      **shop snapshot** — daily A-34 files, orders, promotions, vouchers, flash-sale details,
      LIVE and video lists — and an **offline build** that asks the ranking mode and writes the
      HTML page, a JSON of every number, and the message draft.
    - Snapshots live **outside the repo**, one folder per shop and end date; order data holds
      buyer information and is never committed.
    - Tests use synthetic snapshots, never Fujiwa data.
    - A runbook: (1) the owner runs the fetch with `!` so credentials never pass through the
      agent; (2) build; (3) read the page and its labels; (4) edit the message; (5) send;
      (6) keep the page and the sent message with the snapshot.

## Dropped in the grill

- **Basket, shipping and weight section** (order composition, buyer-paid shipping share, the
  >10 kg logistics fee). Agreed in question 8, then removed by the owner in the consolidation
  round. The analysis code in `optimize_product/basket.py` stays for the card report.
- **Affiliate split into two separate funnel rows** — kept as one channel with sub-rows.
- **A daily CTOR line inside each hero profile** — replaced by the shop-level timeline.

## Consequences

- One page per shop answers "which channel moved GMV, through which factor, for which product,
  and what was running at the time" — the Fujiwa questions — without hand work.
- First run per shop costs ~60 A-34 calls (paginated by product), plus orders; each daily
  refresh costs one day.
- The page deliberately shows no technical identifiers, so this ADR and the code's
  docstrings are the only map from a page number to its source field.
- Conclusions are weaker on small shops by design: Chưa rõ nguyên nhân and Chưa đủ dữ liệu
  will be common, and that is the honest reading.
- Open: the voucher-per-order field is unverified (decision 10 has a fallback); Seller Center
  may expose finer-than-daily data that the API does not — not pursued.
