# Process Order — who does what, per fulfilment path

Sources: `~/Juli-AI-local/tiktok-corpora/partner_documents/` (authoritative for API),
`academy_documents/` (VN seller UI). **Who**: T-auto = TikTok unprompted · S-phys = physical act ·
S-UI = seller/agent decision · W = API write · R = API read.

Region dominates everything. Vietnam is **SEA** → the "**Schedule shipping**" flow, not
"Purchase shipping" (`api-reference/fulfillment/fulfillment-api-overview.md:27-53`).

## A1 — FBS + Ship by TikTok ("Vận chuyển qua Nền tảng")

| Step | Who | Endpoint / webhook | Precondition | TikTok next, automatically | HITL |
|---|---|---|---|---|---|
| 0 pickup/print defaults | S-UI, **no API** | — | — | default = last choice | one-time (`…/huong-dan-ay-u-ve-van-chuyen-qua-nen-tang-3726090757621506.md:20-27`) |
| 1 paid → `ON_HOLD` | T-auto | wh #1 | payment | 1h remorse: buyer cancels with no seller approval; recipient address unreadable | never act |
| 2 → `AWAITING_SHIPMENT` | T-auto | wh #1 | 1h elapsed | "occurs automatically"; **"ON_HOLD orders are not allowed to be fulfilled"** (`orders/order-api-overview.md:70,100-103`) | wait, don't race |
| 3 read order | R | Get Order List / Detail | — | — | `fulfillment_type`, `shipping_type`, `delivery_option_id`, `rts_sla`/`tts_sla`/`cancel_order_sla` (`:245-250`) |
| 4 package exists | **T-auto** | Get Package Detail / `order.packages[]` | order paid | TikTok creates it — VN prod orders already carry `packages[{id}]` (`contract-collection.md:213,232`) | **no Create Packages in SEA** (§B) |
| 5 stock check | S-phys/S-UI | — | — | — | the real gate |
| 6 combine | S-UI or W | Search Combinable (A-11) → Combine (B-13) | pre-ship | wh #4 `sc_type=COMBINE` | UI forces prompt at "Sắp xếp Vận chuyển"; ≤20 orders/tracking no., same name+address |
| 7 split | S-UI or W | Split Attributes (A-10) → Split Orders (B-17) | SEA = all-units only, no sub-SKU (`fulfillment/split-orders-202309.md:17-24`) | wh #4 `SPLIT` | VN prod returned `can_split:false` (`contract-collection.md:349`) |
| 8 **arrange shipment** | **W, required** | **Ship Package** `POST /fulfillment/202309/packages/{id}/ship`, `handover_method` PICKUP\|DROP_OFF + `pickup_slot` | not cancelled, **no pending cancel request** | **generates label, assigns carrier, order→`AWAITING_COLLECTION`, package→`PROCESSING`** | = "Sắp xếp Vận chuyển". After it "**the buyer can not cancel request without seller approval**" (`order-api-overview.md:135`) |
| 8b slots | R | Get Package Handover Time Slots (`can_pickup`/`can_drop_off`/`can_van_collection`/`pickup_slots[]`) | package exists | — | `21011053` outside pick-up slot |
| 9 label / pick list | R | Get Package Shipping Document (`SHIPPING_LABEL`, `PACKING_SLIP`, `PICK_LIST`) | **Ship Package first** (`get-package-shipping-document-202309.md:17`) | — | "Documents couldn't be printed after the package has been pickup" (`:315`) |
| 10 print + pack | S-phys | — | — | — | packaging policy enforceable |
| 11 handover | **S-phys** | — | label printed | **courier scan → `IN_TRANSIT` / package `FULFILLING`, initiator TikTok** (`order-api-overview.md:139-146`; `search-package-202309.md:169-170`) | pull cancelled parcels from the pile |
| 12 delivered | T-auto | wh #1; Get Tracking / Package Detail | — | `IN_TRANSIT`→`DELIVERED`→`COMPLETED` | **no package-status webhook** — poll |
| 13 failed delivery / RTS | T-auto | — | — | 3 sub-states; "Đã giao lại cho NBH" ⇒ auto-cancel + refund | **no Partner API** — Seller Center tab only (`…quan-ly-on-hang-giao-khong-thanh-cong-8873269289797392.md:18-21`) |
| 14 auto-cancel | T-auto | — | the 3 SLA fields | cancel + refund; >7d no scan ⇒ SYSTEM cancel | read the SLAs off the order, don't recompute |

## A2 — FBS + Ship by Seller / SOF

Steps 1-3, 5-7, 14 identical. Differences:

| Step | Who | Endpoint | Note |
|---|---|---|---|
| 8 ship | **W** | SEA/LATAM: **Ship Package / Batch Ship with `self_shipment{tracking_number, shipping_provider_id}`**. US/EMEA use Mark Package As Shipped — "exclusive to US, UK, ES, IE, IT, DE, FR, JP" (`mark-package-as-shipped-202309.md:17`), **not VN** | provider from Get Shipping Providers by `delivery_option_id`; TikTok validates the tracking number and **cancels the order if it can't** (`fulfillment-api-overview.md:86,113-121`) |
| 9/12 label, tracking | — | **none** | "Không thể in qua TikTok"; "Không có chi tiết theo dõi cho đơn hàng SOF" (`…seller-own-fleet-sof-tren-10018260.md:22-23`) |
| 10-11 book carrier, pack, hand over | **S-phys, off-platform** | — | |
| 12b **delivery outcome** | **W, mandatory** | **Update Package Delivery Status** `POST /fulfillment/202309/packages/deliver` — `delivery_type` + `fail_delivery_reason` + POD `file_url` (uploaded via Fulfillment Upload Delivery File/Image) | "only sellers utilizing the **SOF (Seller Own Fleet)** capability … **only available for the SEA region**" (`update-package-delivery-status-202309.md:17`); partial failure via `data.errors[]` |
| timings | | | **delivered/failed only ≥24h after shipped**; tracking editable **36h**; **TikTok cancels on day 13 from payment**; **attempt delivery twice** before marking failed; POD kept 1 year; **no COD on SOF** (SOF page `:24-26,52,54,60,102,104`) |
| fix tracking | W | Update Shipping Info / Update Package Shipping Info | seller-shipped only; `21011050`/`21011051` — limited window, **once** |

⚠️ Day-13 here vs the 15-day figure in the earlier report — two academy pages disagree; treat 13 as operating.

## A3 — FBT / MCF

| Step | Who | Endpoint | Note |
|---|---|---|---|
| order lands | T-auto | Get Order List, `fulfillment_type=FULFILLMENT_BY_TIKTOK` | recipient address **redacted** |
| pick/pack/label/ship/deliver | **T-auto entirely** | none | "Do I need to handle shipping operations for orders with 'FULFILL_BY_TIKTOK'? **No. TikTok will fulfill the order.**" (`fulfillment-api-overview.md:122-123`). Ship Package returns **`21008025` "Seller cannot operate orders which are fulfilled by platform"** |
| off-platform orders | W | Create FBT MCF Order → "automatically submitted to the FBT system"; Get FBT MCF Order Status; Cancel FBT MCF Order per consign order | `seller.fbt.info`; gate on Get FBT Merchant MCF Status |
| inventory | R | Search FBT Inventory; Query Goods Inventory For MCF | |
| inbound (Replenish, not this workflow) | S-UI + W | Inbound Plan → Confirm Method → Ship Inbound → Print Labels → Update Tracking (`seller.fbt.inbound`) | `fulfilled-by-tiktok-fbt/16f0ojsg.md` |
| webhooks | | #21 inbound, #22 onboarding, #23 goods match, #24 inventory, **#58 MCF status** | on-platform FBT orders emit ordinary **#1**; no FBT-order webhook |

## B. Is `Ship Package` required on the platform path?

**Yes in SEA/VN, and it is the pivotal write.** The courier scan does the *next* transition.

- "Schedule shipping from TikTok (SEA, EMEA, LATAM)… **Use the Ship Package API to schedule the
  package handover time and method.**" (`fulfillment-api-overview.md:49-53`); the endpoint itself:
  "**TikTok Shipping: Schedule a package handover time for TikTok Shipping carriers to pickup a
  package from seller.**" (`ship-package-202309.md:19`).
- It gates the label — "A shipping label is only available **after shipping has been arranged**" (`:125`).
- It moves the order to `AWAITING_COLLECTION`, initiator **Seller**; the package to `PROCESSING` =
  "arranged by seller, waiting for carrier". The **scan** produces `IN_TRANSIT`/`FULFILLING`,
  initiator **TikTok** (`order-api-overview.md:132-146`; `search-package-202309.md:169-172`).

**Batch Ship Packages** is the same op, N packages, both shipping types
(`batch-ship-packages-202309.md:17-20`), and is **partial-success**: `code:0` with a per-package
`data.errors[]` (`10007014 "package in freeze status"`) — check only the top-level code and you
report phantom successes at volume.

**Create Packages**: "Use this API to ship orders (purchase labels). **This API is region specific to
the US and JP**" (`create-packages-202512.md:17`). Not a SEA prerequisite — TikTok creates the package
at order time (VN prod `packages:[{id}]` before any seller action; A-13 live sandbox
`package_status:"TO_FULFILL"`, `sub_status:"STOCKING"` — `contract-collection.md:411`). No Create
Packages capture exists in `contract-collection.md`.

## C. API cannot do (Seller Center / physical only)

Choose the carrier on platform shipping ("nhà bán hàng **không được** lựa chọn nhà cung cấp dịch vụ
vận chuyển" — platform-guide FAQ); set pickup/drop-off and print **defaults**; print, pick, pack,
weigh, hand over; book a drop-off point (API returns only a `drop_off_point_url`); change an order's
shipping method after creation; declare OHC capacity; toggle Holiday Mode; work the failed-delivery
return branch; dispute a carrier failure (ticket only); the app-only edit-split screen; enrol in SOF.
**`Confirm Package Shipment` is not a seller endpoint** — "Only **warehouse service providers who
have been certified by the platform** have permission" (`supply-chain/confirm-package-shipment-202309.md:17`).

## D. FBT

Per order the seller does **nothing**; the write endpoints reject it (`21008025`). Surface = order
reads with redacted address, FBT inventory reads, and the **MCF** family for orders originating *off*
TikTok. **There is no "FBT order search" endpoint** — that name does not exist in this corpus;
on-platform FBT orders come from Get Order List. Process Order for an FBT seller should be
**monitor-only** (wh #1 + #24), escalating only stock risk, which belongs to Replenish Inventory.
**The VN academy corpus does not corroborate FBT in Vietnam at all** — every FBT claim here is
API-doc-only.

## E. HITL points, ranked by mega-sale frequency

| # | Decision | Freq | Safe default |
|---|---|---|---|
| 1 | combine prompt | very high | **auto-proceed + notify** when name/address match and nothing pending; irreversible after collection |
| 2 | out of stock at pack time | high | **must confirm** — cancel costs LDR + violation points; delay-with-consent is allowed |
| 3 | **buyer cancel request after packages arranged** (wh #11 `..._PENDING`) | high | **must confirm.** Ship/Create are documented as forbidden while pending (`fulfillment-api-overview.md:41-44,56-59`); post-ship the API refuses (`21011041`, `21008044`); unanswered ⇒ auto-cancel at 48h. **Highest-risk race — never auto-ship over it.** |
| 4 | recipient address update (#3) after packing | medium | **must confirm** — re-fetch detail; label is stale; TikTok may itself split (`#4 sc_type=ADDRESS_UPDATE_SPLIT`), so re-read packages before any write |
| 5 | ship errors advising cancellation (`11021010/13/15/…` "you may cancel the order without penalty") | medium | **must confirm** — never auto-cancel off an error string |
| 6 | split (`11006013/14` phones must ship alone) | low-med | forced ⇒ auto+notify; discretionary ⇒ confirm |
| 7 | abnormal package (>7d no scan) | low | auto-proceed + notify (ticket); no API |
| 8 | failed delivery / RTS | low | **must confirm** — no API |
| 9 | SOF delivery outcome | per SOF order | success ≥24h auto with POD; **failure branch must confirm** |

## F. Corrections

1. **§5A step 4 Create Packages is wrong for VN** — US/JP-only. Replace with a *read* yielding
   `package_id`; the stated rationale (L216-222) is answered by the platform, not a seller call.
2. **§5A step 7 Confirm Package Shipment must be deleted** — certified warehouse providers only, and
   uncaptured (`contract-collection.md:1396`).
3. **§5A 5a/6a inverted** — Ship Package must precede Get Package Shipping Document.
4. **§5A 5b wrong** — ship-by-seller in SEA does not skip a TikTok call; it *is* Ship Package with
   `self_shipment`, preceded by a Get Shipping Providers read.
5. **Missing**: Update Package Delivery Status (SOF, 24h/36h/day-13), the failed-delivery branch, and
   the four SLA fields.
6. **No cancellation guard anywhere** — wh #11 must block every ship write.
7. **§5B** substantively right; #58 is MCF-only, #22/#23 unsubscribed (`webhooks.md:89-94`).
8. **§6 placement** confirmed wrong: combine/split precede the ship write.
9. **Earlier report** (`journey-order-shipping.md:124`, "no seller 'shipped' write in the platform
   path"): **there is one** — Ship Package; the scan governs `IN_TRANSIT`, not `AWAITING_COLLECTION`.
   Add SOF day-13, twice-attempt, COD exclusion.
10. **Contract gaps**: `shipping_type`, `delivery_option_id`, `FULFILLMENT_BY_TIKTOK` appear in
    **zero** live captures — the exact branch fields. A-13's live `TO_FULFILL`/`STOCKING` is **not in
    the documented enum**, so a doc-enum state machine falls through on real data.

---

**Summary.** In Vietnam TikTok creates the order *and* the package and holds it an hour; the seller
decides stock, combine and split; then exactly one API write — **Ship Package** — books the handover,
generates the label and stops the dispatch clock; the seller physically prints, packs and hands over;
and from the courier scan on every transition is TikTok's. Ship-by-seller swaps the label and slot for
the seller's own carrier and tracking number in the same call, then adds one more mandatory write —
Update Package Delivery Status, with a 24-hour floor, a 36-hour edit window and a day-13 auto-cancel.
FBT is monitor-only; the ship endpoints refuse it by design. `execution_layer.md` ships a US-shaped
chain into a SEA market — wrong writes, wrong order — and the one guard that matters at volume,
"never ship while a cancellation is pending", is absent entirely.
