# ADR-086: The runtime database role, and why tenant isolation is a connection property

**Status:** Proposed
**Date:** 2026-08-26
**Supersedes/amends:** none. Constrains W7-A (#1326, #1327, #1328, #1329, #1330).

## Context

W7 was planned on the premise, recorded in `docs/handoffs/w7-production-readiness.md`, that
the deployed runtime "authenticates as the Supabase pooler `postgres` role, which owns the
tables and is therefore exempt from row policies entirely". That premise is true but
incomplete, and the incomplete half changes what the wave can promise.

Verified against the deployed project on 2026-08-26:

| Fact | Value |
|---|---|
| Connected role | `postgres` (via `aws-1-us-west-2.pooler.supabase.com:5432`, session mode) |
| `rolsuper` | `f` |
| `rolbypassrls` | **`t`** |
| Member of | `service_role` (itself `BYPASSRLS`), `pg_read_all_data`, `authenticator`, … |
| Owns | **all 33** tables in `public` |
| Tables with RLS enabled | **14**, one policy each, **`relforcerowsecurity = f` on every one** |
| `juli_app` | does not exist |

Postgres exempts a role from row policies for two *independent* reasons: a table's owner is
exempt by default, and a role holding `BYPASSRLS` is exempt unconditionally.
`FORCE ROW LEVEL SECURITY` removes the first exemption. **It does not affect the second.**

The runtime role holds both. Removing the attribute requires `ALTER ROLE postgres NOBYPASSRLS`,
which is superuser-only; the project connects as a non-superuser and `supabase_admin` is not
ours to drive on a managed Supabase project.

Two queries establish the state, and the second is the proof:

```
select current_setting('app.current_user_id');
ERROR:  unrecognized configuration parameter "app.current_user_id"

select count(*) from products;
120
```

If the `products_isolation` policy were being evaluated, the second query would raise the same
error as the first, because the policy dereferences that unset setting. It returns rows instead.
The policies are not failing closed — they are not running. Separately, `grep` finds no writer
of `app.current_user_id` anywhere in `backend/src`; only the migrations that define the policies
and the tests asserting their text mention it.

## Decision

1. **The owner path is permanently bypassable, and we say so.** No change in this repository can
   make a connection as `postgres` subject to row policies on this project. Tenant isolation is
   therefore a property of *which role a process connected as*, not a property the database
   enforces uniformly.

2. **`#1330`'s boot check refuses to start** when the connected role owns tables in `public` or
   carries `rolbypassrls`, in production configurations. This is the enforceable form of the
   guarantee, it costs one catalog query, and it fails at boot rather than during a cross-tenant
   read.

3. **Connection strings are split by purpose.** The application environment carries only the
   `juli_app` URL. The owner URL is reserved for Alembic and operator tooling and is kept out of
   the app's environment. `#1326`'s grant map is written against this split.

4. **`FORCE ROW LEVEL SECURITY` is applied to the tenant-column tables**, on the narrower
   justification that if `juli_app` ever creates a table it becomes that table's owner and would
   be exempt on it. Insurance against ownership drift, not a fix for the `postgres` path.
   This does **not** reopen ADR-085's rejected option "`FORCE ROW LEVEL SECURITY` on the
   owner": that alternative proposed FORCE as the constraint on `postgres`, which this ADR
   shows cannot work at all, since `FORCE` does not touch a `BYPASSRLS` role. ADR-085's
   rejection stands on stronger grounds than it knew.

5. **`#1326` adds `ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public`.** Migrations run
   as the owner, so every future table would otherwise be invisible to `juli_app` and each new
   migration would silently break the runtime.

6. **The tenant identity is set with `SET LOCAL`, inside the transaction.** The project is on the
   pooler in session mode (port 5432), where a plain `SET` would persist on the pooled connection
   and leak one tenant's identity into the next request that reuses it. Port 6543
   (transaction mode) is open on the same host, so this is one config change away from being live.
   `services/agent/runner/ledger.py:312` already establishes the transaction-scoped seam.

7. **`juli_app` is provisioned in-repo as `NOLOGIN`; `LOGIN` is granted out of band.** Migration
   043 creates the role behind a `DO $$ … IF NOT EXISTS … $$` guard — roles are cluster-global
   while migrations are per-database, so an unguarded `CREATE ROLE` fails on the second database
   in the cluster — and carries the whole grant map idempotently. One out-of-band step grants
   `LOGIN` with a password and writes the URL into `/etc/juli/api.env`. The rejected alternative,
   a "console-managed" role, is not a Supabase feature: there is no custom-role UI, so it means
   the same SQL typed by hand into the SQL editor, unversioned and unreviewable. The forgotten
   second step is loud rather than silent, because decision 2's boot check turns it into a failure
   to start.

8. **The grant is DML-only.** `SELECT, INSERT, UPDATE, DELETE` on the tenant tables, `USAGE,
   SELECT` on sequences, `USAGE` on the schema — no `CREATE`, no `ALL`, no `TRUNCATE`, no
   ownership. Supabase's own custom-role guide (`docs/guides/database/prisma`) grants
   `create on schema public` and `all on all tables` because Prisma creates shadow databases for
   its own migrations; Alembic does not, since it runs as the owner. Taking the vendor snippet
   verbatim would leave the role that must not own objects one `CREATE TABLE` away from owning
   one.

   The pooler supports this: Supabase documents custom roles through Supavisor as
   `postgres://<role>.<PROJECT-REF>@<region>.pooler.supabase.com:5432`, and recommends a custom
   role over `postgres` for security and observability. No probe of the deployed project was
   needed to establish it.

## Consequences

- Gate #1339 observation 1 can honestly claim isolation for connections made as `juli_app`, and
  must not claim the database enforces it against every connection. The attestation wording
  follows this ADR, not the handoff's original premise.
- `#1329`'s "enumerate from `pg_catalog`" approach is load-bearing rather than stylistic: the
  handoff's hardcoded counts were already stale (14 policies, not 10; 33 tables, not `models.py`'s
  37).
- A misconfigured deploy will not start. For this check that is the intended behaviour.
- **`juli_app`'s attributes are asserted, never assumed.** The project runs PostgreSQL 17.6, where the PG16 `CREATEROLE` reform lets a role confer attributes it holds itself — and `postgres` holds both `CREATEROLE` and `BYPASSRLS`. A `juli_app` minted by the owner is therefore *capable* of carrying bypass. `#1329`'s proof reads `rolbypassrls`, `rolsuper` and table ownership for the runtime role out of `pg_catalog` and fails on any of them, rather than relying on the grant being impossible.
- Backfill migrations touching a forced table must set the tenant GUC or toggle `NO FORCE` around
  themselves. DDL is unaffected, so most of Alembic is untouched.
- **W6 collision: the demo tenant is not owned by its visitors.** `services/seeds/demo_tenant.py`
  gives the demo shop a single deterministic `user_id`, while ADR-084 d.1 and
  `core/security/dependencies.py:65` give every anonymous visitor a *distinct* `users` row.
  Once #1327 sets the tenant identity and #1328 makes the policies deny, the demo returns
  zero rows for every visitor — silently, as an empty dashboard. #1328 must carry an
  explicitly named policy admitting the seeded `DEMO_SHOP_ID` for anonymous identities.
  Note this is invisible to the W6/W7 disjointness contract, which enumerates *files*: the
  two waves touch disjoint paths and collide only in runtime semantics.
- **Policy shape is a performance decision, not only a correctness one.** The existing
  policies read `shop_id IN (SELECT id FROM shops WHERE user_id = current_setting(…)::uuid)`,
  a subquery re-evaluated per row scanned. #1328 should wrap the lookup in a `STABLE`
  function so the planner hoists it once per statement. Denormalising the tenancy column
  onto child tables is the other standard fix and is **not** available here: ADR-085
  rejected it as "a duplicated tenancy fact that can drift, and a drifting tenancy fact is a
  cross-tenant leak", and pairs its `EXISTS`-on-parent policies with an `EXPLAIN` assertion
  in the NFRs. Decided at rewrite time, not discovered under load.
- The 5 tables with no tenant column (`workflow_run_events`, `run_confirmations`,
  `impact_readings`, `action_card_approvals`, `webhook_raw_events`) remain an open question for
  `#1328`: policed by joining to a parent, or explicitly out of scope with a recorded reason.

## Options considered

**Transfer table ownership away from `postgres`.** Rejected: `BYPASSRLS` on the role survives it,
so the bypass remains and the migration story gets worse.

**`FORCE ROW LEVEL SECURITY` as the primary control.** Rejected as primary: it closes the owner
exemption while `BYPASSRLS` keeps the door open, which would have produced a guarantee that reads
stronger than it is. Retained as secondary per decision 4.

**Warn instead of refusing at boot.** Rejected: the failure this prevents is a silent cross-tenant
read, and a warning in a log nobody reads at deploy time is how ADR-079-class losses happen.
