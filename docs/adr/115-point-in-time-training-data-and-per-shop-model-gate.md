# ADR-115: Training data is point-in-time, reproducible and holdout-guarded, and a model reaches a shop only through a four-step gate with automatic rollback

**Status:** Accepted (owner, 2026-10-20, grill D70)
**Date:** 2026-10-20
**Related ADRs / decisions:** grill D12 / D13 = fast-track **D70.12 / D70.13**
(`docs/product/data-platform/GRILL_LOG.md`, gap map `GAP_MAP_FASTTRACK.md` rows D12, D13);
ADR-107 (`card_events`, amended for D70.9 — this ADR adds the `shadow` event and the snapshot
link); ADR-112 (ingestion platform: readiness levels L1–L3 = D70.3, `ops` job queue, D15 test
layers); ADR-113 (shop data: D4 product versions `valid_from`, D5 `last_revised_at`); ADR-114
(experiments and arms, D70.10); [ADR-077](077-incremental-impact-measurement.md) (DiD impact);
[ADR-046](046-cdp-medallion-physical-model.md) (medallion); [ADR-089](089-fleet-scoped-work-under-tenant-isolation.md)
(fleet work under RLS); [ADR-101](101-tests-derive-from-captured-fixtures.md) (fixtures).
Fast-track: D24.6 (calibration factor), D30.1c (`run_baselines`), D30.3 (Performance Prediction),
D51 / D53 / D59 (Gate A–C, `ml_guard`, data roles in juli-sim-pilot), P23, P8-C.

## Context

Grill goal 3: training data must be replayable and leak-free, the intervention schedule is
design information, and a model is switched on for a shop only after an evaluation gate.

What this branch has (head `c413d448`, MIG head 094):

- **Known-at times exist, but not uniformly.** Bronze `order_raw_payloads` /
  `return_raw_payloads` carry `received_at` (MIG 023); `ingest_raw_payloads.received_at`
  (MIG 088); `product_snapshots.taken_at` (MIG 087, D30.1a); `run_baselines.captured_at`
  (MIG 087, D30.1c). `analytics_performance_intervals` (MIG 017/018/075) is upserted in place —
  `updated_at` is overwritten on every re-pull, so the value *as known* on an earlier day is lost
  from silver (bronze keeps it only where bronze exists).
- **`gold.ml_feature_snapshots`** (MIG 021: `id, shop_id, snapshot_at, feature_version,
  payload json`, index `(shop_id, snapshot_at)`; RLS + `SELECT, INSERT, UPDATE` to `juli_app`
  in MIG 046) has **no writer**.
- **`run_baselines`** freezes, per (run, phase ∈ approval / execution), the 14-day pre-series,
  price, active promotions, content hash and listing codes
  (`services/product_history/baselines.py::capture_run_baseline`).
- **The incumbent predictor is D30.3** (`services/optimize_product/prediction.py`): a prior lift
  range per (lever, Quality-Score gap bucket) × a calibration factor from `lever_calibrations`
  (MIG 080; shop / fleet shrinkage, `MIN_SHOP_RESULTS = 5`, `SHRINKAGE_K = 5`). Its output is
  stored as `prediction` JSON on the card proposal and drives the D29 KPI range. It is internal
  (D30.5). It has never been scored for interval coverage. `lever_calibrations` is current-state
  (upserted), but every update is logged once in `run_measurement_finals`
  (`calibration_from`, `calibration_to`, `computed_at`), so its value at any past instant can be
  replayed.
- **The discipline already proven in research.** juli-sim-pilot `ml_guard.py` (owner 2026-10-17,
  D51 / D59): a committed registry `ml_pipeline/frozen_test.json` of test sets with status
  `pending → frozen → used`; `assert_not_frozen(path)` in every fitting / selection loader (a
  pending set is blocked before its data lands); a SHA-256 fingerprint; `final_test(model,
  score_fn)` runs once per (model, set) and then the set becomes ordinary training data;
  `register_prediction` pre-registers a prediction before the outcome exists (D51.6);
  `drop_frozen_shops` for shop-level holdouts. Its data-role registry is `v03/leakage.py`
  `DATA_ROLES` / `check_roles` (D53.3: `idea / priority / context / outcome / feature`, review
  features only if dated before prediction time). Gate C's promotion rule is
  `v03/ml_pipeline/CONTRACT.md` §6: **ΔELPD > 2 SE vs the best fixed baseline after the leakage
  audit**, plus **90 % interval coverage** of real effects (funnel CONTRACT §10.4, D53.4). The
  first real test (findings ledger E6/E7, 2026-10-18/20) shows why both are needed: FastMoss
  snapshot 2 passed by > 2 SE, while the Ory new-shop set failed and covered only 3/6 and 2/11 —
  intervals too narrow for a new shop.

Nothing in the backend has a dataset builder, a manifest, a holdout registry, a model registry,
shadow mode or rollback (gap map: D12 "Missing (1 partial)", D13 "Missing").

## Decision

### Part A — training data (D70.12)

1. **Every silver row has a known-at time; the builder reads only what was known before the
   cut-off.** Known-at per source, named `known_at` in every builder query:

   | Source | `known_at` |
   |---|---|
   | bronze (any) | `received_at` |
   | silver from bronze (D8, ADR-112) | the source bronze row's `received_at` via `bronze_id` |
   | product versions (D4, ADR-113) | `valid_from` (= `product_snapshots.taken_at` until the view lands) |
   | daily performance (D5, ADR-113) | first known: `first_known_at`; revised: see below |
   | promotions | `first_seen_at`, then `tiktok_update_time` / `refreshed_at` per change |
   | orders / returns silver (MIG 025) | bronze `received_at` (not `tiktok_created_at`) |
   | `run_baselines` | `captured_at` |
   | `lever_calibrations` | replayed from `run_measurement_finals.computed_at` / `calibration_to` |
   | `card_events`, `experiment_assignments` | `occurred_at` / assignment time |

   Because D5 re-pulls the last 7 days and updates silver with `last_revised_at`, a revised count
   overwrites what was known earlier. **The next migration after 094** adds an append-only
   `silver.product_daily_metric_revisions(shop_id, product_id, channel, day, known_at,
   <counts>, bronze_id)`, PK `(shop_id, product_id, channel, day, known_at)`, written by the D5
   mapper only when a re-pull changes a count (bounded: 7 days × changed rows). The builder takes
   the latest revision with `known_at ≤ cutoff`. Module: `services/ml/dataset/pit.py`
   (`as_of(query, cutoff)` helper used by every feature reader; a raw `SELECT` on a silver table
   inside `services/ml/` is a lint failure). Cut-off is a timestamp, not a day: the feature for
   day d may use day d−1 only if it was received before the cut-off.

2. **One feature snapshot per proposal, in `gold.ml_feature_snapshots`.** The next migration
   after 094 adds columns `card_id uuid null`, `workflow_key`, `subject_type`, `subject_id`,
   `model_key`, `model_version`, `readiness_level smallint` (ADR-112 L1–L3), `cutoff_at`,
   `content_sha256 char(64)`, `run_baseline_id uuid null`; unique `(card_id)` where not null;
   index `(shop_id, model_key, snapshot_at)`; converts `payload` to `jsonb`; and **revokes
   `UPDATE`** from `juli_app` (MIG 046 granted it; snapshots are append-only like
   `product_snapshots`). Writer: `services/ml/features/snapshot.py::write_feature_snapshot`,
   called inside card emission (`services/action_cards/optimize_product_cards.py`) in the same
   transaction as the `proposed` `card_events` row, whose payload carries `feature_snapshot_id`
   and `feature_version` (ADR-107 amendment field). `feature_version` = `FEATURE_VERSION` in
   `services/ml/features/__init__.py`, a hash of the feature definitions, bumped by CI when they
   change. This is the gap map's corrected P1 item 5 and lands with `card_events` in P1.
   **Reuse of `run_baselines`:** the snapshot does not re-read what `run_baselines` freezes; the
   pre-series in the snapshot is computed by the same `baselines.pre_series` function, and once
   the approval-phase baseline exists its id is linked (`run_baseline_id`) so a training row's
   pre-period and the impact reader's pre-period are byte-identical. A snapshot is written for
   every proposal, including shadow proposals (A.4 below) and rules-only cards, so the incumbent
   and challengers are trained and scored on the same inputs.

3. **A manifest per dataset.** New non-tenant table `ml.dataset_manifests(id, dataset_key,
   built_at, cutoff_rule, date_from, date_to, shop_set jsonb (shop ids + readiness level each),
   mapper_versions jsonb, feature_version, roles_version, holdout_registry_sha256,
   row_count, content_sha256, artifact_uri, builder_commit)`; unique `(dataset_key,
   content_sha256)`. The dataset file (Parquet) goes to the same archive store as the D7 bronze
   export (ADR-112), path `ml/datasets/<dataset_key>/<content_sha256>.parquet`. Rebuilding from
   a manifest (same cut-offs, versions, shop set) must give the same `content_sha256` — that is
   the reproducibility test. Builder: `services/ml/dataset/builder.py`, run as the fleet job
   `ml-dataset-build` on the ADR-112 `ops` queue at P2 priority (fleet read under ADR-089:
   a per-shop loop under each shop's tenant context, aggregated in the job, never a
   cross-tenant SQL read from `juli_app`). The `ml` schema is `juli_ops`-only (like the D52.3
   cross-tenant Ops read): no grant to `juli_app`.

4. **A holdout-window registry in Juli, enforced like `ml_guard`.** `ml.holdout_windows(id,
   name, scope_kind ∈ {days, shop, experiment_arm}, shop_id null, date_from, date_to,
   experiment_id null, arm null, models text[], status ∈ {pending, frozen, used},
   registered_at, frozen_at, fingerprint_sha256, used_at jsonb (model → version, metric, date))`.
   Rules ported from `ml_guard.py`, not reinvented:
   - registered **before** the data exists (future days, a new shop on connect, an ADR-114 arm
     at randomisation) — `pending` already blocks;
   - `services/ml/holdout.py::assert_not_held_out(shop_id, day, arm)` is called by the builder,
     by feature selection and by model selection; rows that hit a `pending` / `frozen` window are
     refused (raise, not silently dropped — the build fails if a selection step asks for them);
   - `final_test(model_version, window, score_fn)` verifies the fingerprint, opens the window for
     that call only, records the result in `used_at`, and refuses a second successful call for
     the same model key; when every listed model has scored, the window becomes `used` and is
     ordinary training data;
   - a scored prediction must be pre-registered (`register_prediction`, D51.6) — its file hash
     sits in `used_at`.
   - Default schedule: one rolling `days` window per quarter (the last 28 days before a build are
     not held out; the window is the next 28 days, registered at build time), one `shop` window
     per new-shop cohort, and every ADR-114 control arm. Experiment control arms remain design
     information for the D10 impact reader; only model *training/selection* is blocked.

5. **A variable-role catalogue with an automated test.** `services/ml/roles.py`:
   `VARIABLE_ROLES: dict["<table>.<column>" | "<derived>", Role]`, `Role(kind, known_at_rule,
   note)`, `kind ∈ {input, context, outcome, priority, leakage_risk, idea}` — the D53.3 vocabulary
   from `v03/leakage.py` with `input` = sim-pilot `feature` and an explicit `leakage_risk` for
   columns that are post-treatment or revised after the fact (e.g. `products.sold_count`,
   review counts after the change, `impact_readings.*`, `run_measurement_finals.*`,
   `lever_calibrations.coefficient` unless replayed as-of). `ROLES_VERSION` is its hash and goes
   into every manifest. Rules: `outcome`, `priority`, `idea` and `leakage_risk` never enter a model
   as inputs; `context` may be a covariate but never a lever.

### Part B — the model gate (D70.13)

6. **Model versions are stored in `ml.model_versions`** (non-tenant, `juli_ops`):
   `(model_key, version)` PK, `artifact_uri` (archive store `ml/models/<key>/<version>/`),
   `artifact_sha256`, `feature_version`, `roles_version`, `train_manifest_id →
   dataset_manifests`, `offline_result jsonb`, `status ∈ {candidate, offline_passed, shadow,
   active, retired, rolled_back}`, `created_at`, `commit`. The incumbent is registered too:
   `model_key = 'lift_range'`, `version = 'd30.3-<hash of PRIOR_LIFT + shrinkage constants>'`
   (`prediction.py` gets a `PREDICTION_VERSION` constant). `lever_calibrations` stays the
   incumbent's online state; it is not a model version.

7. **Step 1 — offline gate (Gate C rule).** On the registered holdout (A.4), scored once:
   (a) the candidate beats the incumbent — and every fixed baseline in the model's contract
   (D30.3 lift range; persistence; category median) — by **ΔELPD > 2 SE**, SE clustered by shop
   (product family within a single shop, as in the funnel CONTRACT); (b) **empirical coverage of
   the nominal 90 % interval** on held-out outcomes: point ≥ 0.80 and the binomial 95 % upper
   bound ≥ 0.90 (not demonstrably under-covering), reported per readiness level and per shop-size
   tier, so a new-shop failure like E7 is visible; (c) the role test (A.5) and the leakage test
   (Verification) pass for its manifest. Result → `model_versions.offline_result`;
   `status = offline_passed`. Thresholds are config (`ml_gate.yaml`), changed only by the owner.

8. **Step 2 — shadow on real shops.** An `offline_passed` version is assigned `stage = shadow`
   (B.9). At every proposal for an assigned shop it runs next to the incumbent and writes a
   `card_events` row `event_type = 'shadow'` (ADR-107 amendment) with its prediction / ranking,
   interval and `feature_snapshot_id`; `actor = 'system'`; never shown, never sent to the card
   surface. A shadow row may have `card_id` NULL (the model proposed something the rules did not):
   then `shadow_subject` + `paired_card_id null`; a CHECK allows NULL `card_id` only for
   `shadow`. Duration N weeks is computed at shadow start from expected final readings
   (ADR-107 measurement plan): the smallest N with enough readings to estimate coverage ±5 pts
   and the step-1 ΔELPD at 80 % power, min 2, max 8; stored on the assignment and never
   extended after data is seen. Shadow is scored like step 1 on the shadow period.

9. **Step 3 — rollout by qualifying group; others stay on rules.** `ml.model_assignments(id,
   model_key, version, stage ∈ {shadow, active}, scope_kind ∈ {shop, category, shop_group},
   scope_value, min_readiness smallint, approved_by, approved_at, starts_at, ends_at,
   end_reason)`; one open assignment per (model_key, scope, stage). Resolution for a shop:
   shop > shop_group > category > none = rules (incumbent). A group qualifies when its shadow
   result passes step-1 thresholds on that group's own rows. Every promotion shadow → active is
   approved by the owner in the Ops console (MIG 083) — no automatic promotion. Changes are logged
   append-only in `ml.model_assignment_events(assignment_id, event ∈ {created, promoted,
   rolled_back, ended}, reason, metrics jsonb, actor, occurred_at)`. The resolved
   `(model_key, version)` is frozen on each `proposed` event (D70.9).

10. **Readiness gates eligibility (ADR-112 L1–L3).** Training: a shop enters a dataset only from
    the day it reached **L3** (measured endpoint depth); its level is in the manifest.
    Serving: **shadow** from L1 (no exposure, builds evidence for small shops); **active** only
    for shops at ≥ `min_readiness` of the assignment, default **L2**; an L1 shop always gets the
    rules card with the "sơ bộ" label (D70.3). A shop whose level drops (token revoked, backfill
    reset) falls back to rules at its next proposal.

11. **Step 4 — monitoring and automatic rollback.** Weekly fleet job `ml-model-monitor`
    (`services/ml/gate/monitor.py`, `ops` queue) per active assignment, trailing 4 weeks:
    - **acceptance rate** from `card_events` (approved ÷ approved + dismissed + expired) vs the
      same group on rules over the shadow baseline; drop > 10 pts with ≥ 30 decisions;
    - **measured impact**: pooled effect per `change_kind` (ADR-107 `change_kind_pooled_effects`,
      ADR-077 DiD, ADR-114 randomised arms when present) significantly negative;
    - **interval coverage**: binomial 95 % upper bound < 0.90 on ≥ 20 final readings.
    Any breach → the assignment ends with `end_reason`, the previous active version for that scope
    (or rules) resumes, `rolled_back` assignment event + model status, an alert through
    `services/alerts` (rule `ml_model_rollback`), and an Ops-console row. Re-promotion needs a new
    owner approval. The incumbent D30.3 is monitored by the same job (coverage only), so the bar
    a challenger must clear is measured, not assumed.

## Consequences

**Positive**
- Any training row can be rebuilt bit-for-bit from bronze + manifest; leakage becomes a CI failure
  instead of a review finding.
- The research discipline (`ml_guard`, Gate C, data roles) moves into the product unchanged in
  meaning, so a model promoted in juli-sim-pilot and one promoted in Juli face the same bar.
- D30.3 gets its first honest scorecard (coverage) before any challenger exists.
- One shop's bad model cannot reach other shops: assignments are scoped and roll back alone.

**Negative**
- More storage: one feature snapshot per proposal (incl. shadow), a revisions side-table, Parquet
  datasets. Bounded by proposals/day and the 7-day revision window.
- Shadow scoring only sees outcomes of cards that were executed (rules cards); a shadow proposal
  the rules never made has no outcome. Coverage and ELPD are therefore computed on the executed
  subset; ranking quality needs ADR-114 arms. Stated in every gate report.
- Holdouts delay learning (a window is training data only after it is `used`).

**Follow-ups**
- P1: feature-snapshot writer + `ml_feature_snapshots` columns with `card_events` (corrected P1-5).
- P7 (D70.16): `services/ml/{dataset,features,holdout,roles,gate}/`, `ml` schema tables,
  revisions table, `ml-dataset-build` / `ml-model-monitor` jobs, Ops console pages, `PREDICTION_VERSION`.
- Confirm that `run_measurement_finals` holds every `lever_calibrations` update since MIG 080
  (replay = current value); if not, start a `lever_calibration_history` now.
- Runbook (D15): "roll back a model by hand", "re-register a holdout", "rebuild from manifest".

## Owner flags (conflicts with what the branch has)

- MIG 046 grants `UPDATE` on `gold.ml_feature_snapshots`; this ADR revokes it (append-only).
- ADR-107 says `card_id → action_cards` is required; shadow rows need NULL `card_id` (CHECK-limited
  to `event_type = 'shadow'`). Coordinate with the ADR-107 amendment.
- `analytics_performance_intervals` loses earlier-known values on re-pull; the revisions table is
  the fix until D5 silver (ADR-113) replaces it. Until then, datasets with cut-offs before the
  revisions table existed use bronze where present and are marked `pit_exact = false` in the manifest.
- Thresholds in B.7/B.8/B.11 (0.80, 10 pts, 30 / 20 readings, 2–8 weeks) are proposed defaults.

## Alternatives considered (grill options not taken)

- **Train on current silver, rely on reviews to catch leakage** — no known-at; revisions and
  post-treatment counts leak silently (sim-pilot E5 is the precedent).
- **Holdout by random row split** — leaks across days and shops; sim-pilot E1–E3 showed reused
  holdouts read optimistic.
- **Keep the registry in juli-sim-pilot only** — product data would not be guarded where it is
  built; the backend must enforce it.
- **Switch a model on fleet-wide after offline pass** — skips shadow; E7 shows offline success on
  one population does not transfer to new shops.
- **Automatic promotion on thresholds** — rejected: the owner approves every promotion; only
  rollback is automatic.

## Verification

D15 layers (ADR-112):
- **(6) Leakage** — `tests/ml/test_point_in_time.py`: build features at cut-off t on a fixture
  shop, insert / revise every source with `known_at > t`, rebuild, assert identical
  `content_sha256`; `tests/ml/test_variable_roles.py`: every column in a feature definition has a
  role, no `outcome / priority / idea / leakage_risk` as input, and (real Postgres, schema
  introspection) every column of every table the builder reads is registered — a new column
  without a role fails CI.
- **Holdout** — port of `test_ml_guard.py`: pending blocks, fingerprint mismatch raises, second
  `final_test` refused, `used` window readable; builder raises on a held-out shop / arm.
- **(2) Real Postgres** — two-tenant RLS on `gold.ml_feature_snapshots` (incl. UPDATE denied),
  `juli_app` has no access to schema `ml`, unique snapshot per card, revisions PK idempotent,
  shadow-row CHECK.
- **Reproducibility** — rebuild from a manifest on a fixture DB gives the same hash.
- **Gate / monitor** — pure unit tests on synthetic readings: 2-SE rule, coverage bounds, N-weeks,
  each breach triggers rollback to the previous version, not to rules, when one exists.
- CI tier: DB invariants in the Postgres (`migration_heavy`-marked where they migrate) issue tier;
  the rest in the default unit tier.
