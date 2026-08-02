---
description: Run the Architect planning phase — focus, grill-with-docs, to-prd, to-issues.
argument-hint: [what to plan]
---

Dispatch the `architect` subagent to plan: **$ARGUMENTS**

Task it with the canonical Planning sequence — `focus` → `grill-with-docs` → `to-prd` →
`to-issues` — and remind it that grilling is one question at a time, each with a recommended
answer, updating `CONTEXT.md` and `docs/adr/` inline as decisions crystallise.

The Architect must not implement, assign executor domains, validate, or ship.

Because grilling is interactive, relay the Architect's questions back to the user verbatim
and pass their answers through. Do not answer scope questions on the user's behalf.

When it finishes, report: decisions made, documents written, issue numbers created, any
`epicRegistry` entry added, open questions, and the next command to run.
