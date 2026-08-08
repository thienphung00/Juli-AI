# backend/src/juli_backend/services/action_cards

## Purpose

Manual-refresh pipeline persistence for **Decision** rows (Action Cards per
`CONTEXT.md` and ADR-021). Poll (optional) → scoring → Postgres upsert.
`persist_scoring_result` is also the durability boundary for **continuous**
scoring candidates on compute (#715, B-3) — idempotent, status-preserving,
and freshness-stamped so it is safe for a webhook-driven or hourly-reconcile
scoring stage to call repeatedly for the same shop without corrupting
in-flight card state. (Wiring a continuous compute trigger's scoring stage
— e.g. `cdp_speed.decision_rules_scoring_stage` — onto this function is not
owned by this module; see `services/cdp_speed/MODULE.md`.)

`emission_budget.apply_emission_budget` (#716, B-4) is a second, independent
durability boundary: it throttles which persisted candidates *surface* into
the Demo active set (max active / cooldown / novelty), on its own cadence,
separate from `persist_scoring_result`'s recomputation cadence. Wiring
`apply_emission_budget` onto a scheduled trigger is **not** done by this
slice — see "Out of scope".

## Public API

- `run_action_card_refresh(session, shop_id, *, poll=True)` → `list[ActionCard]`
- `persist_scoring_result(session, shop_id, result, *, emission_config=None)` → `list[ActionCard]`
- `IN_FLIGHT_STATUSES` — `frozenset[str]` (`approved`, `dismissed`, `executing`)
  — statuses `persist_scoring_result` will not overwrite on re-scoring (#715).
  **Unchanged by #716** (see "Collision 2" below) — the hard rule for B-4 was
  to resolve the dismiss-cooldown deadlock without narrowing this frozenset.
- `persist_legacy_recommendations(session, shop_id)` → `None` — sole write owner
  for retained `recommendations` rows (legacy GET /v1/recommendations refresh path)
- `maybe_poll_tiktok_data(session, shop_id)` — Fujiwa poll when `TIKTOK_APP_*` set
- `enqueue_action_card_refresh(session, *, shop_id)` → Celery task id
- `emission_budget.apply_emission_budget(session, shop_id, *, now=None, config=None)`
  → `EmissionBudgetOutcome` (#716, B-4) — throttles `status == "active"`
  candidates into the surfaced set; writes only `surfaced_at` /
  `suppressed_reason`, never candidate content.
- `emission_budget.EmissionBudgetOutcome` — `surfaced: list[ActionCard]`,
  `suppressed: dict[str, list[ActionCard]]` (keyed by reason)
- `emission_budget.SUPPRESSED_REASON_ACTIVE_CAP` / `_COOLDOWN` /
  `_WEEKLY_NOVELTY_CAP` — the three defined `ActionCard.suppressed_reason`
  values. Only the first two are ever actually assigned by current code
  (fill-to-cap, #716 B-4 cycle 2 — see "Soft novelty quota = fill to cap"
  below); `_WEEKLY_NOVELTY_CAP` is retained for schema/API stability.
- `core.config.decision_emission_config()` / `DecisionEmissionConfig` —
  tunables consumed by both `persist_scoring_result` (cooldown-expiry
  supersede) and `apply_emission_budget` (cap / cooldown / novelty)

## HTTP (via `api/routes/action_cards.py`)

- `POST /v1/action-cards/refresh` — 202 Accepted, enqueues Celery task
- `GET /v1/action-cards` — persisted active cards only (no regeneration)

## Dependencies

- `juli_backend.services.scoring.pipeline` — `run_daily_scoring_for_shop` (unchanged)
- `juli_backend.repositories.repos.ActionCardsRepo` — idempotent `(shop_id, workflow_key)` upsert
- `juli_backend.workers.services.polling` — optional Fujiwa poll before scoring
- Celery enqueue via injectable `RefreshDispatcher` — production adapter in
  `juli_backend.workers.dispatch_binding` (bound at API/worker startup; #554)

## Key behaviors

- Unique constraint on `(shop_id, workflow_key)` — re-refresh updates rows in place
- Sole write owner for `action_cards` and retained legacy `recommendations` tables
- No Redis; Postgres is the sole store (ADR-021)
- HTTP handlers never run scoring inline — same pattern as `execution/dispatch.py`
- `DAILY_SCORING_CRON_UTC` remains unused (manual refresh only)
- Analytics-backed CTR (#428) ranks mid/large Ads workflows (`create_activity_7a`,
  `update_activity_7c`) through unchanged `run_action_card_refresh` →
  `persist_scoring_result`; ROAS/CAC cards appear only when spend ETL supplies denominators
- List API freshness: `metadata.computed_at` (scoring run) and `updated_at` (row bump);
  `recommendation.computed_at` duplicates the same timestamp — no separate envelope field (#429)
- **Freshness column (#715, B-3, ADR-038):** `ActionCard.computed_at` (nullable
  `DateTime(timezone=True)`, migration `026_action_cards_computed_at`) carries the
  scoring run's `ScoringSignals.computed_at` on a real, queryable column — the
  same "when did this compute run finish" semantics as `GoldKpiEnvelope.computed_at`
  / `AnalyticsKpiEnvelope.computed_at` — in addition to the pre-existing
  `metadata.computed_at` / `recommendation.computed_at` JSON copies (kept for
  backward-compatible reads; #429). The dedicated "promotion"/`surfaced_at`
  timestamp landed in #716 (B-4) — see "Decision emission/surfacing budget"
  below; it is written only by `emission_budget.apply_emission_budget`, never
  by `persist_scoring_result`.
- **Idempotent-upsert + status-preservation (#715, B-3):** `persist_scoring_result`
  looks up the existing `(shop_id, workflow_key)` row *before* delegating to
  `ActionCardsRepo.upsert`. If the existing row's `status` is in
  `IN_FLIGHT_STATUSES` (`approved` / `dismissed` / `executing`), the row is
  left completely untouched — no status, content, or `computed_at` change —
  and the untouched card is still included in the returned list so callers see
  the full candidate set for the run. Only a card still in the `"active"`
  candidate status (or not yet persisted) is upserted. This preserves seller
  (or dry-run) decisions across continuous re-scoring without a second
  surfacing-state model living in this module.
- **Negative-path / atomicity:** `persist_scoring_result` performs no `commit`
  itself (same as before) — a caller wrapping the call in a transaction that
  rolls back on failure (e.g. the Shared Compute Orchestrator's isolated
  scoring failure domain, #713) leaves previously-committed cards exactly as
  they were; a failure partway through one run's recommendation loop leaves no
  partial row from that run visible after rollback.

## Decision emission/surfacing budget (#716, B-4, ADR-038 §6)

Throttles which persisted candidate Action Cards *surface* into the Demo
active set — max 5 active, 7-day per-workflow cooldown after a terminal
action, soft weekly novelty cap of 3 (all tunable via
`core.config.decision_emission_config()` / `CDP_DECISION_EMISSION_MAX_ACTIVE`,
`CDP_DECISION_EMISSION_COOLDOWN_DAYS`, `CDP_DECISION_EMISSION_WEEKLY_NOVELTY_CAP`
— never hardcoded at call sites). Lives in `emission_budget.py`, deliberately
separate from `persist.py`: **surfacing and scoring are independently
gated** — `apply_emission_budget` runs on its own cadence and never touches
candidate content; `persist_scoring_result` runs on its own cadence and
never touches the surfacing columns.

### Soft novelty quota = fill to cap (operator decision, #716 B-4 cycle 2)

The quota shipped in cycle 1 was, as built, a **hard gate**:
`apply_emission_budget` ran cooldown → novelty → active_cap as three
sequential unconditional suppressions. Because `weekly_novelty_cap` (3) <
`max_active` (5) and novelty ran first, a shop with more than 3 new
workflows in a week could never reach 5 surfaced Decisions — `max_active`
was structurally unreachable through fresh candidates, even though the PRD
and ADR-038 §6 call the quota *soft*. Review ruled this a defect; the
operator decided **soft means "fill to cap"**: the weekly novelty cap is a
**churn target**, not a supply ceiling — `max_active` is the only hard
ceiling on surfacing. Once the weekly quota is consumed, additional novel
candidates still surface as long as the surfaced set is below `max_active`
— they fill the remaining slots rather than leaving them idle.

`apply_emission_budget` now runs three passes, in this order:

1. **Cooldown (hard, unconditional, unchanged).** A workflow inside its
   `cooldown_days` window after a terminal action never surfaces, no matter
   how many slots are free. This gate was not touched by the cycle-2 change.
2. **Weekly novelty quota (soft — orders preference, does not eliminate).**
   Candidates that pass cooldown are partitioned, in priority order, into a
   **within-quota** group (any candidate whose `workflow_key` was already
   counted novel earlier this week, plus the first `weekly_novelty_cap`
   distinct *new* `workflow_key`s) and a **novelty-overflow** group
   (additional new `workflow_key`s beyond the quota). Priority order is
   preserved inside each group. This partitioning by itself never removes a
   candidate — it only decides who gets first claim on a scarce slot.
3. **Active cap (hard, the only real supply ceiling).** The within-quota
   group is walked first, then the overflow group, surfacing candidates
   until `max_active` is reached; everything left over — from either
   group — is suppressed as `active_cap`.

**Suppression-reason consequence:** because step 2 no longer eliminates
candidates, `SUPPRESSED_REASON_WEEKLY_NOVELTY_CAP` (`"weekly_novelty_cap"`)
is **structurally unreachable** under current code — every suppression is
now either `cooldown` (step 1) or `active_cap` (step 3, whether the
candidate was within-quota or overflow). The constant and its
`SUPPRESSED_REASONS` membership are kept — the `ActionCard.suppressed_reason`
column, `EmissionBudgetOutcome.suppressed` dict shape, and the
`emission_budget_applied` log's `suppressed_weekly_novelty_cap` aggregate
field all still reference it (always `0`/empty under current semantics) —
for schema/API stability and in case a future slice reintroduces a
hard-gate mode. `test_weekly_novelty_cap_reason_is_structurally_unreachable`
in `tests/unit/test_decision_emission_budget.py` documents this rather than
leaving it as silent dead code.

**Worked example** (defaults: `max_active=5`, `weekly_novelty_cap=3`,
`cooldown_days=7`), 6 brand-new candidates in one week, none in cooldown:
the first 3 (priority order) fill the quota, the other 3 overflow it; the
active-cap pass then surfaces 5 of the 6 (quota-satisfied first, then the
best-priority overflow candidate) and suppresses the 6th as `active_cap` —
zero slots left idle. See
`test_worked_example_six_novel_candidates_default_config_fills_zero_idle_slots`.

**Ledger accounting stays truthful:** `DecisionEmissionNoveltyLedger` only
ever gets a row for a candidate that actually ends up in the surfaced set
this run — including novelty-overflow candidates that made it in because a
slot was free (the weekly counter must track real surfacings for tuning,
not just quota-abiding ones) — and never for a candidate suppressed by
`active_cap`, novelty-overflow or not.

### Emission/surfacing persistence model — columns, not a status enum

Two models were on the table (per the issue): a new `status` enum
(`candidate`/`surfaced`/`suppressed`) or additive **columns**
(`ActionCard.surfaced_at`, `ActionCard.suppressed_reason`). **Columns were
chosen.** `ActionCard.status` already carries the seller-lifecycle meaning
established in ADR-021/#303 (`active` = un-actioned candidate, `approved` /
`dismissed` / `executing` = seller/dry-run decisions) and is read by
`ActionCardsRepo.list_active`, `GET /v1/action-cards`, and B-3's
status-preservation guard. Repurposing it into a *different* three-state
axis (candidate/surfaced/suppressed) would collide with that existing
meaning and reach into the public read API (#718, B-6) and dry-run execution
(#717, B-5) — both explicitly out of this slice. Additive columns answer
"is this candidate currently surfaced" (`surfaced_at IS NOT NULL`) and "why
not" (`suppressed_reason`) without touching `status` at all — queryable
separately from "all scored rows" via `ix_action_cards_shop_surfaced_at`
(migration `027_decision_emission_budget`). The two columns are mutually
exclusive after each `apply_emission_budget` run (surfaced clears the
reason; suppressed clears `surfaced_at`).

### Collision 1 — US-11 (recompute must survive suppression)

Resolution: a **no-op by construction**, once the columns model is chosen.
`persist_scoring_result` only ever skips upserting a candidate when its
`status` is in `IN_FLIGHT_STATUSES` — a budget-suppressed candidate keeps
`status == "active"` (it is never demoted to a third status), so every
scoring run refreshes its content exactly like a surfaced candidate's. The
"nowhere to live" risk named in the issue is specifically the failure mode
of the *other* model (a `status == "suppressed"` value would have needed
adding to some skip-set to avoid the emission budget's own decision being
clobbered by recompute, and a bug there would silently freeze suppressed
candidates forever) — the columns model sidesteps that risk entirely because
`persist_scoring_result` and `apply_emission_budget` write disjoint columns.
Proven by `test_suppressed_candidate_is_still_recomputed_on_next_scoring_run`
(`tests/unit/test_decision_emission_budget.py`).

### Collision 2 — the cooldown must be able to finish

`dismissed` is (unchanged) inside `IN_FLIGHT_STATUSES`, so B-3's guard alone
would freeze a dismissed row forever — a 7-day cooldown that starts on
dismiss but structurally can never re-open, because nothing ever produces a
fresh candidate for that `workflow_key` again. **Resolution chosen: let a
post-cooldown candidate legitimately supersede the `dismissed` row** —
`IN_FLIGHT_STATUSES` itself is **not** narrowed (still exactly `approved` /
`dismissed` / `executing`; `test_in_flight_statuses_...` in both #715's and
#716's test files assert this). Instead, `persist.py` adds one additional
check purely on the `dismissed` branch:
`_dismiss_cooldown_expired(existing, now=computed_at, cooldown_days=...)` —
true only when `now - (existing.dismissed_at or existing.updated_at) >=
cooldown_days`. When true, the fresh candidate is allowed to upsert in place
(status resets to `"active"`, `dismissed_at` clears so the clock does not
appear "still running" on the next check); when false, behavior is
byte-for-byte what B-3 shipped. `approved` and `executing` are **not** given
this escape hatch — only an explicit outcome should ever move a workflow out
of those, not the mere passage of time; this is intentional, not an
oversight, and is proven by
`test_approved_and_executing_are_never_time_boxed_superseded`. B-3's own
`test_inflight_status_not_overwritten_by_rescoring` in
`tests/unit/test_action_card_freshness_persistence.py` is untouched and
still passes unmodified — its 2-hour rescore gap never reaches the 7-day
default cooldown, so behavior there is identical to pre-#716.

### Durable weekly novelty counter (Postgres, not Redis)

`DecisionEmissionNoveltyLedger` (`decision_emission_novelty_ledger`, migration
`027_decision_emission_budget`) — one row per `(shop_id, week_start,
workflow_key)`, inserted the first time a workflow_key actually surfaces in
an ISO week (never for a candidate that only got *classified* novel but was
then suppressed by `active_cap`). `apply_emission_budget` reads this table
(never Redis) to know how much of the week's novelty quota is already
spent — across calls, across processes — so the churn target holds even if
`apply_emission_budget` runs more than once in the same week. A
workflow_key already in this week's ledger surfaces "for free" (it joins
the within-quota group with no further novelty cost); the quota only
partitions *new* workflow_keys entering the surfaced set for the first time
that week into within-quota vs. novelty-overflow (#716 B-4 cycle 2 —
fill-to-cap; see "Soft novelty quota = fill to cap" above) — it no longer
gates them outright as long as room remains under `max_active`.

## Out of scope

- Celery beat / scheduled scoring
- Redis read-through cache (emission-budget state included — Postgres is SoT
  per ADR-038; `test_no_redis_dependency_in_emission_budget_module` guards this)
- Seller-facing "Decision" UI (`web/`)
- Wiring `apply_emission_budget` onto a scheduled/webhook trigger was
  originally out of scope for this slice (mirroring how B-3 shipped
  `persist_scoring_result` before B-2/orchestrator wiring landed), but a
  Meta routing correction under the #716 (B-4) issue added a real production
  caller: `cdp_speed.decision_rules_scoring_stage` (commit `fc75b3ac`) now
  invokes `apply_emission_budget` immediately after `persist_scoring_result`
  on every continuous-trigger compute run — see
  `services/cdp_speed/decision_rules_scoring.py` and
  `tests/unit/test_cdp_speed_decision_rules_scoring_emission.py`.
- Public Decision read API — #718, B-6
- Demo dry-run execution — #717, B-5
