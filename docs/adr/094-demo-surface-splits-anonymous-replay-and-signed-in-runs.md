# ADR-094: The demo surface splits — anonymous replay without persistence, real runs behind sign-in

**Status:** Accepted
**Date:** 2026-09-07
**Deciders:** owner, with a Claude Code session
**Amends:** [ADR-084](084-agent-demo-surface-tenancy-and-replay.md) decisions 1 and 2
(which themselves amend [ADR-076](076-agent-demo-execution-experience.md) decisions 1, 2, 4).
**Builds on:** [ADR-075](075-agent-approval-gate-and-security-prerequisites.md) (JWT on every
agent route — reaffirmed here, not weakened), [ADR-074](074-agent-event-streaming-and-relay.md)
(event union, replay authority).
**Design spec:** [`PUI-DESIGN.md`](../product/agent-workflow-execution/PUI-DESIGN.md) — still
the wireframe, stage-model, motion and copy authority.
**Scope:** W6 / PRD #1308, Demo Launch.

## Context

ADR-084 settled the demo surface on 2026-08-25: a seeded demo tenant, an anonymous Supabase
session scoped to it, and golden scenarios replayed through the real streaming endpoint as
real `workflow_run_events` rows. Every visitor — anonymous or signed in — was to transact
against real persistence.

Implementing that stalled on three things. None is an engineering defect; all three were
verified against the deployed system and `origin/main` on 2026-09-07.

1. **Identity linking has no answer at this layer (#1353).** `workflow_runs` has no user
   column — a run belongs to a shop, and read access goes through `get_active_shop`. The
   demo tenant is *deliberately shared* across all visitors, so "your runs" is not a
   well-defined subset of it. The three available options were a schema change in a lane
   with no migration authority, a tenancy leak (a linked user reading every other visitor's
   runs), or a silent descope. ADR-084 did not foresee that its own shared-tenant decision
   made its own linking requirement undefinable.

2. **The anonymous session's precondition was never met.** Supabase anonymous sign-in is an
   owner console action. `GET /auth/v1/settings` on the deployed project reports
   `"anonymous_users": false`.

3. **The seeded tenant does not exist in production and nothing would create it.**
   `seed_demo_tenant()` is on `origin/main` with unit tests
   (`tests/unit/test_demo_tenant_seed.py`) and **no caller anywhere** under
   `backend/src/juli_backend` — no startup hook, no CLI, no migration. `DEMO_SHOP_ID` is
   unset on the deployed host, which by ADR-084 decision 1 means the anonymous path is
   required to fail loudly. #1312 shipped a producer that nothing invokes.

Meanwhile `apps/demo` on `origin/main` is *already* a zero-database, zero-auth surface:
`lib/mock-data.ts` holds hand-authored content, `components/demo-state.tsx` declares
`mode: "mock"` as its only mode and keeps mutable state in `localStorage`, and
`lib/agent-event-stream.ts` — the real SSE transport — carries a docstring stating that
nothing under `apps/demo` imports it. ADR-084 decision 2 planned to delete that mock. The
Demo Launch needs a visitor-facing surface sooner than that deletion can be paid for.

## Decision

1. **The anonymous entry is a client replay with no persistence.** "Dùng thử Demo" mints no
   session, calls no authenticated route, creates no `auth.users` row, and writes nothing to
   Postgres. It renders captured content in the browser so a visitor can feel how the
   product works. ADR-084 decision 1's anonymous JWT scoped to a demo tenant is **withdrawn**.

   This is *safer* than what it replaces, not a relaxation. The failure ADR-084 was written
   to prevent (#1283) was an **unauthenticated route serving a live merchant's data**. A
   surface with no route and no database connection cannot reproduce it. ADR-075 is
   untouched and unweakened: every agent route still requires a JWT, and the anonymous
   surface reaches no agent route at all.

   *Rejected:* keeping the anonymous Supabase session purely to satisfy ADR-084's wording —
   it costs an owner console action, an abuse surface that mints a real user row per visitor,
   and an unbounded `auth.users` table, all to authenticate a caller that reads nothing.

2. **The seeded demo tenant is a capture source, not a runtime tenant.** #1312's seed exists
   so a real run can be executed against synthetic data and captured for replay. It is
   **not** required in production, and `DEMO_SHOP_ID` becomes a capture-environment setting
   rather than a production one. This retires finding 3 above as a blocker: the missing
   production caller is no longer a gap, because production is no longer where the seed
   needs to run.

3. **Signed-in users get real sessions, real persistence, and real runs on their own shop.**
   "Đăng nhập với Google" goes through Supabase Auth's Google provider to a real, distinct
   identity with a real database row. Their runs execute against **their own connected
   shop** — never the demo tenant, which is synthetic capture material and nobody's business.

   **Sequencing, stated plainly because it constrains the launch.** A real run needs a
   connected shop, and no seller-facing connect flow exists: `api/routes/auth_tiktok.py`
   exposes only a public `/callback` taking no authenticated user, so it binds no shop to a
   signed-in identity. Therefore:

   - **At Demo Launch** the signed-in path delivers a real session, a real user row, and a
     connect-shop screen that states its actual state honestly — no control implying a
     working merchant exchange that is not wired.
   - **Real runs on the seller's own shop follow when connect-shop lands**, as a named
     follow-up rather than an implied capability.

4. **Supabase anonymous sign-in is not a prerequisite for anything in W6.** The owner action
   recorded in `docs/handoffs/owner-hitl-queue.md` §5a is withdrawn. §5b (the Google provider
   plus a GCP OAuth client) becomes the **only** Supabase Auth prerequisite for the Demo
   Launch, and therefore the critical path.

5. **Replay drift is an accepted cost, bounded and time-boxed.** ADR-084 decision 2's
   prohibition on hand-authored event JSON **stands unchanged for anything the server
   serves**: no hand-authored row ever enters `workflow_run_events`. It is relaxed for the
   client replay only, which may ship for launch from `mock-data.ts`.

   The cost is real and is named here rather than discovered later: a hand-maintained second
   source drifts from the first while both suites stay green — the defect class behind six
   W3 post-merge fixes. Two mitigations bound it. First, the replay is no longer pretending
   to be the authenticated product; the signed-in path is where truth is demonstrated.
   Second, replacing `mock-data.ts` with tool-captured, contract-validated scenarios (#1311)
   is recorded as the follow-up, with an explicit trigger: **the first time the replay and
   the real product visibly disagree, or the first external demo where that disagreement
   would matter.**

## Rationale

*Extracted during the W6→main reconcile to satisfy `check_adr`, which requires a
`## Rationale` heading (#1853). Nothing below is new reasoning — it summarises what
this ADR already argues in the section named, which remains the fuller account.*

From **Context**: ADR-084 settled the demo surface on 2026-08-25 as a seeded
demo tenant with an anonymous Supabase session scoped to it, replaying golden
scenarios through the real streaming endpoint as real `workflow_run_events` rows
— *every* visitor, anonymous or signed in, transacting against real persistence.
Splitting the surface removes the anonymous visitor from that path entirely,
which is what lets the replay door call nothing at all.

## Consequences

- **#1353 is dissolved, not answered.** With no anonymous persistence there are no anonymous
  runs to preserve across identity linking. The question stops existing rather than getting
  one of its three unsatisfying answers.
- **#1313 collapses.** Anonymous JWT verification, demo-tenant scoping, 404-never-403, and
  per-user-session rate buckets all describe a session this ADR removes. The issue is
  rescoped or closed; what survives of it belongs to the signed-in path.
- **#1319's acceptance criteria are rewritten.** Its bar "both entries produce a real
  session; neither creates an unauthenticated path" no longer holds: the demo entry is now
  *deliberately* sessionless and dataless, and the honest statement of that is the criterion.
  Its linking criterion goes with #1353.
- **`apps/demo/MODULE.md` stays true, where ADR-084 would have retired it.** "Mock is the
  only enabled mode" and sign-in that "never routes or requests data" remain accurate for the
  anonymous surface; the sign-in claim is what changes when the Google door lands.
- **The Demo Launch depends on one owner action.** §5b — a GCP OAuth client and the Supabase
  Google provider. Nothing else in this shape needs a console.
- **The demo can lie, and we have said so.** Decision 5 makes that a recorded, triggered
  debt rather than an accident. Anyone reading the demo as evidence of product behaviour
  should read the signed-in path instead.

## Evidence

Verified 2026-09-07 against the deployed Supabase project and `origin/main`:

| Claim | How verified |
|---|---|
| Anonymous sign-in disabled | `GET /auth/v1/settings` → `"anonymous_users": false` |
| Google provider unconfigured | same response → `"google": false` |
| `DEMO_SHOP_ID` unset in production | `/etc/juli/api.env` on the deployed host |
| `seed_demo_tenant()` has no production caller | grep over `backend/src/juli_backend`; only `tests/unit/test_demo_tenant_seed.py` references it |
| Demo app is mock-only | `demo-state.tsx` (`mode: "mock"`, sole variant), `mock-data.ts`, `agent-event-stream.ts` docstring |
| No seller-facing connect flow | `api/routes/auth_tiktok.py` — public `/callback` only, no authenticated-user dependency |
| `workflow_runs` has no user column | #1353, verified against the model |
