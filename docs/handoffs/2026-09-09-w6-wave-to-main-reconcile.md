# Handoff: reconcile the W6 wave with `main` (PR #1844)

For the agent or session that owns **W7 / backend**. Written to be picked up with no prior
context: ids, commands and the reasoning are inline.

**The task.** `feature/agent-w6-wave` is 120 commits behind `main` and 20 ahead. Merging
`main` into the wave produces **46 conflicts**. PR **#1844** (wave → main) is open and
cannot merge until this is done. The reconcile lands **on the wave branch**, in the shape
[#1451 / #1640] used, with the full suite green — then #1844 becomes mergeable.

**Why it is being handed over rather than done.** Six conflicts are in backend files that
W7 changed heavily on `main` — tenant scoping, the `juli_app` role cutover, RLS. Resolving
those on judgement risks silently dropping either wave's or main's work, and a half-merged
tenant-scoping change is not something CI reliably catches. The analysis below removes most
of that risk, but the verification wants someone who knows the W7 changes.

---

## The finding that shrinks this job

**No W6 feature slice touches any of the six backend files.** Their only wave-side history
is two reconcile commits:

```
576c84758  chore(wave): reconcile the W6 wave with main (#1451) (#1640)   [wave-only]
eaae4a54f  chore(wave): reconcile the W6 wave with main after W7 landed   [wave-only]
```

Both are squash-merged reconcile PRs that **replayed main's content into the wave as new
commits**, which is why they are not reachable from `main` and why they conflict. Checked
with:

```bash
base=$(git merge-base origin/feature/agent-w6-wave origin/main)
git log --no-merges --oneline $base..origin/feature/agent-w6-wave -- <file>
```

For all six backend files that returns only those two commits. Meanwhile `main` has moved
on with real fixes to the same files:

| File | main's later commits |
|---|---|
| `database/tenant_context.py` | #1693 auth reads its own user · #1666 backfill partition commits · #1599 re-enter tenant scope per stage · #1536 shop-scoped session reads own shop |
| `repositories/identity.py` | #1698 bootstrap reads own shops · #1693 · #1499 code-standard refactor |
| `api/dependencies.py` | #1698 · #1402 W7 production-write |
| `repositories/_base.py`, `api/routes/agent_runs.py`, `services/agent_runs/events.py` | 2 each, same era |

**So the expected resolution for all six is `--theirs` (main).** The wave's copy is a stale
snapshot of main's own code; main's copy is that plus the later fixes. The wave has no
feature stake to preserve.

⚠️ **Verify before trusting it.** Those reconcile commits were squashes, so they *could*
carry a conflict resolution that diverges from main rather than a clean copy. Before taking
main wholesale, confirm no W6 slice imports a symbol that only the wave's copy provides:

```bash
# after resolving, from the wave worktree
grep -rn "from juli_backend" apps/ backend/src/juli_backend/services/agent/ | grep -v __pycache__
PYTHONPATH="$PWD/backend/src" python -c "import juli_backend.api.app"   # import graph intact
```

---

## The 46 conflicts, grouped with intent

### Backend — 6 · take `main`, then verify
```
backend/src/juli_backend/api/dependencies.py
backend/src/juli_backend/api/routes/agent_runs.py
backend/src/juli_backend/database/tenant_context.py
backend/src/juli_backend/repositories/_base.py
backend/src/juli_backend/repositories/identity.py
backend/src/juli_backend/services/agent_runs/events.py
```
Per the finding above. `api/routes/agent_runs.py` shows `172+/1034-` on the wave side —
that is the wave holding an older, larger version, not the wave deleting main's work.

### `apps/demo` — 6 · take the **wave** (this is W6's own surface)
```
apps/demo/MODULE.md
apps/demo/src/app/globals.css
apps/demo/src/components/in-progress-panel.tsx
apps/demo/src/lib/run-surface/use-run-stream.ts
apps/demo/src/lib/run-surface/__tests__/use-run-stream.test.tsx
apps/demo/src/__tests__/run-ledger-panel.test.tsx
```
`in-progress-panel.tsx` and `use-run-stream.ts` carry #1836 and #1752 respectively and are
the wave's substance. **Do not take main's copy of these** — main predates the replay work
entirely. If main has independent edits here, reconcile by hand and keep both.

### Tests — 10 · read each; most are additive on both sides
```
tests/integration/test_agent_events_streaming_matrix.py
tests/unit/test_agent_run_event_stream.py  test_command_subsumption_provider.py
tests/unit/test_impact_honesty.py          test_implementation_artifact.py
tests/unit/test_negative_dataset.py        test_ratchets.py
tests/unit/test_status_record_gate.py      test_test_quality.py
tests/unit/test_three_tier_ci_contract.py
```
`test_test_quality.py` is an **add/add** conflict — both sides created it independently;
merge the two bodies rather than choosing.

### `eval/` — 6 · main's, unless the wave changed scoring deliberately
```
eval/baselines/debt_ratchet_baseline.json  eval/curate_negatives.py
eval/fixtures/parent-cache.template.json   eval/gate_scoring.py
eval/negative_dataset.py                   eval/quality_detectors.py
```
`debt_ratchet_baseline.json` is a ratchet — take the **stricter** value, never the looser
one, or the ratchet silently loosens.

### `agent-runtime/` — 5 · take `main` except the manifest
```
agent-runtime/config/agent-runtime.config.yml
agent-runtime/scripts/ci/capture_providers/run_metrics.py
agent-runtime/scripts/ci/generate_status_records.py
agent-runtime/scripts/ci/task_transcripts.py
agent-runtime/artifacts/waves/wave-agent-w6.json     ← see below
```

⚠️ **`wave-agent-w6.json` has now conflicted three times today.** It is a JSON array of
issue numbers, so two branches each appending one line collide every time, and a bad
resolution produces **invalid JSON** that fails `policy-checks` with a message that says
nothing about JSON. It happened on #1753 and again on #1825. Resolve by taking the **union**
and re-serialising, never by hand-patching:

```python
import json, re, pathlib
p = pathlib.Path("agent-runtime/artifacts/waves/wave-agent-w6.json")
nums = sorted({int(n) for n in re.findall(r'^\s*(1\d{3}),?\s*$', p.read_text(), re.M)})
p.write_text(json.dumps({"schemaVersion":"1.0.0","artifactType":"wave_manifest",
  "waveId":"wave-agent-w6","branch":"feature/agent-w6-wave","issues":nums}, indent=2) + "\n")
json.loads(p.read_text())   # prove it parses before committing
```
Expected union: `1272 1309 1311 1313 1314 1315 1316 1317 1318 1319 1320 1321 1451 1752 1764 1772 1836`

### Docs and skills — 13 · additive both sides, merge both
```
CONTEXT.md  dictionary.md  .gitleaksignore
.cursor/skills/domain/backend/SKILL.md  .cursor/skills/domain/data-platform/SKILL.md
docs/adr/089 091 092 093  docs/adr/README.md
docs/product/agent-workflow-execution/PLAN.md
docs/product/agent-workflow-execution/v1-workflow-spec.md
docs/security/threat-model.md
```
`docs/adr/README.md` and `PLAN.md` are append-heavy — keep both sides' rows. ADR 089/091/092/093
conflicts are almost certainly the wave holding older copies; take `main`.

---

## Verification before pushing

`pnpm check:demo` alone is **not** sufficient — that was true of every W6 slice, but this
reconcile touches the backend, so the backend suite is the point.

```bash
# from the wave worktree, PYTHONPATH pinned — an editable install elsewhere in
# .worktrees/ will otherwise resolve juli_backend to another tree and every
# result becomes unattributable (the generators refuse to run for this reason)
PYTHONPATH="$PWD/backend/src" pytest -q
ruff check backend tests scripts && ruff format --check backend tests scripts

# W6's own surface, on Node 20 via nvm — Node 26's global localStorage shadows
# jsdom's and produces false failures in files you never touched
pnpm check:demo

# the exit-gate journey: 37/37 before this reconcile. Kill any stale server on
# 3100 first or playwright.config.ts's reuseExistingServer serves an old build
lsof -ti :3100 | xargs -r kill
pnpm --filter @juli/demo exec playwright test e2e/exit-gate/ --project=desktop
```

**The two-tenant isolation proof and the RLS tests are the ones that matter most** — they are
what a wrong resolution of `tenant_context.py` would break, and they are why this is handed
to whoever owns W7.

---

## Context you should not have to reconstruct

- **PR #1844** carries the full wave inventory, the ADR-094 rescope, and the 37/37 result.
- **[ADR-094](../adr/094-demo-surface-splits-anonymous-replay-and-signed-in-runs.md)** (Accepted)
  rescoped the wave mid-flight: anonymous → client replay with no session and no database
  row; signed-in → real runs on their own shop. #1313 is closed as superseded, #1353 dissolved.
- **Three `/v1/*` leaks** were found on the replay path during the wave (#1752's confirm,
  #1772's analytics via `ImpactBlock`, #1836's ledger call). **None were caught by the static
  module-graph test** — each by the e2e journey or by reading code. Recorded as defect 4 on
  #1754: the test cannot express runtime gating, so it stays green only by omitting the
  surfaces that use it. Treat the journey as the enforcement point, not that test.
- **The release is unblocked.** It had failed three consecutive times on the additive-only
  gate refusing migration `056_series_source_column`. Run manually as a separately-operated
  step on 2026-09-09 (backup taken and verified, SQL previewed offline, single revision,
  catalog-verified). Gate now reports `ADDITIVE-ONLY: ACCEPTED — pending revisions: (none)`.
  Note `056_series_source_column.py` was copied into `~/releases/25491b06`'s `versions/`
  directory on the VPS to run it, and **deliberately left there** — removing it would leave
  alembic at a revision with no file on disk.
- **After #1844 merges**, `demo.app-juli.com` gets W6 on the next release, and **#1322** (the
  W6 HITL gate) becomes walkable for the first time. It is not walkable today: the live demo
  still serves a pre-#1319 build.
