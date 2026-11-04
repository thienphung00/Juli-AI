# P91 — every card for every aspect, versions to compare, manual offers, card codes

Owner decisions, 2026-11-04 (after P90 shipped as `fasttrack-deploy-20261104T0109Z`). Builds on P90
(`p90-metrics.md`, `p90-plan.md`, ADR-120 / ADR-121). UI is drawn first and approved by the owner before it
is built (same rule as P90).

## D-1 All cards, all aspects, kept (no "phương án khác")
- The generators already propose cards per product across families (listing, ads, promotion, voucher, sale,
  combo, affiliate). Every eligible card is now **persisted** — ranking no longer drops a card because its
  product already has a better one.
- `duplicate_product` stops being a drop filter. It becomes the per-product queue: each open card gets
  `product_queue` = 1, 2, 3 … among the open cards of the same product (best score first). The other hard
  filters (`locked_by_plan`, `out_of_stock`, `below_operating_floor`, `over_spend_cap`,
  `negative_profit_p50`) still drop.
- **Sản phẩm (product page)** shows every open card of that product, grouped by family, each with its versions.
- **Quyết định stays one card per product**: the card with `product_queue = 1`.
- **Replacement when a card closes**: when the product's Quyết định card closes, the next open card of that
  product moves up (re-numbered queue, the new #1 appears in Quyết định). Closed =
  `dismissed` / `withdrawn` / `expired` / `superseded` at once; `executed` closes for the queue only when its
  measurement window ends (the ADR-077 reading is in, or the window's end date passed), so two changes of one
  product are never measured in the same window (contract 11). Approving a card supersedes nothing else; the
  other open cards of that product wait in the queue.
- No "phương án khác" label anywhere.

## D-2 Versions inside a card (comparison)
- Every card carries **2–4 versions**: `versions[]`, each a full evaluation of the same change with other inputs
  (e.g. voucher 10k / 15k / 20k with its min spend; combo tier 5 % / 10 % / fixed price; ads budget −20 % /
  +20 % / +50 %; title A / B). Version 1 = the engine's default (the ranked one). Each version has the same
  payload as a card today (five numbers before → after, Δ profit P50 and range, margin, AOV, cost, floor breaches,
  spend check, certain vs predicted layers).
- The generator picks the alternative inputs per change_kind from the kind's sliders (`kinds.py`); a version that
  is refused or breaches the floor is still shown, marked, never ranked.
- The seller approves **one version**; `chosen_version` is recorded on the decision and in the card events.
  What-if on a version updates that version only.

## D-3 Manual offers and comparison ("Tự tạo phương án", "So sánh phương án")
- `POST …/recommendations/compare` (Ops Xem+ and Demo seller; saves nothing): 2–4 variants, each
  `{change_kind, items, extra (addon_item, gift_item, pair items), inputs}` → the same `build_card` output per
  variant, side by side, plus the deltas between them (profit, margin, AOV, orders, GMV, cost).
- `POST …/recommendations/manual` (Ops Vận hành and Demo seller): saves one variant (or a compare's chosen one)
  as a card with `origin = "manual"`, `created_by` (staff or seller user id), its own versions if more than one
  variant was sent. It enters the product's queue at its score; if the creator asks `primary = true`, it takes
  `product_queue = 1` and the previous #1 moves to 2. Approve / Đã làm / verification / learning work unchanged;
  learning statistics keep `origin` so manual and engine cards are calibrated and reported separately.
- **Combo calculator widened** (existing `eval_bundle` / `eval_add_on` / `eval_gift` reused):
  - a combo of **2–3 different products** (each with qty), not only tiers of one product;
  - discount as **% / amount (đ) / fixed combo price (đ)**;
  - optional **stacked voucher** (existing voucher rule) and optional **gift item** (cost = giá vốn + đóng gói);
  - per combo: buyer pays, fees (per-order fees once, split by value), contribution, margin, AOV, floor check per
    SKU in the combo, cost per combo order, break-even extra combo orders; predicted range via the lift model
    (`combo_pack`).

## D-4 Titles: 100 characters
- `MAX_TITLE_CHARS = 100` for Shopee title cards (was 120). Every title a card proposes — rule-based today, an
  LLM writer later — is cut to 100 at a word boundary and refused above 100; the manual/what-if title input is
  refused above 100 (422). The LLM writer, when added, gets the 100 limit in its prompt AND the same hard check.

## D-5 Card codes (for the future Excel export)
- Every card gets a **human-readable code**, unique per shop and never reused: `JC-<yymm>-<seq4>` (e.g.
  `JC-2611-0007`, sequence per shop across months) assigned when the card is first persisted; versions are
  `JC-2611-0007-V1` … `-V4`; a card that replaces another through re-generation keeps `supersedes` → the old code.
  The UUID stays the primary key; the code is shown on the card (Demo and Ops) and carried in events.
- New migration 116: `shop_proposals.code` (unique per shop) + a per-shop counter; backfill existing Shopee cards.
- Export itself is a later step; the code, versions, chosen version, inputs before/after, status history
  (`card_events`) and verification result must all be readable by card code so the export is one query.

## Waves
1. Backend core (D-1, D-2, D-4, D-5) ‖ Backend manual + compare + combo (D-3) ‖ Design artboards. Parallel; file
   ownership below.
2. Owner approves the artboards.
3. Frontend Demo + Ops ‖ integration tests on ORY data. Then one deploy.

File ownership in wave 1 (no agent edits another's files; the orchestrator integrates):
- Core: `ranking.py`, `service.py`, `store.py`, `config.py`, `generators.py`, `listing.py`, `cards.py`,
  `models/shop_proposals.py`, migration 116, existing reco routes, their tests.
- Manual: new `manual.py`, `combo.py` (calculator), `evaluate.py` additions only as new functions, new route files
  `ops_shopee_reco_manual.py`, `demo_shopee_reco_manual.py` (+ router registration lines), their tests.
- Design: `docs/product/design/shopee-shop/` only.
- Bookkeeping (`DECISIONS.md`, `PROGRESS.md`, `LOG.md`, this file): orchestrator only.
