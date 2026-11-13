# ADR-122: One Shopee funnel, stored once, behind every screen and every option result

**Status:** Accepted (owner, 2026-11-09, grill P98 C1–C10)
**Date:** 2026-11-09
**Deciders:** owner (Thiên) with the agent.

**Builds on:** [ADR-120](120-shopee-precise-shop-view-profit-floor-and-sources.md) d.3 (the KPI chain
Lượt xem → CTR → CTOR → AOV → GMV → Biên lợi nhuận), [ADR-121](121-shopee-models-simulation-and-learning-loop.md)
(the predicted range). P97 D85.2 (ShopMetrics: headline GMV / đơn = Shopee shop totals, migration 123).

## Context

ADR-120 names the chain but not where each factor comes from. As built (P97):

- GMV, đơn, AOV and profit come from ShopMetrics (`shopee_shop_metrics_daily`,
  `shopee_product_metrics_daily`): Shopee's shop totals, product splits scaled to them.
- Views and clicks come from the per-source traffic tables, and CTOR there divides **those tables' own
  order count** by clicks.

The two order counts differ, so Views × CTR × CTOR ≠ Đơn even before any change. The builder's
"So sánh phương án" (`shopee_builder/before_after.py`) then moves GMV from a money layer and one funnel
metric separately: a title / cover option raises views or CTR while đơn and AOV stay "unchanged" and
GMV still rises; AOV's range is a ratio of two percentiles. Options cannot be compared on one footing.

## Decisions

1. **Option result (grill C1).** Every option (Voucher, Combo, Ads, Affiliate, …) is judged on
   Δ GMV, Δ Đơn and Δ Lợi nhuận (low / likely / high), always derived through the funnel —
   **Đơn = Lượt xem × CTR × CTOR**, **GMV = Đơn × AOV**, **Lợi nhuận = Đơn × lợi nhuận mỗi đơn − chi phí
   cố định của thay đổi** — never estimated directly. Each option names one or two **driver metrics**
   from Lượt xem, CTR, CTOR, AOV; only drivers change. Đơn moves only when a driver sits above đơn
   (Lượt xem, CTR, CTOR); an AOV-only option has Δ Đơn = 0 by construction. The option's own costs
   (discount, commission, samples, ad spend) enter lợi nhuận mỗi đơn or the fixed cost, not the drivers.

2. **One funnel, stored once (grill C2).** The funnel is built in the materialized daily tables
   (migration 123) and every Demo screen (Tổng quan, Phân tích, Sản phẩm, KOL, Quyết định, Kế hoạch) and
   every backend calculation (cards, builder, plan base, measurement) reads it from there — no screen or
   service recomputes a factor from another source.
   - Đơn, GMV, AOV, lợi nhuận mỗi đơn: ShopMetrics (match Tổng quan by construction).
   - Lượt xem, lượt nhấp: the traffic tables, stored on the same day rows.
   - **CTR = lượt nhấp ÷ lượt xem; CTOR = đơn (ShopMetrics) ÷ lượt nhấp**; ratios are always computed
     from the window's sums, never averaged per day. So Lượt xem × CTR × CTOR = Đơn exactly.
   - Window: the same last 30 complete days ending at the Tổng quan anchor; scope: the product(s) an
     option touches, or the shop for a shop-wide option.
   - A scope with no traffic rows shows Lượt xem / CTR / CTOR as "chưa có dữ liệu", and an option
     driven by them is "chưa ước tính được" for it — never a fallback number.
   - The cards say once: "CTOR = đơn (theo Tổng quan) ÷ lượt nhấp" (it can differ from the CTOR in
     Shopee's traffic report).

3. **The funnel is stored per traffic source (grill C2b).** Sources as the traffic tables split them:
   Thẻ sản phẩm (ngoài Trang shop), Trang shop, Live, Video, Liên kết, and the residual
   "Chênh lệch nguồn". Đơn per source are scaled to ShopMetrics đơn (as product splits are), so the
   sources add up exactly to Tổng quan and the residual shows what Shopee does not assign. Each source
   has its own Lượt xem, lượt nhấp, CTR, CTOR. Quảng cáo is stored as the "trong đó" share of Thẻ sản
   phẩm (ad views, clicks, đơn, spend), never added on top (ADR-120 d.3). An option names the source(s)
   its drivers act on and changes only those; the shop's Δ is the sum. A shop-wide driver (voucher,
   price, combo) applies to every source and the results add up. Product × source rows exist where the
   item-traffic reader has run; otherwise the product uses its all-source funnel and the card says so.

4. **Ranges are whole scenarios (grill C3).** Each driver gets its uncertain effect (the lift
   distribution the model already produces; two drivers are drawn together); a few thousand outcomes
   are simulated through the full funnel with a fixed seed (same option → same numbers); outcomes are
   ranked by Δ Lợi nhuận and low / likely / high are the outcomes at P10 / P50 / P90 — every metric of a
   column comes from that one outcome, so the funnel holds exactly in each column. "Before" numbers are
   measured and carry no range.

5. **Minimal card (grill C9, owner: "minimal cognitive load").** Every option card has the same lines:
   - **Δ Lợi nhuận** — money · % for the strategy's whole duration, with its range (low … high);
     under it one build-up line of at most three parts: extra đơn × lợi nhuận mỗi đơn, the AOV effect,
     minus the offer's cost.
   - **Δ GMV** and **Δ Đơn** — money (count) · %, likely value. An option that cannot move đơn shows
     "+0" and why, in a few words.
   - **Tác động** — the one or two drivers, % change only, on one line.
   - **Chi phí** and the break-even on one line ("hoà vốn khi thêm ≥ N đơn hoặc AOV ≥ X").
   - **Sau N ngày** — totals before → after for the whole strategy: GMV and Lợi nhuận = the same scope's
     base for N days plus the strategy's total uplift.
   Every % is against the same scope's base for the same number of days (the 30-day base scaled to the
   duration). A strategy without an end date (price, title, cover, variations, a new combo listing) uses
   a 30-day horizon labelled "30 ngày đầu". Everything else — the seven funnel metrics in đ, the low /
   high scenarios, the source a driver acts on, per-day / per-order figures — sits behind "Chi tiết";
   the estimate basis shows as a small tag only when it is weak ("ước tính chung").
   **Comparison table:** one row per strategy — Thời gian, Δ Lợi nhuận, Δ GMV, Δ Đơn (money · %, the
   row's own total) — sorted by Δ Lợi nhuận per 30 days so strategies of different durations rank
   fairly.

6. **Voucher (grill C4).** Voucher đơn tối thiểu: drivers **AOV** (baskets raised to the minimum) and
   **CTOR** (a visible discount converts more clicks; small prior labelled "ước tính chung" until ORY's
   measured vouchers calibrate it, ADR-121). Tri ân / đánh giá: CTOR. Giảm mức voucher: CTOR (down), the
   saving enters lợi nhuận mỗi đơn. Source by scope: shop / product voucher → every source of the scope;
   livestream voucher → Live; follower voucher → every source, scaled by the measured follower share
   ("chưa biết tỉ lệ người theo dõi" until measured). Cost = discount per use × expected uses (today's
   qualifying orders + the extra orders + orders raised over the minimum, capped by the usage limit);
   lợi nhuận mỗi đơn falls by the discount on the orders that use it.

7. **Combo (grill C5).** *Combo khuyến mãi* (tiers on existing listings): drivers **AOV** (buyers buy
   up to a tier) and **CTOR** (the "Mua N giảm X%" badge on the card), every source of its products;
   cost = the discount on **every** order that reaches a tier, including orders that already bought that
   many without it (counted from the shop's own order lines). *New combo listing* (pack × variation
   options): orders that already hold those quantities switch to it (AOV and lợi nhuận mỗi đơn change,
   Δ Đơn 0); its **extra orders come only from the shop's own matching pack variations** — a new pack
   option takes the measured CTOR and AOV of the same pack size of the same product, views from the
   product's current views. Without such evidence Δ Đơn is "+0 · chưa có dữ liệu cho quy cách này"
   (never a general prior). The listing's own measured funnel replaces the estimate once it runs
   (ADR-121 loop).

8. **Ads, new campaigns (grill C6).** Setups for Dịch vụ Hiển thị Sản phẩm (chiến dịch nhóm / đơn):
   products, daily budget, ROAS target or Shopee-optimised, dates; compared first, entered by hand,
   auto-filled later. Driver **Lượt xem** (ad impressions, added to the "trong đó Quảng cáo" share of
   Thẻ sản phẩm) from spend through the shop's measured CPM, with the spend a ROAS target lets Shopee
   use taken from the shop's history at similar targets. CTR / CTOR (direct orders ÷ clicks) / AOV of
   the ad traffic: same product's past campaigns > same ad type shop-wide. **Only extra orders count,
   measured** from the shop's history — the product's organic Thẻ sản phẩm orders on days with vs
   without ads (owner: option (c), no general-prior fallback). Without that history Δ Đơn / Δ Lợi
   nhuận are "chưa ước tính được — cần chạy thử", with the exact cost, the break-even ("cần ≥ N đơn tăng
   thêm") and a short measured test offered. Broad orders scale by the same extra share. Chi tiết shows
   "ROAS Shopee" (attributed) beside "ROAS tăng thêm" (extra only). Cost = spend over the period.

9. **Affiliate / KOL (grill C7).** Inputs: KOLs chosen from the KOL table, products, a targeted
   commission % and / or samples (product, quantity per KOL, shipping cost). Driver **Lượt xem** on
   the Liên kết source for the chosen KOLs × products only; each KOL's CTR / CTOR / AOV from their own
   measured row. Cost is exact: commission % × the KOL's GMV, samples = quantity × (giá vốn + đóng gói)
   + shipping. **Extra orders are measured only** (as for Ads): from the shop's own before / after on that
   KOL; until then the card leads with the cost and the break-even ("cần ≥ N đơn (≈ X lượt nhấp với tỉ lệ
   chuyển đổi của KOL này) để hoà vốn") and Δ Đơn is "chưa ước tính được — đo sau lần gửi mẫu đầu".
   **Cashback / coupon affiliates** (e.g. accesstradevn, shopbackvn_) are labelled "trang hoàn tiền / mã
   giảm giá", are not suggested samples, and their orders do not count as extra when measuring.

10. **Every other option (grill C8).** Drivers and source per family:
    | Family | Options | Drivers | Source |
    |---|---|---|---|
    | Price | Giá, Giảm giá sản phẩm, Flash Sale, Đăng ký chương trình, Mega sale | CTOR + AOV | every source |
    | Listing: title / keywords | Tiêu đề, Từ khoá | Lượt xem + CTR | Thẻ sản phẩm |
    | Listing: image | Ảnh bìa, Hiển thị giá | CTR | Thẻ sản phẩm |
    | Listing: page | Dòng đầu mô tả | CTOR | every source |
    | Listing: visibility | Ẩn / đăng lại | Lượt xem | every source |
    | Basket | Mua kèm deal sốc, Bộ / quy cách nhiều món, Cơ cấu phân loại | AOV (+ CTOR for variation changes) | every source |
    | Gift | Quà tặng kèm | CTOR | every source |
    Evidence for these families: this product's own history (days with vs without the change) > the
    shop's measured results > a general prior tagged "ước tính chung". **Ads and Affiliate stay
    measured-only** (d.8, d.9) because Shopee's attribution inflates them. Ads edits (budget, ROAS, pause,
    keywords, add / remove product) are hidden from the builder for now (owner: no edits of existing
    campaigns).

11. **Accuracy is proven four ways (grill C10).**
    1. *Funnel tests, every option kind, at build time:* in every scenario column Lượt xem × CTR × CTOR
       = Đơn (to rounding of one order), Đơn × AOV = GMV (± 1đ), the Δ Lợi nhuận build-up adds up, the
       sources add up to the shop. A failure fails the deploy gate.
    2. *Cross-screen test (Postgres fixture):* Tổng quan, Phân tích, Sản phẩm, Kế hoạch and the builder's
       "before" show the same Lượt xem, CTR, CTOR, Đơn, AOV, GMV, Lợi nhuận for the same shop, scope and
       window.
    3. *Daily production check:* after each metrics rebuild the stored funnel is compared with Shopee's
       raw shop totals and the traffic tables; a gap above 1 % or a broken identity is logged and shown in
       Ops as "lệch số liệu" for that shop and day — never silently corrected.
    4. *Scoring after the run:* every executed option's prediction is frozen at approval and scored at
       14 / 28 days (ADR-121); the card shows "Đo được: Δ Lợi nhuận X (dự kiến Y)", Ops tracks coverage
       (target ≈ 80 % inside low–high), and a family that keeps missing is widened or switched to
       "chưa ước tính được" by the existing calibration.

12. **Two margins per variation (owner, 2026-11-09).** Everywhere a variation's margin appears
    (Sản phẩm › Phiên bản sản phẩm, So sánh phân loại, the combo builder rows):
    - **Biên ở giá bán — chắc chắn:** one order at today's selling price through the shop's fee
      schedule, giá vốn and packaging only (today's `variations.unit_margin`).
    - **Biên cuối — ước tính:** the same order minus this variation's measured 30-day rates of shop
      voucher, affiliate commission and ad cost (ads allocated by revenue as `product.py` does); a
      variation without history takes its product's rates, and the cell says so. Same name as ADR-120
      d.4 ③ "biên lợi nhuận cuối".
    The combo builder prices (target margin) and floor-checks on **Biên cuối**; it shows both. Also on
    the product page: "Đơn 30 ngày" counts orders (units in Chi tiết), each variation's SKU chip shows
    its pack key (G500001×3), and the footer drops the "giả định 1/3 giá" text (no 1/3 fallback,
    "chưa tính" when giá vốn is missing, as in the builder, P92 B-7.1).

13. **Estimates settled at the wave-2 merge (owner, 2026-11-09).**
    - *E1 — visible-offer CTOR prior:* 0 % / 1 % / 3 % (low / likely / high), tagged "ước tính chung"
      until the shop's own measured offers calibrate it (ADR-121).
    - *E2 — reach to a voucher minimum or a combo tier:* **measured** from the shop's order lines —
      the share of orders within 20 % below the minimum / tier today; the 0 / 20 / 50 % prior only
      when there are too few orders to measure (then tagged "ước tính chung").
    - *E3 — a new combo listing's extra orders:* only pack sizes the shop does **not** sell today add
      orders (from the matching variation's measured rates); a pack size the shop already sells is
      switching — Δ Đơn 0, AOV and lợi nhuận mỗi đơn change.
    - The second driver of a two-driver option takes 50 % of the lead lift, tagged "ước tính chung".

14. **One Lợi nhuận (owner, 2026-11-09, found by the cross-screen test d.11.2).** The headline profit on
    every screen (Tổng quan, Phân tích, Sản phẩm, Kế hoạch, the builder "before") is the ShopMetrics
    profit: the profit of the orders with line detail, scaled to the shop totals (× shop GMV ÷
    order-line GMV), so it matches the GMV and đơn beside it; tagged "ước tính theo tỉ lệ" when the
    scale is above 1. The profit waterfall stays as the breakdown, labelled "chi tiết trên N đơn có dữ
    liệu chi phí (X % GMV)". CTR / CTOR are never rounded as fractions: every screen carries the
    percent with two decimals (or the full fraction).

## P99 amendment (2026-11-10)

Found by the cross-screen check of the P98 deploy; the decisions above stand, these refine them:

- **d.7:** a new combo listing with no pack evidence **and** no basket that would switch is "chưa ước
  tính được — chưa có dữ liệu cho quy cách này" (no result numbers), never an all-+0 estimate. With
  switching baskets the measured AOV effect stays and Δ Đơn is +0 with the note.
- **d.9:** a commission rate without a chosen KOL (the builder's Liên kết tab) gets an option result:
  cost = commission % × the product's expected Liên kết GMV + samples, its break-even, extra orders
  "chưa ước tính được". So it joins So sánh and Kế hoạch like any other option.
- **d.8:** a new-campaign setup of the Ads tab is a builder version (`ads_new`) and can be added to
  Kế hoạch; there it is "chưa ước tính được" with its exact cost until measured.
- **d.2 / d.5 / d.12:** Kế hoạch adds a card's Δ only onto the base it was computed on (each card and
  each product block carry that base and their "sau"); its cost per month is the card's result cost
  (the spend cap reads it too); So sánh "Hôm nay" is the versions' own scope; every "hôm nay" margin is
  `ProductProfit.margin_pct` math (shop: `ShopProfit.margin_pct`). Profit per order counts the orders
  of the days with costs and says "trên N ngày có dữ liệu chi phí" when some days have none.
- **d.5:** a voucher without dates is evaluated, saved and planned on the same 30-day horizon.

## P99b amendment (2026-11-10, owner)

- **Kế hoạch = the next 30 days from today.** A draft plan is recomputed live on the newest anchor
  (no frozen base / ``as_of``; "Cập nhật số" is no longer needed). The horizon is today .. +29 in the
  shop's calendar (``aggregate.horizon``). Each card counts its own-dates Δ and cost **only on its
  own days inside the horizon** (Δ per own day × counted days; never ×30/days); a change without
  dates starts with the plan (a group's first day); a card wholly outside counts 0 and says so
  (``outside_horizon``). Plan total = baseline 30 days + Σ counted Δ; cards on one product still add
  (d.2: each result stands on the same base with its own drivers; the base is counted once per
  scope). The spend cap compares the horizon's spend (spend/day × 30 + the cards' counted cost).
- **Tự tạo uses the set dates (d.5):** a version's ``delta`` / ``cost`` cover exactly its own days
  (``dates``); ``per_30d`` is secondary, labelled "Quy đổi 30 ngày (tham khảo)" (still the sort key
  of So sánh). The plan card repeats the version's own figures as ``result.own``.
- **No stored daily rows = a state, not numbers (d.2/d.3):** a screen's window (Tổng quan, Sản
  phẩm, xếp hạng, Luồng, the builder base and picker, Kế hoạch) with a data day lacking its stored
  row raises ``stored.RowsNotMaterialized`` -> 409 ``rows_not_materialized`` "Chưa có số liệu theo
  ngày cho khoảng này — đang tính lại"; the raw-table path (the old unspread period split) only
  feeds the metrics rebuild. A window whose data days all have rows reads the rows even when some
  are not ``complete``. A comparison window without rows is withheld (not comparable).
- **Unknown is null with a reason:** a plan card without a result has an unknown cost
  (``cost_unknown_cards``), never the money layer's; the money layer's "certain" figures are null on
  the option-result path; profit per order is unknown when the base counts its days and none with
  costs had an order (no silent ÷ every order); the plan's Δ biên / AOV stay null when the profit /
  đơn are unknown; ``totals_partial`` / ``totals_note`` name what the totals leave out.

## Consequences

- **Live numbers change.** Options whose driver sits above đơn now move đơn (a minimum-spend voucher
  no longer shows Δ Đơn 0); CTOR on cards, Phân tích and Sản phẩm follows d.2; every card and the
  comparison table change shape (d.5).
- **New storage:** the source funnel (d.3) is a new materialized table filled by the same `after_ingest`
  hook and backfill as migration 123 (one migration, expand-only).
- **One engine replaces two paths:** `shopee_builder/before_after.py` and the per-kind money layer stop
  producing results on their own; evaluators keep producing costs and profit per order, and one funnel
  engine (drivers → scenarios → result) produces every option result.
- **Ads and Affiliate show fewer numbers at first** ("chưa ước tính được — cần chạy thử" / "đo sau lần
  gửi mẫu đầu") until ORY's own history measures them; their cost and break-even are always exact.
- **Plan:** `fasttrack/contracts/p98-plan.md`.

## P99c amendment (2026-11-10, owner)

- **A saved profit rule rebuilds the stored daily rows.** Saving giá vốn, packaging, pack, VAT or
  exclusion rules (`materialize.PROFIT_RULE_KEYS`) rebuilds every data day of the shop in the same
  transaction (`materialize.after_rules_change`), so no screen reads profit computed with the old
  cost. A failed rebuild deletes those days' rows: screens answer `rows_not_materialized` until the
  backfill CLI runs. Rules have no effective dates, hence all days.
- **Tự tạo cost / break-even cover the version's own days** (`result.days`, else the set dates,
  else 30 for an undated version); a figure that cannot be computed for those days is null with
  `no_result_for_days`, never a 30-day number.
- **So sánh ranks by Δ lợi nhuận per day of the set dates** (`sort_basis.key =
  delta_profit_per_day`), unknowns last; the UI keeps the server's order. `per_30d` is a labelled
  secondary reference only.
