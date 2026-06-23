# Purpose

Use when writing/reviewing Python in this repo (FastAPI, async services, modules under `src/`).

# Core Principles

- Prefer clarity over cleverness; optimize for change.
- Type hints are part of the interface; keep them accurate.
- Keep domain logic out of HTTP routes; routes orchestrate.
- Favor composition + small functions over inheritance trees.
- Prefer dataclasses / Pydantic models for data, not dict soup.
- Depend on abstractions (Protocols), inject implementations (DI).
- Async is for I/O; avoid blocking calls in async code paths.
- Boundaries are explicit: API ↔ use case ↔ domain ↔ infrastructure.
- Errors: raise specific exceptions, wrap with context, never swallow.

# Preferred Patterns

- **Type hints**
  - Use modern hints (`list[str]`, `dict[str, Any]`, `X | None`).
  - Use `Protocol` for dependencies consumed by domain/use-cases.
  - Prefer narrow return types (don’t return `Any` unless unavoidable).
- **Dataclasses**
  - Use `@dataclass(frozen=True)` for value objects; mutable only when needed.
  - Validate invariants in `__post_init__` (domain), not in routes.
- **Dependency injection**
  - Routes accept interfaces (service/use-case) via FastAPI dependencies.
  - Use constructors to inject repos/clients; avoid module globals.
- **Async I/O**
  - Use async HTTP clients and DB drivers; don’t call `requests` in async.
  - Keep timeouts explicit; propagate cancellation (don’t blanket-catch `CancelledError`).
- **Package organization**
  - `api/`: request/response shapes + routing only.
  - `use_cases/`: orchestration + transaction boundaries.
  - `domain/`: pure business rules + entities + policies.
  - `infrastructure/`: external systems (DB, HTTP, queues) behind interfaces.
- **Separation of concerns**
  - Parsing/validation at boundaries; domain functions accept typed inputs.
  - Side effects live at edges; domain stays deterministic.

# Avoid

- Business logic in FastAPI routes.
- “God services” that do everything (HTTP + DB + rules + formatting).
- Deep inheritance for “frameworky” reuse; prefer composition + helpers.
- Premature abstractions (generic repositories, over-general base classes).
- Hidden global state (singletons, mutable module-level caches).
- Blocking I/O inside `async def` (file, network, DB).
- Broad `except Exception:` without re-raise + context.
- Unbounded results in list endpoints (always paginate/bound).

# Code Review Checklist

- **Interfaces**: public functions/classes have correct type hints.
- **Boundaries**: route → use case → domain → infra separation is preserved.
- **Async**: no blocking calls in async paths; timeouts set; cancellation respected.
- **Errors**: specific exceptions; no silent failure; message/context is safe (no secrets).
- **Data**: dataclasses/models used instead of dicts; invariants enforced once.
- **Coupling**: domain does not import FastAPI/DB clients directly.
- **Performance**: bounded loops/queries; no accidental N+1 patterns.

# Agent Instructions

- Keep new modules small; wire via DI instead of global imports.
- Default to `Protocol` for external dependencies consumed by domain/use-cases.
- Put HTTP concerns (status codes, Depends, request parsing) in `api/` only.
- For async endpoints: use async clients, add timeouts, and return typed models.
- Add/adjust tests for new logic (unit-first); don’t “fix” by weakening assertions.

