
---
name: qa
description: Runs an interactive QA session where the user reports bugs conversationally and the agent files durable, user-focused GitHub issues using the project’s domain language. Use when the user wants to report bugs, do QA, file issues conversationally, or mentions “QA session”.
---

## QA session

Run an interactive QA session. The user describes problems they’re encountering; you lightly clarify, explore the codebase for context and domain language, and file GitHub issues immediately.

### Session loop

Keep going issue-by-issue until the user says they’re done. Don’t batch multiple reports into one issue unless they’re clearly the same behavior.

For **each** issue the user raises:

#### 1) Listen and lightly clarify

Let the user describe the problem in their own words. Ask **at most 2–3** short clarifying questions focused on:

- expected vs actual behavior
- steps to reproduce (if not obvious)
- consistent vs intermittent

Do not over-interview. If it’s clear enough to file, move on.

#### 2) Explore the codebase in the background (context only)

While talking to the user, explore the repo to learn:

- the domain language used in the relevant area (check `UBIQUITOUS_LANGUAGE.md` if it exists)
- what the feature is supposed to do
- the user-facing behavior boundary

Goal is **not** to find a fix—only to write a better issue. The issue must **not** reference file paths, line numbers, or internal module names.

#### 3) Assess scope: single issue or breakdown

Break down into multiple issues when:

- the report spans multiple independent behavior problems
- separable concerns could be worked on in parallel
- there are distinct symptoms/failure modes that need independent reproduction/verification

Keep as a single issue when it’s one behavior that’s wrong in one place.

#### 4) File the GitHub issue(s)

Create GitHub issues using `gh issue create`. Do **not** ask the user to review first—file and share URLs immediately.

##### Single issue template

## What happened

[Describe the actual behavior the user experienced, in plain language]

## What I expected

[Describe the expected behavior]

## Steps to reproduce

1. [Concrete, numbered steps a developer can follow]
2. [Use domain terms from the codebase, not internal module names]
3. [Include relevant inputs, flags, or configuration]

## Additional context

[Any extra observations (from the user or exploration) using domain language; no file paths/line numbers]

##### Breakdown (multiple issues)

Create issues in dependency order (blockers first) so you can reference real issue numbers.

Use this template for each sub-issue:

## Parent issue

#<parent-issue-number> (if you created a tracking issue) or "Reported during QA session"

## What's wrong

[Describe this specific behavior problem—only this slice]

## What I expected

[Expected behavior for this slice]

## Steps to reproduce

1. [Steps specific to THIS issue]

## Blocked by

- #<issue-number> (if truly blocked)

Or "None — can start immediately".

## Additional context

[Extra observations relevant to this slice]

##### Rules for all issue bodies

- No file paths or line numbers
- Use the project’s domain language
- Describe behaviors, not code
- Reproduction steps are mandatory (ask if you can’t determine them)
- Keep it concise (readable in ~30 seconds)

#### 5) Continue the session

After filing, print all issue URLs (and blocking relationships if any), then ask:

“Next issue, or are we done?”

