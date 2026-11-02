# ADR-118: A Shopee shop runs the Analyze → Recommend → Execute → Measure loop through proposal records an operator writes, the client approves and a person executes

**Status:** Accepted (owner, 2026-11-02)
**Date:** 2026-11-02
**Related ADRs / decisions:** ADR-116 (client / public lanes, consent), ADR-117 (Shopee files through
the ingest gateway; `lever_plans`, `kpi_*` Ops tables), D10 (Terms acceptance grants consent),
D13 (Juli never writes promotions), D25 (Juli Ops), D42 G4 (contract terms and forecasts never shown
to a seller).
Owner decisions 2026-11-02 (this session): proposals live in new tables keyed on Shopee items, not in
`action_cards`; the client's representative approves **in the app**; until that ships, approvals arrive
by email and documents and the operator records them; Ory's data consent comes from connecting the shop
and accepting the Terms in the app, not from a contract row; exports are pulled every Monday and before
and after each test wave.

## Context

Ory (Shopee) is under contract, but Juli has no Shopee Open Platform access: data arrives only as
Seller Centre exports pulled through a sub-account (ADR-117), and every change on the shop is made by
the client's representative by hand. The loop runs today outside Juli: findings from
`juli-client-ops/tools/*.py`, recommendations as documents, approvals by email, an empty
`approval_log.csv`, no record of execution, results in the KPI appendix.

Juli's own loop is TikTok-shaped end to end (code read 2026-11-02):

- Recommendations are `action_cards` keyed on `products.id`; `products.tiktok_product_id` is NOT NULL
  and ADR-117 rejected widening it. Approval (`services/agent/approval.py`) creates a `workflow_runs`
  row that needs a TikTok product.
- Execution is the TikTok write path; the only manual mode is the promotion lever flow
  (`waiting_external` → "Tôi đã áp dụng" → read-only TikTok verify), with no executor identity or evidence.
- Measurement (`run_baselines`, `services/lever_flows/measurement.py`) reads TikTok analytics tables.
- Ops can create experiment groups (`POST /v1/ops/shops/{id}/groups`) but cannot create a proposal,
  record an approval or record an execution.

The goal is to run the real Ory loop inside Juli now, so that Open Platform access later changes only
the data source and the executor, not the records.

## Decision

### 1. Four tables, client lane, tenant-direct (RLS on `app.current_shop_id`)

The representative reads and approves proposals, so they are tenant rows (ADR-116), not Ops-only.
Expected effects and forecasts stay in the Ops-only `lever_plans` / `kpi_forecasts` (D42 G4); a
proposal may point at a `lever_plans` row but a seller never reads it.

- **`shop_proposals`**: `id`, `shop_id`, `platform`, `cycle` (e.g. "2026-11 Đợt 1"), `kind`
  (title, price, voucher, flash_sale, ads, bundle, program, stock, other), `subject_type`
  (item, shop, campaign), `item_id` (the platform item id, string, as in `platform_items`; NULL for
  shop / campaign), `subject_label`, `change_before` / `change_after` (JSON, seller-readable), `reason`
  (seller-readable text), `planned_start`, `status`, `revision`, `supersedes_id`, `lever_plan_id`
  (nullable), `proposed_by_staff_id`, `created_at`, `updated_at`.
- **`shop_proposal_approvals`** (append-only): `proposal_id`, `decision` (approved, rejected,
  changes_requested), `channel` (in_app, email, document), `decided_by_user_id` (in_app) or
  `recorded_by_staff_id` (email / document), `evidence_ref` (required unless in_app: a pointer to the
  archived email or signed document, never the content), `proposal_snapshot` (the exact text the client
  approved), `note`, `decided_at`.
- **`shop_proposal_executions`** (append-only): `proposal_id`, `executed_at`, `executor_role`
  (client_representative, juli_operator, platform_api), `executed_by_user_id` (nullable),
  `recorded_by_staff_id` / `recorded_by_user_id`, `channel`, `evidence_ref`, `verified_at`,
  `verified_how` (export_readback, sub_account_read, api), `verified_state` (JSON). No personal names:
  a person is a Juli user id or a role.
- **`shop_proposal_results`**: `proposal_id`, `method` (pre_post_vs_untested, contract_kpi), `metric`,
  `pre_from` / `pre_to` / `post_from` / `post_to`, `value`, `comparison`, `band`, `verdict`
  (dat, khong_dat, chua_ket_luan), `data_through` (last export day used), `computed_at`, `job_version`.

Status moves only forward through the service: draft → sent → approved / rejected /
changes_requested → executed → measured; withdrawn from any state before executed. A changed proposal
is a new revision (`supersedes_id`), never an edit after it was sent.

### 2. Who writes what

| Action | Today (first cycle) | When in-app approval ships | With Open Platform |
|---|---|---|---|
| Create / send proposal | Operator in Ops (`POST /v1/ops/shops/{id}/proposals`, role operator, `ops_audit_log`) | same | same, or generated from analysis |
| Approve | Operator records the email / document approval (`channel` email or document, `evidence_ref` required) | Representative presses approve / reject in the app (`channel=in_app`, own user id) | same |
| Execute | Representative changes the shop; operator records it (`executor_role=client_representative`) | Representative records it in the app | Juli writes via the write path (`executor_role=platform_api`) |
| Verify | Next Monday export read back (`verified_how=export_readback`) | same | API read |
| Measure | Job over `platform_daily_metrics` → `shop_proposal_results` | same | same table, API rows |

### 3. Measurement

Day 0 is the verified `executed_at`. Two methods, matching what is promised to the client:
per proposal, item impressions / clicks / CTR in the 7 days after vs. the 7 days before, against
untested items in the same cycle, counted only outside the weekly noise band; per contract, the
Phụ lục 01 KPIs at each milestone from `kpi_contracts` / `kpi_targets` / `kpi_exclusions` (ADR-117
step 3). The reader works on `platform_daily_metrics` only; `platform_period_metrics` is never summed by
day. A window not yet covered by an export is `chua_ket_luan`, with `data_through` stating why.

### 4. Consent and visibility

Writes need the shop's `service` consent, granted when the owner connects the shop after accepting the
Terms (D10; `POST /v1/shops/shopee` grants it since 2026-11-02). The representative sees proposals,
approvals, executions and results for their own shop; never `lever_plans`, `kpi_forecasts`, contract
terms or other shops.

## Consequences

- The Ory cycle is recorded in Juli from the first wave; `approval_log.csv` is replaced by
  `shop_proposal_approvals` (a one-off import carries any rows written before).
- Nothing TikTok changes. Converting proposals into `action_cards` is a later mapping, once a Shopee
  product model exists.
- Build order: migration 109 + models + Ops endpoints (record cycle) → measurement job (with ADR-117
  step 3) → Ops cycle page → seller approve endpoint and screen.

## Alternatives rejected

- **Widen `action_cards` / `products` to Shopee.** Touches every TikTok path; ADR-117 already rejected
  widening `products`.
- **Ops-only proposal tables.** The representative could never approve in the app.
- **Keep approvals in email only.** Leaves the contract's per-change approval outside Juli and unauditable.
