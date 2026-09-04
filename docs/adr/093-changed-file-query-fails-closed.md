# ADR-093 — A query that cannot answer must not return a value that means something else

**Status:** Accepted — 2026-09-04 (#1571, PR #1577)

## Context

`git_changed_files()` in `agent-runtime/scripts/ci/common.py` answers one question — *what
did this branch change* — for every diff-driven validate gate. Four gates consume it:
`check_handoff.py:38`, `check_module_boundaries.py:71`, `check_module_drift.py:28`,
`check_adr.py:37`. Each scopes its work by the answer, so each is exactly as trustworthy as
the answer is.

It had two compounding faults.

**A nominally read-only query mutated the repository it queried.** Before diffing, it ran
`git fetch origin <base> --depth=1`. That shallow-grafts the base ref: `origin/<base>` stays
resolvable *by name* while the history behind it is destroyed, so the `git diff
origin/<base>...HEAD` on the next line aborts for want of a merge base. On a complete
(`fetch-depth: 0`) checkout this cut `origin/main` from 5 commits to 1 — measured on a real
clone, not inferred. The query truncated the very history it then failed to read.

**Failure returned `[]`.** The `except (subprocess.CalledProcessError, FileNotFoundError):
return []` swallowed the abort, and every caller reads `[]` as "this PR changed nothing" →
"nothing in scope" → PASS. The defect was invisible for the reason that makes it a class
rather than a bug: **the failure mode and the success mode were the same value.** `[]` is a
legitimate answer to "what changed" — a docs-only branch, a revert, an empty range all
produce it honestly — so no caller could have told the two apart, and no amount of caller-side
care would have helped. This is a **fail-open disguised as a valid result**: the gate does not
report that it could not check, it reports that there was nothing to check.

The evidence that this is one class and not one incident:

- It is the common root under **#1529** (`check_adr` saw `changed=[]` with ADR-092 committed
  in the tree), **#1570** (`differential_tdd` could not resolve a merge base against
  `origin/main`), and the two W5 reviewers who measured red→green by hand and recorded
  `manualDifferentialTdd` because the automated path told them nothing.
- The same shape was found **independently** by #1540's reviewer, from a different direction,
  as that review's finding **F6** — while reviewing an unrelated gate. Two searches converging
  on one shape is the signal that the shape, not the function, is the thing to record.
- `actions/checkout` is depth-1 by default and only the `changes` and `gitleaks` jobs set
  `fetch-depth: 0`, so CI reproduced the shallow precondition on nearly every job.
- `pr.yml`'s `validate-gates` job already carries a hand-written workaround for it (`git reset
  --soft "${merge_base}"`, `unset GITHUB_BASE_REF`), with a comment naming the exact mechanism.
  The workaround is the tell: the defect was known well enough to be routed around at the call
  site and never fixed at the source.

## Decision

**A query that cannot answer must raise, not return a value that means something else.**

Concretely, for `git_changed_files()`:

1. **Unresolvable raises.** `ChangedFilesUnresolved(spec, reason)` — a `RuntimeError` carrying
   the ref spec it tried and the reason it failed — is raised whenever the changed-file set
   cannot be determined: the git CLI is absent, the diff exits non-zero, or the spec shares no
   merge base with `HEAD` even after deepening.
2. **`[]` is reserved for the genuine answer.** After this change an empty list means, and can
   only mean, "nothing changed". The value regains a single meaning.
3. **A read query never mutates the repository.** The fetch fires only when the merge base does
   not already resolve, so a resolvable base is queried with no network and no repository
   change at all. When a fetch is needed it **deepens** — `--unshallow` on a shallow clone,
   then a plain refspec fetch — and **never `--depth=1`**. History may be widened to answer a
   question; it may never be narrowed.

**Callers choose their fail-closed shape, and two shapes are correct.** Both are legal; a third
is not.

- **Catch and record.** `check_handoff`, `check_module_boundaries` and `check_module_drift`
  catch `ChangedFilesUnresolved` and emit a FAIL verdict naming `exc.reason`. A gate that
  reaches its own reporting path should report, and a named cause is worth more to the next
  reader than a stack trace.
- **Propagate and ERROR.** `check_adr` deliberately does not catch. The exception propagates,
  no `<name>: PASS|FAIL` verdict line is printed, and `pr.yml`'s `verdict_re`
  (`^[a-z_]+: (PASS|FAIL)`) already classifies a missing verdict on a blocking gate as
  `ERROR - exited N with no PASS/FAIL verdict (raised, or could not read its input)`. The
  outcome is fail-closed without editing a file a peer slice (#1529) owns. A test pins this
  behaviour so the absence of a `try` is a decision on the record rather than an omission.
- **Forbidden:** catching and continuing. Any handler that maps the exception back onto an
  empty list, a default, or a skip re-creates the defect this ADR exists to remove.

This ADR covers the changed-file contract only. It does not close the artifact half of the same
silence (see Consequences).

## Rationale

**Why an exception rather than a sentinel or `Optional[list]`.** The rejected alternative was to
keep returning a value — `None`, a sentinel object, `list | None` — and let callers test for it.
It fails for the same reason the original code failed: *a value callers can ignore will be
ignored, silently, and the result will look like working code.* `changed = git_changed_files()
or []` is a natural thing to write; so is `if changed:`; so is forgetting the `None` branch
entirely. Each of those restores the exact fail-open, reviews clean, and produces the same
indistinguishable `[]` at the point of use. Fixing "the failure value reads as a valid answer"
by introducing a second failure value that reads as a valid answer is a rename, not a fix.

An exception has no default behaviour. It cannot be ignored into a pass: unhandled, it is loud
by construction in this harness (missing verdict ⇒ ERROR on a blocking gate); handled, the
handler must name a reason to say anything at all. The cost of the contract is paid at the call
site by whoever is in a position to decide what an unanswerable question means for their gate —
which is where the decision belongs.

`Optional[list]` is the weakest of the three, because its protection is a type checker rather
than a runtime: it holds only where the callers are actually type-checked. `agent-runtime/scripts`
only entered the lint perimeter with #1528, and static checks run at issue tier, so a locally
merged wave can ship a caller nobody type-checked. A guarantee that depends on a job having run
is not a guarantee for a harness whose subject is gates that cannot fail silently.

**Why breaking is the right answer.** A backward-compatible route existed — a `strict=False`
parameter defaulting to the old swallow-and-return-`[]`. It preserves the defect at every call
site that does not opt in, which is every call site by default, and it makes the safe behaviour
the one you have to remember. The safe behaviour must be the one you get for free. The four
callers were enumerated and each converted deliberately; four is a migration, not a hazard.

**Why the fetch policy is part of the contract and not an implementation detail.** The
`--depth=1` fetch is what made the diff unanswerable; a version that raised honestly but still
truncated its own base would fail closed on every shallow CI job and be reverted within a week
for noise. Honesty about failure and not manufacturing the failure are one decision. The general
form — *widen history to answer, never narrow it* — is what stops the next helper reintroducing
the same side effect under a different name.

**Why this generalises past one function.** The rule to measure future harness code against:
*an answer value that is also the failure value is a fail-open, however carefully the caller is
written.* Any helper that answers a question on behalf of a gate — a changed-file set, a merge
base, a coverage number, an artifact lookup — must be able to say "I could not tell" in a way
that is structurally distinct from every legitimate answer it can give. Where the neighbouring
bootstrap-pin gate had to degrade rather than raise, it recorded `anchorDegraded` with a reason
(#1540, [ADR-092](092-gate-configuration-edits-and-the-anchor-rule.md)): different mechanism,
same rule — never to a silent pass.

## Consequences

- **The contract is breaking and the migration cost is permanent.** Every future caller of
  `git_changed_files()` must choose catch-and-record or propagate-and-ERROR. There is no
  correct third option and no default that is safe to inherit. A new gate that wraps the call
  in a bare `except Exception` is a regression to this ADR, not a style preference.
- **`check_adr.py` is untouched by design.** It is peer-owned by #1529; its fail-closed
  behaviour comes from `pr.yml`'s verdict rule, not from a handler in the file. If #1529 later
  gives it a handler, that is a move from one legal shape to the other and needs no amendment
  here.
- **This ADR is the evidence `check_adr` asked for, not a way around it.** The gate fired on
  `interfaceChanges[].breaking: true`; review confirmed the label is accurate and declined to
  flip it, since editing a gate's input to clear the gate is exactly what
  [ADR-092](092-gate-configuration-edits-and-the-anchor-rule.md) forbids. The decision is
  recorded instead.
- **The artifact half of the same silence stays open, and this ADR does not claim it.**
  `check_adr` reads `interfaceChanges` from `agent-runtime/artifacts/reviews/`, which
  [ADR-003](003-ai-native-cicd-policy.md) gitignores, so CI never sees the file and that limb of
  the gate is **vacuous in CI** — measured: moving the artifact aside flips the gate from FAIL
  exit 1 to PASS exit 0. Owned by **#1529** and **#1562**. This ADR makes the *query* honest; the
  gate's breaking-interface limb still needs its input to be visible to CI before it means
  anything there. Both halves are required; neither substitutes for the other.
- **CI behaviour on depth-1 jobs changes from silent to loud.** A job that cannot resolve its
  base now spends a deepening fetch or fails visibly, where it previously passed instantly and
  emptily. That is the intended cost. #1574 covers giving the test job full history so the
  common case does not pay it.
- **`pr.yml`'s existing workaround still works and is retained.** The `reset --soft` +
  `unset GITHUB_BASE_REF` path drives the working-tree fallback, which is unchanged. It is now
  redundant in principle, but this ADR does not authorize removing it: any removal must
  demonstrate the gates can still be made red without it, per ADR-092 criterion 2.
- **A consequence for reading local runs.** With `GITHUB_BASE_REF` unset and no `base_ref`
  argument, the query answers "what is in the working tree versus `HEAD`". After a commit that
  is legitimately empty, and gates scoped by it legitimately see nothing — the same reason
  `pr.yml` moves `HEAD` back to the merge base before running them. That is now a correct empty
  answer rather than a swallowed error, but it still has to be invoked correctly to be useful.
