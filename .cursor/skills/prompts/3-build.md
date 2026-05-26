# Phase 3: Build — Prompt Template

> Copy, fill in the `{{placeholders}}`, and paste into a new chat.

---

```
## Role

You are an implementation agent on branch `feature/agent-b-implementation`.
You follow the standards in `.cursor/rules/` and use only skills from
`.cursor/skills_B/`.

## Feature

**{{feature-name}}** — {{one-sentence description}}

## Context to Load

{{Paste the "Load (Required)" section from the Phase 2 focus plan, or
reference it:}}
- `/context/features/{{feature-name}}/architecture.md`
- `/context/features/{{feature-name}}/api-contracts.md`
- `/context/features/{{feature-name}}/edge-cases.md`
- {{list affected source modules from the focus plan}}

## Standards That Apply

{{Paste the "Standards Applied" section from Phase 2, e.g.:}}
- [x] Reliability — external API calls detected
- [x] Observability — new endpoint
- [ ] Security — no user-facing input
- [ ] Build-AI — no AI integration

## Instructions

1. Read the architecture and API contract docs before writing any code.
2. Implement the feature following the system design:
   - Create/modify services, models, routes as specified
   - Handle every edge case from `edge-cases.md`
   - Write unit tests alongside implementation
   - Follow error handling patterns from `.cursor/rules/reliability.mdc`
   - Add structured logging per `.cursor/rules/observability.mdc`
3. Use conventional commits: `feat({{scope}}): ...`, `test({{scope}}): ...`
4. Keep functions < 30 lines, single responsibility.
5. After implementation, list:
   - Files created/modified
   - Tests added
   - Any deviations from the spec (with justification)
   - Open questions for the review phase
```

---

### When to use

- Implementing any feature that does NOT involve AI/LLM integration
- For AI features, use this template AND supplement with `3b-build-ai.md`

### Exit criteria

- All components from `architecture.md` implemented
- All API contracts fulfilled (including error responses)
- All edge cases from `edge-cases.md` handled
- Unit tests written and passing
- Structured logging on error paths

### Next phase

Hand off to **Phase 4: Review** (`4-review.md`)
