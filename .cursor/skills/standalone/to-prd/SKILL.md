---
name: to-prd
description: Synthesizes the current conversation context and codebase understanding into a PRD, then files it as a GitHub issue. Use when the user asks to create a PRD, spec, or requirements doc from the current context, or when they want it submitted as a GitHub issue.
---

## to-prd

Turn the current conversation context into a PRD and submit it as a GitHub issue. Do **not** interview the user—synthesize what you already know from the conversation and repository patterns.

In the `build-feature` pipeline, consume the **grill-with-docs → to-prd handoff** and updated
canonical docs (`EXECUTION.md`, `docs/system-design.md`, `docs/architecture/`, ADRs).
Do not re-interview; note assumptions from the handoff in the PRD.

### Process

#### 1) Understand the current state

- Read the grill-with-docs handoff (if present) and relevant `EXECUTION.md` slices
- Explore the repo enough to understand:
  - the product surface area (apps/services/packages)
  - the major modules and boundaries
  - existing conventions for APIs, schemas, testing, and deployment
  - any prior art similar to the requested feature

#### 2) Sketch the “deep modules” first

Propose major modules to build or modify to implement the feature. Prefer “deep modules”: they encapsulate lots of behavior behind a small, stable, testable interface.

- Identify:
  - modules you’ll add/modify (by responsibility, not file path)
  - each module’s public interface (functions/classes/events/APIs, described in words)
  - important contracts (inputs/outputs, errors, invariants)
  - integration points (UI ↔ API, service ↔ DB, worker ↔ queue, etc.)

#### 3) Lightweight expectation check

Without interviewing, do a quick alignment pass:

- Briefly list the proposed modules and ask:
  - whether this matches expectations
  - which modules they want tests written for

If the user doesn’t respond, proceed with the most reasonable defaults and note assumptions in “Implementation Decisions”.

#### 4) Write the PRD

Use the template below. Keep it from the user’s perspective. Do **not** include specific file paths or code snippets.

##### PRD template

**Problem Statement**
The problem that the user is facing, from the user's perspective.

**Solution**
The solution to the problem, from the user's perspective.

**User Stories**
A LONG, numbered list of user stories, extremely extensive and covering all aspects of the feature.

Format each as:
As an <role>, I want <capability>, so that <benefit>.

**Implementation Decisions**
A list of implementation decisions made, including (as applicable):
- modules to build/modify (by responsibility)
- interfaces/contracts that will be modified
- technical clarifications and assumptions
- architectural decisions
- schema changes
- API contracts
- specific interactions (described behaviorally)

**Testing Decisions**
Testing decisions that were made, including:
- what makes a good test (test external behavior, not implementation details)
- which modules will be tested
- prior art for tests in the codebase (if any)

**Out of Scope**
What is out of scope for this PRD.

**Further Notes**
Any further notes, risks, rollout, observability, migration, and follow-ups.

#### 5) Submit as a GitHub issue

Create an issue in the current repo using `gh`:

- Title: a short, user-facing title (avoid internal module names)
- Body: the PRD, with headings and a short “Assumptions” bullet list if needed
- Labels: apply labels only if the repo already uses an obvious labeling scheme

Use a heredoc to avoid formatting issues when creating the issue body.

