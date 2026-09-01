# Production-Write Capability Cutover Runbook

**Scope:** Migrate the Juli-AI production database connection from the `postgres` superuser role to the `juli_app` non-owner role with explicit table grants and row-level security (RLS) enforcement.

**References:**
- ADR-085 decision 1: Non-owner runtime role with explicit grants
- ADR-085 decision 3: RLS policy enforcement for tenant isolation
- Issue #1326: Create non-owner `juli_app` role and explicit grants
- Issue #1330: Boot-time precondition check for production-write capability
- Issue #1331: Threat model and isolation proof

---

## Pre-Cutover Verification

Before beginning the cutover, verify that:

1. **RLS policies are deployed** — Run migrations 045 and 046:
   ```bash
   # On the target database (via Alembic on VPS, never locally)
   alembic upgrade head
   ```

2. **RLS is enabled on all tenant-scoped tables** — Run the verification command (see below)

3. **The `juli_app` role exists** — Migration 043 creates it; verify:
   ```sql
   SELECT rolname, rolcanlogin, rolinherit FROM pg_roles WHERE rolname = 'juli_app';
   ```
   Expected: One row with `rolcanlogin=false`, `rolinherit=true`

---

## Cutover Steps

### Step 1: Grant Membership (Out-of-Band, Owner-Only Action)

On the production database, grant the login role membership in `juli_app`. This step **cannot be performed by the `juli_app` role itself** (it has no NOLOGIN); only the database owner (postgres) or another superuser can perform it.

**On the VPS, as root or via SSH:**

```bash
# Connect as postgres (superuser)
psql -U postgres -d juli_prod

# Grant membership to the login role (replace USER with your actual login)
GRANT juli_app TO <USER>;

# Verify
SELECT *
FROM pg_auth_members
WHERE roleid = (SELECT oid FROM pg_roles WHERE rolname = 'juli_app');
```

**Expected output:** One row showing the login user as a member of `juli_app`.

### Step 2: Update DATABASE_URL Environment Variable

**This is the active cutover step.** Change the database connection to use the login role that is now a member of `juli_app`. Update the environment variable on all production hosts:

**On the VPS or via your deployment system:**

```bash
# OLD (superuser connection)
# DATABASE_URL=postgresql://postgres:<password>@<host>:5432/juli_prod

# NEW (non-owner connection via juli_app membership)
# DATABASE_URL=postgresql://<USER>:<password>@<host>:5432/juli_prod
```

Replace `<USER>` with the login role you granted `juli_app` membership to, and update `<password>` and `<host>` accordingly.

**Deployment note:** Use your deployment system (systemd, env vars, secrets manager) to update this variable across all running processes. The change takes effect on the next process restart.

### Step 3: Restart API and Worker Processes

**Order matters:** Always restart workers before the API to avoid race conditions on queued jobs.

```bash
# Restart workers first
systemctl restart juli-worker

# Wait for workers to stabilize (check logs for `assert_agent_runtime_config` PASS)
sleep 30
journalctl -u juli-worker -n 20

# Restart API
systemctl restart juli-api

# Verify both processes started successfully
systemctl status juli-api juli-worker
journalctl -u juli-api -n 20
```

If either process fails to boot, check the logs for `assert_agent_runtime_config` errors. The error message will name the specific precondition that failed.

---

## Post-Cutover Verification

### Verification Command 1: Role and Privileges

Verify that the connection is using the correct role and that RLS is in effect:

```sql
-- Run this as the connection's current role (post-cutover)
-- Expected: Current user is NOT 'postgres', but a role with juli_app membership

SELECT current_user;
-- Expected: <YOUR_LOGIN_ROLE> (not postgres)

SELECT * FROM pg_roles WHERE rolname = current_user;
-- Expected: rolcanlogin=true (this is the login role)

SELECT * FROM pg_roles WHERE rolname = 'juli_app';
-- Expected: rolcanlogin=false (this is the non-owner role)

SELECT *
FROM pg_auth_members
WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)
AND roleid = (SELECT oid FROM pg_roles WHERE rolname = 'juli_app');
-- Expected: One row showing membership in juli_app

-- Verify table ownership
SELECT
    n.nspname,
    t.relname,
    u.usename as owner_role
FROM pg_class t
JOIN pg_namespace n ON t.relnamespace = n.oid
JOIN pg_user u ON t.relowner = u.usesysid
WHERE n.nspname IN ('public', 'bronze', 'silver', 'ops', 'gold')
AND t.relkind = 'r'
AND u.usename = current_user
LIMIT 10;
-- Expected: No rows (current role should own no tables)
```

### Verification Command 2: RLS Enforcement

Verify that RLS policies are enforced for all tenant-scoped tables:

```sql
-- Run this as the connection's current role (post-cutover)
-- Verify RLS is enabled on all tenant-scoped tables

SELECT
    n.nspname,
    t.relname,
    t.relrowsecurity,
    COUNT(p.*) as policy_count
FROM pg_class t
JOIN pg_namespace n ON t.relnamespace = n.oid
LEFT JOIN pg_policy p ON p.polrelid = t.oid
WHERE (n.nspname, t.relname) IN (
    ('public', 'tiktok_credentials'),
    ('public', 'tiktok_sync_state'),
    ('public', 'orders'),
    ('public', 'order_items'),
    ('public', 'returns'),
    ('public', 'products'),
    ('public', 'inventory_items'),
    ('public', 'settlements'),
    ('public', 'creators'),
    ('public', 'livestreams'),
    ('public', 'analytics_performance_intervals'),
    ('public', 'alert_configs'),
    ('public', 'alert_history'),
    ('public', 'workflow_webhook_signals'),
    ('public', 'workflow_runs'),
    ('public', 'tool_executions'),
    ('public', 'workflow_outcome_records'),
    ('public', 'action_cards'),
    ('public', 'decision_emission_novelty_ledger'),
    ('public', 'demo_execution_records'),
    ('public', 'recommendations'),
    ('public', 'campaigns'),
    ('public', 'graph_edges'),
    ('public', 'analytics_kpi_envelopes'),
    ('silver', 'orders'),
    ('silver', 'returns'),
    ('ops', 'analytics_backfill_partitions'),
    ('gold', 'kpi_envelopes'),
    ('gold', 'ml_feature_snapshots'),
    ('bronze', 'order_raw_payloads'),
    ('bronze', 'return_raw_payloads'),
    ('bronze', 'ctor_performance_raw_payloads'),
    ('bronze', 'live_hours_raw_payloads'),
    ('public', 'processed_events'),
    ('public', 'production_write_authorizations'),
    ('public', 'workflow_run_events'),
    ('public', 'run_confirmations'),
    ('public', 'impact_readings'),
    ('public', 'action_card_approvals')
)
GROUP BY n.nspname, t.relname, t.relrowsecurity
ORDER BY n.nspname, t.relname;
-- Expected: All rows have relrowsecurity=true and policy_count >= 1
```

---

## Rollback Procedure

**Critical:** The rollback is **NOT** an `alembic downgrade`. Downgrading migrations 045 or 046 will break the deployment because the grant permissions remain in place. Instead, rollback by reverting the `DATABASE_URL` environment variable change.

### Rollback Step 1: Revert DATABASE_URL

Change the `DATABASE_URL` environment variable back to the postgres superuser connection:

```bash
# NEW (production-write-capable connection)
# DATABASE_URL=postgresql://<USER>:<password>@<host>:5432/juli_prod

# OLD (reverted to superuser)
# DATABASE_URL=postgresql://postgres:<password>@<host>:5432/juli_prod
```

Update the environment variable via your deployment system (systemd, secrets manager, etc.).

### Rollback Step 2: Restart Processes

```bash
# Restart workers first
systemctl restart juli-worker

# Wait for stability
sleep 30
journalctl -u juli-worker -n 20

# Restart API
systemctl restart juli-api

# Verify
systemctl status juli-api juli-worker
journalctl -u juli-api -n 20
```

### Rollback Step 3: (Optional) Revoke Membership

If you want to fully revert the membership grant, you can revoke it (as superuser):

```bash
# On the VPS as postgres (superuser)
psql -U postgres -d juli_prod

# Revoke membership from the login role
REVOKE juli_app FROM <USER>;
```

This is optional because the grant remains harmless if the `DATABASE_URL` uses a different role. However, for cleanliness, it's recommended to revoke it.

---

## Runbook Checklist

- [ ] Pre-cutover: Verify RLS policies deployed (migrations 045-046)
- [ ] Pre-cutover: Verify RLS enabled on all tenant tables (Verification Command 2)
- [ ] Pre-cutover: Verify `juli_app` role exists
- [ ] Step 1: Grant membership to login role (`GRANT juli_app TO <USER>`)
- [ ] Step 2: Update `DATABASE_URL` on all production hosts
- [ ] Step 3: Restart workers, then API, in order
- [ ] Step 3: Verify startup logs for `assert_agent_runtime_config` PASS
- [ ] Post-cutover: Run Verification Command 1 (role and privileges)
- [ ] Post-cutover: Run Verification Command 2 (RLS enforcement)
- [ ] Documentation: Link this runbook in the deployment guide

---

## Monitoring After Cutover

Monitor the following for the first 24 hours:

1. **Boot-time check logs** — Look for `assert_agent_runtime_config: check 7` in worker and API startup logs. Errors here indicate precondition failures.

2. **Application logs** — Look for unexpected `RelationNotFound`, `ProgrammingError`, or permission errors in the application's operation logs. These indicate that `juli_app` is missing a required grant.

3. **RLS policy enforcement** — Monitor that writes to tenant-scoped tables continue to be scoped to the correct tenant (no cross-tenant data leakage).

4. **Migration downtime** — None expected. The cutover is an environment variable change and does not require schema changes or data migration.

---

## Notes for Operations

- **The migration is additive:** Downgrades of migrations 043-046 are not the rollback. The rollback is the `DATABASE_URL` change.
- **Owner bypass still works:** The `postgres` role continues to bypass RLS (by design); use it only for admin tasks.
- **No schema changes needed:** The cutover does not require any changes to the schema after migrations 043-046 are deployed.
- **Idempotent and reversible:** The cutover can be performed multiple times; reverting `DATABASE_URL` reverts the effect.

---

## Emergency Contacts

- Database owner / production team: [contact info]
- On-call engineer: [contact info]
