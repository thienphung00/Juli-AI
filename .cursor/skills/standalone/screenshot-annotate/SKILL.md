---
name: screenshot-annotate
description: >-
  Converts UI screenshots into structured markdown files describing visible UI state.
  Invoked internally by the ui-bug skill only — not user-invoked directly.
---

# Screenshot annotate

Convert one or more UI screenshots into structured markdown files
that describe the visible state of the UI. Invoked as the first step of the ui-bug pipeline.

## Input

One or more image files (PNG, JPG) and an optional plain-language description.

## Output

For each screenshot, produce a markdown file at `docs/ui-bugs/YYYY-MM-DD-{slug}-N.md`:

```markdown
# UI state: [surface] — [brief description]
Surface: ios/ | web/
Date: YYYY-MM-DD

## Visible components
[List every distinct UI component visible in the screenshot.
 For each: component name (use CONTEXT.md terms if available), approximate position,
 and current visible value or state.]

## Developer annotation (to be completed by developer)
[Leave this section blank — the ui-bug skill will pause for user input here.]

## Design token references
[For any component where a value is visually wrong, note the design token
 that governs it from ui-ux-design.mdc. If the token is not known, leave blank.]
```

## Constraints

- Do not include seller financial data values in the markdown, even if visible in the screenshot.
  Describe the component type only ("revenue card", "ROAS metric"), not the value shown.
- Use `CONTEXT.md` glossary terms for any Juli AI-specific component names.
- If `CONTEXT.md` does not exist, use descriptive names. Do not invent Juli AI-specific terms.
