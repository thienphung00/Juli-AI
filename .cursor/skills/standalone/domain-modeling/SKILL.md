---
name: domain-modeling
description: >-
  Builds and maintains the project's shared domain language by stewarding CONTEXT.md
  and proposing ADRs when architectural decisions crystallise. Use when the user says
  "update the domain model", "add this to context", "we need a new term", "update
  CONTEXT.md", or when invoked by grill-with-docs mid-workflow.
---

# Domain modeling

Continuously build and maintain the project's shared domain language.
Stewards `CONTEXT.md` and proposes ADRs when architectural decisions crystallise.
Can be invoked mid-workflow — does not require a dedicated session.

## Repo layout (Juli)

| Artifact | Location | Notes |
|----------|----------|-------|
| Domain glossary | `CONTEXT.md` at repo root | Single context — no `CONTEXT-MAP.md` unless the repo splits into multiple bounded contexts |
| ADRs | `docs/adr/` | **Not** `docs/adr/` — 28+ ADRs already live here |
| ADR index | `docs/adr/README.md` | Update when adding an ADR |

---

## CONTEXT.md format

### Structure

```markdown
# Juli AI — ubiquitous language

{One or two sentences: what this glossary covers.}

## [Domain area]

**Term**:
One or two sentences defining what it IS — not what it does.
_Avoid_: alias1, alias2

**Another term**:
Definition.
_Avoid_: overloaded word
```

Group terms under `## [Domain area]` when natural clusters emerge (e.g. TikTok Shop seller, listings, ML metrics, UI). A flat list under one heading is fine when all terms belong to one area.

### Example (Juli)

```markdown
# Juli AI — ubiquitous language

Shared domain language for seller-money workflows across `ios/`, `web/`, and `src/`.

## TikTok Shop seller

**Shop**:
A single TikTok Shop account managed by Juli AI. One seller may own multiple Shops.
_Avoid_: store, account (when meaning TikTok's native account entity)

**SPS (Shop Performance Score)**:
Juli's composite health metric for a Shop. Not a TikTok-native metric.
_Avoid_: health score (generic)

## Metrics

**AHR (Ad Health Ratio)**:
ROAS normalised against the seller's category benchmark. Range 0–1.
_Avoid_: ad score
```

### Rules

- **Be opinionated.** Pick the canonical term; list rejected synonyms under `_Avoid_`.
- **Keep definitions tight.** One or two sentences max. Define what it **is**, not what it does.
- **Project-specific only.** General programming concepts (timeouts, JWT, pytest fixtures) do not belong unless Juli gives them a special meaning (e.g. **VP**, **AHR**). Before adding a term, ask: is this unique to Juli, or a general concept?
- **Link ADRs when a term is decision-defined:** `See ADR-012` in the term block or domain section.
- **Create lazily** — only write `CONTEXT.md` when the first term is resolved.

### Single vs multi-context

- **This repo:** single context → one root `CONTEXT.md`. Do not create `CONTEXT-MAP.md`.
- **If `CONTEXT-MAP.md` ever appears:** read it to find per-context glossaries; infer which context the current topic relates to; ask if unclear.

### When a new term is introduced

- Check if it conflicts with any existing `CONTEXT.md` entry or `_Avoid_` alias.
- If it conflicts, surface the conflict before writing anything.
- If it is new, add it to the relevant domain area section.

---

## ADR format (`docs/adr/`)

### Location and numbering

- Path: `docs/adr/NNN-slug.md` (3-digit prefix, hyphen slug — e.g. `029-my-decision.md`).
- Scan `docs/adr/` for the highest existing number and increment by one.
- **Always** add a row to `docs/adr/README.md`.

### Default template (match existing ADRs)

Use for decisions that need context for future readers. Follow the shape of ADRs 001–028:

```markdown
# ADR-NNN: {Short title}

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNN
**Date:** YYYY-MM-DD
**Deciders:** [who decided]

## Context
{Why this decision came up.}

## Decision
{What was decided.}

## Consequences
{Non-obvious downstream effects — only when they add value.}

## Options considered
{Rejected alternatives — only when the rejection is non-obvious.}
```

Existing ADRs may also include Rationale, Rollout, References — add those sections when genuinely useful.

### Lightweight template (escape hatch)

When the decision is small but still meets all three gates below, a single paragraph is acceptable:

```markdown
# ADR-NNN: {Short title}

**Status:** Accepted
**Date:** YYYY-MM-DD

{1–3 sentences: context, decision, and why.}
```

Optional sections (Status beyond Accepted, Considered Options, Consequences) only when they add genuine value.

### When to offer an ADR

All three must be true:

1. **Hard to reverse** — changing it later has meaningful cost.
2. **Surprising without context** — a future reader will wonder "why did they do it this way?"
3. **Real trade-off** — genuine alternatives existed and one was chosen for specific reasons.

If easy to reverse → skip (just change it). If not surprising → skip. If no alternative → skip ("we did the obvious thing").

### What qualifies

- Architectural shape (monorepo layout, event-sourced write vs projected read model)
- Integration patterns between modules (`src/`, `web/`, `ios/`)
- Technology choices with lock-in (database, auth provider, deployment target — not every library)
- Boundary and scope decisions ("Customer data owned by X; others reference by ID only")
- Deliberate deviations from the obvious path ("manual SQL instead of ORM because …")
- Constraints not visible in code (compliance, partner API latency contracts)
- Rejected alternatives when the rejection is non-obvious

### After creating an ADR

- Update `docs/adr/README.md` with number, title, and status.
- Link from the relevant `CONTEXT.md` domain section if the decision defines a term.

---

## What domain-modeling does NOT do

- It does not rewrite `CONTEXT.md` sections unprompted.
- It does not create ADRs for ephemeral decisions ("not worth it right now").
- It does not touch implementation files.
- It does not create `docs/adr/` or use `0001-` numbering.
