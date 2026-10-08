# ADR-109: The Demo app follows the sales demo video — Analysis splits into Sản phẩm and Nội dung, every metric cell opens a GMV-attributed ranking

**Status:** Proposed (grill in progress — decisions 6+ open)
**Date:** 2026-10-08
**Deciders:** grill session, owner + Claude (Opus).

**Builds on:** [ADR-108](108-shop-diagnosis-report.md) (channel split, per-channel funnel,
log-share contributions, confidence labels, Vietnamese-only wording);
[ADR-106](106-optimize-product-outcome-labels-and-stage-diagnosis.md) (funnel identity
GMV = Lượt hiển thị sản phẩm × CTR × CTOR × AOV (SKU), A-34 channel blocks); fast-track
decisions D21 (the demo becomes the product) and D22 (recoverable-GMV ranking for cards).
**Amends:** D21's UI source: the visual reference is the sales demo video
(`juli-content-engine/projects/sales-demo-01`, `screens/index.html`, master cut 0:57 for the
analysis drill-down), with tokens from `docs/product/design/colors_and_type.css`.
**Does not change:** what the backend computes for ADR-108 reports or ADR-106 cards, write
policy (D13), or the Quyết định card ranking (D22).

## Context

After P7 the demo app shows real cards and the ADR-108 report, styled after the app-kit mock
(`docs/product/design/ui_kits/app/index.html`). The owner's sales calls now use a demo video
whose screens show a different, more legible product: a left rail, a five-stage header
(Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường), conclusion-style page titles, a 5-stream
matrix on Home, one funnel row per traffic stream with the bottleneck highlighted and a
"✦ Juli gợi ý", and under it a ranked table of the SKUs dragging the bottleneck down with
TikTok's diagnosis per row. Customers who saw the video should find the same product.

## Decisions

1. **Source of truth.** Layout, navigation and screen components follow the sales demo
   video. Colours, type, radii, shadows and button styles come from
   `colors_and_type.css` (the index.html kit). The two already share one language (white,
   pink accent), so conflicts are about structure, not palette.

2. **Phân tích has two sub-tabs**, each with its two TikTok traffic streams:
   - **Sản phẩm** — Thẻ sản phẩm của người bán + Tab Cửa hàng.
   - **Nội dung** — Video của người bán + LIVE của người bán.

   Order inside each sub-tab, as in the video at 0:57: stream funnels → bottleneck with
   "✦ Juli gợi ý" → ranked table of what drags the clicked metric → detail panel for one
   row. Liên kết (affiliate) is not a sub-tab: it appears on Home, greyed, "chỉ theo dõi"
   (ADR-108: affiliate is for understanding the shop only).

3. **The rest of the ADR-108 report.**
   - **Home** shows the 5-stream matrix (Lượt hiển thị sản phẩm / CTR / CTOR / AOV per
     stream, green/red cells, Liên kết greyed) under GMV / Đơn / AOV cards.
   - **Khuyến mãi** (flash sale coverage and true depth, vouchers) and the **event
     timeline** sit in the Sản phẩm sub-tab under the ranking, **collapsed by default**
     with "Xem thêm".
   - **Hero-product profiles** are a list; each row **expands in place** to the full
     5-channel profile.

4. **Every metric cell is a button that re-ranks the table.**
   - Sản phẩm: Lượt hiển thị sản phẩm, CTR, CTOR and AOV are clickable on both streams. The
     CTOR cell is wider and carries its two steps, Tỷ lệ thêm vào giỏ hàng and đơn/thêm giỏ.
   - Nội dung (checked against TikTok Academy VN, "Cẩm nang lưu lượng LIVE"):
     - **Video** — Lượt hiển thị sản phẩm and CTR clickable; the table ranks individual
       videos.
     - **LIVE** — Lượt hiển thị sản phẩm, CTR and **CTOR** clickable (TikTok's CTOR levers
       for LIVE are host actions: urgency, limited stock, limited offers); the table ranks
       LIVE sessions.
     - Video CTOR and AOV on both content streams are shown, not clickable, with
       "phụ thuộc sản phẩm → xem tab Sản phẩm": after a click the buyer is on the product
       page, and AOV is set by which products are pinned, their price and bundles.

5. **Ranking = GMV/day each row's change in the clicked metric moved.**
   - Per row (product, video or LIVE session) within the stream, GMV/day over the last 30
     vs the prior 30 days is split across the four factors with ADR-108's log-share
     (`ΔGMV × ln(f₁/f₀) ÷ ln(GMV₁/GMV₀)`). When a side is zero, use sequential substitution
     in the order Hiển thị → CTR → CTOR → AOV with later factors at prior values (exact,
     defined at zero); a missing prior rate takes the stream's prior median.
   - Default view "Kéo xuống" (largest negative first), toggle "Kéo lên".
   - Rows are labelled with ADR-108's confidence rules on the quantity behind the clicked
     metric: lượt hiển thị for Hiển thị (**floor 1,000 per window**), lượt bấm for CTR,
     đơn hàng SKU for CTOR and AOV. Rõ first, then Tham khảo; below 10 on both sides →
     not listed individually.
   - At most 10 listed rows; rows under 1 % of the stream's change are folded.
   - Three closing rows make the table add up to the cell's GMV figure: **N sản phẩm ít
     đơn**, **Các sản phẩm khác**, **Thay đổi cơ cấu sản phẩm** (stream factor minus the sum
     of row factors — the mix effect).

6. **Quyết định** keeps D22: cards focus on hero products and the largest GMV gain from
   improving a metric. (Screen layout: open, see below.)

7. **Navigation.** Desktop: left rail Trang chủ / Quyết định / Phân tích / **Juli**.
   Mobile (< 768 px): bottom bar with the same four. **Juli** (24-hour activity log and the
   daily loop) is **shown but locked** in this phase — visible, not navigable, labelled as
   coming. Cài đặt (connect shop, switch shop, sign out) moves into the shop-avatar menu in
   the header. The header carries the shop avatar, name, "TikTok Shop · ngành · N SKU" and
   "Juli đang chạy · cập nhật HH:MM" from the last sync.

## Open (next grill questions)

- The five-stage header stepper: what it means in the product (shop's daily cycle vs one
  card's state vs video only).
- Quyết định layout: grouped cards per bottleneck with one target and "Duyệt N thẻ"
  (video) vs per-card approve; run view as the video's step timeline + queue.
- Đo lường / Kết quả screen (before → after, hours saved) while P6 is not built.

## Consequences

- **Backend work.** Decision 5 needs per-product, per-channel daily metrics for the whole
  catalogue (A-34 channel blocks), not only the five hero profiles of ADR-108 nor the
  all-channel ADR-106 diagnosis; and per-video / per-LIVE-session impressions, CTR and CTOR.
  Whether the current fetch has these per video and per session is to be verified before
  building.
- The ranking and the card ranking share one unit (₫/day), so a row in Phân tích and a card in
  Quyết định can be compared directly.
- e2e specs that pin the bottom bar on desktop and the Cài đặt destination change again.
