# Purpose

Use when adding or changing Python behaviour in this repo. Tests are fast,
deterministic, cover the failure paths, and read as a description of the
behaviour. The exemplar modules (copy their shape, not just their ideas):

| Testing a… | Copy |
|------------|------|
| repository | `tests/unit/test_repositories_base.py`, `test_repositories_commerce.py` |
| service with a failure ladder | `tests/unit/test_repositories_production_write.py` (parametrized miss matrix) |
| two implementations of one contract | `tests/unit/test_kpi_caches.py` (one parametrized class, both adapters) |
| an async generator / stream | `tests/unit/test_agent_run_event_stream.py` with `tests/support/event_stream.py` |
| a route | `tests/unit/test_agent_confirmation_decision_route.py` on the `auth_client` fixture |
| code driving an external client | `tests/unit/test_analytics_poll_cycle.py` — contract-shaped fakes instead of `MagicMock` |

# Core Principles

- Unit tests first; integration tests only where boundaries demand it.
- Determinism is non-negotiable: no network, no wall-clock sleeps, no randomness.
- Test behaviour and contracts, not implementation details.
- One behaviour per test, written as given / when / then with blank lines between.
- Fixtures reduce duplication; the data a test is *about* stays inline.
- Fakes at boundaries (HTTP clients, Redis, queues), never inside pure domain.
- Parametrize a matrix; never copy a test body.

# Modular Monolith Test Layers

Per [PRD #550 Testing Decisions](docs/product/phases/modular-monolith-upgrade/PRD.md#testing-decisions) — place tests by boundary, not by convenience.

| Layer | Scope | Placement | Rules |
|-------|-------|-----------|-------|
| **Unit** | One module | `tests/unit/` | Exercise only that module's **public surface** (facades, ports, published helpers). Fake cross-module deps; never import another module's internals. |
| **Integration** | Module collaboration | `tests/integration/` | Call **public facades** across module boundaries only — prove contracts (import edges, ownership, dispatcher ports) without reaching private files. |
| **E2E** | User workflows | existing E2E suites | Drive complete flows from the **outside** (HTTP, CLI, browser). Assert outcomes, not internal layout. |

- Default suite stays offline: no live TikTok/Supabase; use fakes and registry/contract checks (`test_import_boundaries`, `test_ownership_registry`).
- Architecture checks (import-linter, cycle audit, ownership registry) complement tests — a green unit suite that crosses module internals is still wrong.

# `tests/support` — use it, do not copy it

| Need | Import |
|------|--------|
| a user / shop / product / order / credential / workflow run | `tests.support.builders.make_*` — unique defaults, override only what the test is about |
| the app + an authenticated tenant | fixtures `tenant`, `shop`, `app`, `auth_client` (`tests/unit/conftest.py`); or `tests.support.api.authenticated_client` for a second tenant |
| Redis | `tests.support.fakes.FakeAsyncRedis` — set `get_raises` / `set_raises` for an outage |
| Postgres gate | `tests.support.postgres.requires_postgres` — the only definition |
| time | `tests.support.clock.SteppingClock` — inject as `now`; never `asyncio.sleep` to wait |
| the SSE stream | `tests.support.event_stream` — `FakePubSub`, subscriber doubles, `sse_ids`, `drain` |
| TikTok polling collaborators | `tests.support.tiktok_fakes` — resources and rate limiter with the real signatures, recording calls |

A module that defines its own `shop` fixture, `_database_url()`, or `FakeAsyncRedis`
is repeating something that exists. Delete it and import.

# Preferred Patterns

- **Naming**: `test_<behaviour>_<condition>` in plain words —
  `test_another_shops_row_reads_as_missing_not_forbidden`. Never a ticket or AC code in
  the name (`test_ac2_…`, `test_issue_1234_…`); cite the issue in the docstring instead.
- **Classes group one behaviour**: `class TestUpsert:` holds every upsert proof. The class
  docstring states the rule under test in one sentence.
- **Failures**: `pytest.raises(Type, match=...)` — assert the type and the message intent.
  For typed domain errors also assert the `error_code`.
- **Doubles** are hand-written classes with the real method signatures
  (`class FailingSubscriber: async def subscribe(self, channel)`). `MagicMock()` and
  `**kwargs`-swallowing stubs prove that something was called, not that the real call
  would work. When a real collaborator is cheap (a repository on the test session), use it.
- **Assert on outcomes**: return values, persisted rows (re-read them), HTTP status and
  body. Not `assert_called_with`, not `_private` attributes, not log text — a log event
  name is asserted only when the log *is* the contract (an operator runbook greps for it).
- **Parametrize** matrices with `ids=`; a `pytest.param(..., id="expired")` per case.
- **Async**: `asyncio_mode = auto` — no `pytest.mark.asyncio`, no `pytestmark`. Async
  fixtures are plain `@pytest.fixture`. Waiting is done with an injected interval and
  `asyncio.wait_for`, never a real-time `sleep` in the test body.
- **Regression**: every fix lands with the test that would have caught it, named for the
  behaviour and citing the issue in its docstring.

# Avoid

- Network calls in tests (even "local" HTTP) unless explicitly integration/E2E.
- Sleeping for timing; use injected clocks/intervals or deterministic triggers.
- Meta-tests that assert on prose in `.md` files or on the text of source code, unless the
  text *is* the contract (a CI gate reads it).
- Reaching into `_private` names. If the behaviour is not reachable through the public
  surface, the module needs a seam, not the test a shortcut.
- Test modules over ~500 lines: split by behaviour the same way source splits by aggregate.
- Brittle fixtures coupled to ordering or global state; reset singletons in a fixture.

# Code Review Checklist

- **Happy path**: primary behaviour covered with clear assertions.
- **Failure path**: expected exceptions covered — type, message intent, error code.
- **Edge cases**: empty inputs, `None`, boundary numbers, duplicates, the other tenant.
- **Regression**: the changed behaviour has a targeted test.
- **Isolation**: no real network; external services faked at boundaries.
- **Determinism**: no wall-clock dependence; no hidden global state.
- **Reuse**: nothing in the module duplicates `tests/support`.

# Agent Instructions

- When changing behaviour: write or adjust the test first, then the minimal implementation.
- Open the exemplar for the kind of thing you are testing before writing a line.
- Use builders for setup; keep the values the test is about explicit in the test.
- Run `ruff format` and `ruff check` on the test file; pre-commit lints tests with E501.
- Run with `PYTHONPATH=backend/src` in a worktree, or the green is against the wrong tree.
