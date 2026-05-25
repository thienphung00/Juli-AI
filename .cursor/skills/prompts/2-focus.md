# Phase 2: Focus — Prompt Template

> Copy, fill in the `{{placeholders}}`, and paste into a new chat.

---

```
## Role

You are a context navigator agent. Read and follow the focus skill at
`.cursor/skills_B/focus/SKILL.md` before doing anything else.

## Task

Prepare the context loading plan for implementing **{{feature-name}}**.
The discover phase has already produced specs at:
`/context/features/{{feature-name}}/`

## What Was Discovered

{{Paste a 2-3 sentence summary from the discover phase, or say "read the
discover output at the path above."}}

## Instructions

1. Classify the implementation task — detect what it touches:
   external APIs, AI models, DB, new endpoints, frontend, background jobs,
   integration connectors.

2. Produce a context loading plan with these sections:

   ### Load (Required)
   - Feature docs: `architecture.md`, `api-contracts.md` (always)
   - Affected source modules
   - Applicable skills (e.g., `build-ai` if AI detected)

   ### Load (If Needed)
   - `edge-cases.md`, `db-changes.md`, `ai-eval-plan.md`
   - Review checklists matching the task type

   ### DO NOT Load
   - Unaffected services, historical specs, full codebase
   - `PRD.md` (business context — not needed for implementation)

   ### Standards Applied
   - Check which standards trigger: reliability, security,
     observability, performance, build-ai

3. Verify the context budget:
   - 60-70% reserved for code and task
   - 20-30% for context docs
   - 10% for agent reasoning

4. Output the final plan as a markdown document I can reference
   during the build phase.
```

---

### When to use

- After discover has produced specs, before implementation begins
- When switching between features mid-session
- When the agent seems confused (likely wrong or stale context)

### Exit criteria

- Context plan document listing load/skip/standards decisions
- Context fits within budget (no overload)
- Affected layers and applicable standards explicitly identified

### Next phase

Hand off to **Phase 3: Build** (`3-build.md`) or **Phase 3b: Build-AI** (`3b-build-ai.md`)
