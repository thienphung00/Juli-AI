# Contracts for running W8, W9 and W10 as parallel agent loops

Written 2026-09-07, after the W7 cutover. Every item below is a rule that was
*earned* — each one cost real time in the W7-bis loop, and each is stated with
the evidence rather than as style advice.

**Read this before starting a W8/W9/W10 slice.** It is not a process document.
It is a list of the specific ways work in this repo silently produces a wrong
green.

---

## 1. Lane assignment — what may run in parallel

From #1620's dependency map, verified 2026-09-07:

```
W8            (#1652; slices #1653-#1657, gate #1658)   no W6/W7 dependency  -> STARTABLE NOW
W9-A/P-SHARED (#1620)                                    day one, serial      -> STARTABLE NOW
W9-C/P-CAPTURE (#1622)                                   day one, HITL        -> owner
W9-D/P-UI-V1  (#1623)                                    needs W6 run view    -> BLOCKED by W6
W10-A/B/C     (#1624/#1625/#1626)                        need W9 slices       -> BLOCKED by W9
Definition of done (ALL)                                 #1339 gate           -> release gate
```

**The gate is a release gate, not a build gate.** W9 and W10 can be built while
#1339 is open; nothing in them can be called *done* until it closes.

### One writer per path

One task, one worktree, one writer. Concurrent agents must have **disjoint write
paths**. A read-only agent needs an explicit prohibition on `worktree remove`,
`branch -d`, `clean`, `commit`, `push`, `checkout` — the tool list alone does not
convey it.

Never `git checkout`, `reset` or `stash` in the primary working directory.

---

## 2. The scope rule (the W7 lesson, generalised)

**A session that opens its own connection inherits no tenant scope and must take
one.**

Three production defects in one day, each hidden behind the last, all the same
root and each found only because someone actually exercised the surface:

| | read | when | symptom |
|---|---|---|---|
| #1691 | `users` | before the request scope exists | `401 User not found` |
| #1697 | `shops` | before the request scope exists | `403 Shop not accessible` |
| #1700 | `workflow_run_events` | after it, on a **different session** | `200` with **zero bytes** |

The first two are *pre-scope bootstrap* reads and are bounded at two. The third
is a different class and was not covered by that reasoning — a stream
deliberately uses its own session factory because "the request session closes too
early", and that new session never inherited the scope.

**Before writing any repository read, ask which session it runs on and whether
that session has a scope.** If the code opens `async with session_factory()`,
the answer is no.

### The worst failure shape

`#1700` returned `HTTP 200` with an empty body. Nothing raised, nothing logged an
error, and the client rendered an empty timeline that looked like truth. When you
add a scope parameter, make it **required, not optional** — an optional one
defaults to no scope and reproduces exactly this.

---

## 3. Implementation contract

### A test that has not been seen to fail proves nothing

Every regression test must be verified RED against the defect, then green with
the fix. Concretely: revert the fix, run the test, record the failure count, put
the fix back.

This caught real problems repeatedly. On #1683 only ONE of three new tests went
red — the other two passed against the unfixed code and were kept as contracts
with the module docstring saying so, rather than being presented as proof.

### Doubles must honour the real contract

- A `**kwargs` double proves routing, not that the real call would work. Bind to
  the real signature.
- A hand-rolled double omitted `structured_log_fields`, which the orchestrator
  calls — replaced with the real `CallBudgetGovernor`.
- A call-counting double could not express #1673 at all: "`mark_failed` was
  called" stayed true throughout the outage. Model flush/rollback/commit
  semantics when the bug is about transactions.
- Prefer the REAL collaborator over a fake. #1691's first test asserted against a
  hand-written fake repo — it only proved the fake did what the fake was written
  to do.

### The substrate has to be able to see the defect

SQLite does not enforce `TIMESTAMP WITHOUT TIME ZONE`, so #1675 was invisible to
the unit suite by construction. Epic #175's registered lock says it directly:
*match the column's declared tz-awareness exactly; regression tests must run
against real Postgres/asyncpg.*

If a test calls `create_all`, give it its **own disposable database**. Doing that
on the shared CI database leaves tables with no `alembic_version` row, which is
what produces `DuplicateTable` in a later stage.

### An ORM cache can hide a policy

Checking RLS twice in one session returned a cached object and read as "the
policy is not enforced". **Use a fresh session per assertion** when testing
isolation.

---

## 4. Review contract

A review that only reads the diff will pass all three W7 defects. Check:

1. **Did the test go red against the defect?** Ask for the failure output.
2. **Which session does each new read run on, and is it scoped?**
3. **Does the substrate enforce the constraint under test?** (SQLite vs Postgres)
4. **Is the claim narrower than the evidence?** "Verified" must name what was run.
5. **Does an empty result mean success or denial?** If they are
   indistinguishable, the check is unfalsifiable and must be rewritten.

Point 5 has bitten twice. `list_demo_runs` catches every exception and returns
`{"data": []}`, so an empty list is identical to an RLS refusal. #1339 had to be
amended once for the same reason: it originally required verifying behaviour
"under `system_scope()`", a function with **zero callers** — so the condition
could never be observed either way.

---

## 5. Tooling traps that produce false readings

Each of these reported something untrue during the W7-bis loop.

| trap | what happened | do instead |
|---|---|---|
| `journalctl --since "today HH:MM"` | matched nothing while the data was there; reported a beat as never having fired | `--since "-3h"` |
| `pgrep -f <script>` | matched its own SSH command string; reported a dead probe as running | `ps -eo cmd \| grep -c '[s]cript'` |
| Local file copied into a worktree | primary dir was 26 commits behind; a docs PR showed **84 deletions** and would have reverted someone's work | `git show origin/main:<path>`, then check `--stat` shows insertions only |
| `nohup ... &` over SSH | died with the session; the "armed" watcher never ran | `setsid ... < /dev/null & disown`, then verify by output |
| Debt ratchet | the detector scans **comment text** — a comment naming a rule code creates the identity it describes | reword; never regenerate the baseline to pass |
| Golden fixture | running the unit suite rewrites `optimize_product_confirm_pause.json` in place (#1677) | `git checkout --` it before staging; never commit it |
| A method named `list` | shadows the builtin for every annotation BELOW it in the class body; mypy infers `list?[X]` and the error surfaces in a **different module** | `builtins.list[X]` |

---

## 6. Measuring production without breaking it

**Manual diagnostics against production tables can take a beat down.** Two issues
(#1676, #1681) were filed as production bugs and had to be withdrawn: the cause
was diagnostic activity contending with production writers on
`analytics_performance_intervals`.

- Check what the measurement itself costs before attributing what it finds.
- Schedule around known beats. The hourly reconcile runs at `:00`–`:02`; trigger
  manual work at `:03`+.
- A journal-derived "nothing was running" is only ever a claim about *scheduled*
  work. It cannot see manual runs, and using it to disprove contention is invalid
  — that mistake was made and published before being caught.

**Merged is not fixed.** Confirm the deployed sha carries the change
(`readlink -f /root/releases/current`, then grep the symbol) before believing a
fix is live.

---

## 7. Per-issue gate checklist

Nothing merges without all of these:

```bash
python agent-runtime/scripts/meta_prepare_executor.py --issue <N>   # readyForExecutor: true
ruff check backend tests && ruff format --check backend tests
mypy backend/src/juli_backend --ignore-missing-imports --disable-error-code=valid-type
pytest tests/unit/test_ratchets.py tests/unit/test_test_quality.py -q   # slow; needs --timeout=600
python agent-runtime/scripts/ci/generate_status_records.py
python agent-runtime/scripts/ci/check_artifact_retention_guard.py --issue <N>   # PASS
```

Never `git add -f` anything under `agent-runtime/artifacts/{reviews,
implementations,intent-reviews,validation,optimization}/`. They are gitignored by
design; `tests/unit/test_status_record_gate.py` fails CI on any tracked JSON there.

The ratchet and corpus tests exceed the default 30s pytest timeout under load.
That is slowness, not failure — re-run with `--timeout=600` before diagnosing.

---

## 8. What "done" means while #1339 is open

A W8/W9/W10 slice may be **implemented, reviewed, merged and deployed** while the
gate is open. It may not be called *done*: #1620's map makes the definition of
done for all of W9 and W10 depend on #1339 and #1469 (#1469 is closed; #1339 is
not).

Say "merged and deployed, gate pending" rather than "done". The distinction is
the whole point of a gate.
