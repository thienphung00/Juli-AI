# Checkpoint + Handoff Persistence

Two durable layers support agent-phase resumption and knowledge transfer. Agents
maintain these directly — **no Python helper module**. Read/write YAML and Markdown
files at phase boundaries.

## Invocation modes

| Context | Persistence | Rule |
|---------|-------------|------|
| **Full issue cycle** (Planning → Implementation → Review) | **Mandatory** | Every phase writes checkpoint + handoff per table below |
| **Standalone** (skill invoked directly) | **Optional** | Deliver phase output in chat. Write checkpoint/handoff files only when the user asks or when resuming an in-flight issue |

**Resume** (any context, when `.agent-state/` exists): read checkpoint → latest `docs/handoffs/issue-{N}-*.md` → GitHub issue. Do not re-read full chat history.

### Agent phase obligations

| Phase | Checkpoint section | Handoff file |
|-------|-------------------|--------------|
| Planning (`to-prd`, `to-issues`) | `to_prd_phase` / `to_issues_phase` on feature or issue checkpoint | chat only |
| `qa` (bug filing) | stub `issue-{N}.checkpoint.yml` when issue filed | chat only |
| `focus` | `focus_phase` | `docs/handoffs/issue-{N}-focus.md` |
| Implementation (Executor) | `implementation_phase` | `docs/handoffs/issue-{N}-implementation.md` |
| `review` | `review_phase` | `docs/handoffs/issue-{N}-review.md` |
| `validate` | `validate_phase` | checkpoint only (JSON artifact is system of record) |
| `ship` | `ship_phase` (status ✓) | `docs/handoffs/issue-{N}-ship.md` optional |

Legacy handoff names `issue-{N}-tdd.md` and checkpoint `tdd_phase` are still valid
for resume on in-flight issues.

Paths: `.agent-state/feature-{slug}.checkpoint.yml` (planning) · `.agent-state/issue-{N}.checkpoint.yml` (implementation). Both gitignored.

---

## Echo Discipline (reduces thread tokens)

**After writing any handoff file, output only a compact TL;DR in chat — not the full template body.**

```
✅ DO:  "✓ focus done — wrote docs/handoffs/issue-{N}-focus.md
         Key decisions: [1–2 lines]. Next: implementation."

❌ DON'T: paste the full handoff markdown body into the chat thread
```

Rules:
- Echo ≤ 5 lines in chat after each phase; reference the file by path.
- The next agent reads the handoff file directly — not the chat echo.
- For standalone skill invocations on ad-hoc tasks, skip the handoff file and end with one inline recap line: `✅ Done: [what changed] — [file:lines] — Next: [next step]`

---

## Tier 1: Checkpoints (local runtime state)

**Path:** `.agent-state/issue-{N}.checkpoint.yml` (per issue) or
`.agent-state/feature-{slug}.checkpoint.yml` (feature planning before issues exist)

**Git:** Local only — `.agent-state/` is gitignored. PR history is the audit trail.

### Resume protocol (mandatory on session start or mid-issue takeover)

1. Read `.agent-state/issue-{N}.checkpoint.yml` if it exists (~400 tokens).
2. Read the latest handoff: `docs/handoffs/issue-{N}-{last_phase}.md` (accept `-tdd` as legacy alias for `-implementation`).
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
  architectural_notes: ["ADR-NNN in docs/adr/", "{module boundary note}"]

implementation_phase:                # legacy alias: tdd_phase
  status: "✓" | "⏳" | "✗"
  branch: "feature/issue-{N}-{slug}"  # or fix/issue-{N}-{slug}
  executor_domain: "backend" | "ui-ux" | "data-platform" | "machine-learning"
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

Used by Architect Agent Planning (`to-prd` → `to-issues`) before per-issue files exist:

```yaml
# .agent-state/feature-{slug}.checkpoint.yml
feature_slug: "{slug}"
title: "{feature name}"
created_at: "{ISO-8601}"
last_updated_at: "{ISO-8601}"

planning_phase:                      # canonical doc governance (formerly discover)
  status: "✓" | "⏳" | "✗"
  key_findings: ["{finding}"]
  assumptions: ["{assumption}"]
  canonical_updates:
    - "EXECUTION.md: {what changed}"
    - "docs/adr/: ADR-NNN"
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
| Implementation | Append test metrics + branch | `implementation_phase` |
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
| `focus` | `docs/handoffs/issue-{N}-focus.md` | **Yes** — before Implementation |
| Implementation | `docs/handoffs/issue-{N}-implementation.md` | **Yes** — before `review` |
| `review` | `docs/handoffs/issue-{N}-review.md` | **Yes** — before `validate` |
| `validate` | (checkpoint only) | No separate file |
| `ship` | `docs/handoffs/issue-{N}-ship.md` | Optional — after merge |

Legacy `issue-{N}-tdd.md` files remain valid for historical issues.

### Handoff templates

Templates live in `docs/templates/handoffs/` — load the specific file only when writing a handoff.

| Phase | Template |
|-------|---------|
| `focus` → Implementation | [`docs/templates/handoffs/focus-implementation.md`](../../../docs/templates/handoffs/focus-implementation.md) |
| Implementation → `review` | [`docs/templates/handoffs/implementation-review.md`](../../../docs/templates/handoffs/implementation-review.md) |
| `review` → `validate` | [`docs/templates/handoffs/review-validate.md`](../../../docs/templates/handoffs/review-validate.md) |
| `ship` (optional) | [`docs/templates/handoffs/ship-complete.md`](../../../docs/templates/handoffs/ship-complete.md) |
| Planning → `to-prd` | [`docs/templates/handoffs/planning-to-prd.md`](../../../docs/templates/handoffs/planning-to-prd.md) |

---

## Success metrics

| Metric | Target |
|--------|--------|
| Checkpoint per issue | 100% after `to-issues` stubs |
| Handoff files | focus + implementation + review (minimum) |
| Resume tokens | <500 from checkpoint alone |
| Onboarding | <5 min via handoffs + issue body |
| Phase completeness | Every phase has status ✓/⏳/✗ |

## Integration

- **Agent runtime:** [`docs/architecture/agent-runtime.md`](../../../docs/architecture/agent-runtime.md) — phase model and ownership
- **Standalone skills** (`to-prd`, `to-issues`, `focus`, `review`, `validate`, `ship`, `qa`): each links here for persistence rules
- **Validate gate:** `scripts/validate/check_handoff.py` skips when no legacy handoff on branch;
  `docs/handoffs/issue-*-{phase}.md` files are the continuity source alongside `EXECUTION.md`
- **Parallel agents:** `docs/handoffs/_bootstrap.md` — each window reads its issue checkpoint first
