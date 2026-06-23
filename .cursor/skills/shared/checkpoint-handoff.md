# Checkpoint + Handoff Persistence

Two durable layers support workflow resumption and knowledge transfer. Agents maintain these
directly — **no Python helper module**. Read/write YAML and Markdown files at phase boundaries.

## Invocation modes

| Context | Persistence | Rule |
|---------|-------------|------|
| **Workflow** (`build-feature`, `fix-bug`) | **Mandatory** | Every phase writes checkpoint + handoff per table below. Child skills inherit this even when their own `SKILL.md` marks persistence optional. |
| **Standalone** (skill invoked directly) | **Optional** | Deliver phase output in chat. Write checkpoint/handoff files only when the user asks or when resuming an in-flight issue. |

**Resume** (any context, when `.agent-state/` exists): read checkpoint → latest `docs/handoffs/issue-{N}-*.md` → GitHub issue. Do not re-read full chat history.

### Workflow phase obligations

| Phase | Checkpoint section | Handoff file |
|-------|-------------------|--------------|
| `grill-with-docs` | `grill_with_docs_phase` on feature checkpoint | chat only |
| `to-prd` | `to_prd_phase` on feature checkpoint | chat only |
| `to-issues` | stub `issue-{N}.checkpoint.yml` per filed issue | chat only |
| `qa` (fix-bug) | stub `issue-{N}.checkpoint.yml` when issue filed | chat only |
| `focus` | `focus_phase` | `docs/handoffs/issue-{N}-focus.md` |
| `tdd` | `tdd_phase` | `docs/handoffs/issue-{N}-tdd.md` |
| `review` | `review_phase` | `docs/handoffs/issue-{N}-review.md` |
| `validate` | `validate_phase` | checkpoint only (JSON artifact is system of record) |
| `ship` | `ship_phase` (status ✓) | `docs/handoffs/issue-{N}-ship.md` optional |

Paths: `.agent-state/feature-{slug}.checkpoint.yml` (planning) · `.agent-state/issue-{N}.checkpoint.yml` (implementation). Both gitignored.

---

## Echo Discipline (reduces thread tokens)

**After writing any handoff file, output only a compact TL;DR in chat — not the full template body.**

```
✅ DO:  "✓ focus done — wrote docs/handoffs/issue-{N}-focus.md
         Key decisions: [1–2 lines]. Next: tdd."

❌ DON'T: paste the full handoff markdown body into the chat thread
```

Rules:
- Echo ≤ 5 lines in chat after each phase; reference the file by path.
- The next agent reads the handoff file directly — not the chat echo.
- For standalone skill invocations (not via build-feature/fix-bug workflow), skip the handoff file entirely and end with one inline recap line: `✅ Done: [what changed] — [file:lines] — Next: [next step]`

---

## Tier 1: Checkpoints (local runtime state)

**Path:** `.agent-state/issue-{N}.checkpoint.yml` (per issue) or
`.agent-state/feature-{slug}.checkpoint.yml` (feature planning before issues exist)

**Git:** Local only — `.agent-state/` is gitignored. PR history is the audit trail.

### Resume protocol (mandatory on session start or mid-issue takeover)

1. Read `.agent-state/issue-{N}.checkpoint.yml` if it exists (~400 tokens).
2. Read the latest handoff: `docs/handoffs/issue-{N}-{last_phase}.md`.
3. Read GitHub issue `#N` for acceptance criteria.
4. Do **not** re-read full chat history unless checkpoint/handoffs are missing.

### Issue checkpoint schema

```yaml
# .agent-state/issue-{N}.checkpoint.yml
issue_id: {N}
title: "{brief title from GitHub issue}"
parent_prd: "#{prd-number}"          # optional
execution_slice: "{e.g. P1-3}"       # from EXECUTION.md when applicable
created_at: "{ISO-8601}"
last_updated_at: "{ISO-8601}"

to_issues_phase:                     # written when issue is filed (to-issues)
  status: "✓" | "⏳" | "✗"
  afk_or_hitl: "AFK" | "HITL"
  blocked_by: ["#{other}", "none"]

focus_phase:
  status: "✓" | "⏳" | "✗"
  acceptance_criteria: ["{AC 1}", "{AC 2}"]
  files_to_touch: ["{path}", "{path}"]
  key_decisions:
    - choice: "{decision}"
      rationale: "{why}"
      rejected: ["{alt 1}"]
  architectural_notes: ["ADR-NNN in docs/decisions/", "{module boundary note}"]

tdd_phase:
  status: "✓" | "⏳" | "✗"
  branch: "feature/issue-{N}-{slug}"  # or fix/issue-{N}-{slug} for fix-bug
  tests_written: {number}
  test_summary: ["{file}::{test} — {behavior}"]
  acceptance_criteria_status:
    - criterion: "{AC}"
      covered_by: "{test name}"
      status: "✓" | "deferred"

review_phase:
  status: "✓" | "⏳" | "✗"
  issues_found:
    - type: "{reliability|security|...}"
      description: "{what}"
      fix: "{what changed}"
  validation_checks:
    pytest: "✓ passed" | "✗ failed"
    ruff: "✓ passed" | "skipped"
    mypy: "✓ passed" | "skipped"
    review_artifact: "artifacts/reviews/review-issue-{N}.json"

validate_phase:
  status: "✓" | "⏳" | "✗"
  artifact: "artifacts/validation/validation-issue-{N}.json"
  checks_passed: "{N}/{total}"

ship_phase:
  status: "⏳" | "✓"
  commit_hash: "{short SHA if merged}"
  branch: "feature/issue-{N}-{slug}"
  pr_url: "{URL if opened}"

resumption_notes: |
  Last phase completed: {phase}
  Next action: {specific next step}
  Read: docs/handoffs/issue-{N}-{last_phase}.md

tokens_to_resume: ~400
```

### Feature planning checkpoint schema

Used by `grill-with-docs` → `to-prd` → `to-issues` before per-issue files exist:

```yaml
# .agent-state/feature-{slug}.checkpoint.yml
feature_slug: "{slug}"
title: "{feature name}"
created_at: "{ISO-8601}"
last_updated_at: "{ISO-8601}"

grill_with_docs_phase:
  status: "✓" | "⏳" | "✗"
  key_findings: ["{finding}"]
  assumptions: ["{assumption}"]
  canonical_updates:
    - "EXECUTION.md: {what changed}"
    - "docs/decisions/: ADR-NNN"
  next_actions: ["to-prd"]

to_prd_phase:
  status: "✓" | "⏳" | "✗"
  prd_issue: "#{number}"
  modules_identified: ["{module}: {responsibility}"]

to_issues_phase:
  status: "✓" | "⏳" | "✗"
  issue_queue: ["#{N1}", "#{N2}"]
  next_action: "focus on #{first}"
```

### Checkpoint update rules

| Phase | Action | Section |
|-------|--------|---------|
| `to-issues` | Create stub per filed issue | `to_issues_phase` + issue metadata |
| `focus` | Append decisions + files | `focus_phase` |
| `tdd` | Append test metrics + branch | `tdd_phase` |
| `review` | Append findings + review artifact | `review_phase` |
| `validate` | Append gate results | `validate_phase` |
| `ship` | Mark shipped + commit/PR | `ship_phase` |

Always set `last_updated_at` to current ISO timestamp. Create `.agent-state/` if missing.

---

## Tier 2: Handoff files (committed knowledge transfer)

**Path:** `docs/handoffs/issue-{N}-{phase}.md`

Handoffs are **committed** (unlike checkpoints). They document *what* was decided/built and *why*
for future agents. Follow existing repo style (see `docs/handoffs/issue-120-focus.md`).

### When to write

| Phase | File | Required |
|-------|------|----------|
| `focus` | `docs/handoffs/issue-{N}-focus.md` | **Yes** — before `tdd` |
| `tdd` | `docs/handoffs/issue-{N}-tdd.md` | **Yes** — before `review` |
| `review` | `docs/handoffs/issue-{N}-review.md` | **Yes** — before `validate` |
| `validate` | (checkpoint only) | No separate file |
| `ship` | `docs/handoffs/issue-{N}-ship.md` | Optional — after merge |

### Handoff templates

Templates live in `docs/templates/handoffs/` — load the specific file only when writing a handoff.

| Phase | Template |
|-------|---------|
| `focus` → `tdd` | [`docs/templates/handoffs/focus-tdd.md`](../../../docs/templates/handoffs/focus-tdd.md) |
| `tdd` → `review` | [`docs/templates/handoffs/tdd-review.md`](../../../docs/templates/handoffs/tdd-review.md) |
| `review` → `validate` | [`docs/templates/handoffs/review-validate.md`](../../../docs/templates/handoffs/review-validate.md) |
| `ship` (optional) | [`docs/templates/handoffs/ship-complete.md`](../../../docs/templates/handoffs/ship-complete.md) |

---

## Success metrics

| Metric | Target |
|--------|--------|
| Checkpoint per issue | 100% after `to-issues` stubs |
| Handoff files | focus + tdd + review (minimum) |
| Resume tokens | <500 from checkpoint alone |
| Onboarding | <5 min via handoffs + issue body |
| Phase completeness | Every phase has status ✓/⏳/✗ |

## Integration

- **Workflow skills** (`build-feature`, `fix-bug`): one-line pointer here; persistence always on.
- **Standalone skills** (`grill-with-docs`, `to-prd`, `to-issues`, `focus`, `tdd`, `review`, `validate`, `ship`, `qa`): each has a short optional/mandatory block linking here.
- **Validate gate:** `scripts/validate/check_handoff.py` skips when no legacy handoff on branch.
- **Parallel agents:** one worktree per issue; slice status in `EXECUTION.md`; see `issue-workflow.mdc`.
