# Seller journey — Promotion & Campaigns (Khuyến mãi / Chương trình & Chiến dịch)

Catalog `docs/integrations/tiktok_corpora/academy-catalog.json`; bodies in
`/Users/macos/Juli-AI-local/tiktok-corpora/academy_documents/`. 119 seller-scoped pages matched
(32 `Khuyến mãi > Khuyến Mãi`, 21 `Chương Trình và Chiến Dịch`, 15 `Tổng Quan`, 10 `Courses > Chiến Dịch`,
8 `Siêu sale`, 6 Policy Center, 4 `Phân tích dữ liệu > Marketing`, 3 FAQ, 2 Agreement Center); 28 read.
Curated summaries at `docs/integrations/tiktok_platform/seller/*.md` cited, not duplicated.

## A. Seller-run promotions

Common shell: Seller Center desktop → Khuyến mãi / Công cụ khuyến mãi → Tạo khuyến mãi → name + window →
product/SKU pick (online or bulk Excel: product ID, variation ID, discount price, total limit, per-buyer
limit) → price config → Đồng ý & đăng. Manage in **Khuyến mãi của tôi** (Edit / Kết thúc / Sao chép). The
Seller Center app can only *view and end*, and cannot do variation-level config.

**1. Product Discount (Giảm Giá Sản Phẩm)** — `feature-guides/seller/khuyen-mai/giam-gia-san-pham-6837782308177665.md`
[API-automatable]. Window **10 min–30 days**. Discount form: **% off** (original price stays editable, the
discount recomputes off it) or **fixed price** (original price is *frozen* for the duration). Scope
product-level (one price for all variations) or variation-level; up to 2,000 products. Optional
**Khuyến mãi/Chiết khấu thông minh** recommends products and discounts by bucket (new / trending /
bestseller / slow-moving / uncompetitive). Edits: *upcoming* — window, price, limit type, raise or lower
limits; *ongoing* — cannot switch limit type, **can only increase** limits. Band 1%–90%.

**2. Shop Flash Sale (Flash Sale của shop / Deal chớp nhoáng)** — `.../flash-sale-cua-shop-6837782307768065.md`
[policy-gated]. Eligibility **first**: Shop Rating **≥ 2.5 (VN)** *and* Violation Points **< 36** *and*
balance > −100 USD; refreshed daily; failing blocks create *and* edit in desktop, app "and TTS Open API",
but already-scheduled promos keep running. Channel: all-channel / LIVE / creator-LIVE (the last two
official- or affiliate-account only, with shared vs reserved creator stock). Windows: all-channel
**10 min–3 days**, LIVE 1 min–3 days, creator LIVE 10 min–14 days. **Price floor: below the product's
lowest price in the last 14 days *including the seller's own product discount*; with no 14-day order
history, below the original price.** LIVE variant: ≤ 14-day low including campaign price and co-funded
offers. Seller Center shows a warning plus a suggested price on violation. Edits: *upcoming* — anything;
*ongoing* — **extend the window only**. ⚠️ This page's comparison table says "API không được hỗ trợ" for
all three flash-sale types, yet its eligibility text names TTS Open API and `contract-collection.md` §B-5
has a verified sandbox `createActivity` with `"activity_type":"FLASHSALE"` — open verification item.

**3. Voucher (Voucher thông thường / phiếu thưởng)** — `.../voucher-thong-thuong-cua-nha-ban-hang-5159633199597314.md`
[**Seller-Center-only**]. Channel all-channels or Shopping Center. Fields: amount or % off; **min spend**;
**max discount per order** (must be ≥ % × min spend); redemption count; collectible count (default 99,999,
first-come-first-served against the redemption count); claims per customer; scope whole-shop or specific
products. Caps: fixed amount 0 < x < 1e9; **with a min spend the cap is 50% off**; percentage vouchers
1%–50%. Edits: *ongoing* — **total quantity increase only**; *upcoming* — discount and usage editable.
One seller voucher per order (highest discount wins); redemptions restored on cancel/return.
`contract-collection.md:1515-1518` records that no Partner API coupon create/search/delete exists.

**4. Seller Shipping Discount (Chiết Khấu Phí Vận Chuyển)** — `.../chiet-khau-phi-van-chuyen-cua-nha-ban-hang-6837782308292353.md`
[policy-gated]. Eligibility: positive shop balance *and* past the incubation stage. Fields: indefinite or
fixed window; shipping methods (standard-only / all); regions (all / specific); free vs partial; min spend;
**min item count**; whole-shop or specific products. Check / Edit / Terminate any time.

**5. Buy More Save More (Mua Sỉ Giá Hời, BMSM)** — `.../mua-si-gia-hoi-bmsm-6837797940381441.md`. Window
**10 min–365 days**; eligible customer group (all / new / existing / repeat); tiers of quantity + % off,
**max 2 tiers**, tier 2 strictly greater on both axes; optional once-per-customer; optional **budget**
(exhaustion auto-deactivates the promo). Max **30** ongoing+upcoming; **one BMSM per product per window**
(a shop-wide one blocks product-specific ones). Edits: *ongoing* — **extend window, increase budget only**;
budget is increase-only forever. Hitting tier 2 applies tier-2 % to *all* units. Band 1%–50%.

Adjacent, same family, not read deeply: Ưu Đãi Theo Gói (bundle), Quà Tặng Khi Mua Hàng (GWP), Chiết Khấu
Hàng Mới Về (new arrival, fixed 30–50%), Mã Khuyến Mãi, chat / new-customer / repeat / CRM vouchers.

## B. Platform campaigns — **human-only, no Partner API surface**

Sources `.../chien-dich-san-pham-8901645928908546.md`, `.../chien-dich-ong-tai-tro-8901645929072386.md`,
`.../tinh-nang-quan-ly-gia-3723270759630593.md`,
`policy-center/seller/nguyen-tac-ve-tieu-chi-u-ieu-kien-tham-gia-chien-dich-danh-c-3043429823514369.md`,
`courses/chuong-trinh-flash-sale-deal-chop-nhoang-3889910332606225.md`.

Browse Marketing → Chiến dịch (each card shows type, campaign window, registration window) → Đăng ký ngay
shows per-campaign criteria → submit products online, by **bulk online** (price strategy: % off / amount
off / use retail price / **use the max-campaign-price rule**) or by **Excel** (blank or pre-filled with
recommended campaign price and campaign stock). **Đăng ký một lần nhấp** enrols all eligible products
across a mega-campaign's sub-campaigns. TikTok ops may also register products for you — they queue in
*Chờ đăng ký* for per-product or bulk Phê duyệt / Từ chối. **Online price negotiation**: the platform
proposes a price, the seller accepts or declines within a deadline or it expires.

Commitments: every registration is reviewed and can be rejected; on approval **campaign stock is locked**
and the **campaign price is shown for the whole window, suppressing every other seller price** (flash
sale, product discount). TikTok records submitted campaign prices and may require matching or beating them
to enter future campaigns. Post-submission you may only **raise stock or lower price** (immediate, no
approval) — never raise price or cut stock; remove via **Xóa** while under review or **Thu hồi** once
approved (needs approval, not offered on every campaign). Co-funded products under subsidy review cannot
have price edited at all.

Eligibility (policy page): with shop rating — Rating > 3.0, Account Health > 50; product negative-review
rate < 1.5% (30 d); seller-fault return/refund < 7% (electronics, H&B, grocery, mother&baby) or < 8.8%
(home & living, fashion), 7 d. Without shop rating — AHR > 50, late dispatch < 10%, seller-fault
cancellation < 10%, seller-fault negative review < 3%. **Re-checked continuously; a shop can be dropped
mid-campaign.**

**Flash Sale Deal Chớp Nhoáng** is a *program*, not the tool: register in Chiến dịch or via AM, accept
T&Cs, then the platform selects qualifying products (VP < 24, no severe violations, rating e.g. > 4.0,
price competitive against **30-day price history**, ≥1 sales history). A **service fee applies to every
successfully delivered order** since 17 Feb 2025. Exit = Registration Record → Withdraw → 1–2 days review.
Mega-sale cadence: teaser from **T-14 days**, ad budget ramp ≤ +30%/day vs BAU; year calendar in
`courses/seller/lich-chien-dich-tiktokshop-2026-6210902215264001.md`.

## C. Rules that constrain automated promo changes

Stacking (`.../cach-tinh-khuyen-mai-cong-don-2965628697724674.md`): three layers — **(1) single-product**
(campaign price, shop flash sale, product discount, new-arrival) where *only one applies*; **(2) cart-level**
(BMSM, GWP) stacking on layer 1; **(3) vouchers**, stacking on both but **one per order**, best discount
auto-selected. Min-spend for layers 2–3 is tested against the **post-layer-1 price**. Product priority:
creator-LIVE flash = LIVE flash > **campaign price** > shop flash sale > product discount. Across
campaigns: mega tier > daily, then co-funded > non-co-funded, then lowest price. Once a campaign is
approved, all other tools' prices simply stop applying (FAQ `.../ieu-gi-xay-ra-neu-thoi-gian-dien-ra-chien-dich-trung-voi-cac-2898390372845314.md`).
Seller Center ships **Phân tích hiểu sâu về định giá** (price forecast + promotion simulator + stacking
rules) as the seller's oracle for the final buyer-visible price.

Discount bands (`.../huong-dan-ve-muc-giam-gia-khuyen-mai-do-nha-ban-hang-tai-tro-1651976556480273.md`),
normal → eligible-holiday: product discount 1–90% → 1–90%; new arrival 30–50% both; flash sale (all
variants) 1–50% → **1–99%**; bundle 1–50%; BMSM 1–50% → 1–99%; seller vouchers 1–99%; private vouchers
(chat, repeat, CRM, promo code) 1–50%. Holidays are legally defined VN dates and the promo window must fall
**entirely** inside them; timezone GMT+7.

Price-history rules: flash sale below the 14-day low *including seller discount*; campaign thresholds may
be % below retail, below the seller's discounted price, below the **L30/60/90/180-day low**, inside a band,
or at/below the same product's price **on other e-commerce platforms** (`tinh-nang-quan-ly-gia`).

Penalties: promo-tools T&C (`.../tiktok-shop-seller-promotional-tools-terms-and-conditions-6837780085360385.md`)
— auto-suspension below the minimum balance, TikTok may suspend promo tools at any time, seller bears all
promo cost and price-compliance liability, excessive discounting is non-compliant. Curated:
`tiktok_platform/seller/compliance.md:149-154` (bait-and-switch pricing, manual flash-sale claims, fake
vouchers prohibited), `policy.md:77-78` (inconsistent promotion 1–48 VP, prohibited promotion 6–48 VP),
`account-health.md:143` (sanction cancels promotions/subsidies), `implementation-hooks.md:13,29`
(VP ≥ 12 pauses affiliate/campaign for 7 days).

## D. Analytics used to judge a promo

`.../analytics/marketing/phan-tich-cong-cu-khuyen-mai-382806895920898.md`: La bàn Dữ liệu → Khuyến Mãi →
Công Cụ Khuyến Mãi. Key data (revenue, orders, buyers) with period deltas; top promotions by GMV; promotion
list filtered by status (ongoing/upcoming/deactivated/expired) and type; drill-down gives promo ID, window,
timestamps and a **product list with revenue, orders, buyers, conversion rate**.
`GMV = original price − all discounts + buyer-paid fees`. **Data is D-1, never real time** — the binding
constraint on any auto-optimize loop. Voucher lens: redemption rate + AOV (low redemption ⇒ min spend too
high or wrong products). BMSM lens: usage and average items per order. Program lens
(`.../so-lieu-phan-tich-chuong-trinh-flash-sale-5307890866112273.md`): scheduled products, flash-sale
sub-orders, % of shop sub-orders, Flash Sale GMV, % of shop GMV, **service fee**; 3 months of history, shown
only with products scheduled now or in the last 30 days. Campaign: La bàn dữ liệu → Tiếp thị → Hiệu suất
chiến dịch — YTD plus a **real-time in-campaign dashboard**
(`.../phan-tich-chien-dich-8437277152495376.md`, `.../bang-so-lieu-chien-dich-tong-quan-784314702989073.md`).

## E. Alignment with `docs/product/execution_layer.md`

| Juli step | Verdict |
|---|---|
| 4.1 Inventory Search (`:190`), 4.2 Get Activity (`:190`) | MATCH |
| **4.3 Update Price — "baseline markdown, applied regardless of which promotion lever is chosen"** (`:191`) | **WRONG-ORDER / harmful.** A fixed-price product discount *freezes* the original price, so the update is blocked while it runs; a % promo recomputes off the new lower list price, so markdown + promo **compounds**; marking down today *raises* the 14-day floor a flash sale must beat; and it permanently tightens L30–180-day campaign price thresholds. |
| 4.4 Create Activity, Seller Flash Sale, "eligibility guard" (`:192`, rationale `:180-186`) | **GAP** — right instinct, wrong predicate. Stated gate is "past-order-history and pricing checks"; the real gate is Rating ≥ 2.5 (VN) **and** VP < 36 **and** balance > −100 USD, daily-refreshed, with in-flight promos grandfathered. Order history only selects *which* price floor applies. |
| 4.4 `activity_type` enum `FIXED_PRICE\|DIRECT_DISCOUNT\|FLASHSALE\|SHIPPING_DISCOUNT\|BUY_MORE_SAVE_MORE` (`:192`) | Partial — only `FIXED_PRICE` (A-25) and `FLASHSALE` (B-5) verified in `contract-collection.md`; the other three unverified. Vouchers correctly absent. |
| 4.5 Update Activity Product (`:193`); 4.5.5 / 4.7 webhook #39 + Deactivate (`:194,:197`) | MATCH (`quantity_limit` / `quantity_per_user` = total & per-buyer limits) |
| 4 overall — no price-floor, discount-band or duration precheck | **MISSING PREREQUISITE** — Seller Center warns a human with a suggested price; the API just rejects |
| 7a Create Activity (`:280-286`) | MATCH, but no duration or discount-band guard |
| 7b "Delete Activity" (`:288-299`) | GAP (naming) — TikTok has no delete, only Kết thúc / Vô hiệu hóa / Thu hồi; history is retained |
| 7c Update Activity `POST .../activities/{id}` (`:301-306`) | **WRONG** — `contract-collection.md:1201` says `PUT`, and only title/window are shown as editable; the ongoing-edit matrix is encoded nowhere |
| Campaign join; vouchers | **MISSING** — a whole human-only journey and a Seller-Center-only tool, both silently absent |

## F. CONFIRM vs safe-to-automate

**CONFIRM:** any price/discount below a margin floor or at the tool max; anything using the 99% holiday
band; **all campaign registration, campaign price submission, negotiation acceptance and platform-initiated
registration approval** (price is remembered as a future bar, stock locks, campaign price suppresses
everything else); `Update Price` while any promo/campaign is scheduled or live; shop-wide BMSM or voucher;
joining/leaving the Flash Sale program or Campaign PLUS; anything while VP ≥ 12 or rating is near threshold.

**Safe to automate (notify):** deactivating an expired/ended or stock-exhausted activity; **extending** an
ongoing window and **raising** purchase limits, voucher quantity or BMSM budget (the only ongoing edits
TikTok permits — all monotonic, none price-touching); reading analytics and proposing a change; all
read-only pre-flight checks (eligibility, 14-day low, discount band, duration bounds, stacking collision).

## G. Top 5 corrections, ranked

1. **Make `Update Price` (4.3) conditional and post-decision** — "markdown *or* promotion, not both". As
   written it compounds discounts, is blocked under a fixed-price promo, raises the flash-sale floor, and
   damages future campaign-price eligibility.
2. **Replace the flash-sale eligibility predicate** with Rating ≥ 2.5 (VN) ∧ VP < 36 ∧ balance > −100 USD,
   wired to the account-health signals in `tiktok_platform/seller/account-health.md`.
3. **Add a pre-submit validator to 7a/7c** encoding discount bands per tool, duration min/max per tool, the
   14-day-lowest floor, layer-1 stacking collisions, and the ongoing-edit matrix (extend/raise only).
4. **Split the family into three declared lanes** — API-automatable (product discount, flash sale, shipping
   discount, BMSM), Seller-Center-only (all vouchers, promo codes, GWP; cite
   `contract-collection.md:1515-1518`), human-only campaigns (registration, negotiation, withdrawal).
5. **Fix the contract defects**: 7c is `PUT` not `POST`; mark three `activity_type` values unverified;
   rename 7b "Delete Activity" → "End Activity"; resolve the flash-sale-over-API contradiction in §A.2.

**Summary.** Every seller-funded promotion uses the same form — name, window, products or SKUs, a percentage
or fixed price, purchase limits — but each of the five tools has its own duration bounds, discount band, and
a near-frozen edit policy once live: on a running promo you can essentially only extend it or raise limits
and budgets, never re-price it. Prices do not add up naively: TikTok resolves single-product promos by a
fixed priority (campaign price > shop flash sale > product discount), stacks cart-level promos and then one
best voucher on top, and enforces floors — a flash sale must undercut the 14-day low including the seller's
own discount, and campaign entry is benchmarked against 30-to-180-day price history and even other
platforms. Platform campaigns are a different animal: reviewed registration, stock locked on approval, the
campaign price shown for the whole window and remembered as the bar for the next campaign, and no Partner
API touching any of it. Juli's execution layer gets the lifecycle roughly right but carries three defects —
a "baseline markdown before every promotion" step that is actively harmful, a wrong flash-sale eligibility
rule, and no pre-submit validation of the floors and bands Seller Center enforces for a human — plus two
gaps: vouchers are Seller-Center-only, and campaign participation has no workflow at all.
