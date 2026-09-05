# Seller journey — Product (Sản phẩm) vs Juli's execution layer

Catalog filter → **145 matching entries** (81 feature-guides, 46 policy-center, 8 agreement-center, 7 FAQ, 2 courses, 1 trang-chu). ~26 bodies read. Procedural core: `feature-guides/seller/products/**` and `policy-center/seller/Đăng bán sản phẩm/**`.

**Primary sources** (under `academy_documents/`, `fg`=feature-guides, `pc`=policy-center, `ac`=agreement-center):
*Quản lý Sản phẩm* `fg/seller/products/quan-ly-san-pham-10008556.md` · *Đề Xuất Thông Minh* `…/e-xuat-thong-minh-cho-quan-ly-san-pham-1398156382816001.md` · *Quản Lý Hàng Tồn Kho* `…/quan-ly-hang-ton-kho-10013877.md` · *Trình Tối Ưu Hoá Sản Phẩm* `…/trinh-toi-uu-hoa-san-pham-6532499267012354.md` · *Chẩn đoán giá* `…/chan-oan-gia-7563289900353282.md` · *Chương trình Luôn sẵn hàng* `…/chuong-trinh-luon-san-hang-3018868526483201.md` · *Sản phẩm thanh lý* `…/san-pham-thanh-ly-1265022967236369.md` · *Thêm sản phẩm hiện có* `…/them-san-pham-hien-co-tu-tiktok-shop-8929647753037584.md` · *Chẩn Đoán Thẻ Sản Phẩm* `fg/seller/analytics/product-card/chan-oan-the-san-pham-5792290376255233.md` · *Trình Tối Ưu Hóa Tiêu Đề* `…/trinh-toi-uu-hoa-tieu-e-san-pham-8617918787323649.md` · *Tiêu đề, mô tả, hình ảnh và video* `pc/seller/tieu-e-mo-ta-hinh-anh-va-video-ve-san-pham-5918681919178512.md` · *Nguyên tắc đăng bán giá* `pc/seller/nguyen-tac-ang-ban-gia-san-pham-5918681919260432.md` · *Thuộc tính sản phẩm & Thông tin vận chuyển* `pc/seller/thuoc-tinh-san-pham-thong-tin-van-chuyen-5985153894614801.md` · *Thay đổi sản phẩm/Tái sử dụng bài đăng* `pc/seller/thay-oi-san-pham-tai-su-dung-bai-ang-ban-san-pham-2666070329149201.md` · *Hướng dẫn đăng bán sản phẩm* `ac/online-agreement/huong-dan-ang-ban-san-pham-tai-tiktok-shop-10008395.md`

---

## A. Create Product — Sản phẩm > Quản lý sản phẩm > Thêm sản phẩm mới

| # | Step | Class |
|---|---|---|
| 1 | Path: single · bulk Excel · **Niêm yết sản phẩm hiện có** (clone a live listing; blocked without brand auth or invite-only category access) · app · API | API-automatable |
| 2 | **Thông tin cơ bản** — upload images first; system suggests **name + category from the image** | API-automatable |
| 3 | Suggestion chain: keywords → title → category *derived from title* → attributes *from title+category* → AI description (≥3 keywords, ≤200 chars, 5 variants, banned words block generation). Trend keywords refresh **weekly** | API + human check |
| 4 | **Danh mục** decides required attributes, brand need, compliance docs; using the suggested category "increases the chance of passing QC" | policy-gated |
| 5 | Brand name allowed only with brand authorization | human-only |
| 6 | Images ≤9, 1:1, ≥600×600, ≤10MB; main image = front of real product, uniform bg, ≥60% of frame, uncropped, no blur/watermark. Video ≤1 (policy ≤5MB vs guide ≤20MB — **pages disagree**). Media Center (5GB) is the reliable image-URL source | API-automatable |
| 7 | **Chi tiết sản phẩm**: description ≥30 words, ≤30 banners, size chart, ≤250 chars per selling point | API-automatable |
| 8 | **Thông tin bán hàng**: variants (**only variant 1 can carry images**), price, stock, warehouse; launch discount % defaults to **30 days**; purchase min/max limits are **request-gated, 7-day turnaround** | mixed |
| 9 | **Vận chuyển**: dimensions, weight **1–100 kg** | API-automatable |
| 10 | Per-category mandatory attributes; from **2026-03-20** Beauty, Health, Mother&Baby, F&B must give licence type, registration no., issue date, issuing body. Universal: name, origin, responsible entity + address | policy-gated |
| 11 | **Lưu bản nháp** (never reviewed) **or Đăng sản phẩm** (submitted). Left pane previews the PDP in Shop Tab / LIVE / search | API-automatable |
| 12 | Status tabs: Trực tuyến · Đã vô hiệu hóa · **Đã tạm ngưng** — *Không thành công* (fixable, resubmit) vs *Đóng băng* (**cannot edit or resubmit**) · Bản nháp · Xóa (restorable) | human decision |

**Review SLA is not published anywhere in the VN corpus.** The only SLAs found: Product-Opportunity match review **2–3 days**, price-diagnostic feedback **2 business days**. Bulk listing returns a precheck error file (reason in the last column); the online bulk editor handles ≤5,000 variants.

---

## B. Optimize / Edit

Edit: Quản lý sản phẩm > **Chỉnh sửa** > **Cập nhật**. Bulk: Công cụ hàng loạt > Chỉnh sửa sản phẩm hàng loạt, 5 templates (Sales = price/qty/SKU · Basic = name/description/affiliate commission · Shipping · Image links · Attributes · All); ≤50,000 selected, 5,000/template; bulk image edit ≤200.

**Four listing-quality tools TikTok already gives the seller:**
1. **Trình Tối Ưu Hoá Sản Phẩm** (Sản phẩm > Công cụ Tối Ưu Hoá Sản Phẩm) — per-product orders/views + improvement points, **diagnostic tags**, recommendation-vs-search filters, AI title/description rewrite, AI image enhance, **bulk title optimization**. Won't generate from a thin description or enhance a blurry image.
2. **Trình Tối Ưu Hóa Tiêu Đề Sản Phẩm** (La bàn dữ liệu > Tìm kiếm) — keywords matched to product features + search intent with a **search-volume score**; results appear **one day later**.
3. **Chẩn Đoán Thẻ Sản Phẩm** — **14 growth recommendations** incl. title optimization, product-info optimization, price attractiveness, more promo tools, COD, more creators.
4. **Chẩn đoán giá**.

**Price rules — the biggest divergence.** Price Diagnostics tiers each SKU *Giá không cạnh tranh / cạnh tranh / tốt nhất* and reprices **through Chiết Khấu Sản Phẩm (SKU-level) or Voucher Nhà Bán Hàng (product-level) — not by editing the base price**. Both default to 30 days. Product Discount is unavailable while the SKU is in a campaign or Flash Deal → voucher only. The price must be **held ≥1 day** to earn the traffic benefit; the low-price badge is per-product and lost when undercut. Sellers may dispute a recommendation (2 business days); **no penalty for declining**.
Policy floor: listing price must always exceed sale price; total price incl. tax; harmful behaviours include abnormal market prices and **"điều chỉnh hoặc thay đổi giá đột ngột trong một khoảng thời gian ngắn"** — stated qualitatively, **no numeric cap published** (confirmed by exhaustive grep).

**Re-review triggers:** no explicit list exists in the corpus (grep-confirmed). What *is* explicit is the risk boundary — *Thay đổi sản phẩm/Tái sử dụng bài đăng* and listing-guide §3.1.8: changing **title, category, images or description** so the listing represents a materially different product is an enforcement violation; §3.1.7 names the same edit combination as clickbait. Minor image/price/description/SKU edits on an unchanged product are explicitly permitted. One concrete edit gate: title **≥25 chars** (Flash Deal exempt) — existing listings are grandfathered but **must satisfy it on their next edit before submitting**.

---

## C. Stock on a product

- **Sản phẩm > Quản lý hàng tồn kho**, SKU-level. Buckets **Đủ hàng / Còn ít (≤ alert value) / Hết hàng (0)**.
- States: Có sẵn (physical) · **Hiện có** (unreserved, the sellable number) · Đã khóa cho chiến dịch / nhà sáng tạo / đã chốt đơn. Write rule: **available must exceed locked**.
- Editing: inline for one warehouse; **multi-warehouse opens a per-warehouse popup** and greys out the inline box.
- TikTok's own maths: Doanh số (7/14/21/30/45/60d) · **Dự báo doanh số (30 ngày)** across Shop Tab/LIVE/video · **Số lượng bổ sung hàng đề xuất = (forecast × period) − Hiện có** · **Số ngày cung ứng**.
- Alerts by quantity **or days of supply**, over 4 channels (Home > Nhiệm vụ "Còn ít" card, Message Center, app push, email). Bulk set is hidden above 1,000 SKUs. **No per-warehouse alerting.**
- **Xuất danh sách bổ sung hàng** exports the OOS/low/at-alert replenishment list.
- **Tự động về lại hàng** (auto-restock on cancellation), per-SKU or bulk. TikTok says **turn it OFF if you sell on multiple platforms or sync from an ERP** — the corpus's *only* ERP/3rd-party mention; there is no supplier or ERP surface in Seller Center.
- 30-day SKU history with channel, seller edits, buyer purchases + order id. A 0-stock SKU stays listed and unbuyable; only deletion removes it.
- **Chương trình Luôn sẵn hàng**: commit and **lock** stock for traffic + subsidy, with an estimated **GMV uplift**; the seller cannot reduce it; unlock is **auto-approved for only 3 SKUs per seller**, beyond that a reasoned form.
- **Sản phẩm thanh lý**: label SKUs that won't be restocked — **excluded from low/OOS alerts**, extra visibility, own Clearance section in the app. Cannot label at 0 stock; **adding stock silently strips the label and all benefits**.
- **Giới hạn mua của khách hàng**: per-product min/max purchase quantity, request-gated (7 days).

---

## D. Alignment (`docs/product/execution_layer.md`)

| Juli step | Academy | Verdict |
|---|---|---|
| Create step 1 Get Category / step 3 Get Attributes (L102–105) | Category chosen *after* images+title, from a suggestion derived from them | **WRONG-ORDER** |
| Create step 2 Check Listing Prerequisites (L103) | Brand auth + invite-only access + per-category licence fields (2026-03-20) | MATCH, under-specified |
| Create step 5 Upload Image (L106) | Media Center as image host; main-image composition rules | **GAP** |
| Create steps 6–7 SEO / title suggestions (L108–109) | Same three signals + weekly trend keywords, 5-variant AI description | **MATCH** |
| Create step 8 Create Product (L110) | Draft vs Publish is a real fork; drafts are never reviewed | **GAP** (no draft state) |
| Create steps 9/9.5 + webhooks #5/#37 (L111–112) | Status tabs; *Không thành công* vs terminal *Đóng băng* | MATCH; no rejection/resubmit loop |
| Optimize step 5 Edit Product (L128) | Bounded by the substantive-change prohibition and the ≥25-char title gate on next edit | **MISSING-PREREQUISITE** |
| Optimize step 6 Update Price (L129) | Repricing via Product Discount / Voucher, blocked in campaign/Flash Deal, 30-day default, hold ≥1 day | **WRONG** |
| `playbooks/optimize_product.py` 6 steps | TikTok already emits the diagnosis Juli re-derives | **GAP** |
| Replenish step 1 Inventory Search (L152) | Dashboard already returns forecast, recommended reorder qty, days of supply | **GAP** (T1/T10 duplicate a first-party number) |
| Replenish 2a supplier/ERP (L153–155) | No ERP surface; auto-restock toggle TikTok says to disable under ERP sync | **MISSING-PREREQUISITE** (double-count risk) |
| Replenish warehouses (L152–157) | Per-warehouse popup; total-only alerts | **GAP** |
| Replenish — Always-in-Stock (absent) | Locked committed stock, 3 auto-unlocks per seller | **MISSING-PREREQUISITE** |
| Clear Excess step 3 markdown (L177) | Markdown runs through discount/voucher | **WRONG** |
| Clear Excess steps 4–5 Flash Sale (L178–180) | Matches the promotion tooling | **MATCH** |
| Clear Excess step 6a zero out stock (L182) | **Sản phẩm thanh lý** is the intended mechanism; a 0-stock SKU can't be labelled | **WRONG** |

---

## E. Judgment points and never-automate

**Candidate CONFIRM pauses:** category choice · brand-name usage · compliance/licence values · which AI title/description variant to accept (TikTok itself warns its AI output "may be inaccurate — check carefully before publishing") · accepting a Price-Diagnostics recommendation · discount vs voucher (SKU vs product blast radius) · any stock write on a multi-warehouse SKU · enrolling in Luôn sẵn hàng · setting/clearing Thanh lý · toggling auto-restock.

**Never automate:** (1) editing title + category + images + description together on a live listing — the exact fingerprint of prohibited listing repurposing/clickbait; (2) repeated price moves in a short window; (3) comparative, superlative, weight-loss or "cure" claims in generated copy; (4) writing stock below the locked quantity on a Luôn sẵn hàng SKU; (5) adding stock to a Thanh lý SKU; (6) resubmitting an *Đóng băng* product.

---

## F. Top 5 corrections, ranked

1. **Replace base-price mutation with the discount/voucher path** in Optimize Product (L129) and Clear Excess (L177), adding the campaign/Flash-Deal precheck and the 30-day / ≥1-day-hold semantics. Base-price edits become the exception.
2. **Add a "read TikTok's diagnosis first" step to Optimize Product**, before `get_seo_keywords` (playbook step 2+3). Product Optimizer tags, the 14 Card-Diagnostics recommendations and the Price-Diagnostics tier are first-party ground truth; today's playbook re-derives a diagnosis that can contradict what the seller sees on screen.
3. **Replenish: reconcile to TikTok's own numbers and guard the write** (L146–157). Consume "Số lượng bổ sung hàng đề xuất" and "Số ngày cung ứng" as the baseline T1/T10 argue against, and gate the write on three checks absent today — auto-restock state, Luôn sẵn hàng lock, multi-warehouse allocation.
4. **Clear Excess: make Sản phẩm thanh lý step 6**, not "zero out floor stock" (L182) — zeroing forfeits the visibility boost and the app's Clearance section, and a 0-stock SKU can no longer be labelled at all.
5. **Create Hero Product: fix step order and add two gates** (L102–110) — image → title → suggested category → attributes; an explicit draft-vs-submit fork; a rejection loop distinguishing *Không thành công* (resubmit) from *Đóng băng* (terminal); plus the per-category licence attributes live since 2026-03-20.

---

**Summary.** TikTok Shop's product journey is far more instrumented than Juli's four workflows assume: the platform already tells the seller which listings are weak, which titles to fix with which keywords, what the competitive price tier is, how many units to reorder and how many days of cover remain. Juli's biggest risks are not missing steps but three mismatched mechanisms — repricing through the base price when TikTok reprices through discounts and vouchers; zeroing stock to clear excess when TikTok has a purpose-built Clearance label; and writing inventory without checking the three things that can silently invalidate the write (auto-restock, committed-stock locks, multi-warehouse). Create Hero Product's step order is also inverted relative to the real screen, where the image drives the title which drives the category. The highest-value next move is to make Juli read TikTok's own diagnostics before proposing anything, so its recommendation and the one already on the seller's screen cannot disagree.
