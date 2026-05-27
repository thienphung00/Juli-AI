---
name: to-issues
description: Breaks a plan, spec, or PRD into independently-grabbable GitHub issues using tracer-bullet vertical slices. Use when the user wants implementation tickets created from a plan, wants a spec decomposed into reviewable issues, or wants parser or hand-history fixes split into one-test-per-behavior slices with TDD-style acceptance criteria.
---

## To Issues

Break a plan into independently-grabbable GitHub issues using vertical slices (tracer bullets).

### Process

#### 1) Gather context

- Work from whatever is already in the conversation context.
- If the user passes a GitHub issue number or URL, fetch it with `gh issue view <number>` (include comments).

#### 2) Explore the codebase (optional)

If you have not already explored the codebase, explore it enough to understand the current state.

#### 3) Draft vertical slices

Break the plan into tracer-bullet issues.

- Each issue is a **thin vertical slice** that cuts through all integration layers end-to-end (not a horizontal slice of one layer).
- A completed slice is **demoable or verifiable** on its own.
- Prefer **many thin** slices over **few thick** ones.

Each slice must be marked:

- **AFK**: can be implemented and merged without human interaction.
- **HITL**: requires human interaction (e.g., architecture decision, product/design review).

Prefer **AFK** over **HITL** where possible.

**Parser / hand-history work (TDD-aligned slices)**

When the backlog is “hands that don’t parse” or unknown bet/stack line formats, shape slices so each issue is **one behavior**, not a mega-fix:

- **Finding issues**: turn each failure mode into **one failing test** with a **minimal fixture** (raw hand-history text) and a **single expectation**: either a successful parse (assert on the smallest JSON or struct that proves the line is understood) or a **documented error** (assert on exception type/message or on an explicit `parse_error` field—pick what the codebase already uses and stay consistent).
- **Naming**: test and issue titles should say *what* broke (e.g. scientific notation chip counts, `1.2K` suffix, odd spaces, all-in for less than remaining stack) so CI output points at the format, not “parser broke”.
- **Implementing**: the vertical slice is **RED** (test committed or on branch, fails) → **GREEN** (smallest parser change that makes only that test pass, without widening behavior blindly) → **REFACTOR** once green if duplication appears. Avoid a large parser rewrite until there is a **regression net** of these fixtures; add tests in the same order you discover failures.

Repository pattern: inline hand strings plus `_parse_first_hand`-style helpers in `tests/test_parser_filters.py` (and siblings) next to `parser.gg` / `parse_hand_block`—extend that style rather than introducing a second convention.

#### 4) Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked as HITL and AFK?

Iterate until the user approves the breakdown.

#### 5) Create the GitHub issues

For each approved slice, create a GitHub issue using `gh issue create`.

- Create issues in **dependency order** (blockers first) so you can reference real issue numbers in the "Blocked by" field.
- Do **not** close or modify any parent issue.

Use this body template.

### Issue body template

## Parent
<!-- If the source was a GitHub issue, otherwise omit this section -->

## What to build
<!-- Describe end-to-end behavior, not layer-by-layer implementation -->

## Acceptance criteria
- Criterion 1
- Criterion 2
- Criterion 3
<!-- Parser slice example: one new pytest with minimal raw hand fixture; expectation is either parsed field(s) or explicit error contract; no unrelated parser churn. -->

## Blocked by
<!-- "None - can start immediately" OR "Blocked by #123" -->

