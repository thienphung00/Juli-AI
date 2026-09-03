# Returns, Refunds & Cancellations — VN Seller Journey (academy corpus)

Corpus: `/Users/macos/Juli-AI-local/tiktok-corpora/academy_documents/`. ~56 catalog entries matched;
20 bodies read. Juli side: `docs/product/execution_layer.md` L310–429. The curated
`docs/integrations/tiktok_platform/seller/policy.md` only carries SFCR/SFRR violation-point rows
(L41, L43) — there is **no curated returns-policy doc**; this is a real gap, not a duplicate.

---

## A. Cancellation (pre-shipment)

Sources: *Quản Lý Yêu Cầu Hủy Đơn* (`feature-guides/seller/tra-hang-hoan-tien/quan-ly-yeu-cau-huy-on-963525829347074.md`);
*Hủy đơn hàng* (`policy-center/seller/huy-on-hang-578506941728513.md`); *Nguyên tắc Tự động hủy đơn*
(`policy-center/seller/nguyen-tac-tu-ong-huy-on-6837776050571010.md`); *Chính sách hủy đơn hàng, trả hàng và hoàn tiền* §3
(`agreement-center/.../…-6837773789234946.md`); *Bằng Chứng Cần Cung Cấp để Từ Chối…* (`feature-guides/seller/on-hang-van-chuyen/bang-chung-…-10011803.md`).

1. Request lands in **Order Management → "Việc cần làm" → filter "Hủy"** (redirects to "Tất cả").
   Hover splits *auto-approved by platform* vs *awaiting you*. [API-automatable]
2. **Decision window: 2 calendar days / 48 hours.** [API-automatable]
3. Approve → order cancelled, buyer refunded in full. [API-automatable]
4. Reject → **must** pick a reason **and upload evidence**. VN reject-reason list for cancellations is
   only **two** entries: *"Sản phẩm đã được đóng gói"* (evidence: packing/shipping photos) and
   *"Đã đạt được thỏa thuận với Khách Hàng"* (evidence: chat screenshot). [policy-gated — evidence upload]
5. **Timeout default: platform auto-cancels and refunds the buyer at 48h** (Nguyên tắc Tự động hủy đơn).
6. Buyer may **dispute a rejection within 7 calendar days** (after-sales dispute rules).
7. Seller-initiated cancel: **Order Management → Hành động khác → Hủy**, allowed only before
   *"Đã vận chuyển – Đang vận chuyển"*. Seller-fault reasons (out of stock, wrong price) count into **SFCR**.
   Sellers are forbidden from asking buyers to cancel. Support cannot cancel on the seller's behalf. [human-only judgment; API-executable]
8. Special case: free-shipping-voucher order with >1 item — no partial cancel; items already
   *"Chờ vận chuyển – Chờ lấy hàng"* are the seller's call, items not yet ready are **auto-approved**.
9. **Inventory:** pre-shipment hold releases automatically. But if a cancelled parcel was still picked up,
   it returns as **"Giao hàng không thành công"**, the seller pays return freight, and recovery is an
   appeal ("Tôi chưa nhận được gói hàng hoàn trả" / "Sản phẩm bị hư hỏng hoặc đã bị sử dụng"). [human-only]

## B. Return (post-shipment)

Sources: *Quản lý yêu cầu trả hàng và hoàn tiền* (`…/quan-ly-yeu-cau-tra-hang-va-hoan-tien-6819122768905985.md`);
*Trả hàng và hoàn tiền* (`policy-center/seller/tra-hang-va-hoan-tien-1766935302801169.md`); *Phương Thức Trả Hàng và Hoàn Tiền*
(`…/phuong-thuc-tra-hang-va-hoan-tien-1398156382422785.md`); *Hoàn Tiền Một Phần* (`…/hoan-tien-mot-phan-3325723009222416.md`);
*Thương lượng với người mua* (`…/thuong-luong-voi-nguoi-mua-5529285474109185.md`); *Khiếu Nại Yêu Cầu Trả Hàng/Hoàn Tiền* (`…-10017858.md`);
*Trả Hàng Không Thành Công* (`…-8356736328402705.md`); agreement-center §4.

1. **Buyer filing window: 15 calendar days** after status = "Đã giao hàng"; **6 days** for Mẹ & Bé, F&B,
   phones/electronics, home-improvement categories. (Not 30 days.)
2. Intake: **Orders → Quản lý yêu cầu trả hàng → "Đang chờ hành động của bạn" → filter "Trả hàng và hoàn tiền"**.
   Cards distinguish *platform-approved return*, *returnless refund*, *Fast Refund (Hoàn tiền nhanh)*,
   *platform-approved refund*. [API-automatable]
3. **First review: 1 calendar day** to approve/reject. Miss it → **platform auto-approves**; you keep the
   right to inspect and reject on receipt. [API-automatable]
4. Reject requires reason + evidence (packing video, listing photos, chat screenshots). Unreasonable
   rejection is itself an enforceable violation (§4.4.1). [policy-gated]
5. **RMA / ship-back:** buyer must ship within **10 calendar days** of approval or the request closes with
   no refund. Three methods: drop-off (J&T, GHN, ViettelPost), home pickup (3 attempts, then converts to
   drop-off), **self-arranged** (buyer uploads tracking within 10 days; not platform-integrated, platform
   not liable for loss). Tracked on **Quản lý hàng trả lại**. [API-automatable read]
6. **Inspection window: 2 calendar days** from receipt → approve (refund releases) or reject with one of
   4 reasons (item not the one shipped / not received / damaged-or-used / missing parts) plus photo-video
   evidence. **Miss it → auto-approved AND you forfeit the appeal.** [human-only judgment]
   Self-arranged returns: seller must review within **14 calendar days** of tracking upload; if the item
   never arrives within 14 days the platform auto-refunds.
7. **Fast Refund:** money is released at drop-off/pickup scan, before you inspect. Appeal afterwards.
8. **Partial refund / negotiation:** "Hoàn tiền toàn bộ/một phần" sends a chat offer; buyer has
   **1 calendar day**; **one formal offer per request only**. Platform guidance: 80% missing parts,
   70% damaged, 50% signs of use; ≤10% of units affected → negotiate, <50% affected → refund 50%.
   Buyer acceptance ⇒ **SFRR exemption**; buyer refusal/silence ⇒ back to the standard path. [human-only]
9. **Appeal/dispute:** **7 calendar days** from when the appeal becomes available; **one appeal only**;
   unavailable once you click "Xác nhận kiện hàng"; supplemental docs within **24 hours**. Grounds:
   unfair arbitration, auto-approved-for-late-delivery, Fast Refund, or parcel not received within 3 days
   of refund. (A separate FAQ states the appeal button shows for **15 calendar days** from successful
   refund — the two figures conflict; treat 7 days as the safe bound.) [human-only]
10. **Failed return:** seller refuses the parcel, or 3 failed re-delivery attempts → carrier destroys it
    after **7 days**; the seller has those 7 days to reclaim.
11. **Freight:** seller pays return freight when the reason is seller-fault. Self-arranged seller-fault
    returns trigger an **automatic voucher compensation to the buyer, deducted from the seller's balance**.
    "Đổi ý" returns: platform pays the return leg; seller pays outbound capped at ₫40,000 (standard) /
    ₫20,000 (express), and must approve if the item is resellable.
12. Post-dispute, a lost appeal can require **shipping the item back to the buyer within 3 business days**;
    freight reimbursed within 14 days.

## C. Refund-only (no return)

Source: *Quản lý yêu cầu chỉ hoàn tiền* (`…/quan-ly-yeu-cau-chi-hoan-tien-4924096304482065.md`).

1. **Orders → Quản lý hàng trả lại → "Đang chờ hành động"**, tag **"Chỉ hoàn tiền"**.
2. **1 calendar day** to approve or reject; **no extension exists** (explicit FAQ). Timeout → auto-approve.
3. Reject reasons are split by stage (in-transit vs delivered) — 7 delivered-stage reasons incl.
   "Cần gửi yêu cầu hoàn tiền & trả hàng", "Đã giao đúng hàng", "Sản phẩm sẽ được gửi riêng",
   "Lý do không rõ ràng hoặc thiếu bằng chứng"; most need photo/chat evidence. [policy-gated]
4. Non-returnable categories are refund-only by design.
5. Platform-decided refund-only: appeal within **7 calendar days** of refund (agreement-center §4.2.1 says
   **3 business days** for platform-handled refund-only — conflicting; use the shorter).
6. Missing-item refund-only: **1 calendar day** to negotiate before the platform decides for you.

## D. TikTok's own automation (Juli must not race these)

| Timer | Rule |
|---|---|
| 48h | Unhandled buyer cancellation → **platform auto-cancels + refunds** |
| 1 calendar day | Unhandled return / refund-only first review → **auto-approved** |
| 2 calendar days | Unhandled return inspection → **auto-approved, appeal forfeited** |
| 14 calendar days | Self-arranged return not received → **auto-refund** |
| 10 calendar days | Buyer doesn't ship → request **auto-closed**, no refund |
| At scan | **Fast Refund** pays before seller inspection |
| Fulfillment SLA | Auto-cancel for late dispatch, pre-order +2d, seller-ship not delivered in 15 days, unpaid order, LSP-reported loss/damage, fraud. Email warning ≥1 calendar day prior |
| Monthly | **Công cụ phê duyệt tự động**: if the seller fails to review >90% of requests on time in a month, the platform turns on auto-approve for requests <₫790,000 (adjustable), any reason except "suspected counterfeit", max 3 per customer/month, on for ≥15 calendar days |
| Seller rules | Orders → **Cài đặt hoàn thiện đơn hàng** → Hủy / Trả hàng và hoàn tiền tabs: auto-approve-cancel, returnless-refund, auto-approve-refund. **Seller rules override platform rules, and anything they auto-approve is final and non-appealable.** Recommended cap ₫50,000 |

**Metrics.** SFCR < 2.5% (7-day window) → ≥10% throttles order volume to 90/70/50% and deducts 5–10 AHR
points. SFRR < 1.5% (30-day) → no direct enforcement but hits Shop Score and affiliate access; excluded
when buyer cancels, buyer never ships, seller wins arbitration, or reason = "Đổi ý". **AHT (Thời gian xử lý
hậu mãi) < 20h**, 60-day rolling — advisory from May 2026, counted into Shop Score from **July 2026**;
timed-out requests count their **entire** waiting time into AHT.

## E. Alignment with Juli 8a/8b/8c

| Juli step | Academy | Verdict |
|---|---|---|
| 8a step 0–1 intake (L349–350) | Việc cần làm → Hủy | MATCH |
| 8a step 2 decision eligibility (L351) | 48h window | MATCH (encode 48h explicitly) |
| 8a step 3 Get Reject Reasons (L352) | VN reject needs reason **+ evidence upload** | MATCH but **MISSING-PREREQUISITE**: no evidence-attachment step |
| 8a — seller-initiated cancel | "Hành động khác → Hủy", SFCR impact | MISSING |
| 8a — cancelled-but-picked-up parcel | "Giao hàng không thành công" + appeal | MISSING |
| 8a inventory note (L358, L413) | Hold releases automatically | MATCH |
| 8b step 2 "30-day window" (L370) | VN = **15 days** (6 for some categories) | **WRONG** |
| 8b step 3/3.5 RMA (L371–372) | 3 return methods, 10-day ship-back | MATCH, but 10-day close and method branch MISSING |
| 8b — first-review 1-day clock | Auto-approve at 1 day | MISSING |
| 8b — 2-day inspection before approve/reject | Approve/Reject Return (L376) is modelled as one decision | **WRONG-ORDER**: TikTok has *two* decisions (intake, then post-receipt inspection); Juli collapses them |
| 8b — partial refund / negotiation, Fast Refund, failed return, appeal | All present in academy | MISSING |
| 8b step 7a FBS manual restock (L377) | Inspect-then-restock | MATCH |
| 8c step 2 Calculate Refund (L395) | Partial-refund amounts + platform guidance % | MATCH |
| 8c — 1-day timer, no extension | Explicit | MISSING |
| 8c — appeal 7 days / 3 business days | Explicit | MISSING |
| **"Auto-approve clean requests" (L331)** | TikTok already auto-approves on timeout; platform pre-approves most returns; seller auto-rules are non-appealable | **CONFLICT** — see below |
| **"Auto-reject with documented reason" (L332)** | Unreasonable rejection is an enforceable violation (§4.4.1); every reject needs uploaded evidence | **CONFLICT / policy-gated** |

**Is "auto-approve clean requests" consistent with TikTok's defaults?** Only partially. Approving fast is
correct for AHT, but Juli approving via API duplicates what TikTok's own timers and pre-approval already
do, and — critically — Juli approving an *inspection-stage* return before the item is physically checked
throws away the seller's only remaining leverage. The safe framing is: Juli auto-approves **intake-stage**
requests inside the seller's own configured value/reason envelope, and never the inspection-stage decision.

**Is "Get Reject Reasons" really required for VN?** Yes. Every VN reject path is a reason picked from a
fixed enumerated list, and all but three of them carry a mandatory evidence upload. The gap is not the
call — it is that Juli has no evidence-attachment step after it.

## F. CONFIRM pauses vs safe auto-triage

**Require a human CONFIRM:** rejecting anything (evidence + violation exposure); the post-receipt
inspection decision; any partial-refund/negotiation offer (one shot per request, and it is a price
concession); filing an appeal (one shot, 7 days); seller-initiated cancellation (SFCR); accepting a
"Đổi ý" return where resellability is arguable; suspected-counterfeit cases (explicitly excluded from
platform auto-approve).

**Safe to auto-triage:** intake, classification and queue ordering by remaining clock; approving
intake-stage requests already matching the seller's configured auto-rules; approving requests the platform
has already pre-approved (a no-op that improves AHT); reading RMA/tracking state; surfacing the
2-day inspection deadline and the 7-day appeal deadline; the "buyer never shipped in 10 days" close.

## G. Top 5 corrections for 8a/8b/8c

1. **Split 8b's single approve/reject into two gated decisions** — intake (1 day) and post-receipt
   inspection (2 days, 14 for self-arranged) — with the second one CONFIRM-only. Everything else here
   depends on this. (L364–388)
2. **Fix the eligibility window**: 15 calendar days from delivered, 6 for the exception categories — not
   30. (L370)
3. **Model TikTok's own timers as first-class state** (48h / 1d / 2d / 10d / 14d / Fast Refund) so Juli
   never races an auto-approval or claims credit for one, and so AHT (<20h, scored from July 2026) is the
   optimisation target rather than raw approval rate. (L323–333)
4. **Add evidence attachment + the enumerated VN reason lists** to every reject path, and downgrade
   "auto-reject" (L332) to "prepare a reject with evidence, pause for CONFIRM" — unjustified rejection is
   an enforceable violation.
5. **Add the negotiation / partial-refund lane** (one offer, 1-day buyer clock, 80/70/50 guidance) as the
   preferred alternative to rejection, since buyer acceptance is the only documented **SFRR exemption**;
   and add the appeal lane (7 days, one shot, 24h supplemental docs).

---

**Summary.** For a Vietnamese TikTok Shop seller, after-sales is a race against TikTok's own clocks, not a
free-form approval queue: a buyer cancellation auto-cancels at 48 hours, a return or refund-only request
auto-approves at 1 calendar day, and a returned parcel auto-approves at 2 calendar days after arrival —
and missing that last one also destroys the seller's right to appeal. The platform pre-approves most
returns itself, pays some refunds at the drop-off scan (Fast Refund), and turns on a blanket auto-approve
tool for sellers who fall behind. The seller's real leverage sits in three narrow places: a
one-shot partial-refund negotiation (the only documented SFRR exemption), a properly evidenced rejection,
and a one-shot 7-day appeal. Juli's 8a/8b/8c capture the API surface accurately but model post-sales as a
single approve/reject decision on a 30-day window, which is wrong on both counts for VN — the window is 15
days (6 for several categories) and there are two decisions, not one. The highest-value corrections are to
split the return decision in two, encode TikTok's timers as state so Juli optimises the AHT metric that
starts counting in July 2026 instead of duplicating the platform's own automation, and to route every
rejection and every negotiation offer through a human CONFIRM, because each is one-shot and each carries
enforcement or margin risk.
