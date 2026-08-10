---
name: intent-review
description: >-
  Judges Spec fidelity (intent-to-code match), Fowler smells, and light
  convention/pattern citations against the diff since a fixed point. Emits an
  intent-review artifact that Guardrails must consume as given. Use when the
  Review Agent runs, or when reviewing a branch, PR, or "review since X" for
  design-fit and structure — not for reliability/security domain checklists.
---

# Intent review (Spec fidelity × structure)

Owns **intent-to-code fidelity** and **structural blocking judgment** for the
Review Agent sequence:

`intent-review` → `guardrails` → `validate` → ship-ready

| Owns | Does NOT do |
|------|-------------|
| Spec fidelity (did the diff match PR/design **intent**?) | Full Guardrails domain tables |
| Fowler smell-baseline (sole **merge-blocking** structure judge) | Reliability / security / observability / performance checks |
| Light convention / pattern citations | AC ↔ test **coverage** mapping (that is Guardrails) |
| Emit `intent-review` artifact | Emit ADR-003 `review-issue-<n>.json` |

Boundary rules (authority, Spec vs AC, no re-litigation): see
[BOUNDARY.md](BOUNDARY.md). Smell catalogue: [REFERENCE.md](REFERENCE.md).

## Issue tracker

GitHub Issues via `gh issue view <n> --comments` (or `gh pr view` for PRs).

## Process

### 0. Modular monolith four questions (when applicable)

For backend- or architecture-touching PRs, confirm the author answered the four
required questions in [`.github/pull_request_template.md`](../../../.github/pull_request_template.md)
(same wording in [`.cursor/rules/code-review.mdc`](../../../.cursor/rules/code-review.mdc)):

1. **Does it work?** — Tests (unit / integration / E2E as applicable).
2. **Does it belong in this module?** — Ownership (routes, models, services, tables, tasks, Redis keys, integrations).
3. **Did it create forbidden dependencies?** — Import-linter + cycle check.
4. **Can this module still be extracted later?** — Architecture (deep module / facade discipline; no new god-file or cross-module internal reach-through).

Fold violations into smells / convention_notes or Spec fidelity as appropriate; do
not invent alternate wording for these questions.

### 1. Pin the fixed point

Ask if unspecified. Capture once:

```bash
git rev-parse <fixed-point>          # must resolve
git diff <fixed-point>...HEAD        # three-dot; must be non-empty
git log <fixed-point>..HEAD --oneline
```

Fail here on bad ref or empty diff — not inside sub-agents.

### 2. Identify the intent source (Spec axis)

In order:

1. Issue / PR references in commits — fetch body + linked design notes.
2. Path the user passed.
3. PRD/spec under `docs/`, `docs/product/`, `docs/handoffs/`, `.scratch/` matching
   branch or feature.

If none: ask. If user says none → `spec_fidelity: "pass"` with note
`no_intent_source`, and only run Standards (smells + conventions).

**Spec fidelity** = developer-level **intent-to-code** match (design/PRD/issue
narrative). It is **not** AC↔test coverage (Guardrails owns that).

### 3. Standards sources (conventions only)

List paths for light convention/pattern citations. Prefer:

- `.cursor/rules/patterns.mdc`, `code-quality.mdc` (naming/layout conventions)
- Affected `MODULE.md`, domain skill conventions

**Do not** load `guardrails/SKILL.md` domain tables as standards input — that
duplicates Guardrails. Smell baseline always applies (REFERENCE.md); paste it
in full into the Standards sub-agent.

### 4. Parallel sub-agents

One message, two Task calls (`generalPurpose`, `readonly: true` when available).

**Standards sub-agent** — diff + commit list + convention source paths + smell
baseline pasted in full. Brief: report (a) light convention/pattern breaches
(cite file + rule); (b) baseline smells (name + hunk). Smells = judgement calls;
repo convention docs override baseline. Skip tooling-enforced items. Under 400 words.

**Spec sub-agent** — diff + commit list + intent source. Brief: (a) intent asked
for but missing/partial; (b) behaviour not in intent (creep); (c) looks done but
wrong vs intent. Quote intent line each time. Under 400 words. Skip if no source.

### 5. Aggregate + emit artifact

Human report under `## Spec fidelity` and `## Structure` (smells + conventions).
Do not merge axes.

Then write the machine contract (required):

```bash
mkdir -p agent-runtime/artifacts/intent-reviews
# write JSON — see schema; or:
python agent-runtime/scripts/ci/generate_intent_review_artifact.py --issue <n> --input-json /tmp/intent-review.json
```

### Artifact contract (required fields)

```json
{
  "artifactType": "intent_review",
  "id": "intent-review-issue-<n>",
  "issue": <n>,
  "spec_fidelity": "pass" | "fail",
  "smells": [
    {
      "name": "Feature Envy",
      "path": "file.py",
      "hunk": "quoted or summarised",
      "judgement": true
    }
  ],
  "convention_notes": [
    {
      "standard": "patterns.mdc — API envelope",
      "path": "file.py",
      "note": "..."
    }
  ]
}
```

| Field | Semantics |
|-------|-----------|
| `spec_fidelity` | `fail` if any intent-to-code gap, creep that contradicts intent, or wrong-vs-intent finding; else `pass` |
| `smells` | Structural findings; empty array if none. **Blocking authority** for structure lives here |
| `convention_notes` | Light citations; empty if none |

Schema: [`agent-runtime/docs/schemas/intent-review-artifact.schema.json`](../../../agent-runtime/docs/schemas/intent-review-artifact.schema.json)

Path: `agent-runtime/artifacts/intent-reviews/intent-review-issue-<n>.json`

Commit on the feature branch with the code under review.

## Visual review (ui-ux issues)

When the diff touches `apps/demo`, `apps/dashboard`, or `packages/ui`: view the screenshots
referenced in the implementation artifact (capture them yourself if missing —
`pnpm --filter @juli/demo dev`, then `npx playwright screenshot`). Judge the rendered
output against the `docs/product/design/` root authorities, not just the diff text. A UI
change that passes text-level spec fidelity but reads flat or unpolished is a Spec-axis
finding, not a pass.

## Authority (structure)

From BOUNDARY.md — verbatim:

> Executor MAY clean up structure during GREEN (refactor step). Only intent-review
> MAY block merge on structure.
