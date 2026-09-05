# ADR-094 — The bootstrap anchor's base ref tracks the run's actual base

**Status:** Accepted — 2026-09-04 (#1608, PR TBD)

## Context

ADR-092 (#1540) replaced `pinBranch: HEAD` with `pinBranch: merge-base:origin/main` — the fork
point between a branch and `main`, resolved fresh at check time. That closed the defect where
the anchor tracked the branch's own tip. It introduced a narrower one: `origin/main` is a
**hardcoded** base ref, and `classify-tier` in `pr.yml` sets CI tier `issue` exactly when
`github.base_ref` matches `feature/*-wave` — an issue-tier PR's real base is that wave branch,
not `main`. The same file already had the correct pattern next to the wrong one:
`validate-gates` and `policy-checks` both resolve `origin/${BASE_REF}` from `github.base_ref`
dynamically. The two jobs answered "what is this run's base" differently.

This was filed (#1608) as latent — nothing consumed the base-anchored gates against a real
repository yet, only synthetic fixtures. It went live before the fix did. `tests/unit/test_mutants.py::test_clean_record_produces_no_failures`
re-runs the artifact-sensitive gates against *this checkout*, and `harness_bootstrap_pin`'s own
shipped-config test resolves the shipped `pinBranch` against the real repo, so the moment
#1540 shipped `merge-base:origin/main` and #1604 made `origin/main` resolvable in CI, the
wrong-base defect started reddening PRs. The wave `feature/harness-e-w5-wave` had already
landed #1529's `agent-runtime/docs/schemas/status-record.schema.json` change — a watched
`sourcePaths` entry — before `main` had it. Anchoring to `origin/main` computed a fork point
that predates that landed, reviewed wave commit, so `diff_harness_paths_since` reported it as
drift on every subsequent issue-tier PR built on the wave. Confirmed live on PR #1561 (the
`test` job, `check_harness_bootstrap_pin: FAIL`, run 33854292100) and reproduced in a faithful
checkout of that PR's merge ref.

## Decision

**The base-ref half of the anchor spec is a token, `BASE_REF`, substituted at check time for
this run's actual base ref — never a hardcoded branch name.**

`agent-runtime.config.yml`:

```yaml
pinBranch: merge-base:origin/BASE_REF
```

`harness_bootstrap_pin.resolve_bootstrap_anchor_with_note` substitutes a trailing `BASE_REF`
path segment (matched as a whole segment, not a substring, so a real ref merely containing
those letters is untouched) via `resolve_base_ref_token()`:

1. `os.environ["BASE_REF"]` if set — the convention `validate-gates`/`policy-checks` already
   use, now also set at job level on `test` and `full-regression` from `github.base_ref || 'main'`
   (the `|| 'main'` only matters for `full-regression`: `github.base_ref` is empty on a
   `merge_group` trigger, which GitHub does not populate for that event, and `full-regression`
   is the pre-merge-to-main gate reached by both a `pull_request→main` and a `merge_group` run.
   `main` is not a guess there — this workflow's own `merge_group: branches: [main]` trigger
   makes it the only value the fallback could ever need to supply, the same reasoning
   `classify-tier` already applies by hardcoding `tier=main` unconditionally on `merge_group`).
2. `os.environ["GITHUB_BASE_REF"]` — GitHub Actions' own var, set natively for `pull_request`
   events, as a second line of defense.
3. **This branch's git upstream** (`git rev-parse --abbrev-ref --symbolic-full-name @{u}`),
   screened for self-reference. Neither CI env var is set for a bare local `pytest` run, and
   the harness's own primary local workflow is a worktree cut from a wave branch — this
   epic's own issue branches (#1540, #1604, #1608 itself) are all created that way. Defaulting
   straight to `"main"` there reproduced this exact bug for every local run on the very branch
   that fixes it: `BASE_REF=<wave> pytest ...` passed, plain `pytest` (the ordinary case) still
   failed on the wave's own landed change — a #1529-shaped local-vs-CI split from a new angle,
   and the kind of always-wrong-for-the-common-case local failure that teaches people to
   distrust a real drift signal. `@{u}` is fixed by whoever created the branch, not chosen by
   the run that reads it — the same "not self-settable" property `BASE_REF` has — *unless*
   something has since repointed it, which a plain `git push -u` on the branch itself does:
   observed directly on this branch, where publishing its own PR repointed its own upstream at
   its own remote counterpart. `current_branch_names()` (the set `reject_self_referential_ref`
   already checks every anchor spelling against) now includes that `origin/<name>` spelling too,
   so a self-referential upstream is treated as no answer and falls through, not used.
4. `"main"`, recorded as a degradation note (never silent) — correct for a main-tier run, a
   branch cut locally from `main`, or a checkout with no usable upstream at all; wrong for a
   branch whose real base is a wave and none of the above resolved one.

Substitution happens **before** the existing self-referential-ref screen (`reject_self_referential_ref`),
so a substituted value that happened to name the checked-out branch would still be rejected —
the screen applies to what will actually be resolved, not to the unsubstituted template.

`test` and `full-regression` (the two base-anchored jobs; #1604's slice) set `BASE_REF` at job
level and fetch `origin/${BASE_REF}` instead of a literal `origin/main`, preserving #1604's
two-fetch shape (bounded depth-200 fetch of the base, then a re-fetch of the checked-out commit
by its own sha, to restore the shallow boundary the first fetch moves). `test` never sees
`merge_group` (`classify-tier` reaches `tier == 'issue'` only via `pull_request`), so its
`BASE_REF` is the plain `${{ github.base_ref }}`; `full-regression` carries the `|| 'main'`
fallback described above. One dynamic mechanism either way, not a tier conditional plus a
hardcoded exception that happens to agree with it.

`eval/gate_scoring.py`'s fixture previously duplicated the anchor spec as a second hardcoded
literal (`BOOTSTRAP_ANCHOR_SPEC = "merge-base:origin/main"`), with a comment noting it "must
match `bootstrapRef.branch` in `parent-cache.template.json` exactly." That duplication is
exactly how a config fix could fail to reach the thing that exercises it — the eval harness
would keep scoring the *old* spec forever, silently. `_bootstrap_anchor_spec()` now reads
`workflow_prompt_cache.bootstrap.pinBranch` from the shipped config directly; the template's
`bootstrapRef.branch` literal was updated to `merge-base:origin/BASE_REF` to match.

## ADR-092's lock-6 exhibit, applied

Lock 6 forbids clearing a red by moving what a gate is measured against. Criterion 2 requires
a demonstrated FAIL under the *new* configuration, not an assertion that one is possible.

`tests/unit/test_harness_bootstrap_pin.py::test_base_ref_token_anchor_still_catches_drift_the_issue_branch_introduces`
is that exhibit: a repo with `main` → `wave` (one reviewed harness commit) → `issue-branch`
(BASE_REF=`wave`). The corrected anchor resolves to the wave's tip, so the wave's own landed
change is not drift (`test_base_ref_token_anchor_does_not_misreport_the_landed_wave_change` —
the AC from the #1608 escalation, proven directly). Then the issue branch itself edits a
skill file on top of that anchor, and the gate still fails, naming the file. A fix that only
suppressed the false positive without preserving this would have converted an
occasionally-wrong gate into an always-green one — strictly worse, per ADR-092's own framing.
`test_hardcoded_main_anchor_misreports_a_landed_wave_change_as_drift`, in the same fixture,
reproduces the original bug for contrast (`merge-base:origin/main`, no `BASE_REF` set, drift
reported on the wave's own commit).

`test_base_ref_upstream_fallback_still_catches_real_drift` is the same exhibit for the
git-upstream path specifically, since it is reached by a different code path than the
env-var-driven one above and criterion 2 applies to each path a fix touches, not once for the
feature as a whole. Both were mutated directly — `diff_harness_paths_since` patched to always
return `[]` — and confirmed to fail for exactly that reason (`assert passed is False` →
`assert True is False`), then reverted; this is stronger than the mechanical test alone, since
it rules out the exhibit being vacuously true by construction.

The live counterpart: `tests/unit/test_mutants.py::test_clean_record_produces_no_failures`
re-runs `check_harness_bootstrap_pin` against this real checkout. Before the `BASE_REF` env
wiring landed, plain `pytest` (no env, git upstream not yet consulted) failed here exactly as
PR #1561 did in CI. After the `BASE_REF` env wiring but before the git-upstream fallback, the
same plain `pytest` run *still* failed — on this exact branch, mid-implementation, which is
how the local-vs-CI split was found — while `BASE_REF=feature/harness-e-w5-wave pytest ...`
passed. After the git-upstream fallback (and after correcting this worktree's own `@{u}`, which
a prior `git push -u` on this branch had repointed at its own remote counterpart), plain
`pytest` passes with no environment set at all. All states were observed directly, not
inferred, before this ADR was written.

## Rationale

The base ref is workflow-run-scoped information — it is `github.base_ref`, known to the CI job
that runs the gate, and not a property of the repository's history that a config file can name
once and have stay true. Encoding it as a literal in `agent-runtime.config.yml` made the config
correct for exactly one tier and silently wrong for the other; encoding it as a token resolved
from the environment the gate actually runs in keeps the config tier-agnostic and pushes the
tier-specific answer to the one place that already has it.

`GITHUB_BASE_REF` alone was considered and rejected as the *sole* source: it is unset outside
`pull_request` events (a `push`-triggered wave run, or local invocation), and this gate's
consumers include exactly that local case (`meta_prepare_executor.py` run by a human or an
agent in a worktree forked from a wave, as this issue's own implementation loop was). An
explicit `BASE_REF` job-level env, matching the convention two sibling jobs already used,
keeps the wiring visible in `pr.yml` rather than implicit in an Actions-only variable, and the
`GITHUB_BASE_REF` fallback costs nothing extra to keep as a second line of defense.

Degrading to `"main"` when none of the above resolve was chosen over failing closed (raising)
because the substitution is opt-in by construction — a config that names an explicit ref or SHA
never invokes this path at all — and because failing closed here would break every local
invocation of a gate that has run this way, uneventfully, since before this ADR. The
degradation is recorded in `details["anchorDegradationReason"]`, never silent, matching the
precedent ADR-092 already set for the shallow-checkout fallback.

Git's own upstream-tracking ref was chosen over two alternatives considered for the local case.
A candidate-enumeration approach (compute `git merge-base HEAD <c>` against every known
integration base — `origin/main` and every `origin/feature/*-wave` remote-tracking ref present
— and pick the nearest) is more robust in principle, since it does not depend on `@{u}` having
been set correctly and staying that way, but it is meaningfully more code for a fallback that
only matters outside CI, and it still needs its own self-reference and "no candidate found"
handling, so it does not remove the screening logic this ADR already needs. Leaving `@{u}`
unscreened — trusting that a branch created from a wave keeps tracking it — was rejected
outright: it is provably false in the case that matters most, publishing the branch's own PR,
and would have shipped a fallback that works right up until the point a developer does the one
thing every issue branch in this repo does.

## Consequences

- `agent-runtime.config.yml`'s `pinBranch` reads `merge-base:origin/BASE_REF`. A future edit
  reverting it to a hardcoded branch name is caught directly by
  `test_shipped_config_pin_branch_uses_the_base_ref_token` and, at the workflow level, by
  `test_bootstrap_pin_anchor_agrees_with_the_fetched_base_ref`.
- `test` and `full-regression` both carry a `BASE_REF` job env (`${{ github.base_ref }}` and
  `${{ github.base_ref || 'main' }}` respectively) and a fetch step naming `origin/${BASE_REF}`.
  `test_base_anchored_jobs_declare_base_ref_from_github_base_ref` and
  `test_base_anchored_jobs_fetch_the_dynamic_base_ref_after_checkout` (both parametrized over
  the two jobs, i.e. over both CI tiers) hold the two in lockstep with the config;
  `test_full_regression_base_ref_falls_back_to_main_for_merge_group` holds the `merge_group`
  case specifically.
- `eval/gate_scoring.py`'s fixture derives its anchor spec from the shipped config instead of
  duplicating it. This is a **behavior-preserving refactor for every consumer except this
  fix**: before #1608, the duplicate and the config held the same string by hand-maintained
  convention; after, they can't drift, by construction.
- `current_branch_names()` now includes the `origin/<name>` spelling of the checked-out branch,
  not only the bare-name spellings. This closes a residual this ADR originally accepted
  knowingly ("a substituted form structurally cannot collide with `current_branch_names()`'s
  exact spellings... since that check compares against bare branch-name spellings, not
  `origin/`-prefixed ones") once it stopped being theoretical: the git-upstream fallback added
  above makes `origin/<branch>` a real candidate value, and it is exactly what a self-tracking
  upstream (a branch pushed with `-u`) resolves to. `test_base_ref_ignores_a_self_referential_upstream_and_degrades_to_main`
  covers it directly, reproducing the corruption this repo's own `#1608` branch hit.
- This worktree's own `@{u}` was corrupted by an earlier `git push -u origin
  feature/issue-1608-base-ref-anchor` and was restored to `origin/feature/harness-e-w5-wave`
  (its actual, correct base) as part of landing this fix; subsequent pushes on this branch use
  a plain `git push` (no `-u`) so it is not repointed again. This is a one-time local
  correction, not a workflow change this ADR mandates elsewhere — the self-reference screen is
  what makes the mechanism safe in general, not developer discipline about push flags.
- Not addressed here, and out of scope: `sourcePaths` narrowing as a lock-6 surface is tracked
  separately (#1563, per ADR-092's own consequences section).
