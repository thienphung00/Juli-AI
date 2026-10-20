# ADR-107: Card journey log — one append-only record per recommendation, a pre-registered measurement plan, and pooled effects per change type

**Status:** Accepted (owner, 2026-10-20, grill D70.9 / D70.11) — amended
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
   was considered and dropped by the owner as unnecessary for the question being asked
   (superseded by the 2026-10-20 amendment §1: a `shown` event records first display; opens
   and clicks stay untracked).

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
   "khó kết luận", sample not reached, or the reading is `suppressed` / `confounded`; a
   `reverted` label is added by the 2026-10-20 amendment §10).

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
  `executed`, `not_executed`, `reading_preliminary`, `reading_final`, `superseded`
  (superseded by the 2026-10-20 amendment §1–§2); unique on
  (`card_id`, `event_type`) for single-occurrence types; indexes on (`shop_id`, `workflow_key`,
  `occurred_at`) and (`card_id`, `occurred_at`); RLS `tenant_direct` like `action_cards`
  (superseded by the 2026-10-20 amendment §2: SELECT / INSERT only).
  Existing tables are unchanged and are the source for stages 2a, 3a/3b, 4, 5 — events are
  written alongside, not instead (no double source of truth: the view reconciles both)
  (superseded by the 2026-10-20 amendment §1 and §5: existing tables keep their role, the views
  read `card_events` only, and history is backfilled into it).
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
- **Out of scope:** card view/open tracking (superseded by the 2026-10-20 amendment §1 for
  first display only); seller-facing weekly reports; OLAP store.

## Amendment 2026-10-20 — grill D9 / D11 (fast-track D70)

**Decided by:** the owner in the data-platform grill (`docs/product/data-platform/GRILL_LOG.md`,
D9 and D11, option A each), cited on this branch as D70.9 and D70.11 (`fasttrack/DECISIONS.md`
D70). **Re-checked against the branch:** `docs/product/data-platform/GAP_MAP_FASTTRACK.md`
(D9 missing; D11 (1), (2), (4) done; (3), (5), (6) partial) and
`docs/product/data-platform/P0_TIKTOK_WEBHOOKS.md`. **Related:** ADR-077 (impact reading, amended
in the same change), ADR-087 (card revisions), ADR-089 (fleet work under tenant isolation),
ADR-101 (fixtures), ADR-109 d.9 (revert), ADR-112 (ingestion platform, D3 readiness levels,
D2 scheduler), ADR-113 (shop data: D4 versions, D6 timeline), ADR-114 (experiments, D10),
ADR-115 (training data and model gate, D12 / D13); fast-track D13 (Juli never reverts a price),
D30.1a / D30.4 (P23 product history and webhooks), P8-C (`run_write_values`, revert).
**Nothing built here is rebuilt:** `run_write_values` (MIG 078), `production_write_audit`
(MIG 047), `external_changes` / `product_snapshots` / `promotion_activities` (MIG 087),
`services/product_history/*`, `services/run_changes/*` stay and are extended.

### Context

ADR-107 was never built. The grill re-opened it for two reasons: the training data (ADR-115)
needs every recommendation frozen with the model, data readiness and features it was made from;
and the action loop needs to know, per field, whether a change on TikTok was Juli's write, the
seller undoing it, or the seller's own change, so an impact reading is not credited to a card
whose change no longer stands. The branch already records Juli's before/after values (P8-C),
re-reads products on webhooks 15/16/18/39/63 (D30.4) and runs a three-way revert check; what is
missing is the card log, content hashes, per-field attribution and a verdict that acts on it.

### D9 — the card log (`card_events`)

1. **Event vocabulary** (`event_type`, CHECK-constrained). Original names are renamed to the
   grill's; the original types the grill did not list are kept.

   | Event | Actor | Single? | Written by |
   |---|---|---|---|
   | `proposed` | juli | yes | card emission (nightly scoring, ADR-087 revisions) |
   | `shown` | system | yes | first time the card enters the seller's visible list (emission budget, `action_cards.surfaced_at`); not opens or clicks |
   | `accepted` (was `approved`) | seller | yes | approve route |
   | `edited` | seller | no | approve route when the seller changed a proposed value (§4) |
   | `dismissed` | seller | yes | dismiss route, `reason_code` ∈ `not_needed`, `wrong_analysis`, `not_understood`, `already_done`, `later`, `unspecified` (the five Vietnamese reasons of decision 5, in order) |
   | `expired` | system | yes | daily sweep, decision 4 (7 days) |
   | `seller_done` | seller | yes | "Tôi đã làm" on Seller Center cards (kept) |
   | `executed` / `not_executed` | juli | yes | run terminal path; `not_executed` keeps code + group (decision 6) |
   | `reverted` | seller / juli | no | a finished revert run (`workflow_runs.reverts_run_id`), §9 |
   | `impact_preliminary` / `impact_final` (were `reading_*`) | system | yes | impact reader / `run_measurement_finals` writer, §10 |
   | `seller_change` | seller | no | attribution (§8); payload `attribution` ∈ `seller_revert`, `seller_change` |
   | `shadow` | juli | no | model shadow run (D13, ADR-115): prediction / recommendation not shown |
   | `superseded` | system | yes | successor revision emitted (ADR-087) |

   The ADR-107 views (`card_journeys`, `card_funnel_weekly`, …) read `card_events` only.
   `action_cards`, `workflow_runs`, `impact_readings`, `run_measurement_finals` keep their live
   roles; their writers also write the event in the same transaction.

2. **Table** (next migration after 094): `card_events(id uuid pk, card_id uuid null →
   action_cards, shop_id uuid → shops, workflow_key, subject_type, subject_id (TikTok product
   id), event_type, actor ∈ {seller, juli, tiktok, system}, occurred_at timestamptz,
   recorded_at timestamptz default now(), source ∈ {live, backfill}, workflow_run_id null →
   workflow_runs, model_version, readiness_level smallint, feature_snapshot_id uuid null →
   gold.ml_feature_snapshots, payload jsonb, schema_version int, dedup_key text)`.
   - `card_id` is NULL only for `seller_change` with no card (a natural action, §10) and
     `shadow` (its id is in `payload.shadow_id`): CHECK
     `card_id IS NOT NULL OR event_type IN ('seller_change','shadow')`.
   - Unique (`shop_id`, `dedup_key`) — every writer and the backfill derive a deterministic
     key, so a retry or a re-run inserts nothing twice (`ON CONFLICT DO NOTHING`). Partial unique
     (`card_id`, `event_type`) WHERE `event_type` is single-occurrence.
   - Indexes: (`shop_id`, `workflow_key`, `occurred_at`), (`card_id`, `occurred_at`),
     (`shop_id`, `subject_id`, `occurred_at`) for the §10 window lookups.
   - Not partitioned: one row per card stage is small next to the D5 tables; ADR-112's
     partition rule applies if it crosses that ADR's size threshold.
   - **RLS append-only**, the MIG 047 / MIG 078 pattern: `GRANT SELECT, INSERT … TO juli_app`
     only; policies `SELECT USING (shop_id = app_current_shop_id())` and
     `INSERT WITH CHECK (shop_id = app_current_shop_id())`; no UPDATE / DELETE grant or policy.
     Fleet writers (expiry sweep, backfill, impact reader, attribution) set the shop context per
     shop as ADR-089 prescribes; nothing writes across tenants. A correction is a new event.

3. **Frozen at proposal** (`proposed` row, CHECK NOT NULL when `source = 'live'`):
   `model_version` (rule path: `rules:<ADR+amendment>:<config_hash>`, the decision 3 rule version;
   model path: the ADR-115 registry id), `readiness_level` (the shop's D3 level 1 / 2 / 3 at that
   moment, from ADR-112's per-shop readiness; level 1 also stores the "sơ bộ" label), and
   `feature_snapshot_id` — one `gold.ml_feature_snapshots` row (MIG 021, RLS MIG 046, no writer
   until now) written in the same transaction with `feature_version` and `snapshot_at ≤
   occurred_at`. Decision 3's fields and decision 7's plan stay in `payload`.

4. **Edit = a diff, not a copy.** `edited.payload = {base_event_id, diff: [{path, from, to}]}`
   against the `proposed` payload's "Thay đổi đề xuất" values; the original stays in `proposed`.
   The run executes the edited values; `executed` references the run, whose `run_write_values`
   rows hold what was actually written. An edited card's readings are tagged `edited = true` and
   pooled separately from unedited ones (the rule did not produce that change).

5. **Backfill of past cards** — one resumable job `card_events_backfill` (per shop, ADR-089
   fan-out, `source = 'backfill'`, deterministic `dedup_key`, so a second run inserts nothing):

   | Event | Reconstructable? | From |
   |---|---|---|
   | `proposed` | yes, text and subject only | `action_cards` row of that revision (revisions are chained rows, never edited in place — ADR-087): `computed_at`/`created_at`, `title`, `description`, `recommendation_payload`, `workflow_key`, subject. `model_version = 'unknown'` unless `metadata_json` carries it; `readiness_level`, `feature_snapshot_id` and the decision 7 plan are NULL — they were never recorded and are not recomputed (no retroactive pre-registration) |
   | `shown` | partly | `action_cards.surfaced_at` (NULL → not written) |
   | `accepted` | yes | `action_cards.approved_at`, `action_card_approvals`, `workflow_runs.action_card_id` |
   | `edited` | no | values the seller changed were never diffed |
   | `dismissed` | yes, reason no | `action_cards.dismissed_at`; `reason_code = 'unspecified'`. `suppressed_reason` is a system suppression, not a dismissal, and is not mapped |
   | `expired` | no | the 7-day rule did not exist; not inferred |
   | `seller_done` | no | never captured |
   | `executed` / `not_executed` | yes | `workflow_run_events` (MIG 035) `workflow.completed` / `workflow.failed` + `workflow_runs.stop_reason` (code → decision 6 group); lever flows use `run_lever_flows.applied_at` as the real apply time |
   | `reverted` | yes | `workflow_runs.reverts_run_id` (MIG 078) of a finished revert run |
   | `impact_preliminary` / `impact_final` | yes | `impact_readings` (MIG 033) by `run_id` and window; `run_measurement_finals` (MIG 080) label for day-14 |
   | `seller_change` | yes, from P23 onward | `external_changes` (MIG 087) with `juli_write = false`, attributed by §8 where `run_write_values` exists (P8-C onward), else `seller_change` |
   | `superseded` | yes | successor's `supersedes_card_id` + its `created_at` |
   | `shadow` | n/a | no model has run |

   Backfilled cards have no pre-registered plan, so they get buckets but never enter pooled
   effects (decision 7); the views show them as `source = backfill`.

### D11 — Juli's writes, changes outside Juli, revert, impact

6. **(1) Before / after already exist — add hashes and the audit link.** `run_write_values`
   (MIG 078, P8-C, `services/run_changes/recorder.py`) already stores `before_value` (read just
   before the write by `live.py`) and `after_value` (`after_source` read_back | intended).
   Next migration after 094 adds `before_hash`, `after_hash` (sha256 of the field's value
   canonicalised by `services/product_history/normalize.py`, the same form `product_snapshots`
   hashes), `before_read_at`, and `production_write_audit_id uuid null → production_write_audit`
   (MIG 047, one audit row per mutation, many field rows to one). Existing rows: hashes are a
   pure function of stored values and are backfilled; the audit link is backfilled by
   (`run_id`, `tiktok_product_id`, `mutation_kind`) when exactly one row matches, else NULL.

7. **(2) Detection — webhooks where TikTok has them, polling for the rest.** Kept as built
   (D30.4 / P23): webhooks 15 (title, description, main images, attributes), 16 (creation),
   18 (category), 39 / 63 (promotion activity) → `services/product_history/webhooks.py`
   (re-read + diff, 60 s coalesce per (shop, subject), dedupe on `tts_notification_id`); the
   `update_time` reconcile and SKU-price comparison in `services/product_history/job.py`;
   `replay.py`. Per `P0_TIKTOK_WEBHOOKS.md` there is **no webhook for price, SKU add / remove,
   seller deactivate / delete or coupons**, so those stay on Search Products
   `update_time_ge = cursor − 10 min` every 15 min plus one daily full reconcile (job.py
   already compares SKU prices because a price change may not move `update_time`); coupons via
   Search Coupon List every 30–60 min (new, ADR-113). A webhook re-read is a targeted fetch in
   ADR-112's priority lane (D2). Open, owner-run on a test shop: does a Seller Center price edit
   fire 15 / `others`; SKU add / remove; deactivate / delete; webhook 50 once its type is fixed.

8. **(3) Per-field attribution.** `external_changes` (MIG 087) gains `attribution` ∈ {`juli`,
   `seller_revert`, `seller_change`, `mixed`} and `field_attribution jsonb {field: label}`;
   `juli_write` stays (= every field `juli`) for existing readers. `store.matches_juli_write`
   (P23) is generalised to `store.attribute_fields`, per field: value hash equals the `after_hash`
   of a Juli write inside the existing 72 h / 1 h window → `juli`; equals the `before_hash` of
   the most recent Juli write on that (product, field), any age → `seller_revert`; otherwise, or a
   field Juli never writes → `seller_change`. `matches_juli_write` becomes `all(label == 'juli')`,
   so its callers do not change. Every non-`juli` field set emits one `seller_change` event,
   `card_id` = the card whose executed run last wrote that field or whose plan window is open on
   the product, else NULL (a natural action).

9. **(4) Revert — kept.** A revert is a new write through the production write authorization
   and `production_write_audit`, planned and executed by `services/run_changes/{live,revert,planner}.py`
   with the existing three-way check (live value = Juli's after → write the before; = before →
   already reverted, skip; anything else → stop and ask, `run_revert_questions`). The check now
   compares §6 hashes; behaviour is unchanged, including fast-track D13 (prices are never
   reverted by Juli) and the Seller Center refusal. A finished revert writes `reverted` on the
   original card.

10. **(5) Impact — cut at the revert or edit date.** Extends ADR-077 (see its 2026-10-20
    amendment). `services/product_history/overlap.py` today only annotates; it gains
    `measurement_cut(run, window) → (cut_date | None, label | None)` which the impact reader and
    the `run_measurement_finals` writer apply before computing the verdict:
    - a `reverted` event, or a `seller_revert` on a field the run wrote, inside the post window →
      post window ends the day before; label `reverted`;
    - a `seller_change` on the product, another Juli run (ADR-077's existing rule), or a
      promotion / price change from §11 inside the pre or post window → cut at that date; label
      `confounded`.
    A cut reading with fewer post days than the plan is bucketed *Không đo được*; a labelled
    reading is never pooled. Control: ADR-114 randomized control when the product is in an
    experiment assignment, else ADR-077's DiD. **Natural actions:** `seller_change` events with
    no card are measured by the same reader as pseudo-cards (`workflow_key = 'natural'`,
    `change_kind` from the field), reported in a `natural_action_effects` view, never in a
    rule's pool.

11. **(6) Promotions and price through the D6 timeline.** Promotion start / end / product-list
    changes come from `promotion_activities` (MIG 087, `services/product_history/promotions.py`,
    webhooks 39 / 63) and the ADR-113 timeline; price from SKU-price diffs between
    `product_snapshots`. They are attributed like §8 (a promotion Juli created through
    `run_lever_flows`, or a Seller Center card with `seller_done`, is `juli`; anything else is the
    seller's) and feed §10's `confounded` rule.

### Consequences

- **Positive:** one record per recommendation from proposal to final reading, with the model,
  readiness and features frozen — the training rows ADR-115 needs; a reading is no longer
  credited to a change that was undone; seller changes become measurable natural actions.
- **Negative:** every card writer now writes twice (row + event) in one transaction; the
  backfill leaves old cards without plans, so pooled effects start empty; `external_changes`
  attribution depends on poll freshness for price / SKU (up to 15 min late).
- **Follow-ups (P60 / grill P1, P6):** migration + writers + backfill (P1.1); hashes + audit
  link + attribution + `seller_change` events (P1.2); `gold.ml_feature_snapshots` writer (P1.5);
  `measurement_cut` and natural-action view (P6); dismiss sheet sends `reason_code`.

### Alternatives considered

- Reuse `workflow_run_events` (dismiss and expiry happen before a run exists) — rejected, as in
  decision 1.
- Keep run-level `juli_write` boolean only — rejected: a run writing title + image where the
  seller reverts only the image would read as fully Juli's.
- Annotate overlaps and leave the verdict alone (today's `overlap.py`) — rejected: pooled
  effects would count reverted changes.
- Poll-only detection — rejected where webhooks exist (15/16/18/39/63 are near real time);
  webhook-only — impossible for price, SKU, delete, coupons.

### Verification

D15 layers: (2) real Postgres, not marked `migration_heavy`, so they run at issue tier —
`card_events` two-tenant RLS (ADR-089 pattern: tenant B can neither read nor insert tenant A's
rows), `juli_app` UPDATE / DELETE denied, partial unique and CHECK constraints, backfill run twice
= same row count, attribution per field (`juli` / `seller_revert` / `seller_change` / `mixed`) on
seeded `run_write_values` + `external_changes`, the three-way revert check on hashes,
`measurement_cut` labels; (1) webhook 15/63 fixtures (ADR-101) replayed through the re-read path
give the same `external_changes`; (6) leakage: every live `proposed` row's
`feature_snapshot_id.snapshot_at ≤ occurred_at`. Contract test: the five dismiss reasons in the
UI map one-to-one to `reason_code`.
