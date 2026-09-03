# Order & Shipping / Kho Vận — seller journey vs Juli execution layer

Corpus: `academy_documents/` (VN). 86 pages matched the Đơn Hàng & Vận Chuyển / Kho Vận /
Hoàn thành đơn hàng / Thực hiện đơn hàng navs; 22 read in full.

## A. Seller journey — Process Order (FBS, the only model VN documents)

**Step 0 — one-time setup** `[human-only, policy-gated]`
Đơn hàng > **Cài đặt vận chuyển**: enable ≥1 delivery method *per warehouse*; COD auto-applies
to all products once on; carrier is platform-assigned and **not seller-choosable**
("Cài đặt vận chuyển", `feature-guides/seller/on-hang-van-chuyen/cai-at-van-chuyen-7206209079330561.md`).
**Hoàn thiện > Thiết lập phương thức lấy hàng** = pickup vs drop-off default; **Tạo và in nhãn** =
"Vận chuyển Tức thì + In" vs manual ("Thiết Lập Phương Thức Lấy Hàng" `…thiet-lap-phuong-thuc-lay-hang-2976925506144001.md`;
"Nhãn Vận Chuyển" `…nhan-van-chuyen-2981715984320257.md`).

**Step 1 — order lands, triage** `[API-automatable]`
Đơn hàng > **Quản lý đơn hàng**. Status tabs: Chờ vận chuyển, Đang chờ lấy hàng, Đang vận chuyển,
Đã giao, Chưa thanh toán, **Tạm hoãn (on hold)**, Đã hoàn tất, Đã hủy, **Giao hàng không thành công**,
plus a **Hành động cần thiết** tab. Urgency filters: ship ≤24h, auto-cancel ≤24h, overdue,
cancel requested, abnormal package, return/refund requested ("Quản Lý Đơn Hàng" `…quan-ly-on-hang-5910869171717889.md`;
app version `…quan-ly-on-hang-tren-ung-dung-trung-tam-nha-ban-hang-3142758915704592.md`).

**Step 2 — review & stock check** `[human-only]`
Confirm the SKU is actually in stock and shippable; if not, cancel now (Bước 1 of both
"Vận chuyển bởi TikTok" `policy-center/seller/van-chuyen-boi-tiktok-6024728339744528.md` and
"Vận chuyển bởi người bán" `…van-chuyen-boi-nguoi-ban-6091769578522385.md`). Buyer may self-cancel
within **1 hour** of purchase; a seller-side cancel obliges in-app notice + reason + full refund
("Hủy đơn hàng" `policy-center/seller/huy-on-hang-578506941728513.md`).

**Step 3 — Arrange Shipment** `[API-automatable]`
Filter *Cần vận chuyển* by Fulfilment type = Vận chuyển qua Nền tảng, status *Đang chờ Đóng gói*
→ tick orders → **"Sắp xếp Vận chuyển"** ("Hướng Dẫn Đầy Đủ Về 'Vận Chuyển Qua Nền Tảng'"
`…huong-dan-ay-u-ve-van-chuyen-qua-nen-tang-3726090757621506.md`).

**Step 3.5 — combine prompt (interrupt)** `[human-only decision]`
Seller Center *auto-suggests* combining eligible orders at this exact moment: "Gộp các đơn hàng và
tiếp tục", "Xóa" to drop one, or decline. Combined packages stay editable until **Đang chờ lấy hàng**
("Gộp Nhiều Đơn Hàng vào 1 Gói Hàng" `…gop-nhieu-on-hang-vao-1-goi-hang-10012371.md`).

**Step 4 — labels** `[API-automatable]`
Label auto-generates; pick documents (shipping label / packing list / pick list), format, print.
Rejections: buyer-address problem, oversize item, carrier order error → fix → **"Tạo lại nhãn"**.
Print history kept 14 days ("Nhãn Vận Chuyển").

**Step 5 — pack** `[human-only]`
Pack to the printed packing list; packing/labelling do's & don'ts are enforceable policy (no
marketing inserts, no review solicitation, no off-platform QR/links; violations → violation points)
("Đóng gói và dán nhãn" `policy-center/seller/ong-goi-va-dan-nhan-6091769578129169.md`). Optional
barcode verification via **Công Cụ Kiểm Tra Hàng Loạt** (app only) `…cong-cu-kiem-tra-hang-loat-10019439.md`.

**Step 6 — handover** `[human-only]` — pickup or drop-off. LSP scans → status auto-flips to
**Đã vận chuyển**. Explicitly: pull cancelled orders out of the handover pile, or ask the courier to
scan every parcel so cancelled ones are rejected on the spot ("Hủy đơn hàng").

**Step 7 — track / prove delivery** `[API-automatable]` — Đang vận chuyển → Đã giao; proof of
delivery via "Xem thông tin kho vận" > "Bằng chứng giao hàng", **only** for J&T, GHTK, Ninja Van,
BEST. In transit ≥7 days = "Bất thường" (FAQ `…khi-nao-trang-thai-on-hang-uoc-coi-la-bat-thuong-2890936842618626.md`).

**Deadlines** `[policy-gated]` ("Khung thời gian hoàn thành đơn hàng" `policy-center/seller/khung-thoi-gian-hoan-thanh-on-hang-on-hang-tieu-chuan-7261258355672849.md`;
"Nguyên tắc Tự động hủy đơn" `…nguyen-tac-tu-ong-huy-on-6837776050571010.md`):
ordered **before 14:00** on a working day → handover before 23:59 **same** working day; after 14:00 or
non-working day → before 23:59 **next** working day (miss → Late Dispatch Rate). Auto-cancel if not
"Chờ vận chuyển – Chờ lấy hàng" by 23:59 after **2 working days**, or ready-but-not-picked-up by 23:59
after **3 working days**. Working day = Mon–Sat. Unanswered buyer cancel request **48h** → auto-cancel.
Email warning ≥1 calendar day before auto-cancel. **Ship-by-Seller orders must reach "Đã giao hàng"
within 15 calendar days** or auto-cancel.

**Ship by Seller variant** `[API-automatable]` ("Hướng dẫn về 'Vận chuyển bởi Nhà bán hàng'"
`…huong-dan-ve-van-chuyen-boi-nha-ban-hang-3724485006214913.md`): export orders (≤200,000/run) →
book own carrier → upload tracking (bulk template or "Thêm thông tin theo dõi" → **"Gửi gói hàng"**)
→ **separately** upload delivery outcome (success/fail + failure reason, photo attachable). Note:
**you cannot switch shipping method on an existing order**; only the future default via
Vận chuyển > Tùy chọn Vận chuyển (FAQ `…toi-co-the-chuyen-oi-giua-phuong-thuc-van-chuyen-gui-qua-tik-2890226453759746.md`).
Ship-by-Seller / SOF is restricted to selected sellers.

**Split** `[API-automatable]` — documented **only in the Seller Center app**: "…" → **"Tách lô hàng"** →
"Thêm mặt hàng từ kiện hàng ban đầu" → add further packages → pick SKU → confirm; later "Chỉnh sửa
cài đặt tách" ("Hoàn tất đơn hàng của bạn trên Ứng dụng Người bán" `…hoan-tat-on-hang-cua-ban-tren-ung-dung-nguoi-ban-3771850460202753.md`).

## B. FBS vs FBT

**The VN academy corpus does not cover FBT at all.** A word-boundary grep for `FBT` /
"Fulfilled by TikTok" over all 839 pages returns exactly one page — "Chế độ nghỉ lễ"
(`feature-guides/seller/che-o-nghi-le-10017095.md`) — and only as an aside: turning on Holiday Mode
zeroes stock in *all seller warehouses*, but **FBT warehouse stock stays sellable** and the
holiday banner is suppressed. There is **no** enrolment guide, no inbound-shipment procedure, no
FBT daily order handling, and no statement of VN availability. Everything VN-facing describes
FBS with either Vận chuyển qua Nền tảng (platform-assigned LSP) or Vận chuyển bởi người bán / SOF
(selected sellers only). Treat Juli's FBT branches as inferred-from-API-docs, unvalidated by seller docs.

## C. Inventory / warehouse touchpoints (Replenish Inventory)

- **MWH** (`…huong-dan-tinh-nang-mwh-multi-warehouse-10012361.md`): Vận chuyển > **Kho hàng**, up to
  **45 warehouses**, all sellers. Each warehouse has a **Khu vực vận chuyển** (serving region) that
  decides whether its stock can reach a buyer. **Kho mặc định** serves SKUs not stocked at the
  buyer's nearest MWH warehouse or not MWH-registered. Enabling multi-warehouse on a *published*
  product is **irreversible**. Per-warehouse stock edited in Chỉnh sửa sản phẩm or bulk Excel.
  Per-warehouse Holiday Mode zeroes that warehouse's stock for the period.
- **Inventory dashboard** (`feature-guides/seller/products/quan-ly-hang-ton-kho-10013877.md`):
  Sản phẩm > Quản lý hàng tồn kho, SKU level. States Đủ hàng / Còn ít (≤ alert value) / Hết hàng.
  Stock buckets: Có sẵn, Hiện có, Đã khóa cho chiến dịch, Nhà sáng tạo, Đã chốt đơn. TikTok already
  ships **Dự báo doanh số (30d)**, **Số lượng bổ sung hàng đề xuất** = forecast×period − available,
  and **Số ngày cung ứng**. Alerts by quantity *or* days-of-supply → Home > Nhiệm vụ, message center,
  push, email. **"Xuất danh sách bổ sung hàng"** exports a replenishment list. **Tự động về lại hàng**
  (auto-restock on cancel) toggles per SKU/bulk — TikTok explicitly says turn it **OFF** if you sync
  from an ERP or sell multi-platform.
- **ERP/3PL/OMS**: only ever mentioned as "keep your address in sync"
  (`…cap-nhat-quan-trong-thay-oi-ia-chi-theo-on-vi-hanh-chinh-moi-2324329879521025.md`). No ERP integration doc.
- **OHC — Công cụ Năng lực xử lý đơn hàng** (`policy-center/seller/cong-cu-nang-luc-xu-ly-on-hang-2817965594789649.md`):
  seller declares a daily fulfilment capacity; excess orders get an SLA **extension** protecting LDR/FDR/
  auto-cancel. Beta from 13/01/2026, resets 00:00, changes effective next day. Star Shop+/Mall get
  order-surge protection (default cap 3× capacity; at the cap products show "Hết hàng").

## D. Alignment table

| Juli `execution_layer.md` | Academy procedure | Verdict |
|---|---|---|
| L17-36 axis 1 FBT/FBS | VN corpus has no FBT content beyond one Holiday-Mode aside | **GAP** — FBT branch unvalidated for VN |
| L37-53 axis 2 Ship-by-TikTok/Seller | Matches "Vận chuyển qua Nền tảng" vs "bởi Nhà bán hàng" | **MATCH** |
| L37-53 (implied free choice) | Method is fixed per order; only a future default is settable; Ship-by-Seller = selected sellers | **MISSING-PREREQUISITE** |
| §5A step 3 wait `ON_HOLD`→`AWAITING_SHIPMENT` | UI exposes a **Tạm hoãn** tab but no doc explains it or a window | **GAP** — no seller-facing SLA for on-hold |
| §5A step 4 Create Packages | UI equivalent is "Sắp xếp Vận chuyển"; combine prompt fires *here* | **WRONG-ORDER** — §6 combine sits after §5, but the seller decides combine before labels |
| §5A step 5a shipping document | Matches; but pick list + packing list are distinct docs and a print-default setting exists | MATCH w/ omission |
| §5A step 6/7 ship + confirm | Ship-by-TikTok: status flips on **courier scan**, not a seller call | **GAP** — no seller "shipped" write in the platform path |
| §5A step 6b self_shipment | Matches bulk tracking upload | **MATCH** |
| §5A — (absent) | **Update Delivery Status** is a separate mandatory step for Ship-by-Seller (15-day SLA) | **MISSING** |
| §5A step 8 Get Package Detail | Real end-states include Giao hàng không thành công + 3 return-to-seller sub-states | **GAP** |
| §5B FBT read-only | Plausible, but zero VN evidence | GAP |
| §6 Handle Split Package | Split documented app-only; uncombine exists; edit-split-settings exists | MATCH, partial |
| §3 step 1 Inventory Search | Dashboard is SKU-level with locked-stock buckets Juli doesn't model | **GAP** |
| §3 step 2a Update Inventory | Matches direct edit; but **Tự động về lại hàng** must be OFF for ERP sellers | **MISSING-PREREQUISITE** |
| §3 (absent) | TikTok's own forecast / recommended-replenish / days-of-supply already exist | **GAP** — T1/T10 may duplicate or contradict |
| §3 (absent) | MWH: 45 warehouses, serving regions, default warehouse, irreversible enable | **MISSING** |
| §3/§4 (absent) | OHC capacity + Holiday Mode are the real levers when capacity, not stock, is the constraint | **MISSING** |

## E. Candidate CONFIRM pauses (judgment, not data)

1. Combine these N orders into one package? (irreversible after Đang chờ lấy hàng; affects returns)
2. Split this order into K packages, and which SKUs go where?
3. Cancel because stock is genuinely gone — vs delay with buyer consent (allowed, per cancel FAQ).
4. Approve/reject a buyer cancel request inside the 48h clock, including within a combined package.
5. Set/raise the OHC daily capacity and whether to enable surge protection (it makes listings show
   "Hết hàng").
6. Turn on Holiday Mode (zeroes all warehouse stock, cuts traffic, does not excuse existing orders).
7. Turn **Tự động về lại hàng** off for multi-platform/ERP sellers.
8. Enable multi-warehouse on a published product — irreversible.

## F. Top 5 corrections Juli must adopt

1. **Move combine/split ahead of Create Packages.** §6 (L260) must be reachable *from* §5A step 3/4
   (L230+), not after shipping; the platform forces the combine decision at "Sắp xếp Vận chuyển" and
   freezes it at Đang chờ lấy hàng.
2. **Add the SLA clock as a first-class field on Process Order.** 14:00 cutoff, 2/3-working-day
   auto-cancel, 48h cancel-request, 15-calendar-day Ship-by-Seller, Mon–Sat working days, 1-day email
   warning. Note the conflict with `docs/integrations/tiktok_platform/seller/operational-limits.md:97-99`
   (18:00 cutoff, "effective Dec 1, 2025") — one of the two is stale; resolve before shipping T5.
3. **Add a "Update Delivery Status" step to the Ship-by-Seller path and a Failed-Delivery terminal
   branch** (Đang chuyển hoàn / Đã giao lại / Giao cho NBH không thành công), with the appeal action.
4. **Model warehouses in Replenish Inventory** (L146-167): warehouse_id, serving region, default
   warehouse, per-warehouse holiday mode, irreversible MWH enable; and gate `inventory/update` on the
   auto-restock toggle.
5. **Stop treating stock as the only replenishment constraint.** Wire OHC daily capacity + Holiday
   Mode in as the capacity lever, and reconcile T1/T10 with TikTok's native forecast, recommended
   replenishment quantity and days-of-supply rather than presenting a competing number.

---

**Summary.** For Vietnam the seller's real order journey is: set the pickup/label/shipping defaults
once, watch the "Hành động cần thiết" tab, decide per order whether the stock exists, hit "Sắp xếp
Vận chuyển", answer a combine prompt, print label + packing list, pack, and hand the parcel to a
platform-assigned courier whose scan — not a seller API call — marks it shipped; everything after
that is tracking plus a failed-delivery return branch. The whole thing is governed by a 14:00 cutoff
and 2/3-working-day auto-cancel clock that Juli's Process Order workflow currently doesn't represent
at all. Juli's structure is broadly right for FBS but has the combine/split step in the wrong place,
omits the Ship-by-Seller delivery-status update and the failed-delivery outcome, ignores
multi-warehouse entirely in Replenish Inventory, and rests its FBT branches on API docs that the
Vietnamese seller corpus never corroborates — FBT appears exactly once across 839 pages.
