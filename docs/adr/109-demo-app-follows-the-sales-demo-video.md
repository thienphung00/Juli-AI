# ADR-109: The Demo app follows the sales demo video — Analysis splits into Sản phẩm and Nội dung, every metric cell opens a GMV-attributed ranking

**Status:** Proposed
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
   - **Videos and LIVE sessions are new rows, not the same row in two windows.** A video or
     session has no "prior 30 days" of its own, so its effect on a metric is measured
     against the stream's prior-window rate: e.g. a session's CTOR effect =
     its clicks/day × (its CTOR − LIVE CTOR in the prior 30 days) × prior AOV. Rows sum to
     the stream's change through the same closing rows (decision 5).
   - Three closing rows make the table add up to the cell's GMV figure: **N sản phẩm ít
     đơn**, **Các sản phẩm khác**, **Thay đổi cơ cấu sản phẩm** (stream factor minus the sum
     of row factors — the mix effect).

6. **Quyết định** keeps D22: cards focus on hero products and the largest GMV gain from
   improving a metric. Layout as the video's P2 screen:
   - Cards are **grouped by stream and weak stage** ("N thẻ tối ưu để nâng CTOR Thẻ sản
     phẩm"). The group header shows the target (current → target rate, the sum of its
     cards) and "GMV dự kiến" per month from D22's recoverable GMV/day × 30.
   - Each compact card: product code + name, "KPI chính", Lý do, Mã TikTok (diagnosis),
     Đòn bẩy, and the concrete change.
   - **"Duyệt N thẻ"** approves the group and creates N runs that execute **one after
     another** (the video's "Hàng chờ thẻ tối ưu"), never two changes on one product at
     once. Single cards can still be approved or dropped.

7. **Navigation.** Desktop: left rail Trang chủ / Quyết định / Phân tích / **Juli**.
   Mobile (< 768 px): bottom bar with the same four. **Juli** (24-hour activity log and the
   daily loop) is **shown but locked** in this phase — visible, not navigable, labelled as
   coming. Cài đặt (connect shop, switch shop, sign out) moves into the shop-avatar menu in
   the header. The header carries the shop avatar, name, "TikTok Shop · ngành · N SKU" and
   "Juli đang chạy · cập nhật HH:MM" from the last sync.

8. **Five-stage stepper** (Phân tích → Đề xuất → Duyệt → Thực thi → Đo lường) lives **inside
   Quyết định only**, on a card group or a run, and shows **that card's / run's own
   state**. It is not in the global header.

9. **Quyết định keeps the agent-workflow-execution run model** ([PUI-DESIGN](../product/agent-workflow-execution/PUI-DESIGN.md)):
   every approved card is a real `workflow_run` with the staged run view, the run ledger
   (Đang chờ bạn / Đang chạy / Hoàn tất), honest terminal states and a frozen replay of each
   finished run. "Duyệt N thẻ" queues N runs; each run still pauses at its Đề xuất stage for
   the two-step consent before any write (P7 AC-7.4). **Every action is tracked and
   undoable:**
   - Each write records the field's value **before** and **after** (title, description,
     attributes, image) on the run.
   - A finished run that wrote something offers **"Hoàn tác"**: a new run that restores
     the before-values, with the same consent step. A revert is itself tracked.
   - If the seller or someone else changed the field after Juli's write, Hoàn tác refuses
     and says so (S-FR-8: Juli does not overwrite an external change).

10. **Price stays recommendation-only (D13).** A price card appears in its group with
    "Bạn áp dụng trên Seller Center"; "Duyệt N thẻ" runs only the executable cards (title,
    description, attributes, image).

11. **Stability guardrail is the seller's number.** Before the first group runs, Juli asks
    the seller the allowed swing for the metrics a change is not meant to move (Lượt hiển thị
    sản phẩm, CTR, AOV…; suggested ±3 %). After a change, when a metric leaves that band at
    the day-7 check-in (D14), Juli **asks whether to undo** (decision 9's Hoàn tác) — it
    never undoes on its own.

12. **Seller-set rules.** Everything in the video's "Quy tắc do bạn đặt" is set by the seller,
    not chosen by Juli. The rule set Juli needs (stored per shop, each with who set it and
    when):

    | Rule | Used by | Default until set |
    |---|---|---|
    | Ngưỡng giữ ổn định per metric (±%) | decision 11, day-7 check-in | ask before first run |
    | Giá vốn per product (or CSV) | gross-margin ranking (D18), price cards | revenue ranking; price cards hidden |
    | Biên lợi nhuận tối thiểu (%) | price recommendations | no price recommendation |
    | Trần giảm giá per SKU (%) | price recommendations | no price recommendation |
    | Số thẻ mở cùng lúc (≤ 5) | emission budget | 5 |
    | Đòn bẩy được phép tự thực thi (title / description / attributes / image) | run executor | all listing levers; price never (D13) |
    | Từ / thông tin không được sửa (brand terms, claims) | listing writes | none |

    **Operator phase first:** at the start the Juli team fills these inputs on the seller's
    behalf and tests the system with them; each value records that it was set by the team.
    Handing over to the seller is a later step (the same screen, the seller's own login).

13. **Quyết định has three sub-tabs: Đề xuất, Đang thực hiện, Đo lường.**
    - **Đề xuất** — the grouped cards of decision 6.
    - **Đang thực hiện** — the video's execution screen (master cut 1:23), **UI only on the
      existing agent-workflow-execution backend** (runs, SSE event stream, confirmations,
      replay — no backend change for this view). Left: the selected run as a vertical step
      timeline with timestamps (done ✓ / current / upcoming greyed), each step's one-line
      result from the run's events, the consent step inline. Right: "Hàng chờ thẻ tối ưu" —
      the queue with each run's status. The ledger's sections stay: **Đang chờ bạn / Đang
      chạy / Hoàn tất**, with honest terminal states and replay of finished runs.
    - **The timeline is driven only by the run's SSE stream** (`GET /v1/demo/runs/{id}/events`,
      envelope `{workflow_run_id, sequence_number, event_type, timestamp, payload}`), reusing
      `use-run-stream.ts` / `reduce-run-view.ts`; finished runs use the replay endpoint. Each
      step's time is the event `timestamp`; its one-line result is `tool.completed.summary`
      (or `workflow.status.phase_narration` / `assistant.text`). Nothing is invented
      client-side. Mapping of the video's steps to the Optimize Product playbook:

      | Video step | SSE source |
      |---|---|
      | Đọc thông tin / chẩn đoán | `tool.started` / `tool.completed` for `get_product_information` (no TikTok-diagnosis tool exists in the playbook yet) |
      | Phân tích từ khoá, ảnh | `tool.*` for `get_seo_keywords`, `inspect_product_image` |
      | Xác nhận một lần | `workflow.approval_required` → confirmation POST → `workflow.status` |
      | Ghi lên TikTok Shop | `tool.*` for `update_product_listing` / `upload_product_image` |
      | TikTok duyệt lại trang sản phẩm | `tool.*` for `check_product_status` |
      | Kết thúc · đặt lịch đo | `workflow.completed` / `workflow.failed`; day 7 / day 14 dates computed from the completion timestamp by the D14 rule |

      The queue on the right is `GET /v1/demo/runs` (status per run).

    - **Đo lường** — one row per executed run: the product's metrics before → after against
      the expected outcome; before day 7 it says "Đang chờ đủ 7 ngày dữ liệu · đo lúc
      DD/MM" (no invented numbers). Day-7 guardrail breaches (decision 11) surface here
      with the "Hoàn tác?" question. "Giờ nhân sự lấy lại" is **not shown** until it can be
      measured. Readings come from P6.

## Consequences

- **Backend work.** Decision 5 needs per-product, per-channel daily metrics for the whole
  catalogue (A-34 channel blocks), not only the five hero profiles of ADR-108 nor the
  all-channel ADR-106 diagnosis; and per-video / per-LIVE-session impressions, CTR and CTOR.
  Checked on the Fujiwa snapshot (2026-10-06):
  - **Products:** 60 daily A-34 files with channel blocks → per-product, per-channel
    30 vs 30 is computable for the whole catalogue.
  - **LIVE:** each session has product impressions, product clicks, CTR, CTOR (SKU),
    SKU orders and GMV, with start time → complete.
  - **Video:** the list carries views, CTR, SKU orders and GMV **since posting**; per
    video × product detail has product impressions and clicks, but not split by the two
    30-day windows. Needs a date-ranged per-video fetch (to verify against the API), or
    videos posted inside each window only.
- The ranking and the card ranking share one unit (₫/day), so a row in Phân tích and a card in
  Quyết định can be compared directly.
- e2e specs that pin the bottom bar on desktop and the Cài đặt destination change again.
- Decision 13's Đang thực hiện is UI-only. Decision 9's before/after values and the
  Hoàn tác run are the one addition to that backend.
- **New backend work for decisions 9–12:** before/after values on every write, a revert
  run, a per-shop rule store with set-by/set-at (team vs seller), a guardrail check at the
  day-7 reading that raises an "undo?" question, and a rules screen usable by the team.
