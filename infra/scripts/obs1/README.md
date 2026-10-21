# Observation 1 verification (#1339)

Three read-only checks that produce the evidence Observation 1's four bullets ask for.
They mutate nothing: no writes, no role changes, no beat triggers.

Run on the VPS, with the API env loaded:

```bash
set -a; . /etc/juli/api.env; set +a
cd /root/releases/current

.venv/bin/python /root/releases/current/infra/scripts/obs1/check_runtime_role.py
.venv/bin/python /root/releases/current/infra/scripts/obs1/check_cross_tenant_isolation.py
bash /root/releases/current/infra/scripts/obs1/check_beat_cycle.sh
```

| Script | Bullet | Passes when |
|---|---|---|
| `check_runtime_role.py` | 2 | `bypassrls` is False **and** tables owned is 0 |
| `check_cross_tenant_isolation.py` | 3 | the other tenant's row counts are all 0 while own is 1 |
| `check_beat_cycle.sh` | 4 | all named beats show `ok` and scoping errors is 0 |

Bullet 1's public half is `curl` against `/health` (`/v1/demo/analytics` was retired in P61-D and answers 410). Its
authenticated half — a read, an approve, an SSE stream — needs an operator's own token
and is deliberately not scripted here.

## Two things these scripts will not do for you

**They do not trigger beats.** `daily_impact_reader` runs at 03:23 UTC, so a run before
it fires reports `NOT YET RUN` rather than a pass. That is the honest state, not a gap in
the script. (Fast track P61-D retired `analytics_backfill_topup`, the reference-shop hourly
reconcile and `GET /v1/demo/analytics`, owner D72.5.)

**`check_beat_cycle.sh` measures from the worker's last restart.** A deploy restarts the
worker, so the window resets and the daily beats read `NOT YET RUN` again until they next
fire. Read the `worker restarted at` line before reading the verdict.

## A discrepancy the record should state

Bullet 4 asks that beats "complete a cycle under `system_scope()`". `system_scope()`
(`database/tenant_context.py`) sets a Python module global and writes **no database GUC**;
its only effect is suppressing an application-level assertion, and it has **zero callers**.
Under `juli_app` it grants nothing. The beats pass by scoping per shop with
`with_shop_scope`, not by using `system_scope()` — so the bullet is met in substance but
not as worded, and the Obs 1 record should say so rather than imply the named mechanism did
the work.
