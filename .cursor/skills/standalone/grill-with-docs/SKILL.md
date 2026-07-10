---
name: grill-with-docs
description: >-
  Aligns on a plan or design by asking one question at a time with a recommended
  answer, while building CONTEXT.md and docs/adr/ ADRs inline. Use when the
  user says "grill me", "grill with docs", "start grilling", "align before building",
  or when invoked at the start of Planning or refactor work.
---

# Grill with docs

Align on a plan or design by asking one question at a time,
with a recommended answer for each. Simultaneously builds and updates `CONTEXT.md` and
`docs/adr/` ADRs inline as decisions crystallise.

Format rules for CONTEXT and ADRs: follow [`.cursor/skills/standalone/domain-modeling/SKILL.md`](../domain-modeling/SKILL.md) — summarised below.

## Stack context

| Surface | Tech |
|---|---|
| Mobile | Native SwiftUI, `ios/`, iOS 17+, Swift 6 |
| Web | Next.js 14 + React, `web/` |
| Backend | Python / FastAPI modular monolith, `src/` |
| Data | Supabase (Postgres), SQLAlchemy, Alembic |
| Issue tracker | GitHub Issues — `gh issue create/view/close` |
| ADR location | `docs/adr/` (not `docs/adr/`) |
| ADR numbering | `NNN-slug.md` — scan folder, increment (currently 029+) |
| Handoff location | `docs/handoffs/` |
| Domain glossary | `CONTEXT.md` at repo root (single context) |

## Before grilling

1. Check if `CONTEXT.md` exists. If it does, read it. Use glossary terms and `_Avoid_` aliases when decoding user language.
2. Read any ADRs in `docs/adr/` relevant to the topic.
   Summarise what is already decided. Do not re-ask questions that ADRs have settled.
3. If the topic involves the ML/LLM pipeline, read [`.cursor/skills/standalone/domain/mle-agent.md`](../domain/mle-agent.md).
   If the topic involves UI, read `ui-ux-design.mdc`.

## Grilling loop

- Ask one question at a time.
- For each question, provide your recommended answer before waiting for the user's response.
- Walk dependency branches in order: resolve a decision before asking questions that depend on it.
- If a question can be answered by exploring the codebase, explore first — do not ask.

## CONTEXT.md maintenance

- Create `CONTEXT.md` lazily — only when the first domain term is resolved.
- Use the format in `domain-modeling`: `# Title` + intro sentence, `## [Domain area]`, `**Term**:` + definition + `_Avoid_:` aliases.
- **Project-specific terms only** — do not add general programming vocabulary unless Juli-specific.
- When the user uses a term that conflicts with an existing entry, call it out:
  "Your glossary defines '[term]' as [X], but you seem to mean [Y] — which is it?"
- When a vague or overloaded term appears, propose a precise canonical term and list rejected words under `_Avoid_`.
- Update `CONTEXT.md` inline as each term is settled. Do not batch updates.

## ADR creation (`docs/adr/`)

- Scan `docs/adr/` for the next sequence number (`029-…` after current highest).
- Update `docs/adr/README.md` when adding an ADR.
- Only offer an ADR when **all three** are true:
  1. Hard to reverse — changing it later has meaningful cost.
  2. Surprising without context — a future reader would wonder "why?"
  3. Real trade-off — genuine alternatives existed.
- **Default:** structured template (Context, Decision, optional Consequences / Options) — match existing ADRs 001–028.
- **Lightweight escape hatch:** single paragraph when the decision is small but still meets all three gates.
- See `domain-modeling` for full templates and "what qualifies" list.

## Output

- A conversation summary in the format expected by `to-prd`.
- An updated `CONTEXT.md` (if terms were resolved).
- Zero or more new `docs/adr/*.md` files (+ README index row).
