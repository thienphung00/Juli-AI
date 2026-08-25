# Handoff: W7 — the owner can authorize one real change, and prove it was safe (P-PROD)

**PRD:** #1325 · **Gate:** #1339 (HITL) · **Planned:** 2026-08-25 (Architect run; ADR-085 in PR #1340)
**Runs in parallel with W6** (PRD #1308, P-UI). Disjointness contract below is binding.

## Why this wave exists

Gate #1226 observation 2 recorded the production-write chain as blocked by owner decision, with the
unblock order: functional RLS → manual red-team pass → explicit per-mutation owner authorization →
T+7 → a real `impact_readings` row (ADR-077's still-open gate). W7 builds every AFK-engineerable
link of that chain; the three owner acts exist **only** as gate observations in #1339, each with a
recorded "legitimate result" that is not success (declining the production write is the default).

## The finding that shaped the wave

**RLS is absent while looking present.** The 10 existing policies key off
`current_setting('app.current_user_id')`, but nothing in `backend/src` ever sets it — and the
runtime authenticates as the Supabase pooler `postgres` role, which (per migration 032's own
docstring) **owns the tables and is therefore exempt from row policies entirely**. Adding policies
without changing the connection role fixes nothing. Also: `models.py` declares 37 tables (not the
13 PLAN.md assumed), and 5 of them have no tenant column to police
(`workflow_run_events`, `run_confirmations`, `impact_readings`, `action_card_approvals`,
`webhook_raw_events`).

## Issue graph

| # | Title (abbreviated) | Lane / domain | Blocked by |
|---|---|---|---|
| #1326 | `juli_app` non-owner runtime role + explicit grant map | W7-A / data-platform | — |
| #1327 | Tenant identity set per transaction, fail-closed | W7-A / backend | 1326 |
| #1328 | RLS that denies — rewrite the 10 dead policies | W7-A / data-platform | 1327 |
| #1329 | Two-tenant proof, enumerated from `pg_catalog` | W7-A / data-platform | 1328 |
| #1330 | 7th boot check: capability refuses against a bypassable DB | W7-A / backend | 1329 |
| #1331 | Threat model + generated surface inventory | W7-B / backend | — |
| #1332 | Adversarial corpus asserts loop behaviour | W7-B / backend | — |
| #1333 | Generated cross-tenant probe — 404, never 403 | W7-B / backend | 1331 |
| #1334 | Abuse limits verified, incl. cancel's exemption | W7-B / backend | — |
| #1335 | Owner authorization as a single-use row | W7-C / backend | — |
| #1336 | Four preconditions, four names, default off | W7-C / backend | 1335, 1330 |
| #1337 | No-deploy kill switch + audit of every attempt | W7-C / backend | 1336 |
| #1338 | Measurable before the write, unfabricated after | W7-D / backend | — |
| #1339 | **HITL: W7-GATE** | — | 1330, 1332, 1333, 1334, 1336, 1337, 1338 |

**Unblocked day one (6):** #1326, #1331, #1332, #1334, #1335, #1338 — each in its own worktree,
one writer per tree, Meta gate first per issue:

```bash
python agent-runtime/scripts/meta_prepare_executor.py --issue <N>   # must print readyForExecutor: true
```

Routing lanes (PR #1341): `AGT-W7A-DP`, `AGT-W7A-BE`, `AGT-W7B` (default), `AGT-W7C`, `AGT-W7D`.

## Gate #1339 — four observations, all owner-gated

1. **Role cutover** on the deployed host — a clean revert + diagnosis is a pass.
2. **Manual red-team pass** — open findings are the pass *working*; produces an attestation bound
   to the deployed release sha (read by #1336's precondition 4).
3. **Owner authorization for one production mutation** — declining is the default and a pass.
4. **T+7 impact reading** — a real value + confidence tier; a suppressed reading recorded as a
   reading is forbidden by name.

#1339 **supersedes #1226 observation 2** (comment posted there). #1226 stays open only for
observation 1 (sandbox confirm→write, pending realistic sandbox product data — owner action,
merchant `7658096633384781588`).

## Disjointness contract with W6 (binding on every W7 executor)

W7 never touches: `apps/**`, `packages/**`, `api/routes/demo_decisions.py`, the run-list route,
`services/agent/approval.py`, `services/agent/runner/core.py`, `services/agent/sanitize/**`
source, the scenario module, the demo seed, `core/security/dependencies.py`.

Serialization points (declared on the issues):
1. **Alembic linear head** — #1312 (W6) takes migration 042 if it needs one; **W7 starts at 043**
   and never reads head. An unissued 042 is a cheap gap; a branched head is an outage.
2. **`core/security/`** — W7 reads the resolved active shop at the unit-of-work seam;
   `dependencies.py` belongs to W6's #1313 and must not appear in a W7 diff.
3. **CI workflows** — W7 **appends** jobs; never string-replace into a `needs:` block
   (duplicate `- <job>` hazard, see the pr.yml needs-edit incident).

Cross-wave courtesy: #1333's generated probe automatically covers W6's new routes — a W6 route
failing it is reported against the owning W6 issue, never excluded from the probe. #1332 adds
tests/fixtures only; defects needing `runner/core.py` go to #1272.

## Open questions for the owner (answers change scope, not correctness)

1. Does `postgres` actually own the tables on the deployed Supabase project? (#1326/#1330 verify
   at runtime either way; ownership narrows the grant map if different.)
2. `juli_app` login provisioning is deliberately out of git (NOLOGIN + grants; membership granted
   out of band). Confirm vs. a Supabase-console-managed role.
3. ADR-050 C2 (fleet cold-start engine) was **removed** from W7 with a recorded trigger — it
   roughly doubles the wave. Say so if it should become a W7-bis.
4. GA per-shop credential model: assessed, **deferred** with trigger (what remains is per-shop
   `seller_connect` scoping — an architecture, not a fix).

## Merge queue at time of writing

- PR **#1340** — ADR-085 + PLAN.md W7 section (+2 stale tracker rows). Docs, fast-track.
- PR **#1341** — epic registry entry for #1325 + the 5 W7 routing lanes. Must merge before any
  W7 Meta gate runs.
- (This handoff's own PR.)

Both were verified MERGEABLE against main with #1323/#1324 already landed; no ordering constraint
between #1340 and #1341 remains, but #1341 gates W7 implementation start.
