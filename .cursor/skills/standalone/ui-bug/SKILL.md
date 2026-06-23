---
name: ui-bug
description: >-
  Takes UI defect screenshots, converts them to annotated markdown specs, aligns on
  design intent, and decomposes into GitHub issues. Use when the user says "ui bug",
  "visual bug", "the screen looks wrong", "layout is broken", "design doesn't match",
  or when filing UI defect issues for Executor implementation.
---

# UI bug

Take one or more screenshots showing a UI defect, convert them to annotated
markdown specs, align on design intent, and decompose into GitHub issues.

## Step 1 — screenshot-annotate

Invoke `screenshot-annotate` skill.

- **Input:** screenshot file(s) and optional description.
- **Output:** a markdown file per screenshot at `docs/ui-bugs/YYYY-MM-DD-{slug}.md`

## Step 2 — developer annotation (pause for user input)

Present the generated markdown to the user.
Ask: "Please annotate: which component, what the value should be,
and what the current incorrect value is. One annotation per bullet."
Do not proceed until annotations are provided.

## Step 3 — grill-with-docs (design intent alignment)

Load `ui-ux-design.mdc` before grilling.
Ask only questions necessary to understand design intent.
Reference Juli AI's design token system (colors, typography, spacing)
for any value question. Do not ask for values the token system already specifies.
Update `CONTEXT.md` if new UI patterns or terms are resolved.

## Step 4 — to-issues

Create one GitHub issue per distinct UI defect.

Issue body format:

```markdown
## What's wrong
[component name, incorrect value, surface: ios/ or web/]
## What it should be
[correct value from design token system or user annotation]
## Screenshot
[link to docs/ui-bugs/ file]
## Acceptance criterion
[one testable statement: "The [component] renders [value] on [surface]"]
```

Labels: `bug`, `ui`

## Per-issue loop

- `focus` loads `ui-ux` executor + `ui-ux-design` + `swift-patterns` (iOS) or `nextjs` (web).
- Executor uses built-in TDD: SwiftUI Preview (iOS) or React Testing Library (web) as the fast feedback loop.
- `review` → `validate` → `ship` verifies the acceptance criterion passes before closing the issue.
