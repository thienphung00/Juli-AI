# ADR-107: Card journey log — one append-only record per recommendation, a pre-registered measurement plan, and pooled effects per change type

**Status:** Proposed
**Date:** 2026-10-07
**Deciders:** grill-with-docs (Architect) with the owner, eight questions.

**Amends:** [ADR-077](077-incremental-impact-measurement.md) decisions 2 and 4 (the post
window becomes a pre-registered 14 or 28 days; per-card outcome buckets come from a
significance test with a minimum sample, replacing the Cao / Trung bình / Thấp heuristic as the
*judgement* of a card — the heuristic tier stays as seller-facing copy);
[ADR-106](106-optimize-product-outcome-labels-and-stage-diagnosis.md) decision 3 (a product
whose card is on a 28-day plan stays out of the diagnosis queue for 28 days).
**Builds on:** the outcome chain and its four separate metrics (`CONTEXT.md`); ADR-038 /
ADR-087 emission budget and card revisions (unchanged); ADR-106 Amendments 3–5 (card statuses,
owner tests, Seller Center cards, traffic-source check).
**Scope:** every agent workflow. Optimize Product is the first writer.

## Context

Cards are now produced for real shops (Fujiwa, 2026-10-06/07), with five statuses — Juli tự đề
xuất, Cần mức giảm giá tối đa, Thử nghiệm theo kế hoạch của bạn, Bạn tự làm trên Seller Center,
Chưa hỏi TikTok. The owner's question is which recommendations are accepted, which stall at the
suggestion, and which actually move the metric, so the rules can be improved.

What exists: `action_cards` (`approved_at`, `dismissed_at`, `suppressed_reason`, revision chain),
`workflow_runs.stop_reason`, `run_confirmations`, `tool_executions`, `impact_readings`. What is
missing: a frozen record of *what the seller was shown*, the reason a card was dismissed, an
expiry, the "I did it" signal for Seller Center cards, and a measurement that can tell a real
effect from noise.

Sample size is the binding constraint. On Fujiwa's order sample (80 % power, α = 5 %): the
smallest AOV change detectable in 14 days is 14 % (450 mL, ~145 orders), 23 % (300 mL), 27 %
(1250 mL), 32 % (680 mL) and 137 % (Hydrogen, ~6 orders). A 30 % CTOR lift at a 5 % baseline needs
~3.800 clicks ≈ 190 orders per window; no Fujiwa product reaches that on the product-card
channel in 14 days. A single listing cannot be A/B-split on TikTok (one version is shown to
everyone), so measurement stays pre/post against correlated controls (ADR-077) with A/B-grade
sample discipline added on top.

## Decisions

1. **Storage: a new append-only Postgres table `card_events`**, joined to `action_cards` by
   `card_id` and to `shops` by `shop_id`. Rows are never updated. *Rejected:* reusing
   `workflow_run_events` (dismiss and expiry happen before any run exists); an external product
   analytics tool (splits the funnel from `impact_readings`, adds a data processor). Shop
   attributes are not copied into events; they are joined. An OLTP/OLAP split (e.g. a gold
   `card_journeys` table in the ADR-046 medallion) is deferred until volume needs it.

2. **Stages.** A card is always at exactly one stage, derived from its events:
   1 *Đề xuất* → 2a *Chấp nhận* | 2b *Bỏ qua* | 2c *Hết hạn* → 3a *Đã thực hiện* | 3b *Không thực
   hiện được* → 4 *Kết quả sơ bộ (T+7)* → 5 *Kết quả chốt (end of plan)*. View/open tracking
   was considered and dropped by the owner as unnecessary for the question being asked.

3. **The `proposed` event freezes what the seller saw.** Common fields for every workflow:
   `shop_id`, `workflow_key`, subject type + id + display name, Main KPI name and value at
   proposal, the exact Lý do text and its kind (shop median / own trend / owner test / Seller
   Center / pending), the exact Thay đổi đề xuất text and a `change_kind` (e.g. `cover_image`,
   `title`, `description`, `product_discount`, `flash_sale`, `shipping_discount`, `bmsm`,
   `gift`, `review_voucher`, `bundle_deal`, `min_spend_voucher`), the card status kind, and the
   rule version (ADR + amendment, config hash). A `workflow_details` JSON holds the
   workflow's own fields (Optimize Product: label, branch, gaps, evidence source, traffic
   verdict, BMSM threshold, discount depth). Rejected: adding columns to `action_cards` — that
   table serves the live surface and is superseded by revisions, so it cannot hold history.

4. **Expiry: 7 days.** A card at stage 1 with no approve or dismiss for 7 days gets an
   `expired` event (2c). The same 7 days applies to a Seller Center card's "Tôi đã làm" signal.
   Expiry does not hide the product: if the gap persists, nightly scoring emits a chained
   successor (ADR-087), and "expired then re-proposed" is itself a reported signal.

5. **Dismiss reasons** — one optional quick choice, shared by every workflow, owner's wording:
   *Sản phẩm này không cần thay đổi* · *Phân tích/gợi ý sai* · *Không hiểu gợi ý (cần tìm hiểu
   thêm)* · *Tôi đã làm việc này rồi* · *Để sau*. No choice → `unspecified`. Never mandatory.

6. **Not-executed groups (3b)** — database and internal reporting only; the seller sees only
   "Không thực hiện được". The original code is kept on the event; the group is derived:

   | Group | Codes (extend per workflow) |
   |---|---|
   | `seller_declined_confirmation` | `declined`, `confirmation_declined` |
   | `confirmation_expired` | `confirmation_expired` |
   | `tiktok_rejected` | `price_lever_locked`, `aov_lever_locked`, `audit_rejected`, vendor write errors |
   | `shop_precondition_missing` | `discount_cap_unset`, `scope_unavailable`, unconfirmed violation points |
   | `nothing_to_change` | `no_diagnosis_codes`, `concluded_without_changes` |
   | `system_error` | `tool_error_unrecoverable`, `llm_error`, `wall_clock_timeout`, other technical stops |

7. **Measurement plan, pre-registered at proposal.** At proposal Juli computes, from the
   product's last-30-day volume and its own order-value (AOV) or click/order (CTOR) variability,
   the minimum detectable effect (MDE) at α = 5 %, power = 80 %:
   - MDE ≤ 30 % with 14 days of post data → **14-day plan**;
   - else MDE ≤ 30 % with 28 days → **28-day plan**;
   - else → **"khó kết luận"**: the card may still be proposed, the seller sees that this
     product's own result will be hard to conclude, and the card contributes only to pooled
     effects.
   The plan (`planned_days`, expected sample, required sample, MDE) is stored on the `proposed`
   event and shown on the card as "Kết quả sau 14 / 28 ngày". It is never extended after data
   is seen (no peeking). T+7 stays a preliminary, display-only reading; the final reading is at
   the end of the plan. The product is locked from other cards for the plan's length. All three
   numbers (30 %, 5 %, 80 %) are config.

   **Per-card buckets** at the final reading (incremental effect vs the ADR-077 control
   counterfactual, tested at α = 5 %): *Tăng* (significant positive) · *Giảm* (significant
   negative) · *Không đổi* (adequate sample, not significant) · *Không đo được* (plan was
   "khó kết luận", sample not reached, or the reading is `suppressed` / `confounded`).

   **Pooled effect per change type.** The rule's success is judged per
   (`workflow_key`, `change_kind`, metric), not per card: per-card effects (log-ratio vs own
   counterfactual) are combined by inverse-variance weighting; raw clicks or orders are never
   summed across products. A pooled conclusion is reported only when the pooled sample reaches
   the required sample for a 30 % MDE; before that the change type reads "đang tích lũy dữ
   liệu" with its card count. Owner tests and Seller Center cards are bucketed the same way but
   excluded from the rule's pooled success rate.

   **CTR cards must pass the traffic-chain check to enter a pool** (else flagged and excluded,
   with the reason counted): impressions by channel and channel-mix shift; dilution verdict
   (ADR-106 Amendment 4); a shop promotion starting or ending in the window; platform-discount
   share shift on orders; price change or stock-out days; new LIVE sessions or affiliate videos
   tagging the product. Two blind spots are stated in every review: search vs recommendation
   inside the product-card block (A-34 does not split them) and ads / GMV Max (Business API not
   held).

8. **Internal review, no generated page.** Audience: Juli's product and engineering team; the
   seller already sees each card's stage and readings on the card. The information lives as
   database views that the team queries, not as an auto-written HTML report:
   - `card_journeys` — one row per card: frozen proposal fields, current stage, timestamp and
     outcome of every stage, measurement plan, final bucket, pool eligibility and exclusion reason;
   - `card_funnel_weekly` — counts per stage by ISO week × workflow × change kind × card status;
   - `card_dismissals_weekly` and `card_not_executed_weekly` — reason / group distributions;
   - `change_kind_pooled_effects` — pooled estimate, 95 % interval, clean / excluded card counts;
   - `card_review_flags` — change kinds with acceptance < 30 %, *Phân tích/gợi ý sai* > 20 % of
     dismissals, or a significant negative pooled effect (thresholds are config).

## Consequences

- **Schema:** `card_events(id, card_id → action_cards, shop_id → shops, workflow_key,
  event_type, actor ∈ {seller, juli, tiktok, system}, occurred_at, payload jsonb,
  schema_version)`; event types `proposed`, `approved`, `dismissed`, `expired`, `seller_done`,
  `executed`, `not_executed`, `reading_preliminary`, `reading_final`, `superseded`; unique on
  (`card_id`, `event_type`) for single-occurrence types; indexes on (`shop_id`, `workflow_key`,
  `occurred_at`) and (`card_id`, `occurred_at`); RLS `tenant_direct` like `action_cards`.
  Existing tables are unchanged and are the source for stages 2a, 3a/3b, 4, 5 — events are
  written alongside, not instead (no double source of truth: the view reconciles both).
- **Writers:** card emission (`proposed`), approve / dismiss routes (`approved`, `dismissed` with
  reason), a daily expiry sweep (`expired`), a "Tôi đã làm" action on Seller Center cards
  (`seller_done` + start date), the run terminal path (`executed` / `not_executed` with code and
  group), the impact reader (`reading_*` with estimate, SE, bucket).
- **UI:** dismiss sheet with the five reasons; "Tôi đã làm" button with a date on Seller Center
  cards; "Kết quả sau 14 / 28 ngày" or "khó kết luận" on every card; seller-facing failure text
  is only "Không thực hiện được".
- **Impact reader:** reads the plan from the `proposed` event; computes the effect's standard
  error (CTOR from daily clicks/orders, AOV from per-order values in creation-time windows);
  writes the bucket. ADR-077's heuristic tier remains the seller copy.
- **Cycle:** ADR-106 decision 3 becomes "out of the queue until the final reading of the plan".
- **Out of scope:** card view/open tracking; seller-facing weekly reports; OLAP store.
