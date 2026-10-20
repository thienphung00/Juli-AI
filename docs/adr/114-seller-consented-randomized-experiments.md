# ADR-114: Experiments — a seller opts a product set in, Juli randomises inside it, and the pre-registered experiment becomes the impact reader's counterfactual and the models' intervention schedule

- **Status:** Accepted (owner, 2026-10-20, grill D70)
- **Date:** 2026-10-20
- **Decision:** D70.10 (grill D10) — `docs/product/data-platform/GRILL_LOG.md`
- **Related ADRs / decisions:** [ADR-077](077-incremental-impact-measurement.md) (DiD reader,
  `impact_readings`; its "Future A/B experiment reuse" seam), [ADR-107](107-card-journey-log-and-measurement-plan.md)
  as amended by D70.9 / D70.11 (`card_events`, measurement plan, no peeking), ADR-089 (tenant
  isolation, SECURITY DEFINER shape), ADR-101 (fixtures), ADR-105 (verdict + record), ADR-112
  (ingestion platform), ADR-113 (shop data: product versions, promotion timeline), ADR-115 (training
  data and model gate, D70.12 / D70.13). Fast-track: D34 / D39.3 (randomised delayed control,
  P30, MIG 089), D41.3 (CUPED, permutation test, P31), D45 (Ops groups, guard metric, P36, MIG 092),
  D51.6 (pre-registered predictions), D52 (EB-shrunk group lift, P45, MIG 093), D57 (independent
  tests while group tests are off), D60.3 (control groups not shipped to sellers), D61 (no
  algorithm details in public content), D68 (privacy / purge, MIG 094).

## Context

Juli's per-card reading is a ratio-form DiD against correlated siblings (ADR-077). It is the
right default — one TikTok listing shows one version to every buyer, so a per-buyer A/B split
is impossible — but cards are opened *because* a product dropped, so before/after over-credits
levers (regression to the mean) and a shop-wide shock that hits the treated product differently
from its siblings reads as effect. D34 answered this with a randomised delayed control; P30 built
it (`card_groups`, `card_group_members`, MIG 089; `services/action_cards/card_groups.py`,
`group_stats.py`, `group_design.py`), P36 added Ops groups (MIG 092), P45 the EB-shrunk lift read
cross-tenant through `ops_group_lift_draws()` (MIG 093). D57 then switched group tests off for
sellers and D60.3 removed every control-group claim from seller pages: the draw ran without the
seller ever being asked.

The grill (D70.10) keeps randomisation but changes its footing: **only when the seller opts in**.
The seller picks a product set "cho Juli thử"; Juli randomises inside it; the treated arm executes
through the normal approve flow (D70.9). The result must (a) be pre-registered — hypothesis,
metric, sample size / MDE, horizon and a forecast recorded before the end (D51.6); (b) feed the
impact reader as a randomised counterfactual where one exists, DiD otherwise; (c) give the models
an intervention schedule so intervened product-days leave observational training data (D70.12).

What exists and is reused, and what is new:

| Existing | Reused for | Not reused because |
|---|---|---|
| `card_groups` / `card_group_members` (MIG 089, 092) | history; arm draw and verdict code | no consent, no pre-registration, no eligibility snapshot, keyed by `tiktok_product_id`, tied to card drafts |
| `assign_arms`, `assign_arms_stratified`, `order_strata`, `new_seed` (`card_groups.py`) | the draw, unchanged | — |
| `group_stats` (CUPED `adjust_changes`, `permutation_test`, `bootstrap_interval`, `false_alarm_rate`, `shrink_lift`) and `build_verdict` / `compare` | the experiment verdict, unchanged | — |
| `group_design.drift_floor` / `traffic_needed` | MDE and horizon at registration | — |
| `ops_group_lift_draws()` (MIG 093), `lift_draws` / `apply_pooled_eb` (D52) | cross-shop EB prior per lever × metric × channel | extended, not replaced |
| `impact_readings` (MIG 033), `services/impact/*` | per-card reading rows; control pool swapped for the arm | — |
| `lever_calibrations` / `run_measurement_finals` (MIG 080) | the once-per-run calibration update, unchanged | — |
| `card_events` (ADR-107 / D70.9) | actual applied date; consent, stop and shadow events | — |
| **New** | `experiments`, `experiment_assignments`, `services/experiments/`, a view for the intervention schedule | — |

## Decision

1. **Opt-in only; one experiment = one seller-chosen product set × one lever.** Nothing is
   randomised in a shop without a recorded consent for that experiment. From this ADR the
   automatic D34 draw (`apply_groups`, tunable `card_groups`) and Ops-created groups
   (`create_ops_group`, D45) create no new `card_groups` rows; existing rows stay read-only as
   history and stay in the EB prior. A D45-style Ops experiment (e.g. `pack_option`) is created
   by Ops as a *draft* and becomes live only when the seller consents in the app, exactly like a
   seller-started one.

2. **Table `experiments`** (tenant-direct, next migration after 094):
   `id uuid PK`, `shop_id → shops NOT NULL`, `source` ∈ {`seller`, `ops`}, `created_by` (user),
   `hypothesis text` (internal, one line), `lever varchar(48)`, `change_kind` (ADR-107 vocabulary),
   `primary_metric varchar(32)`, `primary_channel varchar(32)`, `guard_metrics jsonb` (D45.2:
   metric, channel, harm threshold), `alpha`, `power`, `mde numeric`, `pre_days int` (14),
   `horizon_days int` (14 or 28 by ADR-107 d.7), `control_share numeric` (config
   `experiment_control_share`, default 0.5), `stratify` ∈ {`orders`, `none`}, `planned_treated`,
   `planned_control`, `seed bigint` (31-bit, `new_seed`), `rule_version` (ADR + config hash),
   `status` ∈ {`draft`, `consented`, `running`, `measured`, `stopped`}, consent block
   (`consented_by`, `consented_at`, `consent_copy_version`), `starts_on date`, `ends_on date`
   (= `starts_on + horizon_days`), `forecast jsonb`, `forecast_registered_at timestamptz`,
   `verdict jsonb` (the `build_verdict` shape incl. `primary.eb`, `metrics`, `net`),
   `measured_at`, stop block (`stopped_at`, `stopped_by`, `stop_reason` ∈ {`seller`, `guard`,
   `shop_disconnected`, `account_deleted`}), `created_at`.
   Checks: `status = 'draft' OR consented_at IS NOT NULL`; `ends_on > starts_on`;
   `status <> 'measured' OR ends_on <= measured_at::date`. Indexes: `(shop_id, status)`,
   `(shop_id, starts_on)`, `(lever, primary_metric, primary_channel) WHERE status = 'measured'`
   for the EB draw.
   **Immutability trigger** `experiments_freeze_preregistration`: once `status <> 'draft'`, the
   design columns (hypothesis … `seed`, `rule_version`, `starts_on`, `ends_on`) cannot change;
   consent and stop columns are write-once; `forecast` may only gain keys, never change one, and
   only while `now() < ends_on` in the shop's day (D51.6); `verdict` is write-once.

3. **Table `experiment_assignments`** (tenant-direct): `id uuid PK`, `shop_id`, `experiment_id →
   experiments`, `product_id varchar(100)` (platform object id, D70.1 naming), `arm` ∈
   {`treated`, `control`}, `stratum varchar(16)`, `assigned_at`, `eligibility jsonb` +
   `eligibility_version` (frozen at the draw: readiness level D70.3, last-30-day volume and
   pre-period metric per day, open cards / plan locks, active promotions from the D70.6 timeline,
   stock state, product version id from ADR-113), `action_card_id → action_cards NULL`,
   `applied_on date NULL` + `applied_event_id → card_events NULL` (filled from the `executed` or
   `seller_done` event per ADR-107 as amended — never from approval time), `exit_on date NULL` +
   `exit_reason` ∈ {`seller_change`, `seller_revert`, `juli_revert`, `deleted`, `stock_out`}
   (from D70.11 attribution), `live boolean`, `released_at`.
   Keys: `UNIQUE (experiment_id, product_id)`; **partial unique `(shop_id, product_id) WHERE
   live`** — a product is in at most one running experiment (no `btree_gist`, D70.7 forbids
   extensions); index `(shop_id, product_id, experiment_id)`. Writes: INSERT at the draw; UPDATE
   only `action_card_id`, `applied_on`, `applied_event_id`, `exit_*`, `live`, `released_at`
   (column-scoped grant, as MIG 065 / 083).

4. **Flow** (`services/experiments/`: `registry.py`, `consent.py`, `assign.py`, `reader.py`,
   `schedule.py`; routes under `/v1/shops/{id}/experiments`, Ops under
   `/v1/ops/shops/{id}/experiments`):
   1. *Set.* The seller opens "Cho Juli thử", picks products and one lever Juli already offers
      that shop. Juli computes eligibility; ineligible products are shown with a plain reason and
      dropped before the draw. Registration computes MDE and horizon with
      `group_design.traffic_needed` and ADR-107 d.7; below ≥ 3 treated + 2 control (D34.4) or an
      MDE above the plan ceiling, the app says the set is too small and offers no experiment.
   2. *Consent.* The seller confirms the consent sheet; one transaction writes the consent block,
      `status = consented` and a `card_events`-style `experiment_consented` record.
   3. *Draw.* `assign_arms_stratified(order_strata(...), seed)` (or `assign_arms` with
      `stratify = none`); `starts_on` = next shop day; `status = running`. Same ids + seed + strata
      → same arms (replayable).
   4. *Treated arm.* Each treated product gets its normal card for the experiment's lever through
      the emission budget, flagged `experiment_id`; the seller approves / edits / dismisses each as
      usual (D70.9). Analysis is by assignment (D34.5); approved-only is secondary.
   5. *Control arm.* Its drafts are suppressed `experiment_control` (as `group_control`) and no
      Juli write touches it until `ends_on`; then `released_at` is set and normal cards resume.
   6. *Forecast.* The live predictor (and every shadow model, decision 7) writes its per-arm
      forecast with 90 % interval, run id, commit and PRIORS_VERSION into `forecast` before
      `ends_on`; the reader scores only forecasts registered in time, and reports whether each was
      registered before `starts_on`.

5. **Stopping rules — fixed horizon, no peeking.** The verdict is computed once, on the first
   analytics day ≥ `ends_on` − 1 (P30's day-14 rule generalised), by the daily beat
   `experiment-reader` scheduled after the ADR-077 impact reader. Before that no arm comparison
   is computed or shown — seller or Ops; Ops sees only accrual (products live, days observed,
   exits). Horizon is never extended after data is seen. **Exceptions:** (a) *guard stop* — a
   pre-declared guard metric crossing its pre-declared harm threshold (D45.2 pattern, checked
   daily on the treated arm vs its own pre-period, not against control) stops the experiment with
   `stop_reason = guard`, and the record makes no effect claim; (b) *seller stop* at any time.
   Either stop: pending treated cards are withdrawn (`superseded`), controls are released, the
   seller is offered the D70.11 revert for executed changes, `verdict` holds accrual only and the
   experiment is excluded from pooled effects and model scoring.

6. **Impact reader: randomised control first, DiD otherwise.** For a run whose product has a
   `treated` assignment in a `measured` experiment, `services/impact` takes the experiment's
   control arm as the control set instead of `control_pool` K-nearest siblings, and the reading
   row records it: next migration adds `impact_readings.method` ∈ {`did`, `randomized`} (default
   `did`) and `experiment_id NULL`. The experiment-level effect is `build_verdict` (median
   difference, CUPED via `adjust_changes`, permutation test under 5 controls, seeded bootstrap,
   false-alarm replay, net-of-cancel basis D55.1). Everything else stays DiD (ADR-077).
   `lever_calibrations` keeps its once-per-run update through `run_measurement_finals`; a
   randomised reading feeds it like any other final. `ops_group_lift_draws()` is replaced
   (`CREATE OR REPLACE`, same signature, `juli_ops` only) by a `UNION ALL` of measured
   `card_groups` and measured `experiments`, so the D52 prior pools both.

7. **Interaction with the D70.13 shadow mode.** Shadow models never read or change the draw, the
   arms, the treated content or the horizon. Their forecasts for experiment products are
   recorded as `card_events` `shadow` rows *and* as keys under `forecast.shadow.<model_version>`
   before `ends_on`; measured experiments are therefore the cleanest scoring set for the D70.13
   (2) shadow period and the D70.13 (4) monitoring. At the draw (step 4.3), in the same
   transaction, the control arm is registered in ADR-115's `ml.holdout_windows`
   (`scope_kind = experiment_arm`, `experiment_id`, `arm = control`, `starts_on`…`ends_on`), so it
   is a test set before any outcome exists (ADR-115 default schedule). Because the `ml` schema is
   `juli_ops`-only, the draw calls `ml_register_experiment_holdout(experiment_id)` — SECURITY
   DEFINER (ADR-089 shape), EXECUTE to `juli_app`, inserting only the window of an experiment
   whose `shop_id = app_current_shop_id()`; the one `ml` write path open to the app role.

8. **Intervention schedule for training (D70.12).** View `experiment_intervention_days(shop_id,
   product_id, day, experiment_id, arm, role)`: treated days from `applied_on` to `ends_on` (+ a
   7-day washout, config) are `intervened`; control days in the window are `experiment_control`.
   ADR-115's builder excludes `intervened` days from observational training data;
   `experiment_control` days are blocked from training / selection by the holdout window of
   decision 7 until every listed model has scored it, and are ordinary untouched days after that
   (`used`). The impact reader still reads them as the counterfactual (ADR-115 d.4). Exited
   assignments end at `exit_on`.

9. **Seller-facing copy (D61, D60.3).** Only inside the signed-in app; nothing on public pages,
   blog, FAQs, llms.txt or demo screens. Copy describes the workflow, never the method: no
   share, seed, thresholds, MDE, statistics, model or "nhóm đối chứng" wording. Strings (owner to
   approve, `consent_copy_version` stamps the shown version): entry "Cho Juli thử"; consent "Juli
   sẽ đề xuất thay đổi cho một phần sản phẩm bạn chọn và giữ nguyên phần còn lại để so sánh. Bạn
   vẫn duyệt từng thay đổi và có thể dừng bất cứ lúc nào."; running "Đang thử — kết quả sau
   N ngày"; stop "Dừng thử"; result one D34.8-style sentence, worded with D31.7, hedged "ước
   tính". Ops sees arms, seeds, intervals, EB.

10. **Guardrails.** The control arm gets no Juli change for the horizon only, then its normal
    cards (delayed control, D34.2); Juli never changes a control product to "balance" anything;
    nothing outside the chosen set is randomised; levers are those already offered to the shop
    (price levers keep the seller's rules and discount caps); every treated write is an
    approved card with before/after values and revert (P8-C, D70.11); stopping costs the seller
    nothing and is never nagged; experiments carry no fee and do not change plan limits;
    cross-tenant reads are aggregate-only (D52.3). Shop disconnect or account deletion stops the
    experiment; `privacy_purge_account` (MIG 094) removes both tables by their `shop_id`.

11. **Security.** Both tables: RLS on, one policy per granted verb via `app_current_shop_id()`
    (MIG 089 shape), `juli_app` SELECT / INSERT / UPDATE (no DELETE), registered `tenant_direct`
    in `database/tenant_scoped_tables.py`.

## Consequences

**Positive.** Levers get an estimate free of regression to the mean and shop-wide shocks where
sellers allow it; consent is explicit, versioned and revocable; pre-registration is enforced by
the database, not by discipline; the forecast rule (D51.6) and the shadow gate (D70.13) get a
clean scoring set; training data learns which days were intervened; all P30–P46 statistics code
is reused unchanged.

**Negative.** Two group stores coexist (`card_groups` history, `experiments` new) until the
history is folded in; the impact reader gains a branch; opt-in will make experiments rare at
first, so DiD remains the reading for most cards; a fixed horizon gives up early wins; plan
locks keep treated and control products out of other cards for the horizon.

**Follow-ups.** (1) Migration (next after 094): two tables, trigger, partial unique index, RLS,
grants, `impact_readings.method` / `experiment_id`, replaced `ops_group_lift_draws()`, view.
(2) `services/experiments/` + `experiment-reader` beat + `experiment_control` suppression in
`emission_budget.py`. (3) App sheet and routes; Ops page next to "Nhóm thử nghiệm". (4) Fold
`card_groups` rows into `experiments` as `source = legacy_d34` once ADR-115's schedule needs
them (owner call). (5) Retire `apply_groups` / `create_ops_group` draw paths and the
`card_groups` tunable. (6) Phase P6 of D70.16.

## Alternatives considered

- **DiD only (no experiments).** Rejected: regression to the mean and differential shocks
  remain; D34's reason stands.
- **Automatic randomisation without consent (the D34 / P30 path).** Rejected by D70.10; the code
  is reused, the trigger is not.
- **Extend `card_groups` in place.** Rejected: it would need consent, pre-registration,
  eligibility, platform-neutral product keys and a different lifecycle — a new table with the old
  one kept as history is cleaner and keeps MIG 093's consumer stable.
- **Per-buyer A/B split.** Impossible: a listing shows one version (ADR-107 context).
- **Sequential testing with alpha spending.** Deferred: samples are small and a fixed horizon is
  simpler to audit; only the pre-declared guard stop is allowed early.

## Verification (D70.15 layers)

- **Unit:** draw reproducibility (golden ids + seed + strata → arms; ADR-101 fixtures); MDE /
  horizon from `traffic_needed`; eligibility exclusions; reader picks `randomized` vs `did`;
  no arm comparison before `ends_on`; guard and seller stops; forecast scored only when
  registered in time; copy test blocks D61 leak patterns in experiment strings.
- **Real Postgres (layer 2, the Postgres CI job — not deselected by `migration_heavy`):** RLS two
  tenants on both tables (`test_two_tenant_isolation_proof.py`, `test_runtime_role_grant_coverage.py`);
  freeze trigger refuses design edits after `draft`, a changed forecast key, a forecast after
  `ends_on`, a second verdict; partial unique refuses a product in two live experiments;
  `ops_group_lift_draws()` returns both sources and is not executable by `juli_app`;
  privacy purge removes both tables.
- **Leakage (layer 6):** the ADR-115 builder drops `intervened` days; a control arm's days are
  refused by `assert_not_held_out` while its window is `pending` / `frozen`; the draw and the
  holdout registration commit together (kill between them → neither exists).
- **Gate:** one consented experiment on Fujiwa end-to-end (consent → draw → approve → applied
  date from `card_events` → verdict at `ends_on` → `impact_readings.method = randomized`).
