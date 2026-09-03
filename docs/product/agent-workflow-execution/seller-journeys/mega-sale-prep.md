# Mega Sale prep journey (TikTok Shop VN) — Architect scout report

Roots: `A/` = `/Users/macos/Juli-AI-local/tiktok-corpora/academy_documents/`, `P/` = `.../partner_documents/`.
839 academy entries → 148 matched the campaign/mega/khuyến-mãi filter; 365 partner entries → 31 matched.

## A. The timeline as TikTok presents it

The canonical T-table is **"Lập kế hoạch cho chương trình khuyến mại Mega Sales theo lịch trình này"**
(`A/feature-guides/seller/lap-ke-hoach-cho-chuong-trinh-khuyen-mai-mega-sales-theo-lic-1113254105663234.md`, lines 15–21);
its checklist companion is **"Cách chuẩn bị cho doanh nghiệp của bạn vào Dịp Mega Sales"** (`…cach-chuan-bi-cho-doanh-nghiep-cua-ban-vao-dip-mega-sales-1157682472044289.md`).
Crucially, TikTok's own T-table is **content and ads only** — it never mentions registration, price or stock. Those come from
**"Cẩm nang chiến dịch"** (`A/policy-center/seller/cam-nang-chien-dich-5292375288432400.md`), which splits the journey into
*Trước / Trong / Sau chiến dịch*. Merged:

| Phase | Tasks (VN wording) | Surface | Deadline / rule |
|---|---|---|---|
| **T-30→T-7 Register** | "Xem các chiến dịch có sẵn" → "Đăng ký sản phẩm" via *Đăng ký hàng loạt trực tuyến* / *Nhập bằng Excel* / *Đăng ký bằng một lần nhấp*; "Xem lại các sản phẩm được đăng ký trên nền tảng" (Phê duyệt/Từ chối hàng loạt) | Marketing > **Chiến dịch** (`/promotion/campaign-tools/all`); tabs *Được đề xuất*, *Đăng ký chờ xử lý*, *Quản lý chiến dịch* | Hard cutoff. Observed: Campaign PLUS "Thời gian đăng ký **30/12 – 12H TRƯA 7/1**" for the 6–8/1 event; VXP "Hạn chót … chiến dịch 11/4 là 12H 8/4" (T-3). "Mọi đơn đăng ký … đều sẽ được xem xét" — rejection possible |
| **T-14→T-7 Eligibility, listing, stock** | Verify *Xếp hạng cửa hàng > 3,0*, *Điểm tình trạng tài khoản > 50* / *Điểm vi phạm < 36*, neg-review and seller-fault-return rates; "Cập nhật các trang thông tin chi tiết về sản phẩm"; "Xem xét giá của đối thủ cạnh tranh"; set *Hàng có sẵn của chiến dịch* | Tình trạng cửa hàng; Quản lý hàng tồn kho; campaign submit form | "Điều kiện … được xem xét **định kỳ**" — removal mid-campaign (`A/policy-center/seller/nguyen-tac-ve-tieu-chi-u-ieu-kien-tham-gia-chien-dich-danh-c-3043429823514369.md`) |
| **T-14→T-7 Teaser** | "Bắt đầu khơi dậy sự hứng thú" (T-14): ≥1 video/day, LIVE anchor link, cross-post. "Chia sẻ nội dung video teaser". Prep "2 – 3 nội dung sáng tạo … mỗi sản phẩm", "2 – 5 … mỗi ngày" | TikTok app / LIVE | ads "không quá 30% mỗi ngày so với ngân sách BAU" |
| **T-5→T-1 Countdown & price** | "Bắt đầu đếm ngược"; resolve *Thương lượng giá chiến dịch trực tuyến* (Đồng ý/Từ chối); layer seller Flash Sale/voucher; +20% cost cap on day 1 | Chiến dịch > Sản phẩm tham gia; Khuyến mãi | Negotiations "phải trả lời … trong một khoảng thời gian đã định" or they expire |
| **T-day** | "Giờ vàng đã điểm!" — publish all content, long LIVE with shift cover, watch stock, reply chat ≤12h | LIVE, Đơn hàng, Chat | Campaign price + locked stock in force |
| **T+1→T+3** | "Duy trì hoạt động hiệu quả" — post-sale promos, taper ads ≤30%/day, ship backlog, handle returns | Đơn hàng, Hậu mãi, La bàn dữ liệu > Hiệu suất chiến dịch | LDR/FDR/auto-cancel resume; aftersale auto-approves at 48h silence |

## B. Task scoring (repetition · effort · pain · API reach · Juli map)

| Task | Rep | Effort | Pain if missed | API reach | Juli |
|---|---|---|---|---|---|
| Watch calendar + registration windows | every event (2–6/mo; 2026 calendar page in `A/courses/seller/`) | low, but daily | miss cutoff ⇒ zero eligibility | **none — no campaign-list endpoint** | NONE |
| Eligibility pre-flight (rating, VP/AHR, neg-review, SFRR) | every | low if data held | silent rejection / mid-event removal | partial: `Get Shop Performance 202509`; VP/AHR not exposed | hooks alerts |
| Pick SKUs + set *giá chiến dịch* per sub-campaign | every | **high** — per SKU × sub-campaign, differing thresholds | rejected price, or margin destroyed and floor poisoned | compute yes (`Get Product`, `Get Shop SKU Performance List`); **submit Seller-Center-only** | Product 2 (read) |
| Set *hàng có sẵn của chiến dịch* | every | med-high | oversell ⇒ SFCR/LDR; understock ⇒ lost GMV | read `Inventory Search`; **campaign-reserve write Seller-Center-only** | Inventory 3/4 (partial) |
| Review platform-submitted / recommended registrations | every | med | enrolled at a price you didn't pick, or slot wasted | Seller-Center-only | NONE |
| Respond to *thương lượng giá* | every | med, time-boxed | expires ⇒ stuck at an uncompetitive price | Seller-Center-only | NONE |
| Layer seller promos around campaign price | every | med | stacking waste (campaign price wins) | **yes**: `POST /promotion/202309/activities`, `…/products`, `deactivate` | **Promotion 7a/7b/7c** |
| Listing quality on hero SKUs | every | high (creative) | low CVR, not "Được đề xuất" | `Get Products SEO Words`, `…/suggestions`, `Partial Edit Product` | **Product 1/2** |
| Physical replenishment by T-14 | every | high (lead time) | stockout mid-sale | `Inventory Search` → `Update Inventory` (FBS) | **Inventory 3** |
| OHC daily capacity + Fulfillment Extension toggle | every | low, must re-check | overflow orders get no extension ⇒ LDR / auto-cancel | Seller-Center-only (beta) | NONE |
| Content plan (2–3/SKU, 2–5/day, T-14 teaser) | every | **very high**, human | no traffic on the day | not in Partner corpus | human |
| Ads ramp ≤+30%/day then taper | every | med, daily | delivery collapse or wasted spend | Ads API (out of scope) | NONE |
| T-day dispatch backlog | every | high volume | LDR/FDR breach ⇒ VP | `Create Packages`, `Ship Package`, `Batch Ship Packages` | **Process Order 5** |
| Post-sale return spike | every | high | seller-fault return rate gates the *next* campaign | Return/Refund API | **Post-sales 8a/8b/8c** |

## C. What TikTok already automates — do not rebuild

- **Đăng ký Chiến dịch Một lần nhấp** (`A/feature-guides/seller/khuyen-mai/ang-ky-chien-dich-mot-lan-nhap-7191197475882768.md`): one click enrolls every eligible SKU into every eligible sub-campaign; three product strategies (all-eligible / recommended-only / CSV), two price strategies (*Giá Tối Ưu*, *Giá Tối Ưu + ưu đãi bổ sung*), with a built-in guard — "Nếu **Giá Tối Ưu** … thấp hơn 80% so với giá bán lẻ, sản phẩm đó sẽ không được đăng ký."
- **Pre-filled Excel / bulk registration** with recommended campaign price *and* stock ("được điền sẵn"), plus a failure report on bad rows (`…/chien-dich-san-pham-8901645928908546.md`).
- **Platform registers on your behalf**; *Được đề xuất* / *Được mời* / *Đăng ký chờ xử lý* tabs with batch approve/reject.
- **Thương lượng giá chiến dịch trực tuyến** — platform proposes optimal prices; seller accepts/rejects (`…/tinh-nang-quan-ly-gia-3723270759630593.md`).
- **Khuyến mãi đề xuất** (`A/feature-guides/seller/khuyen-mai-e-xuat-7351965450307329.md`) — personalised single/combo promo strategies refreshed every 7 days, with live diagnostics bucketing SKUs into *Mới được chọn / Giá khuyến mãi được điều chỉnh / Giữ nguyên*.
- **Inventory forecast already exists**: *Dự báo doanh số (30 ngày)*, *Số lượng bổ sung hàng đề xuất* = (forecast × window) − available, *Số ngày cung ứng*, threshold alerts (`A/feature-guides/seller/products/quan-ly-hang-ton-kho-6837780085163777.md`).
- **OHC tool** (`A/policy-center/seller/cong-cu-nang-luc-xu-ly-on-hang-2817965594789649.md`), **Chế độ nghỉ lễ** (`A/feature-guides/seller/che-o-nghi-le-4151623383713538.md`), and **La bàn dữ liệu > Tiếp thị > Hiệu suất chiến dịch** (YTD + real-time).

## D. Rules that bite

1. **Price memory / LXXD.** Campaign price must beat "giá thấp nhất trước đây của L30/60/90/180D, không bao gồm Khuyến mãi của nền tảng". Other threshold rules: % below retail, below your own product discount, a price band, or match similar products **on TikTok Shop or other platforms**. Today's deep price raises tomorrow's bar.
2. **Stock lock on approval.** "TikTok Shop sẽ khóa số lượng chiến dịch … ngay sau khi … được phê duyệt." Seller Center shows *Đã khóa cho chiến dịch* as its own bucket; `P/api-reference/products/inventory-search-202309.md` has **no equivalent field**, so an API-only stock view overstates what is sellable.
3. **One-way edits.** "Chỉ có thể cập nhật giá thấp hơn. Chỉ có thể cập nhật giá trị lớn hơn cho số lượng hàng tồn kho." Approved items need re-approval; *đang cập nhật* items cannot be withdrawn.
4. **Campaign price beats everything** — "giá của tất cả các công cụ khuyến mãi khác sẽ ngưng áp dụng nếu thời gian trùng nhau"; exceptions are seller LIVE flash sale and winning bids. Across two campaigns: tier (mega > daily) → co-funded > non-co-funded → voucher-vs-direct comparison → lowest price.
5. **Ad ramp ≤ +30%/day** vs BAU, up and down; +20% cost cap on day 1. **Teaser from T-14**, ≥1 video/day, 2–5 creatives/day at peak.
6. **Eligibility re-checked periodically** — falling below rating 3.0 / VP 36 / neg-review 1.5% / seller-fault return 7–8.8% removes you mid-campaign.
7. **OHC extensions stack**: "gia hạn 2 ngày cho chiến dịch 9.9 + OHC 1 ngày = 3 ngày" — but only if *Gia hạn hoàn thiện đơn hàng* is toggled on, effective **the next day** (00:00).
8. **Post-sale**: aftersale auto-approves after 48h of silence; the 7-day seller-fault return rate gates the next campaign.
9. **Account health**: 12 VP blocks new campaigns 7 days; 24 VP blocks mega campaigns 14 days; 36 VP blocks 60 days (`docs/integrations/tiktok_platform/seller/account-health.md:44-46`; gate also in `implementation-hooks.md:13,29`).

## E. Ranking and recommendation

**Platform-campaign registration has NO API.** The Partner corpus contains zero seller campaign endpoints. `Promotion` covers only Product Discount, Flash Deal and read-only Coupon: "All three … are **seller** promotion activities which are 100% funded by the seller" and "You cannot use OpenAPI to create coupon activities" (`P/api-reference/promotion/promotion-api-overview.md`). The only `campaign` endpoints are `Affiliate partner > …Campaign…` (TAP scope, 202405–202508) — affiliate creator campaigns, not mega-sale enrollment. `docs/integrations/tiktok_api/contract-collection.md` has no `campaign` occurrence, and line 75 already records "~~Create Voucher / Coupon~~ — REMOVED … no seller-facing create-coupon operation exists". Every registration-side workflow is therefore a **human checklist Juli prepares**, never a write Juli performs.

Top 5 by pain × repetition × API reach:

1. **Campaign-readiness pre-flight** — trigger: T-10 on a calendar event → reads Analytics shop/SKU performance, `Inventory Search`, `Get Product` → one human checklist ("27 SKUs pass, 4 fail on neg-review") → measure: % submitted SKUs approved.
2. **Campaign price-floor guard** — trigger: seller about to submit or negotiate → reads SKU performance + our own L180 price history + margin → per-SKU max-safe price → measure: margin retained.
3. **Campaign stock reservation plan** — trigger: T-7 → reads `Inventory Search` + sales velocity → per-SKU reserve quantity (write via Seller Center) → measure: stockouts / post-lock oversell.
4. **Peak-day dispatch defense** — trigger: order webhook #1 volume spike → reads `Get Order List`, package status → writes `Create Packages` + `Batch Ship Packages` → measure: LDR/FDR T-day→T+3.
5. **Promo-stacking cleanup** — trigger: campaign approved → reads `Get Activity` + webhook #39 → writes `Deactivate Activity` on overridden seller promos → measure: wasted discount avoided.

**Recommendation: build #1, the Campaign-Readiness Pre-flight** — a read-only briefing fired off the campaign calendar, ending in a Seller-Center checklist, with #2 and #3 as its sections. It recurs every event, is cheap in API reach (Analytics + Products, already contracted), and its failure mode — silent rejection or mid-campaign removal — is invisible until the GMV doesn't arrive.

**Strongest counter-argument:** it performs no write, so Juli ships a well-timed report while TikTok already provides most individual signals — Khuyến mãi đề xuất, inventory forecast, one-click registration with an 80%-of-retail guard, and platform price negotiation. A seller using *Đăng ký Một lần nhấp* gets ~80% of this free. The defensible sliver is **the seller's own margin and L180 price memory**, which TikTok deliberately does not model: its recommendations optimise platform GMV, not the seller's floor. If Juli cannot credibly own that, build #4 instead — dispatch defense is a real write, a real penalty avoided, fully inside Process Order 5.

**Plain English.** TikTok's public "how to prepare" page is a 14-day *content and ads* countdown: teaser at T-14, daily video, countdown at T-5, long LIVE on the day, taper after. The genuinely painful work sits outside that page. For each of the 2–6 campaigns a month in the 2026 calendar, a seller must re-check eligibility, hand-pick SKUs, set a campaign price that beats their own lowest price of the last 30–180 days, reserve stock that is then locked and can only be increased, approve or reject prices the platform proposes, and finish before a hard cutoff typically 3–7 days ahead. None of it is reachable by the Partner API — TikTok's Promotion API only creates the seller's own discounts and flash deals. So Juli's realistic play is not to click "register"; it is to arrive ten days out with a checked, per-SKU readiness briefing — who qualifies, what price protects margin without poisoning the next event's floor, how much stock to lock — and then to defend the dispatch and returns tail after the day, which *is* fully automatable.
