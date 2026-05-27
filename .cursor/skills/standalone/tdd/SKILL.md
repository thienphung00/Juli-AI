---
name: tdd
description: Guides implementation using test-driven development with a red-green-refactor loop and integration-style tests focused on public behavior. Use when the user wants test-first development, mentions “red-green-refactor”, requests integration tests, or asks to fix a bug via TDD.
---

## Test-driven development (TDD)

### Philosophy

Core principle: tests should verify **behavior through public interfaces**, not implementation details. Good tests read like a specification (e.g., “user can checkout with valid cart”) and survive refactors because they don’t care about internal structure.

Avoid tests that are coupled to implementation:

- mocking internal collaborators by default
- testing private methods
- asserting incidental data structures or call sequences
- tests that fail on refactor even when behavior is unchanged

If available in the repo, follow `tests.md` for examples and `mocking.md` for mocking guidelines.

### Anti-pattern: horizontal slices

Do **not** write many tests first and then implement everything (“horizontal slicing”).

- WRONG: RED = test1..testN, then GREEN = impl1..implN
- RIGHT: RED→GREEN for **one** test/behavior at a time (“vertical slices” / tracer bullets)

### Workflow

#### 1) Planning (before writing code)

- Confirm what the **public interface** should look like (APIs, CLI, UI behavior, exported functions, etc.)
- Confirm which **behaviors matter most** to test (critical paths first)
- Identify opportunities for **deep modules** (small interface, deep logic, testable in isolation)
- List **behaviors to test**, not implementation steps

Ask: “What should the public interface look like? Which behaviors are most important to test?”

#### 2) Tracer bullet (first end-to-end test)

- **RED**: write one integration-style test for one behavior → it fails
- **GREEN**: write the minimal real implementation to pass → it passes

This proves the end-to-end path is viable and anchors the rest of the work.

#### 3) Incremental loop (repeat per behavior)

For each next behavior:

- **RED**: add the next test → watch it fail for the right reason
- **GREEN**: add only enough code to pass that test

Rules:

- one test at a time
- no speculative features “for the next tests”
- keep tests focused on observable behavior through the public interface

#### 4) Refactor (only when GREEN)

After tests pass, refactor in small steps:

- extract duplication
- deepen modules (move complexity behind stable interfaces)
- improve design (SOLID where natural)
- run tests after each refactor step

Never refactor while RED.

### Checklist per cycle

- [ ] test describes behavior, not implementation
- [ ] test uses a public interface only
- [ ] test would survive internal refactor
- [ ] implementation is minimal for the current test
- [ ] no speculative features added

