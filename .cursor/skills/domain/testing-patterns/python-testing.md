# Purpose

Use when adding/changing Python behavior in this repo to ensure tests are fast, deterministic, and cover failure/edge paths.

# Core Principles

- Unit tests first; integration tests only where boundaries demand it.
- Determinism is non-negotiable (no network, no time, no randomness).
- Test behavior and contracts, not implementation details.
- One behavior per test; clear AAA structure.
- Fixtures reduce duplication; keep them small and explicit.
- Mock at boundaries (HTTP clients, DB, queues), not inside pure domain.
- Prefer parametrization over copy/paste tests.
- Keep suite fast; slow tests must be isolated/marked.

# Modular Monolith Test Layers

Per [PRD #550 Testing Decisions](docs/product/phases/modular-monolith-upgrade/PRD.md#testing-decisions) — place tests by boundary, not by convenience.

| Layer | Scope | Placement | Rules |
|-------|-------|-----------|-------|
| **Unit** | One module | `tests/unit/` | Exercise only that module's **public surface** (facades, ports, published helpers). Mock or fake cross-module deps; never import another module's internals. |
| **Integration** | Module collaboration | `tests/integration/` | Call **public facades** across module boundaries only — prove contracts (import edges, ownership, dispatcher ports) without reaching private files. |
| **E2E** | User workflows | existing E2E suites | Drive complete flows from the **outside** (HTTP, CLI, browser). Assert outcomes, not internal layout. |

- Default suite stays offline: no live TikTok/Supabase; use fakes and registry/contract checks (`test_import_boundaries`, `test_ownership_registry`).
- Architecture checks (import-linter, cycle audit, ownership registry) complement tests — a green unit suite that crosses module internals is still wrong.

# Preferred Patterns

- **pytest structure**
  - Name tests by behavior: `test_<action>_<condition>_<outcome>`.
  - Use `pytest.raises(..., match=...)` for failures; assert error type + message intent.
- **Fixtures**
  - Use function-scope by default; widen scope only for expensive setup.
  - Avoid “mega fixtures” that build an entire world.
  - Use `tmp_path` for filesystem; never touch real user paths.
- **Mocking**
  - Mock external I/O: TikTok API client, webhooks, DB repos, time sources.
  - Patch where the dependency is *used*, not where it is defined.
  - Prefer fakes (small in-memory implementations) for stable contracts.
- **Parametrization**
  - Use `@pytest.mark.parametrize` for boundary values and matrix cases.
  - Add `ids=` for readability when cases are non-trivial.
- **Async**
  - Use `pytest.mark.asyncio` (or repo’s async test convention) for `async def` tests.
  - Use async fakes/mocks; assert awaited calls (`assert_awaited_once`).
- **Regression focus**
  - Add a test that would have caught the bug; keep it minimal.

# Avoid

- Network calls in tests (even “local” HTTP) unless explicitly integration/E2E.
- Sleeping for timing; use injected clocks or deterministic triggers.
- Snapshot tests for rapidly-changing payloads unless the snapshot is stable and intentional.
- Over-mocking internals (private methods, local helpers).
- Brittle fixtures coupled to ordering or global state.
- Large integration suites by default; keep the “default” run fast.

# Code Review Checklist

- **Happy path**: primary behavior covered with clear assertions.
- **Failure path**: expected exceptions/errors covered (type + message intent).
- **Edge cases**: empty inputs, None/optional values, boundary numbers, duplicates.
- **Regression**: new/changed behavior has a targeted test preventing recurrence.
- **Isolation**: no real network; external services mocked/faked at boundaries.
- **Determinism**: no time dependence; fixed seeds; no hidden global state.
- **Speed**: tests run quickly; slow tests marked and isolated.

# Agent Instructions

- When changing behavior: write/adjust tests first, then implement minimal fix.
- Default to unit tests around domain/use-case functions; mock I/O.
- Use fixtures for shared setup, but keep data explicit inside each test.
- Prefer parametrized tests for input variations instead of duplicating bodies.
- If a test needs time/UUID/randomness, inject a provider and control it in tests.

