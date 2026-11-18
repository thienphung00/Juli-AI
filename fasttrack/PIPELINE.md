# Fast-track pipeline (v2, from the batch after batch-1116a)

Source of the changes: `pipeline-eval/BASELINE-2026-11-16.md` (week-one baseline, metrics M1–M21).
This page is the single operating reference. Handoffs link to it instead of restating it.

## Flow and who decides

| Step | Who | Done when |
|---|---|---|
| 1. Grill | owner + coordinator | one question at a time, each with a recommendation, in plain chat text. Ends with an **acceptance table** (`contracts/EXECUTOR-BRIEF.md` §3) that the owner approves. No executor starts before that. |
| 2. Claim | coordinator | `state.py session`, `state.py batch <branch>`, `state.py claim-migration N` for any migration |
| 3. Slice + brief | coordinator | one brief per slice from `contracts/EXECUTOR-BRIEF.md`; `state.py ab-assign <batch> <slice>` picks arm A or B |
| 4. Build | executor (Sonnet; Opus only for migration/security/integration) | the brief's `## Sources` and acceptance rows are filled in |
| 5. Verify | **separate** verifier (arm A: `review` agent rules; arm B: read-only Sonnet verifier) | every acceptance row has evidence: test id, Chrome screenshot on the sample shop, or a SQL/API result |
| 6. Gate | GitHub | merge the current tip into the batch branch, push it, open the PR (step 7). `fasttrack-pr.yml` runs all five gate jobs on GitHub; `gate_status.py` reports VALID (via ci). A local `predeploy.sh` still counts, but is optional. |
| 7. PR | coordinator | `fasttrack/bin/open_pr.py` (public-repo scrub). The PR body lists what is **NOT** in this deploy. |
| 8. Merge | **owner** | |
| 9. Tag | **owner** | `! <worktree>/fasttrack/bin/tag-deploy.sh <sha> --session <name> --push` |
| 10. Watch + verify live | coordinator | `fasttrack/bin/deploy_watch.py <tag>` (under Monitor), then the **LIVE** acceptance row: dashboard vs a direct read-only query on the sample shop + 1 real shop. Write `DEPLOY_REPORT.md` (each check pass/fail with evidence). "Live" is said only when every check passes. |

The owner is always required for: grill approval, the acceptance table, migrations, auth, security, prod data writes, client data, PR merge, deploy tag, SSH/VPS. Everything else runs without asking.

## Skills, hooks and headless runs (active from cutover)
- **`deploy` skill:** steps 6 → 10 as one checklist, ending with `DEPLOY_REPORT.md`.
- **`fasttrack-handoff` skill:** the hand-off for a fresh session, built from `state.py show`.
- **`orchestrate-batch` skill:** one coordinator splits a batch into worktree tracks, gates each track and merges them in dependency order.
- **PreToolUse hook** (`pipeline-eval/hooks/git_gate.py`), active only once `<git common dir>/fasttrack-state/V2_ACTIVE` exists:
  - blocks `--tags` pushes;
  - blocks a direct `git push` to `fasttrack/optimize-product` (PRs only);
  - blocks hand-made `fasttrack-deploy-*` tags (use `tag-deploy.sh`);
  - blocks a `git push` while `state.py check` reports BLOCKED.
- **Restate before building:** an executor's first output is the term and scope bullets (`contracts/EXECUTOR-BRIEF.md` §2b). Terms live in `GLOSSARY.md`.
- **Headless:** `claude -p` is for scheduled or batch work (pipeline-eval weekly job, lead-gen batches). Run `fasttrack/bin/session_preflight.sh` first. Never give `-p` runs write access to prod, tags or outreach.

## Rules that replace chat coordination

- **State, not messages.** Run `fasttrack/state.py check --session <me> --branch <batch>` before rebase, push, "ready" and tag, and after every compaction. Record facts with `state.py fact` (prod migration head, Connector version, DB host) instead of putting them in memory or handoffs. Use a message only for what the state can't hold, and when you do, quote the state line.
- **"Ready" means the gate is VALID for the tree.** Never say "ready", "all checks pass" or "live" without a `gate_status.py` VALID line, or the `deploy_watch.py` success line for "live".
- **Owner commands:** use the wrappers (`pg-test.sh`, `tag-deploy.sh`, `open_pr.py`). Pipe any other command through `fasttrack/bin/cmdlint.py` before showing it.
- **Open owner questions** go in with `state.py ask` and come out with `state.py answer`. Before each reply to the owner, look at `state.py show`; any open ask is answered or re-asked first, never left buried.
- **Whole suites run on GitHub.** The deploy gate is the PR's `fasttrack-pr.yml` run, so sessions no longer queue for this machine. Locally: targeted tests and `predeploy.sh --fast`. A full local `predeploy.sh` is optional; if one runs, it runs alone (two at once took 4 h and both failed on timeouts, 2026-11-17).
- **Coordinator sessions last one batch, or ~24 h.** Hand off when the batch merges. The next session reads `state.py show` plus the handoff.

## Commands

```
PY=/Users/macos/Juli-AI-v2/juli/.venv/bin/python
$PY fasttrack/state.py show | refresh | check --session S --branch B
fasttrack/predeploy.sh [--fast | --jobs a,b | --dry-run]
$PY fasttrack/gate_status.py <sha>                               # VALID via ci (PR run) or local; --no-ci = local only
$PY fasttrack/bin/open_pr.py --head B --title T --body-file F --session S [--dry-run]
fasttrack/bin/tag-deploy.sh <sha> --session S [--push]          # --push = owner only
$PY fasttrack/bin/deploy_watch.py <tag>
fasttrack/bin/pg-test.sh tests/integration/test_x.py
echo "<command>" | $PY fasttrack/bin/cmdlint.py
fasttrack/bin/session_preflight.sh [--no-call]                   # auth / credits / headers before long or headless runs
```

State lives in `<git common dir>/fasttrack-state/` (shared by every worktree, never committed). `events.jsonl` there is the observability log, read by `pipeline-eval/extract.py`.

## Gate speed-ups, phase 1 (owner-approved 2026-11-17; trial ended 2026-11-18)

- **Trial ended (owner, 2026-11-18):** the deploy gate runs on GitHub, so local runs are optional and the 3-batch side-by-side trial would never fill. No trial run was recorded.
- **Local:** `predeploy.sh` runs the unit suite with `pytest -n 4 --dist loadfile` by default (`JULI_GATE_XDIST=1`). It gates, and it fails unless it ran exactly as many test cases as a serial collection finds. `check.sh` stays serial.
- **CI:** no xdist. The GitHub gate runs the unit suite as 4 serial shards; the two record-only trial jobs are removed from `fasttrack-deploy.yml`.
- **A test that fails only under xdist** is a real finding: it shares state across files. Fix it, or mark it to run serially. Never retry it into a pass. `JULI_GATE_XDIST=trial` runs serial + xdist side by side and `xdist_trial.py` diffs them per test case.
- **Rollback:** `JULI_GATE_XDIST=0` (serial only).
- One suite at a time on this machine; `predeploy.sh` needs ≥ 10 GB free.

## Deploy gate on GitHub, phase 2 (owner, 2026-11-17)

- **What runs:** `.github/workflows/fasttrack-pr.yml`, on every PR into `fasttrack/*`, on the PR's merge commit: `heads`, `frontend`, `static`, `backend-unit` (4 shards) and `check` (4 shards, each with its own throwaway Postgres service). These are the same commands as the deploy workflow; a test pins them.
- **The record:** when all five pass, the `gate` job uploads the artifact `fasttrack-gate-<tree>` (kept 30 days). `gate_status.py` accepts it only from a successful `pull_request` run of `fasttrack-pr.yml` in this repository (forks never count), and prints `VALID for tag (via ci)`. `tag-deploy.sh` refuses a tag without it (or a passing local run).
- **Why the tree matches:** the PR run tests the merge of the batch into the current base. If the base has not moved, the merge commit the owner creates has that same tree. If the base moved, `gate_status.py` says MISSING for the new tree: merge the tip into the batch branch and push, and the PR checks run again.
- **Reading the result:** `gate_status.py <sha>` (curl + `gh auth token`), or the PR's checks page. On a red job, the failing step is in the run log (`deploy_watch.py`'s `failing_steps` reads the same API).
- **A PR that edits `fasttrack-pr.yml`** runs its own version of the checks. The owner reviews workflow changes before merging (agents can't push workflow files anyway).
- **Rollback:** go back to the local gate: `predeploy.sh` + `gate_status.py --no-ci`.

## A/B: executor arms (first 2 batches of v2)

| | Arm A | Arm B |
|---|---|---|
| Executor | repo `executor-<domain>` rules + domain skill (`.claude/agents/executor-*.md`, `.claude/skills/*-executor`) | `general-purpose` with `contracts/EXECUTOR-BRIEF.md` only |
| Verifier | `review` agent rules (`.claude/agents/review.md`), verdict = the filled acceptance table | read-only Sonnet verifier, verdict = the filled acceptance table |
| Same in both | the brief, the acceptance table, `predeploy.sh`, owner gates |

- **Assignment:** `state.py ab-assign <batch> <slice> --session S` balances the arms inside each batch. Put the arm and slice in the subagent's `description`, e.g. `[A:b1-s3] Ads edit estimate`, so the transcript extractor can attribute tokens and tests.
- **Arm A spawn:** sessions started from `~/Juli-AI-v2` can't see `juli/.claude/agents`. Either start the coordinator from `~/Juli-AI-v2/juli`, so `subagent_type: executor-backend` resolves, or spawn `general-purpose` with `model: sonnet` and make the first instruction: "Read and follow `.claude/agents/executor-<domain>.md` and the skill it names. This brief is your workflow cache: §1 = `parentScopeBlock`, §4 = `issueLoadProfile`; there is no Meta cache to wait for. Where those rules and the brief disagree, the brief's acceptance table wins." In sparse sandbox worktrees `.claude/` is absent: read the files from the main checkout `/Users/macos/Juli-AI-v2/juli/.claude/`.
- **Result per slice:** `state.py ab-result <slice> --owner-defects N --done-disproved N --evidence-rows N --evidence-total N --test-runs N --test-failures N --gate pass|fail --wall-minutes N`. The coordinator fills it after the owner's post-deploy check.
- **Decision rule:** after 2 batches (≥ 8 slices), compare M1–M5 and tokens per arm. Keep the arm with fewer owner-found defects. Break ties on cost.
