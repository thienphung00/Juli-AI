# P100 — session briefs (grill of 2026-11-11, after the P99 deploy)

Production: P99 LIVE = `412f3fbd` (tag `fasttrack-deploy-20261110T1426Z`, run 42834151790, no
migration). The owner ran the VPS backfill and loaded Connector 0.3.16. This file is committed
locally on `fasttrack/p99-combo` in worktree `.worktrees/p97-shopee-data` (not pushed); start
from `fasttrack/optimize-product` = `412f3fbd` plus this commit. Standing rules unchanged: ask before
push/tag (per sha), SSH, merging PRs, any browser use beyond the task; never write Fujiwa;
synthetic data only in the repo; owner runs prod SQL / VPS commands (read-only, ORY-scoped);
questions in plain chat. zsh: quote refspecs as `"${S}:refs/heads/…"` and confirm
`origin/<branch>` == sha before tagging.

Two sessions:
- **Session 1 — Shopee client**: the real seller app (app-juli.com) + backend + Connector, on
  ORY's data.
- **Session 2 — ISV demo client**: a minimal synthetic shop on the real backend, same code paths,
  only finished features. Starts after Session 1's pieces land.

---

## A. What the P99 check on ORY found (11/10–09/11)

Working: product 26107129526 = 50 orders (shop 78–85; Shopee file 52), AOV 82–275k (was 12.5k),
views 300–1.6k/day (was 21.306 every day), product ≤ shop every day; one margin per product
across Luồng / Tổng quan / Tự tạo; Tự tạo picker loads; Kế hoạch window 11/11–10/12 and its
cards add up to its Δ.

Still wrong (all are Session 1 work, part 1):
1. **Missing days stored as 0.** Shop orders 0 on 18/10, 28–30/10, 07–08/11 and no row on
   19/10, 31/10, 03/11 = days whose order data never arrived ("Đơn hàng: 21/30 ngày"). They are
   counted as zero sales.
2. **Profit 0,00 on 04/11 with 2 orders**: unknown cost written as 0.
3. **Previous period still wrong**: the product shows orders ▼78,9 % (≈237 vs shop ≈113) and AOV
   ▲143 %. Rows before 12/10 look uncorrected. The owner has not yet pasted
   `days_product_over_shop` (90 d), `missing_day`, the ROAS totals or `ingest_dataset_status`;
   ask for them first.
4. **Three shop profits on Tổng quan**: 2.861.354đ (detail, 78 orders, 92,4 % GMV) vs 857.183đ
   ("ước tính theo tỉ lệ · cùng số với Sản phẩm và Kế hoạch") vs tile "Lợi nhuận —"; margin
   28,0 % on Tổng quan vs 34,1 % on Kế hoạch.
5. **Ads**: "ROAS 4,1 · chi 569.983đ" next to ads GMV 9.347.020đ (= 16,4); Luồng's Dịch vụ Hiển
   thị 8.076.120đ / 61 orders; spend looks low (old `money_scale` flag?); no per-product spend
   ("Đang chạy QC 0", "QC các sản phẩm 0đ").
6. **Per-product traffic "—" on Tổng quan** for every product, while Luồng has it (17.220 views /
   563 clicks for 26107129526).
7. **Orders reader gap**: orders cover 21/30 days → two AOVs (151.621 / 152.688) and two order
   counts (78 / 85); Tự tạo says "6 ngày có dữ liệu chi phí (trong 15 ngày)" on a 30-day base.
8. **Kế hoạch**: "Kế hoạch chưa có thẻ nào." above 4 cards; the old test combo card
   JC-2611-0101 predicts +5,4M GMV with orders flat (AOV 152k → 219k).
9. **Mua kèm / Quà tặng**: the engine OptionResult has no offer cost, so the card cost is 0 and
   break-even is wrong (cost exists only in the money layer, `outcome._cost`).

## B. Decisions (Q1–Q25)

1. Session 1 = real app + backend + Connector on ORY (not an Open Platform API client yet).
2. ISV demo = synthetic shop, but the **same functional features and code paths**.
3. Field labels copy Shopee's forms word for word (see C).
4. **ROI = ΔGMV ÷ cost** (incremental). Ads / Affiliate also show Shopee's attributed ROAS as a
   second line "theo Shopee".
5. **Shop profit = profit from orders with known costs**, one number with its coverage line
   ("trên N đơn có chi phí, X % GMV"). Remove the "ước tính theo tỉ lệ" number; Kế hoạch uses the
   same figure.
6. Remove from Tổng quan: the "5 con số chính" block, the second (Seller Centre) AOV, "Mức ưu
   đãi trên mỗi dòng đơn". Shop metrics: **Hiển thị, CTR, CTOR, AOV, Đơn, Tổng lợi nhuận, Tổng
   GMV**, per traffic source. Card metrics: **Hiển thị, CTR, CTOR, AOV, Đơn, Δ tổng lợi nhuận,
   ΔGMV, margin shift (điểm), ROI**, one break-even line; drop "Tác động" and "Quy đổi 30
   ngày". **The headline is Δ total profit** = profit after − profit before over the period, never
   a margin %-change: a strategy can lower margin per order and still raise total profit.
7. Profit by traffic source: **no** — shop level only.
8. **Execute = checklist** (exact field values, the seller creates it in Seller Centre), on both
   the real app and the ISV demo. No new fill jobs. Defer new combo *listings* (images/titles).
   **Combo Khuyến Mãi first.**
9. Combo: all three Loại Combo (%, số tiền, giá đặc biệt), each converted to an effective % per
   tier.
10. **Combo reach that cannot be measured stays empty**: "chưa ước tính được" with cost and
    break-even only; no prior fallback (today Túi Bio shows "ước tính chung").
11. **Kế hoạch recomputes each product once, with every card active in the period, in a fixed
    order** (offers are not hard-coded — see Q21):
    1. price (Chương Trình Của Shop / Flash sale later) →
    2. order composition (combo tiers on the discounted price, add-on, gift; gift min spend after
       those) →
    3. order-level vouchers (min spend after item/combo discounts) →
    4. buyer-paid → Shopee fees on it →
    5. costs (giá vốn, packaging, gift / add-on giá vốn) →
    6. marketing (ads spend; affiliate commission on buyer-paid) →
    7. profit per order → **Δ total profit** = orders_after × ppo_after − orders_before × ppo_before.
    Funnel lifts combine multiplicatively (views × CTR × CTOR × AOV), capped when two cards push
    the same driver. A single card in Tự tạo goes through the same pipeline with only itself
    active, so Tự tạo = Kế hoạch for a one-card plan. Existing buyers who already qualify get the
    discount too and it is cost (keep).
12. Tracking: a **read-only Connector reader for Kênh Marketing's programme list** (Combo,
    Chương Trình Của Shop, Deal Sốc) detects the programme by name + products + dates → card
    "Đang chạy"; after the window, actual vs expected (Δ total profit, ΔGMV, đơn, AOV, margin
    shift, ROI).
13. Combo triggers: mostly 1 unit per order; unit price low vs shop AOV; margin before combo >
    deepest tier % + margin target.
14. Builder scope: **Combo Khuyến Mãi + Chương Trình Của Shop + Deal Sốc (both types)**, Shopee
    fields, costs inside the card.
15. Fix the ads numbers before any Ads card work. Ads evaluation: **daily budget = the input;
    CPA vs break-even CPA = the verdict** (break-even CPA = profit per order before ads; profit
    after ads = ad orders × (break-even CPA − CPA)); Δ total profit and ROI from *incremental*
    orders (ads on/off days); Shopee ROAS as reference. Placed-order counts are adjusted for the
    shop's cancel rate.
16. **Verify Shopee's stacking first** on one real past ORY order with both a programme and a
    combo (order export price breakdown, read-only): does the combo tier apply to the programme
    price? voucher min spend after combo? fees on buyer-paid?
17. Missing days → "chưa có dữ liệu", excluded from totals and rates, window labelled "N/30 ngày
    có dữ liệu".
18. ISV demo shop: **minimal** synthetic shop in the prod DB, filled by a script in ORY's shape.
    LLM calls only for titles, limited (Q22). juli-content-engine / Remotion make **no** LLM
    call (checked: no LLM SDK in its own code; whisper.cpp is local).
19. Measuring: shortest window that shows a ≥30 % change, ≥3 days, first readout day 7.
20. Cards carry a **banner spec** (type, values from card fields, position, product id) and a
    **title spec** (current title + keyword searches). Juli stores and lets the seller see/edit
    them; juli-content-engine renders and makes the title LLM call.
21. **Kế hoạch view toggles Shop ↔ each product.** Each order comes from **one channel**
    (checkboxes: organic / Ads / Affiliate — Ads and Affiliate never ticked together). Offers
    are checkboxes too, **generated from the offer kinds present in Kế hoạch** (a registry), not
    a hard-coded list — Flash sale and others plug in later through the same registry and the
    same pipeline step (price / composition / order-level).
22. Titles: one LLM call returns 3 candidates (current title + keyword searches), cached on the
    card; "Tạo lại" ≤ 3 per product per day; model per standing decision (GPT-5.4 nano). Demo
    ships pre-generated titles, ≤ 1 live regenerate per product.
23. Banners: **fixed positions, type-based** (see D). **Shop taste**: when a shop connects, run
    one vision LLM call over its existing cover images (≤ ~12) → a cached **shop style profile**
    (palette 3–5 hex, primary/accent, type feel, radius, text density, positions already used).
    Banners are rendered deterministically from templates styled by that profile (compositing,
    no generative images). Re-run on demand or when covers change.
24. Scope confirmed (E, F) **plus Từ khoá cleanup** (G).
25. Sub-phrases ("an toàn" vs "an toàn da") are settled by the LLM keyword step (G.7): it
    separates product-type heads from attributes and groups similar words.

## C. Shopee's real fields (read in Seller Centre 11/11, nothing saved)

**Chương Trình Của Shop** (`/portal/marketing/discount/create`)
- Tên chương trình khuyến mãi (≤150, hidden from buyers); Thời gian khuyến mãi (hour precision,
  ≤180 days); "Đồng bộ … sang Shop nước ngoài".
- Per variation: Giá gốc · **Giá sau giảm (₫) HOẶC %GIẢM** · Kho hàng · **Số lượng sản phẩm
  khuyến mãi** (default Không giới hạn) · **Giới hạn đặt hàng** ("Giới hạn mua tối đa của mỗi
  khách hàng") · **Bật / Tắt**. "Thiết lập hàng loạt" (bulk %GIẢM, quantity, limit).
- Shopee hint per variation: "Giá chưa đáp ứng điều kiện tham gia: Điều chỉnh giá ≤ ₫41.029 …
  Nhãn Rẻ Vô Địch" — a price-competitiveness target worth reading later.
- Builder gaps: programme name, promo stock, per-variation on/off, hour precision.

**Combo Khuyến Mãi** (`/portal/marketing/bundle/new`)
- Tên Combo Khuyến Mãi (≤25, hidden); Thời gian chạy Combo; **Loại Combo**: Giảm giá theo % /
  Giảm giá theo số tiền / Giảm giá đặc biệt; tiers "Mua [N] sản phẩm để được giảm [x] %GIẢM",
  "Thêm mức ưu đãi"; **Giới hạn đặt hàng** (max combos per buyer); Sản phẩm của Combo.
- Builder already matches (`ComboSpec`, `panels-offers.tsx` ComboPanel) except time of day.

**Mua Kèm Deal Sốc** (`/portal/marketing/add-on-deal/create`) — one form, **Loại Deal Sốc**:
- *Mua Kèm Deal Sốc*: Tên chương trình; Thời gian bắt đầu/kết thúc (≥1 h; once created only
  shortenable); **Giới hạn sản phẩm mua kèm** (≤100 add-ons per main product). Step 2 Sản Phẩm
  Chính (≤100), step 3 Sản Phẩm Mua Kèm (price per add-on — not seen: steps 2–3 unlock only after
  "Lưu").
- *Mua Để Nhận Quà*: same name/time; **Điều kiện nhận quà: Mua ₫[X] để nhận [N < 50] quà tặng**;
  step 2 main products, step 3 gift products.
- Builder gaps: one programme with two types; dates; programme name; gift qty ≤ 49 (today ≤ 20);
  cost inside the OptionResult.

Code map (from the P100 research): specs `shopee_builder/specs.py` (ProductDiscountSpec :256,
ComboSpec :103, AddOnSpec :170, GiftSpec :200); engine families
`shopee_builder/engine_families/families.py` (price :259, combo :151, simple_option :312);
not-estimable path `engine/engine.py:458`; wire `engine/contract.py:259`; UI
`apps/demo/src/components/shopee-decisions/builder-p92/panels-offers.tsx`; option card
`shopee-decisions/option-card/option-card.tsx`; promo ingest `ingest/schemas.py:117`
(`SHOPEE_PROMO_TYPES`; no gift type; no tiers stored); Connector has no promotions reader.

## D. Banners (design: https://claude.ai/artifact/4SuySBPc5VbTQFU1SMK1wx)

- Square cover, render 1200×1200 (Shopee min 900×900). **Bottom-left is blocked** (Shopee's
  voucher strip) — no type may use it; a bottom-wide strip is therefore not allowed.
- **Types by shape, fixed positions:**
  - *Ngang* (horizontal strip): top only — Mega sale / campaign name + dates, Flash sale later.
  - *Góc* (corner badge): top-left / top-right — "−X %" (Chương Trình Của Shop), Freeship (only
    when the shop's programme is read), Chính hãng / có VAT (from the listing), Mới / Bán chạy
    (from data).
  - *Thẻ* (card box): middle-right / bottom-right — Giá / đơn vị, Combo tiers, Voucher, Quà tặng
    ("Mua từ 149K tặng …", from the Deal Sốc gift card), Mua kèm ("Mua kèm X chỉ Yđ"), Quy cách
    ("Hộp 100 cái").
- Every value comes from a card or listing field; a missing value shows an empty field, never an
  invented claim. Two banners on one position → warning. Seller edits values, position (within
  the type's allowed set), colour (shop profile palette), size S/M/L.
- **Flow v4 (owner, 2026-11-11), step by step, not all at once:** 1 Chọn mẫu (Tối giản / Nổi bật /
  Khung viền, colours from the shop profile) → 2 Loại ngày (Ngày thường ≤ 3 banners, Mega Sale ≤ 4,
  Mega Sale adds the top strip) → 3 Thêm banner (one per type, editable values, positions limited by
  shape) → 4 Kiểm tra: **one vision LLM call** on the final image + banner spec, flags overload,
  overlap, text too long, empty values, covering the product, and proposes fixes the seller applies →
  5 Tải ảnh PNG 1200×1200. Design: link above (the check is rule-based in the design only).
- Public sources give no official Shopee limit on text or frames on covers (only third-party
  blogs); keep text short and re-check Seller Centre's image policy before launch.

## E. Session 1 — Shopee client (real app, ORY), in order

1. **Data repair** (A.1–A.8): missing days → NULL/"chưa có dữ liệu" (materialize + stored
   sums + coverage label); unknown cost → NULL profit; previous-period rows (re-run backfill
   window or fix spread for pre-12/10); per-product traffic on Tổng quan; ads spend/ROAS one
   source + per-product spend from Shopee's product table + `money_scale` check; Connector orders
   reader gap; Kế hoạch empty-state text. Get the owner's 4 remaining SQL outputs first.
2. **One shop profit** (B.5) across Tổng quan / Sản phẩm / Kế hoạch; remove the redundant
   metrics (B.6, B.7).
3. **Builder, Shopee-exact** (C): Combo Khuyến Mãi (3 types) → Chương Trình Của Shop → Deal Sốc
   (two types); costs inside the OptionResult; ROI; combo reach empty when unmeasurable (B.10).
4. **Verify stacking** (B.16) before step 5.
5. **Kế hoạch pipeline** (B.11) with the Shop ↔ product toggle, channel checkboxes and offer
   registry (B.21); Δ total profit, margin shift, ROI; cross-screen test: Tự tạo = Kế hoạch for a
   one-card plan, per offer kind.
6. **Execute = checklist + tracking reader** (B.8, B.12, B.19).
7. **Card specs**: banner spec + title spec (B.20, B.22, D); shop style profile contract (B.23).
8. **Từ khoá cleanup** (G).
Ads card work only after the ads numbers are fixed (B.15).

## F. Session 2 — ISV demo client

- Minimal synthetic shop (≈6 products, ORY's shape, synthetic names/values) loaded by a script
  into the prod DB; same backend and code paths as Session 1.
- Screens: **Tổng quan, Phân tích, Sản phẩm, Quyết định** — Tự tạo offers only the strategies
  finished in Session 1 (Combo Khuyến Mãi first; Chương Trình Của Shop, Deal Sốc when done).
- Pre-generated titles; ≤ 1 live regenerate per product. Banners rendered from the shop
  profile. No word "demo" visible; the shop is "Dữ liệu mẫu".

## G. Từ khoá — keywords built from titles

Current builder: `services/shop_keywords/decompose.py:464` (`decompose`) +
`collection.normalize_keyword`, called by `seeds.generate`. On 4 synthetic-shaped titles it
returns fragments and boilerplate: `có vat`, `tay tự hủy sinh`, `stahaus túi đựng thực`,
`hủy sinh học stahaus`, and `stahaus nước rửa chén` (wrong brand: one brand applied to every
title).

Rules to implement:
1. **Drop numbers, quantities, prices, sizes before n-grams**: bare numbers ("1 găng tay" →
   "găng tay"), "35 ngày", "99k", "500ml", "100%", "x2 lần", "hộp 100", "size L / M", "20x32cm".
   A phrase made only of a number + unit is dropped, not kept as a keyword.
2. **Dedupe after stripping**: "1 găng tay", "2 găng tay" collapse into one "găng tay" carrying
   the union of item ids.
3. **No mid-phrase cuts**: split titles on `- – , + : / ( ) |` first; n-grams stay inside a chunk
   and may not end inside a known compound ("túi đựng thực phẩm", "sinh học", "rửa chén"); no
   "túi đựng thực", "tay tự hủy sinh".
4. **Sub-phrases** *(Q25, confirm)*: "an toàn" vs "an toàn da" — recommended: keep the longer
   phrase; keep the shorter one only if it also appears on its own (not followed by a modifier) in
   at least one title or is a product-type head noun ("găng tay", "nước rửa chén").
5. **Boilerplate stop-list**: "hàng chính hãng", "có vat", "combo", "chính hãng", "siêu",
   "giá rẻ", "freeship" …
6. **Brand per title**, not one brand for the shop (ORY vs STAHAUS).
7. **One LLM call per shop before lookups** (owner, 2026-11-11). Today Từ khoá uses **no LLM**:
   `decompose` splits titles into patterns (type_function, common_phrase, brand_type,
   brand_function) and the owner looks the seeds up by hand on shopeeanalytics.com (free account;
   anonymous = 5 lookups/day) and uploads JSONL weekly (`collection.py`, ADR-119; Juli's servers
   never fetch the site). New flow: rules 1–6 as a deterministic pre-pass → one GPT-5.4 nano call
   (structured output, through `OpenAIGate`, consent `llm_processing`, one `llm_call_log` row)
   with the titles + candidates → JSON {heads (product types), attributes (material, function,
   benefit: "sinh học", "an toàn da"), similar-word groups, seeds to look up, item_ids}.
   Validation: every word of a seed appears in some title, or the seed sits in a similar-word
   group the model tied to a source title and is shown as "từ gần nghĩa" for the owner to tick;
   item_ids are never dropped. Re-run only when titles change (≤ 1/week). Fewer, cleaner seeds =
   fewer manual lookups.
Tests from synthetic titles in the same shapes (no ORY/Fujiwa data in the repo); the LLM is faked
in tests.

## H. LLM features and cost (estimate, 2026-11-11)

Model GPT-5.4 nano (standing decision): $0.20 / 1M input, $0.02 cached input, $1.25 / 1M output
(OpenAI model page). Reasoning tokens bill as output; image tokens depend on the detail setting.
≈ 26.000 đ / USD. Every call writes `llm_call_log`, so the real token counts can be checked after
the first week and these figures corrected.

| Feature | When | Tokens per call (in / out) | Per call | Typical shop / month | Worst case at the caps |
|---|---|---|---|---|---|
| Titles, 3 candidates | on request; "Tạo lại" ≤ 3 / product / day | ~2,5k / ~1,5k | ≈ $0,0024 (≈ 62 đ) | 30 products × 3 calls = 90 → ≈ $0,22 | 30 × 4 / day × 30 = 3.600 → ≈ $8,6 |
| Keyword cleanup | when titles change, ≤ 1 / week | ~6k / ~3k (200 products: ~15k / ~6k) | ≈ $0,005 – 0,011 | ≤ 5 runs → ≈ $0,03 | same |
| Shop style profile (vision, ≤ 12 covers) | at connect, re-run on demand | ~20–31k / ~1,5k | ≈ $0,008 (≈ 210 đ) | 1–3 runs → ≈ $0,025 | same |
| ISV demo shop | pre-generated once; ≤ 1 live title regenerate / product | — | — | one-off ≈ $0,03 + ≤ $0,015 live | same |
| Banner check (vision, final 1200 px image + spec) | once per banner set, re-run after edits | ~3,5k / ~1k | ≈ $0,002 (≈ 50 đ) | 30 sets × 2 = 60 → ≈ $0,12 | same order |
| Banner rendering, Remotion | every render | no LLM | $0 | $0 | $0 |

Total: **≈ $0,40 per shop per month typical (≈ 10.000 đ)**; worst case at the caps ≈ $9 (≈
235.000 đ), almost all title regenerates — a shop-wide daily cap (e.g. 30 title calls / day)
would bound it at ≈ $2,2. Background jobs (keywords, style profile) can use the Batch API at half
price. Existing LLM paths (builder drafts through `shopee_builder/llm.py`, the agent runtime) are
outside this table.

## I. Replace the manual keyword lookups — Shopee's own keyword data (checked 2026-11-11)

Read in ORY's Seller Centre, nothing created:
- **Product ads (Dịch vụ Hiển thị Sản phẩm) no longer take keywords**: creation offers only "Tối Đa
  Doanh Thu ROAS Tối Ưu bởi Hệ Thống" / "Tối đa Doanh thu Tùy chỉnh ROAS" (ROAS ước tính per
  product, e.g. 6,26 – 11,22). No keyword list there.
- **Dịch vụ Hiển thị Shop+** (`/portal/marketing/pas/shop/create`) bids on keywords. "Thêm từ khóa"
  shows, per keyword: **Từ khóa · Chất lượng từ khóa (x/10) · Tỉ lệ tìm kiếm (search volume) ·
  Giá thầu tham khảo (đ)**.
  - On open: 50 shop-specific suggestions, `POST /api/pas/v1/setup_helper/list_recommended_keyword/`
    (e.g. "bao tay cao su" 75.386 · ₫2.964; "túi đựng thực phẩm" 17.809 · ₫2.100; "túi thực phẩm tự
    hủy sinh học" 862).
  - Typing a seed ("Nhập từ khóa của bạn tại đây"): the seed's own volume plus 49 related keywords,
    `POST /api/pas/v1/setup_helper/search_keyword/` (e.g. "túi đựng thực phẩm sinh học" = 100).
  - Response JSON field names not captured yet — Session 1 reads one response body (with the
    owner's yes) before writing the reader.
- Side finding for E.1: PAS home shows "Chi phí Dịch vụ Hiển thị Hôm nay ₫209.445" while Juli shows
  569.983đ ad spend for 30 days → ad spend is badly under-counted.

Design (scales to many shops — each shop gets its own keywords and profile):
1. **Per shop, in the seller's own session.** The Connector reader runs inside each seller's Seller
   Centre, so `list_recommended_keyword` / `search_keyword` return that shop's data; nothing is
   shared between shops. Rows go to `market_keyword_metrics` (or a shop-scoped table) keyed by
   `shop_id`, `source = "shopee_pas"`, `collected_on`, under RLS like every tenant table.
2. **Flow per shop:** titles → rule pre-pass (G.1–6) → one nano call (G.7) → ≤ N seeds →
   Connector looks each seed up (`search_keyword`, read-only) → volumes + related keywords + bid →
   nano title call uses them as **function-tool input over Juli's own rows only** (no web search).
3. **Budget:** keyword lookups share the Connector's `DAILY_REQUEST_BUDGET` with their own slice
   (like `TODAY_REQUEST_RESERVE` / `BACKFILL_REQUEST_SHARE`); cap seeds per shop per week (e.g. 30),
   refresh only seeds older than 7 days; spread across days for large catalogues.
4. **Shop style profile** (B.23) and keyword sets are both per `shop_id`, cached, re-run on demand;
   LLM calls go through the shop's own consent gate and `llm_call_log`.
5. **No Ads account / no access:** fall back to the existing manual JSONL upload (shopeeanalytics);
   the screen says which source each volume came from. Never invent a volume.
6. Reading is read-only: open the picker's data calls only, never "Tạo", never add keywords.

## J. Read in Seller Centre 2026-11-11 (session 1, read-only, nothing saved)

**Stacking (B.16) — order 260606CCN6JBPX, 06/06/2026, Nước Rửa Chén Ory 500ml × 2:**
- Chương Trình Của Shop "Giảm giá trực tiếp sản phẩm" (31/03–12/06/2026): Giá gốc ₫100.000 →
  Giá sau giảm ₫78.100 (22 %GIẢM).
- Combo "Combo Khuyến mãi" (bundle_deal 443113169043684, Mua 2 giảm 20 %): 2 × 78.100 = 156.200
  → 124.960 = −20 % **of the programme price**. ⇒ combo tiers apply on top of the discounted price
  (effective 62,48 % of list).
- Fees on the post-combo item total: Phí cố định 13.121 = 10,5 % × 124.960; Phí Dịch Vụ 9.873
  (≈ 7,9 %); Phí xử lý giao dịch 8.158 = 6 % × 135.960 (= 124.960 + buyer shipping 11.000).
- Shopee Voucher −17.494 reduces only what the buyer pays (118.466); not in seller revenue, not in
  any fee base. Shop voucher 0 on this order ⇒ "shop-voucher min spend after combo" still unverified.
- Doanh Thu Đơn Hàng 93.808. Bundle API: `GET /api/marketing/v3/bundle_deal/order/info/?bundle_deal_id=`
  gives `price_before_bundle`, `item_price` (= programme price), `bundle_item_price` per order.
- `GET /api/marketing/v3/bundle_deal/list/` (tracking reader, B.12): `bundle_deal_rule`
  {rule_type (2 = %), min_amount, discount_percentage, discount_value, fix_price,
  additional_tiers[]}, start_time/end_time (epoch s), status, time_status (3 running, 4 ended).
  ORY has a running combo "JULI/CBT-1/T11" since 11/11 10:30 (5 % for 2, 10 % for 3).

**Shop+ keyword picker (I) — response shape** (`POST /api/pas/v1/setup_helper/list_recommended_keyword/`
body `{campaign_type:"shop", reference_id:<uuid per page>, suggest_log_data:{page:"suggest_creation"}}`;
`search_keyword/` same body plus `keyword`): `{code:0, msg:"OK", data:[{keyword, state:"normal",
recommended_price, relevance, search_volume, is_recommended, product_suggest_log_data, log_key}]}`,
50 rows. **`recommended_price` is đ × 100.000** (209960901 → ₫2.100 shown). `relevance` =
"Chất lượng từ khóa" x/10; `is_recommended` = the thumbs-up icon; `search_volume` = "Tỉ lệ tìm
kiếm". The searched seed comes back as row 0 ("túi đựng thực phẩm" 17.809, ₫2.100), then 49
related keywords.
