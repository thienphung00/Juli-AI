---
name: handoff
description: >-
  Compacts the current conversation and session state into a handoff document at
  docs/handoffs/ so the next session can continue without re-discovering context.
  Use when the user says "handoff", "end session", "wrap up", "close out", or when
  invoked at the end of a Planning or implementation session.
---

# Handoff

Compact the current conversation and session state into a handoff document
so the next session can continue without re-discovering context.

## Output file

`docs/handoffs/YYYY-MM-DD-{slug}.md`

where `slug` = 2–4 word kebab-case summary of the session topic.

## Required sections

1. **Session summary** (2–3 sentences: what was attempted, what was completed)
2. **Decisions made** (list only — no rationale; rationale belongs in ADRs)
3. **Current state** (which issues are open, which are closed, what branch is active)
4. **Next steps** (ordered, actionable — what the next session should start with)
5. **Open questions** (unresolved decisions that still need the user's input)
6. **Files changed** (`git diff --name-only` summary)

## Issue-phase checkpoints

For work inside the full issue cycle (Planning → Implementation → Review), use
[`../../shared/checkpoint-handoff.md`](../../shared/checkpoint-handoff.md) for mandatory checkpoint and per-phase handoff files (`docs/handoffs/issue-{N}-{phase}.md`). Do not restate phase tables here — that doc is the source of truth.

## Constraints

- Never include seller financial data (revenue, ROAS, ad spend, inventory values).
  Reference aggregates or labels only ("ROAS declined", not "ROAS = 0.8").
- Keep the file under 400 lines. If context is larger, summarise further.
- The next session starts by reading this file before reading anything else.
