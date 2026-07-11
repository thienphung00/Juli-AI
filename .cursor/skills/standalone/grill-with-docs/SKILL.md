---
name: grill-with-docs
description: >-
  Aligns on a plan or design by asking one question at a time with a recommended
  answer, while building CONTEXT.md and docs/adr/ ADRs inline. Use when scope is
  ambiguous, conflicts need resolution, or planning/implementation alignment is
  required before work proceeds.
---

# Grill with docs

Align on a plan or design by asking one question at a time,
with a recommended answer for each. Simultaneously builds and updates `CONTEXT.md` and
`docs/adr/` ADRs inline as decisions crystallise.

Format rules for CONTEXT and ADRs: follow [`.cursor/skills/standalone/domain-modeling/SKILL.md`](../domain-modeling/SKILL.md).

**Workflow prompt cache:** owned by [`prompt-caching`](../prompt-caching/SKILL.md).
After grilling settles scope decisions, write or refresh cache artifacts using that skill.

## Modes

| Mode | Trigger | Output |
|------|---------|--------|
| **Planning** | New initiative, rescope, ADR work | `CONTEXT.md`, ADRs, PRD; may seed parent cache |
| **Implementation alignment** | `implement issue #N` (child), cache missing/stale | Child scope alignment + refreshed grill cache |

## Resolve parent issue (implementation mode)

Before grilling a child issue, resolve parent #P — see
[`prompt-caching/REFERENCE.md`](../prompt-caching/REFERENCE.md#resolve-parent-issue).

Child issue #N is never the cache anchor.

## Grilling loop

- One question at a time with recommended answer.
- **Child grill:** scope/deferrals unique to #N; explore codebase for issue-specific paths first.
- **Parent grill:** epic-level only — do not bake child-specific modules into parent cache.
- Delta: skip settled decisions unless fingerprint for **that tier** (parent vs child) changed.

### Question discipline

| Do | Don't |
|----|-------|
| Ask about unresolved conflicts or ambiguous AC | Re-ask decisions already in a valid cache |
| Propose a recommended answer with rationale | Batch multiple questions in one turn |
| Update CONTEXT.md / ADRs as decisions land | Embed cache injection rules here — use `prompt-caching` |

## Output

### Planning mode

- PRD input, `CONTEXT.md`, ADRs
- Optional seed for `parent-cache-issue-<P>.json` (via `prompt-caching`)

### Implementation mode

- `scope-alignment-issue-<n>.md` — human-readable child scope
- Valid `grill-cache-issue-<n>.json` with `cacheStatus: valid` before Executor TDD
- Refreshed `parent-cache-issue-<P>.json` when epic scope changed

After alignment completes, hand off to Meta → Executor → Review → Validate. Each phase
loads and updates the child cache per [`prompt-caching`](../prompt-caching/SKILL.md).

## Authority chain (grilling)

When questions arise, resolve in this order:

1. `EXECUTION.md` slice
2. Parent cache epic constant (if exists)
3. **Child** GitHub issue #N acceptance criteria
4. Epic handoff (when not superseded by EXECUTION.md)
5. Legacy — excluded until confirmed
