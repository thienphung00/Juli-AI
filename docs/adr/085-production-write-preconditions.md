# ADR-085: Production-write preconditions — tenant isolation that denies, adversarial proof, and one authorized mutation

**Status:** Proposed
**Date:** 2026-08-25
**Deciders:** grill-with-docs (Architect) with owner

**Amends:** [ADR-061](061-first-user-security-baseline.md) decision 1's RLS deferral
(the trigger it named has fired). **Builds on:**
[ADR-068](068-agent-workflow-execution-boundary.md) (production reads / sandbox writes,
and its 2026-08-11 amendment making production writes the target state),
[ADR-070](070-agent-safe-sanitization-contract.md) (sanitizer chokepoints),
[ADR-075](075-agent-approval-gate-and-security-prerequisites.md) decisions 4–5 (abuse
limits, the six-layer injection posture, and the RLS deferral's *hard trigger*),
[ADR-077](077-incremental-impact-measurement.md) (confidence tiers, the suppressed
vocabulary), [ADR-081](081-refresh-token-rotation.md) (credential lifecycle).
**Scope:** Phase 11d / P-PROD / W7 of [`PLAN.md`](../product/agent-workflow-execution/PLAN.md).

## Context

Gate [#1226](https://github.com/thienphung00/Juli-AI/issues/1226)'s observation-2 record
of 2026-08-25 states the unlock chain in the owner's own words:

> functional RLS → manual red-team pass → an explicit owner authorization for a single
> production mutation on a listing of the owner's choosing → T+7 elapsed →
> `run_daily_impact_reader` produces a real value + confidence tier.

Three links in that chain are owner acts. Two are engineering, and both are larger and
differently shaped than the roadmap assumed. This ADR records what the codebase actually
says, because in four consecutive waves the difference between the plan and the code has
been where the defects lived.

**Finding 1 — the existing RLS policies could not deny anything even if they were
reached, and they are not reached.** Ten policies exist across migrations 001, 002, 017,
019, 020, 022 and 024. Every one keys off `current_setting('app.current_user_id')`. A
repo-wide search finds **no `set_config` and no `SET LOCAL app.current_user_id` anywhere
in `backend/src`** — the only `SET LOCAL` statements in the tree are `lock_timeout` and
`statement_timeout` in `services/agent/runner/ledger.py`. The GUC has never been set, so
the policies have never scoped a row; ADR-061 already recorded this and chose to treat
them as non-functional.

**Finding 2 — even a correct policy would be bypassed, because the application is the
table owner.** Migration `032_close_public_schema_defaults`'s own docstring states it:
*"The backend's own connection is unaffected: it authenticates as the Supabase pooler
`postgres` role."* `infra/scripts/env/api.env.example:16` confirms the shape. Postgres
does not apply row-level policies to a table's owner unless `FORCE ROW LEVEL SECURITY`
is set. So adding policies while the runtime connects as `postgres` produces a green
migration, a green test suite, and **zero enforcement** — precisely the failure shape
the W5 gate found three times (a boot check that asserts a secret is present rather than
usable; a suite that mints its own HS256 tokens against an ES256 provider).

**Finding 3 — "RLS across the 13 tables" is stale as a unit of work.** ADR-061 counted
thirteen unprotected `public` tables in August. `models.py` now declares **37 tables**
across `public`, `bronze`, `silver`, `ops` and `gold`, and migrations 033–041 added six
more after that audit (`impact_readings`, `workflow_runs`, `workflow_run_events`,
`run_confirmations`, and columns on others). ADR-061's own lesson — *"the controls that
survived were the ones expressed as defaults; the ones expressed as conventions
rotted"* — applies to the fix as much as to the decay: a scope expressed as a number is
already wrong.

**Finding 4 — five tenant-scoped tables have no tenant column.**
`workflow_run_events` and `run_confirmations` reach a shop only through `workflow_runs`;
`impact_readings` only through `tool_executions`; `action_card_approvals` only through
`action_cards`; `webhook_raw_events` has no shop lineage at all — only a nullable,
un-keyed `tiktok_shop_id` string, which is exactly why ADR-061 said RLS was
"inexpressible" for it.

**Finding 5 — the machinery the owner's signature is supposed to authorize does not
exist.** ADR-068's amendment says the flip "remains a guard-configuration/capability-grant
change". Today that is true in the weakest sense: `is_sandbox_write_allowed` /
`is_production_read_allowed` in `integrations/tiktok/capabilities.py` are path
allow-lists, and there is no artifact anywhere that represents *"the owner authorized
this specific mutation on this specific listing."* An authorization that exists only as
a sentence in a GitHub comment is not a precondition a program can fail closed on.

**Finding 6 — the impact reader is complete and correctly pessimistic.**
`workers/impact_reader/pipeline.py` is scheduled (`daily-impact-reader`, 03:00 UTC,
after the 02:00 backfill top-up), computes both `preliminary` (T+7) and `final` (T+14)
kinds, and maps `below_floor` to a persisted `suppressed`. Nothing is missing for it to
produce a row — except a production mutation on a shop with analytics history. What *is*
missing is a way to know **before** authorizing a mutation whether the chosen listing can
yield a non-suppressed reading at all, and a guarantee that a `suppressed` row is never
counted as a reading downstream.

## Decision

### 1. Functional RLS means a non-owner runtime role, not more policies

The wave introduces a **`juli_app` runtime role** that owns nothing, is granted exactly
the privileges the application needs, and is the role the API and workers connect as.
Policies then apply because the connecting role is not the owner — no `FORCE ROW LEVEL
SECURITY` is required, and the owner path (`alembic`, admin, break-glass) keeps working
unchanged.

The migration creates a **`NOLOGIN` role and its grants only**. The login role is granted
membership out of band, so no credential enters git and no migration can mint one.

*Rejected:* adding policies while staying on `postgres` — a green migration with zero
enforcement, the exact class of defect this wave exists to close. *Rejected:*
`FORCE ROW LEVEL SECURITY` on `postgres` — it would break every migration and every
admin query, and it makes the safety property depend on remembering to exempt the right
sessions. *Rejected:* ADR-061's "RLS on `gold` only, keyed to `auth.uid()`, when
client-direct reads ship" — that deferral was scoped to PostgREST, and migration 032
revoked `anon`/`authenticated` from `public` entirely, so there is no client-direct path
left for it to defend. The blocker on record is about **the agent write path holding real
seller data**, which is a server-side connection, and only decision 1 addresses it.

### 2. Tenant identity is a transaction-scoped GUC, deny-by-default in SQL and fail-closed in Python

Two settings, set with `SET LOCAL` inside the unit of work: `app.current_user_id` for
user-scoped tables and **`app.current_shop_id`** for the shop-scoped majority. Shop-scoped
policies compare `shop_id = current_setting('app.current_shop_id', true)::uuid`
directly — an index-sargable predicate on columns that are already indexed — instead of
the existing per-row `EXISTS (SELECT 1 FROM shops WHERE user_id = …)` join, which would
put a correlated subquery in front of every row of every hot analytics table.

`missing_ok = true` is deliberate: with the GUC unset, `current_setting` returns NULL,
the comparison is NULL, and the policy **denies** rather than raising. Pair that with a
Python-side assertion at the unit-of-work seam that raises a *named* error before the
query is issued. The pairing matters: SQL-side denial alone would make a missing tenant
context look like an empty result set, which is the worst available failure mode — it
reads as "this seller has no data."

Genuinely fleet-wide work (the beat tasks: reconcile, backfill top-up, impact reader,
reaper, credential refresh) runs under a single named, logged escape — an explicit
`system_scope()` context, not the absence of a scope. An unscoped transaction that has
not opted in is a bug and fails.

The seam is `database/database.py` plus a request/task-scoped context. **It is not
`core/security/dependencies.py`** — the tenant is read from the already-resolved
`get_active_shop` result, so W6's `#1313` keeps sole ownership of the auth dependency
module.

*Rejected:* passing the tenant as a query parameter everywhere — that is what the service
layer already does, and it is the posture the blocker says is insufficient. *Rejected:*
`SET` (session-scoped) rather than `SET LOCAL` — with a connection pool that leaks one
tenant's scope into the next tenant's checkout.

### 3. Coverage is enumerated from the catalog, never from a list

The isolation proof reads `information_schema` / `pg_catalog` at test time, classifies
every table as tenant-scoped-direct, tenant-scoped-via-parent, or non-tenant, and asserts
the correct treatment for each. **A new table lands failing** unless it is protected or
explicitly classified. This is the only form of the fix that does not rot, and it is the
direct application of ADR-061's finding that two unprotected tables landed *during* the
audit that discovered the problem.

Child tables without a tenant column (`workflow_run_events`, `run_confirmations`,
`impact_readings`, `action_card_approvals`) are covered by a policy with an `EXISTS` on
their parent, keyed on the parent's indexed primary key. They are always accessed through
that parent in practice, so the cost is one indexed lookup. **No `shop_id` is
denormalized onto them** — duplicating a tenancy fact creates a drift surface, and a
drifting tenancy fact is a cross-tenant leak.

`webhook_raw_events` has no tenant lineage and therefore gets **no tenant-scoped read
grant** to `juli_app` — `INSERT` for the ingest path only. A table with no tenant column
does not get a policy that pretends otherwise. Adding a tenant column is deferred behind
its own trigger.

### 4. The cutover is a reversible role swap, and the capability flip cannot outrun it

Enabling RLS and creating the role changes nothing about how the deployed system behaves,
because the deployed system still connects as `postgres`. Isolation becomes real at the
moment `DATABASE_URL` names `juli_app` — one environment change, reversible in one
environment change, with the old role still valid. That is deliberate: it makes the
riskiest step the cheapest one to undo, and it keeps the whole wave AFK-completable up to
a single owner action.

To stop the two from being flipped in the wrong order, `assert_agent_runtime_config()`
gains a seventh check: **when the production-write capability is enabled, the process must
verify at boot that its own connection is not a table owner and that RLS is enabled on
every table the catalog classifies as tenant-scoped — otherwise it refuses to start,
naming the check.** The "functional RLS" precondition stops being a promise on a
checklist and becomes a condition the program tests about itself. This is check 6's
existing pattern (production-write capability ⇒ zero unauthenticated route groups)
extended to the precondition that actually matters.

### 5. The manual red-team pass is a gate observation; this wave ships what makes it worth doing

A person probing a system is not an engineering deliverable and cannot be scheduled as
one. What *can* be built, entirely AFK, is everything that makes the manual pass cheap,
targeted and non-repeating:

- **A committed threat model with a machine-checked surface inventory.** Every `/v1/*`
  route and every registered agent tool must appear in the model or CI fails. A threat
  model that can silently omit the surface added last week is a document, not a control.
- **The adversarial corpus becomes a behaviour suite.** `#1218` proved the sanitizer
  neutralizes strings. This wave asserts **behaviour invariance through the scripted
  loop** for all six ADR-075 layers: instruction-bearing vendor text, tool-shaped JSON in
  product fields, invisible-Unicode and bidi payloads, homoglyphs, seller notes
  requesting tool unlocks, and — new — attempts to reach a write outside the playbook
  allow-list, to alter params after the confirmation hash, and to exfiltrate credentials
  or endpoints into output.
- **A cross-tenant probe enumerated from the route table**, asserting 404 (never 403,
  never 200) for every id-taking route, so new routes are covered by default rather than
  by memory.
- **Abuse-limit verification as deployed behaviour**, including the two asymmetries the
  module documents: fail-closed on a Redis outage for approve/confirmation/SSE, and
  cancel structurally exempt because it is the safety valve.

The pass itself, and its findings, are gate observations.

### 6. Per-mutation owner authorization is a row, single-use and expiring — not a sentence

A `production_write_authorizations` row carries `{shop_id, tiktok_product_id,
mutation_kind, authorized_by, reason, expires_at, consumed_at, consumed_by_run_id}`. The
WRITE tool refuses unless a matching **unconsumed, unexpired** row exists for exactly the
shop, product and mutation kind it is about to perform. Issuing the row verifies the
capability binding through `services/tiktok/credential_binding.verify_capability_binding`
first, so an authorization can never be issued against a mis-provisioned credential —
the `#1290` failure ("the product belongs to another seller") becomes impossible to
authorize rather than merely impossible to execute.

This is what converts the owner's decision into a fail-closed code path. It is also what
makes "one listing, one mutation" enforceable rather than aspirational: the blast radius
of an authorization is one row.

*Rejected:* a boolean env var — it authorizes every listing forever and cannot express
"a listing of the owner's choosing". *Rejected:* an allow-list in config — same problem
with a longer edit cycle, and no consumption record.

### 7. The capability flip is a four-precondition resolver with a no-deploy kill switch

`PRODUCTION_WRITE` resolves only when all four hold: the flag is on; a matching
authorization row exists; the RLS boot assertion of decision 4 passed; and a red-team
attestation is recorded for the **deployed release sha**. Each of the four, individually
unmet, refuses with its own named reason and its own test. Default is off.

The kill switch is checked **per tool call**, not at boot, so it takes effect without a
deploy or a restart — the one control whose value is entirely in its latency. Every
production-write attempt, allowed or refused, appends an audit row naming the
authorization that permitted it or the precondition that blocked it.

### 8. A reading is honest at both ends

*Before the write:* a readiness check answers, for a given shop and listing, whether the
pre-window has enough daily rows and a viable control set for a T+7 reading to land above
the confidence floor. The owner runs it before choosing a listing. Without it, the chain
`authorize → wait seven days → discover the reading is suppressed` is a week-long
round trip to no information.

*After the write:* the reader keeps persisting `suppressed` and `confounded` honestly —
that is the correct behaviour and ADR-077 designed it. The rule this wave adds is at the
**read** end: no surface, report or metric that answers "what was the impact" may count a
`suppressed` or `confounded` row as a reading, and the query that closes the gate returns
zero rows when only suppressed rows exist. #1226 forbids closing on a suppressed reading
by name; this makes it structurally hard rather than merely forbidden.

### 9. ADR-050 C2 leaves W7

`PLAN.md` lists "the ADR-050 C2 data dependencies (per-shop analytics topup, OAuth→signals
cold start, 7D bootstrap)" in W7. It does not belong: C2 is a **cold-start fleet engine**
for onboarding many shops, it is nowhere on #1226's chain, and folding it in roughly
doubles the wave while mixing two unrelated deliverables. The one C2-adjacent fact that
*is* on the chain — the production shop needs analytics depth for a T+7 reading — is
already served by the existing single-shop `analytics-backfill-topup` beat and is verified
empirically by decision 8's readiness check.

C2 is deferred with a trigger: **a second live merchant connects, or W8's business-impact
metric needs readings from more than one shop.**

## Consequences

- **Positive:** tenant isolation stops depending on every future author remembering, and
  the capability flip becomes impossible to perform against an unisolated database.
- **Positive:** the owner's authorization becomes auditable, single-use and bounded to one
  listing, so "one production mutation" is a fact the database can prove afterwards.
- **Positive:** the wave is fully AFK up to three owner acts, all of which are gate
  observations — which answers the W6 architect's recorded objection directly.
- **Negative:** the `EXISTS`-on-parent policies add an indexed lookup per row on four
  child tables. Bounded, but it must be measured, not assumed — hence the `EXPLAIN`
  assertion in the NFRs.
- **Negative:** the role cutover is the one step no test can fully derisk, because CI's
  database is not production's. It is mitigated by being a one-line, one-line-reversible
  environment change with the previous role still valid.
- **Deferred:** a tenant column on `webhook_raw_events`; `gold` RLS keyed to `auth.uid()`
  for client-direct reads (ADR-061's 3.5-C deferral, untouched — this wave does not
  re-open the Data API); the GA per-shop credential model; ADR-050 C2.

## Options considered

| Alternative | Why rejected |
| --- | --- |
| Add policies, keep connecting as `postgres` | Owner bypasses RLS. A green migration and zero enforcement — the defect class of the last four waves |
| `FORCE ROW LEVEL SECURITY` on the owner | Breaks migrations and admin access; makes safety depend on exempting the right sessions correctly, forever |
| Denormalize `shop_id` onto the four child tables | A duplicated tenancy fact that can drift, and a drifting tenancy fact is a cross-tenant leak |
| Scope the wave as "RLS on the 13 tables" | The count was already stale before planning started (37 tables now); a scope expressed as a number rots the same way the convention did |
| A boolean `PRODUCTION_WRITE_ENABLED` | Authorizes every listing forever; cannot express "a listing of the owner's choosing"; no consumption record |
| Schedule the manual red-team pass as an implementation issue | It is a person's judgement, not code. It becomes a gate observation; the harness that aims it is the issue |
| Keep ADR-050 C2 in W7 | Doubles the wave, unrelated deliverable, nowhere on #1226's chain |

## References

- Gate [#1226](https://github.com/thienphung00/Juli-AI/issues/1226) — observation-2 record, 2026-08-25
- [ADR-061](061-first-user-security-baseline.md) §1, §2, "Deferred"
- [ADR-075](075-agent-approval-gate-and-security-prerequisites.md) decisions 4, 5, 6
- [ADR-068](068-agent-workflow-execution-boundary.md) + 2026-08-11 amendment
- [ADR-077](077-incremental-impact-measurement.md) decisions 2, 5
- `backend/src/juli_backend/database/migrations/versions/032_close_public_schema_defaults.py` (module docstring — the pooler `postgres` role)
- `backend/src/juli_backend/workers/impact_reader/pipeline.py` (`_PERSISTED_CONFIDENCE`)
- `backend/src/juli_backend/services/tiktok/credential_binding.py` (`verify_capability_binding`)
