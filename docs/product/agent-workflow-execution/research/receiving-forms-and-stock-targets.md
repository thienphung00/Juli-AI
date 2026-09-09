# Q9 receiving / Q10 stock goals — scout report (2026-09-05)

## Q9 — attested ordered/received without a supplier API

### Shopify PO + inventory transfer [DOCUMENTED]
- Mechanism: PO records the commercial agreement; a *linked inventory transfer* handles shipment + receiving. Stock changes ONLY on receive-acceptance, never at PO creation.
- Inputs per line: Receive action (Accept / Reject / Cancel), Receiving quantity, optional per-line comment; "Accept all"/"Reject all" bulk. A Total column shows units accounted-for vs expected.
- Semantics: Accepted -> available at the destination location. Rejected -> recorded on the transfer, adds to no location's available qty. Multiple shipments received individually. Status stays "In progress" until all quantities accounted, then "Transferred". Negative Accepted corrects an over-receipt and flips status back to Partially received.
- Safety: destination location is chosen on the transfer, not on the receiving row; the receive event is the only stock-writing act; corrections are new signed events, not edits.
- https://help.shopify.com/en/manual/products/inventory/purchase-orders/receiving-inventory

### Amazon FBA inbound [DOCUMENTED]
- Expected (shipped qty in plan) vs received, with a Discrepancy column. Reconciliation *cannot be filed until the shipment is Closed* — no claims against an in-flight count.
- Windows: 60 days lost/damaged, up to 9 months inbound loss; investigation 2-30 days.
- Safety: a settle-point (Closed) before disputes; the count is never "final" mid-receipt.
- https://www.threecolts.com/blog/reconcile-amazon-inbound-shipment-claims/

### KiotViet "phiếu nhập hàng" [DOCUMENTED]
- Fields: supplier search (F4), warehouse/branch chosen at the START of the slip (recorded on the slip and its print template), product lines (qty, unit price, line total), totals/discount/amount-due, payment method, notes; serial/IMEI where applicable.
- Two states: Lưu tạm (draft) vs Hoàn thành (complete). Stock increments only on Hoàn thành.
- https://www.kiotviet.vn/huong-dan-su-dung-kiotviet/huong-dan-nhap-hang/tao-phieu-nhap-hang/
- Multi-warehouse is a separate opt-in feature; marketplace sync is KiotViet -> sàn. https://www.kiotviet.vn/kiotviet-ra-mat-tinh-nang-moi-quan-ly-da-kho/

### Sapo [DOCUMENTED — most directly relevant]
- Sync is UNIDIRECTIONAL Sapo -> marketplace (Shopee/Lazada/TikTok Shop/Tiki). Branch<->marketplace-warehouse linked 1:1 at config time.
- Named failure mode: "Sapo đồng bộ kho thành công, nhưng số lượng trên Shopee khác" — a parallel tool or a direct Seller Center edit overwrites without notification. Resolution is manual: check last-successful-sync timestamp, then reconcile.
- Marketplace-side locks (Flash Sale, promo holds) temporarily REJECT updates — the marketplace wins during those windows.
- Real-time push under ~1000 units; every 8h above.
- https://help.sapo.vn/cac-van-de-thuong-gap-khi-dong-bo-kho-va-gia-giua-sapo-va-san-tmdt

### Sellbrite / Linnworks [DOCUMENTED]
- Sellbrite: one designated hub is source of truth (Shopify when connected). "Always make inventory adjustments in Sellbrite" — adjusting in a channel "can interfere with syncing and can even cause you to oversell". Unlinked listings receive no qty updates (fail-closed).
- Linnworks: overselling = listing shows more than available; unified multi-location view with transfers tracked at every stage (removed / in transit / received).
- https://support.sellbrite.com/en/articles/4723907-how-does-inventory-sync-work
- https://help.linnworks.com/support/solutions/articles/7000005535-overselling-troubleshooting-

### Borrow / contradiction
Borrow: (1) split ordered vs received exactly as Shopify splits PO vs transfer — only the received form writes stock; (2) accepted + rejected/short as two numbers so a partial receipt is explicit rather than an under-typed accepted; (3) warehouse chosen at slip level (KiotViet) not per row; (4) a Total accounted-for vs expected readout and an explicit not-yet-closed state; (5) corrections as a new receipt event (Shopify negative-accepted), which naturally re-arms a consent hash.
Contradicts / warns: Juli is NOT the source of truth — TikTok Shop is, and Sapo's documented failure is precisely a blind overwrite. A received-form stock write must be a DELTA applied to a freshly re-read marketplace level, with a staleness check and abort-on-drift, never an absolute set from a number computed at form-render time. Marketplace-side locks (flash sale) can reject the write — that must surface as a failed action, not a silent success.
[INFERRED] "Per-warehouse rows only when multi-warehouse" matches KiotViet/Sapo (warehouse is a slip-level selection that disappears for single-warehouse sellers). No source shows always-on per-warehouse rows.
[INFERRED] Expected-date on the ordered form has no direct analogue found beyond Cogsy lead-time learning; it is reasonable but treat as forecast input only, never as anything that writes stock.

## Q10 — stock goal / target input

### TikTok Shop [DOCUMENTED — decisive]
- Per-SKU "Stock alert" toggle; when on, seller configures the alert on EITHER stock quantity OR days of supply ("order volume based on current sales activity"). Bulk-set across selected SKUs. Max 1 notification/day. Email / message center / both. Not available for Pre-Owned & Collectibles.
- https://seller-us.tiktok.com/university/essay?knowledge_id=4186564050126593&lang=en
- Both units are native to the seller's existing mental model — days of supply is already a TikTok concept, so 30/60/90 chips are consistent with the platform.

### Shopee [DOCUMENTED]
- My Products -> More -> Low Stock Reminder -> "Safety Stock" = a QUANTITY only. No days-of-supply option.
- https://seller.shopee.sg/edu/article/756/reducing-late-shipment-non-fulfilment

### Amazon FBA [DOCUMENTED]
- Working band roughly 28 days (low-inventory-fee floor) to ~22 weeks (utilization surcharge ceiling); commentary converges on 30-45 days as the rewarded target. Aged surcharges at 90/181/365 days. IPI gates storage limits (>400 unlimited standard storage).
- Targets are re-proposed continuously by Amazon (Capacity Monitor, Restock Limits tab) — never a one-time seller entry.

### Cogsy / Inventory Planner [DOCUMENTED, partial]
- Cogsy "Target" = units needed to avoid stockout, DERIVED from Order Lead Time + Safety Margin; lead time auto-learned from recent POs with a manual override. So the seller edits the *drivers*, not the target number.
- https://help.cogsy.com/article/qyz1p3dyyc-products-overview

### Preset + custom UX [DOCUMENTED, adjacent domain]
- Donation-form evidence: suggested levels lift the chosen amount ~12%; 3-4 presets plus a clearly visible custom field is the recommended shape; users gravitate to the second-lowest preset. Strong anchoring effect.
- Implication for Juli: 30/60/90 will anchor hard on 60. Order presets so the *safe* value is not the extreme, and keep "other" visually equal, not buried.

### Borrow / contradiction
Borrow: days-of-supply chips are platform-native on TikTok; keep "other" as a first-class numeric; re-propose the goal over time (Amazon/Cogsy both do) rather than treating the first entry as permanent.
Contradicts the plan: validating `0 <= goal < sellable` mixes units. A days-of-cover goal is not comparable to a sellable unit count; the bound only makes sense after converting via velocity, and with zero velocity the conversion is undefined. Also `goal < sellable` forbids the most common real intent — targeting MORE cover than currently held, which is the entire point of replenishment. [INFERRED] The upper bound should be a sanity cap (e.g. <= 180 days / <= some multiple of velocity), not the current sellable level; only a *clearance* target is legitimately bounded below current stock.

## Q-extra — clearance semantics
- Amazon FBA Grade & Resell [DOCUMENTED]: unfulfillable stock is relisted as used under a NEW Amazon-generated SKU, seller on record. Enrollment is a settings-level opt-in with a per-SKU EXCLUSION list and price settings. Storage fees stop accruing at removal-order submission; clocks restart on relist. https://www.spscommerce.com/community/articles/fba-grade-and-resell-program
- Key pattern: clearance is a separate SKU/lane with its own price and its own fee clock — not a flag on the healthy SKU. Exclusions are explicit per-SKU opt-outs.
- Shopee "clearance tag" and TikTok "Sản phẩm thanh lý" as a seller-settable inventory state: NOT FOUND in seller documentation; Vietnamese-language search surfaced only marketing/consumer clearance pages. Treat as unverified.
- Juli read: a checklist-item approach is directionally fine, but Amazon's evidence says clearance changes economics and identity, not just alerting. At minimum a clearance-marked item should be excluded from restock proposals and from low-stock alerting, and its goal validated as a drawdown target (goal < current) — the one case where the `< sellable` bound is right.
