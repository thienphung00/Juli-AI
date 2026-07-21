---
name: ui-ux-executor
description: >-
  Executor Agent domain skill for web and iOS UI work. Use when implementing
  GitHub issues that touch web/, ios/, components, pages, forms, or visual
  interaction behavior.
---

# UI/UX Executor

Executor Agent domain skill for interface work. Implements issues with built-in
TDD (Red → Green → Refactor). Canonical requirements:
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| `web/` component, page, route, form | `ui-ux-design`, `nextjs`, `react-best-practices` |
| shadcn registry primitive | `shadcn` (only when adding registry components) |
| `ios/` SwiftUI | `swift-patterns`, `ios/MODULE.md` |

## Required context

- `web/MODULE.md` or `ios/MODULE.md` for affected app
- Route/page acceptance criteria from GitHub issue
- Design system docs if present (`Design-md/`, `globals.css` tokens)

## TDD expectations

- **Red:** failing component/route/a11y test for one acceptance criterion
- **Green:** minimal UI change to pass
- **Refactor:** extract components, tighten selectors; tests stay green (advisory —
  only `intent-review` may block merge on structure)

Test surfaces: `web/src/__tests__/`, Playwright when E2E is in scope, `ios/Tests/`.

## Review focus

Accessibility, state handling, hydration/client boundaries, visual consistency,
Vietnamese copy with diacritics, empty/loading/error states.

## Validation

Web: `npm run lint`, `npm run type-check`, `npm run test` in `web/`.
Map each acceptance criterion to a named test where practical.

## Implementation artifact (required handoff)

Before Review Agent, write `agent-runtime/artifacts/implementations/implementation-issue-<n>.json`.

```bash
python agent-runtime/agent-runtime/scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain ui-ux
```

Document TDD cycles in `redGreenRefactorEvidence`, list UI files in `filesModified`,
and map `testsAdded` to acceptance criteria. Record `contextFilesLoaded`, `skillsLoaded`,
`rulesLoaded`, `mcpsUsed` from the session. Use the same `phaseRunId` across
implementation, review, and validation artifacts.

Schema: [`agent-runtime/docs/schemas/implementation-artifact.schema.json`](../../../agent-runtime/docs/schemas/implementation-artifact.schema.json)

## Must not

- Change backend API contracts without a separate backend slice
- Ship or validate — hand off to Review Agent
