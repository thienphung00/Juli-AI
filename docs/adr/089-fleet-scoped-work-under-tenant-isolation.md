# ADR-089: Fleet-scoped work under tenant isolation

**Status:** Proposed

**Supersedes/amends:** Amends ADR-086 (the runtime database role) by answering a question it
did not ask. Constrains #1339 observation 1 and the W7-bis work that follows it.

## Context

ADR-086 established that tenant isolation is a property of the connection: the runtime connects
as `juli_app`, a non-owner role without `BYPASSRLS`, and every unit of work sets the tenant
identity with `SET LOCAL` inside its transaction (decision 6).

It says nothing about work that has no tenant. The words "system scope", "fleet", "beat",
"background" and "worker" do not appear in it. Five Celery beat tasks are exactly that work:

| task | what it is for |
|---|---|
| `credential_refresh_beat` | refresh vendor tokens expiring across the fleet |
| `impact_reader` | compute `impact_readings` for every measurable execution (ADR-077) |
| `reaper` | terminate runs past their wall-clock timeout (enumerates `workflow_runs` fleet-wide; see the correction in decision 5) |
| `analytics_backfill_topup` | daily top-up (single reference shop) |
| `mock_analytics_reconcile` | demo reconcile |

They call `system_scope()`, which is a Python module global and a log line:

```python
async def system_scope(session, caller):
    global _system_scope_active
    _system_scope_active = True
    logger.info("system_scope_enter", extra={"caller": caller})
    yield
```

It issues no `set_config`, no `SET ROLE`, no SQL. Its only effect is to suppress
`TenantContextRequiredError` in `_apply_tenant_context_to_session` — an application-layer check.

**`system_scope`'s correctness has never rested on that flag.** It rested on the connection
being `postgres`, the table owner, which Postgres exempts from row-level security by default.
The flag and the database agree today by coincidence. After #1339 observation 1 cuts
`DATABASE_URL` over to `juli_app`, they diverge: the application check is bypassed, the database
still enforces RLS, and no tenant context is set.

Measured against production at alembic head `049_drop_legacy_isolation` on 2026-09-01:

- 166 RLS policies, **zero** of which permit a read without a tenant context
- `tiktok_credentials`, which `credential_refresh_beat` reads, has RLS enabled and 4 policies

So after the cutover each of those tasks reads **zero rows** from every policied table.

### Why this is worse than an error

#1467 corrects a separate defect in which the policies raise on an empty-string GUC. That fix is
independently right, and it converts these reads from an error into a clean `0`.

For a tenant request with no context, `0` is correct. For a fleet-wide task it is a silent
failure: the task completes, raises nothing, reports success, and does nothing. Tokens quietly
stop being refreshed; impact readings stop being produced; the reaper stops reaping.

That is ADR-086's own "a denial is indistinguishable from data loss" hazard, one layer up from
where ADR-086 discusses it — and it means **fixing #1467 makes #1339 observation 1's fourth
confirmation easier to pass while making the failure harder to see.** "The beat tasks complete a
cycle under `system_scope()` without a scoping error" is satisfied by a cycle that errors on
nothing because it processed nothing.

## Decision

1. **`system_scope()` stops being a database-layer claim, because it never was one.** It remains
   an application-layer marker that suppresses the tenant-context requirement. It is renamed or
   documented so that nothing reads it as conferring database access. No policy will ever consult
   a GUC that the application sets to describe its own privilege.

2. **Fleet-scoped work runs under real per-tenant context for every data access.** A beat task
   enumerates the identifiers it must act on, then loops, setting the tenant context for each
   item exactly as a request does. The per-item work is then subject to the same isolation as
   user traffic, and the two-tenant proof covers it without a special case.

3. **The only cross-tenant read is enumeration, and it returns identifiers.** Where a task
   genuinely cannot know its work list without looking across tenants, it obtains it from a
   `SECURITY DEFINER` function that returns identifiers and scheduling metadata only — shop id,
   run or execution id, a timestamp — and never tenant data: no credentials, no PII, no
   analytics values, no payloads.

4. **Each such function is a reviewed, named exemption.** One function per enumeration, owned by
   a role with the necessary access, `EXECUTE` granted to `juli_app`, and its returned column
   list asserted by a test. A function that returns a row type wider than identifiers is a
   defect, not a convenience.

5. **A task that does not need a cross-tenant read does not get one.**
   `analytics_backfill_topup` runs for a single reference shop and needs no exemption at all.
   The exemption list is justified per task, not granted to "the beat lane".

   **Correction, 2026-09-01.** This decision originally also named `reaper` as needing no
   exemption, on the grounds that it takes run identifiers from Celery. That is wrong, and the
   error is recorded rather than quietly deleted because it is the kind that widens an
   exemption list by accident. `_reap_stale_running_and_queued` enumerates from the database,
   fleet-wide and unfiltered:

   ```python
   stmt = select(WorkflowRun).where(WorkflowRun.status.in_(active_statuses))
   ```

   Celery's `active`/`reserved`/`scheduled` inspection is the *liveness probe* applied to each
   candidate run (`_default_has_live_task(run_id)`), not the source of the work list. The
   original claim came from reading the probe and inferring the enumeration.

   `reaper` therefore needs an enumeration exemption on the same terms as
   `credential_refresh_beat` and `impact_reader`: a `SECURITY DEFINER` function returning run
   ids, their shop ids and the timestamps the staleness comparison needs — never payloads or
   event bodies. Only `analytics_backfill_topup` is exempt from needing an exemption.

6. **`BYPASSRLS` is not granted to any role the application connects as.** ADR-086 decision 1
   names owner-exemption and `BYPASSRLS` as the two ways to escape row policies; W7 removed the
   first. Restoring the second on the worker connection would return the fleet to a bypassable
   database while the boot check (#1330) is asked to make an exception for it — which #1339
   forbids in terms: "what is not legitimate is leaving the host on `juli_app` with a control
   disabled to make something work."

### What the enumerations actually look like

Verified against `origin/main` and against production's `pg_policies` on 2026-09-01, because
the shape of the exemption depends on it.

**`impact_reader`.** `load_measurable_executions` is:

```python
stmt = select(ToolExecution).where(
    ToolExecution.status == TERMINAL_SUCCEEDED,
    ToolExecution.tool_name.in_(measurable_tool_names()),
)
return result.scalars().all()
```

Full ORM rows, every tenant, no `LIMIT` and no date bound — even though the caller immediately
discards rows whose elapse boundary has not passed. Of that row the pipeline uses `updated_at`,
`id`, `shop_id`, `payload_json` and `tool_name`, and only the first three at enumeration time.

So the exemption narrows to `(id, shop_id)` — or `(id, shop_id, updated_at::date)` if the
elapse gate and the anti-join against already-written readings move into the function's `WHERE`
clause, which they can. That turns "every succeeded tool execution in the fleet, in full" into
"the ids of executions with a genuinely pending reading". `payload_json` is then fetched
per-execution under ordinary tenant context.

**Writing the readings needs no second exemption.** `impact_readings` has no `shop_id` column;
its policies reach tenancy through the parent:

```sql
EXISTS (SELECT 1 FROM tool_executions
         WHERE tool_executions.id = impact_readings.tool_execution_id
           AND tool_executions.shop_id = current_setting('app.current_shop_id', true)::uuid)
```

Setting `app.current_shop_id` to the enumerated execution's shop satisfies the read and the
write. This is the case that makes decision 2 workable rather than merely principled: the
per-item loop is enough, and no part of the write path needs to escape RLS.

**Two idempotency helpers are keyed by `tool_execution_id` alone** —
`load_written_kinds` and `load_existing_metric_pairs` — so they are not shop-filtered as
written. Their blast radius is one execution rather than the fleet, and under per-execution
context they resolve through the same parent join. They need no exemption, only the context the
loop already sets.

**`credential_refresh_beat`** takes the same shape: `list_expiring_within()` fleet-wide, then a
loop that is already per-credential.

## Consequences

- Each of the five tasks needs a per-item context loop. The work is a loop-body change, not a
  rewrite: `impact_reader` already passes `execution.shop_id` to its per-execution helpers and
  simply never sets the GUC, and `credential_refresh_beat` already iterates a list.
- The cross-tenant surface shrinks from "every row in every policied table" to "a list of
  identifiers", which is auditable in a way the former is not.
- A `SECURITY DEFINER` function is a privilege boundary and must be written as one: fixed
  `search_path`, no dynamic SQL, arguments that cannot widen the result set.
- Fleet tasks become slower — one context set per item rather than one scan. For daily beats
  this is not a meaningful cost; if a future task needs high-volume fleet access, it is a new
  decision rather than a reason to widen these.
- **#1339 observation 1's fourth confirmation cannot pass until this lands.** It should be
  recorded as diagnosed-and-deferred rather than attempted, because the failure is silent and
  attempting it in production teaches less than the static diagnosis already has.

## Options considered

**Grant `BYPASSRLS` to a dedicated worker role.** One attribute, no code change — and the reason
it is rejected is not purity. The worker connection runs agent code that processes untrusted
vendor content; it is the last connection that should hold an unconditional exemption. It also
re-opens the second of the two escapes ADR-086 named, and would require carving an exception in
#1330's boot check.

**A policy predicated on an `app.system_scope` GUC.** Elegant in outline and unsound in detail:
`juli_app` can set that GUC itself, so any code path — or any injection — can assert
`system_scope = on` and read every tenant. It converts row-level security into an honour system
administered by the role it constrains.

**`SECURITY DEFINER` for every fleet query.** Correct, and heavier than needed. Confining the
exemption to enumeration achieves the same isolation with a handful of functions rather than one
per query, and keeps the actual data reads under ordinary tenant context where the existing
proof already covers them.

**Run beat tasks as the owner on a second connection.** Preserves today's behaviour exactly, and
preserves today's problem: a permanently bypassable connection held open by the worker, which is
what W7 exists to remove. It also splits the runtime across two isolation models, so the boot
check can no longer answer "is this database bypassable" with one answer.
