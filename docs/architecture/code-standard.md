# The Juli code standard

This is the long form of `.cursor/rules/code-quality.mdc`. It exists so an
agent adding a repository, a service or a route can open one file, see the
shape it is expected to produce, and understand why that shape and not
another. Every rule below is demonstrated by a module in the tree; when the
rule and the module disagree, the module is the bug.

## 1. Start from the exemplar

| You are adding | Open first | Then |
|----------------|-----------|------|
| a repository | `backend/src/juli_backend/repositories/_base.py` | `repositories/commerce.py` |
| a service | `backend/src/juli_backend/services/agent_runs/confirmations.py` | its route in `api/routes/agent_runs.py` |
| a route | `backend/src/juli_backend/api/routes/agent_runs.py` | the service it calls |
| shared infrastructure | `backend/src/juli_backend/services/kpi_cache/` | the two adapters over it |
| a test | the matching module in `tests/unit/test_repositories_*.py`, `test_kpi_caches.py`, `test_agent_run_event_stream.py` | `tests/support/` |

## 2. One aggregate per module

`repositories/repos.py` held thirty repository classes in 1,690 lines with two
competing shapes; `api/routes/agent_runs.py` held the SSE machinery, a Redis
adapter, a state machine and a read model in 1,236. Both were correct and both
were unmaintainable: a reader could not tell what a change would touch, and the
same guard (tenant scoping, the stale-write check) was written by hand in
several places inside the same file.

The rule: a module owns one thing. Its docstring says what that thing is, the
rules the module enforces, and the issue or ADR that decided each rule. If the
docstring needs "and", split.

**Before** (one of four identical classes):

```python
class BronzeReturnRawPayloadsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_batch(self, records):
        if not records:
            return []
        rows = [BronzeReturnRawPayload(shop_id=r["shop_id"], ingest_source=r["ingest_source"],
                payload=r["payload"], received_at=r.get("received_at") or datetime.now(UTC),
                tiktok_return_id=r.get("tiktok_return_id"), tiktok_order_id=r.get("tiktok_order_id"),
                source_event_id=r.get("source_event_id")) for r in records]
        self._session.add_all(rows)
        await self._session.flush()
        return rows
```

**After** (`repositories/bronze.py`):

```python
class BronzeReturnRawPayloadsRepo(BronzeRawPayloadsRepo[BronzeReturnRawPayload]):
    """``bronze.return_raw_payloads`` (#605)."""

    _model = BronzeReturnRawPayload
    _vendor_id_fields = ("tiktok_return_id", "tiktok_order_id")
```

The behaviour is declared as data on the class; the loop lives once in the
base. A fifth bronze table is three lines and cannot get the loop wrong.

## 3. Repositories

- **Borrow the session; never commit.** `flush()` so ids and defaults are
  visible, and stop. The request or task that opened the session owns the
  transaction. A repository that commits makes the caller's rollback a lie.
- **Tenant scoping is structural.** Anything under a shop extends
  `ShopScopedRepo` and builds every query through `self._scoped(shop_id, ...)`.
  A hand-written `Model.shop_id == shop_id` inside a subclass is the exact bug
  class the base exists to remove.
- **`get` raises `NotFound`; `find_*` / `get_by_*` return `None`.** The verb
  tells the caller what to expect. A row under another shop is *missing*, not
  *forbidden* — no existence oracle.
- **Upsert is declared, not written.** Set `_lookup_attrs` to the natural key;
  inherit `upsert`. It refuses stale `update_time`, and survives a concurrent
  insert of the same key.
- **Naive UTC at the persistence edge.** `utc_now_naive()` for every `now` a
  repository writes (#1138).

## 4. Services and routes

A route does five things, in order: resolve the tenant, apply gates, call the
service, map the service's typed exception to HTTP, commit and enqueue. It
does not contain the behaviour.

**Before** (inside the route handler, 225 lines):

```python
if confirmation.status == "expired":
    raise _confirmation_error(status.HTTP_410_GONE, ERROR_CONFIRMATION_EXPIRED, "...")
if confirmation.status != PENDING_CONFIRMATION_STATUS:
    raise _confirmation_error(status.HTTP_409_CONFLICT, ERROR_CONFIRMATION_ALREADY_DECIDED, "...")
# ... 180 more lines
```

**After** — the service (`services/agent_runs/confirmations.py`):

```python
class ConfirmationRejected(Exception):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.http_status = _HTTP_STATUS_FOR_CODE[error_code]

async def decide_confirmation(session, run, *, tool_call_id, decision, option_id) -> ConfirmationDecision:
    ...  # the ladder; raises ConfirmationRejected; never commits
```

and the route:

```python
try:
    outcome = await agent_runs.decide_confirmation(session, run, ...)
except agent_runs.ConfirmationRejected as rejected:
    raise HTTPException(status_code=rejected.http_status,
                        detail={"message": rejected.message, "error_code": rejected.error_code}) from None
await session.commit()          # before enqueue: a worker must never see the row pending (#1221)
celery_task_id = _enqueue_resume_agent_workflow(run_id, approved=outcome.approved)
```

The ladder is now testable without HTTP, the HTTP mapping is one table, and
the ordering rule (commit before enqueue) is one visible line with its reason.

**Layering is a gate, not a convention.** `.importlinter.toml` allows
`api → services → {repositories, models, database}` and caps a cross-package
import from `api` at `juli_backend.<package>.<child>`. When a route needs
something deeper — a status enum, an event type — it does not copy the literal
and add a drift test; it moves the behaviour into a depth-2 `services` package
that can import the real definition. `services/agent_runs/events.py` is the
worked example: four locally reproduced constants became imports.

## 5. Shared infrastructure

When two features need the same mechanism, there is one copy and two thin
adapters. `gold_kpi_cache` and `analytics_kpi_cache` each carried their own
Redis client lifecycle; gold had the per-event-loop fix (#871) and analytics
had the socket timeouts (#927), so each was missing a bug fix the other had
already shipped. `services/kpi_cache` holds the client and the read-through
once; each adapter is a key prefix, a repository read and an envelope type.

## 6. Errors, logging, comments

- No bare `except:`. A broad `except Exception` only at a named boundary with
  `# noqa: BLE001 -- <boundary>: <degrade>` on the line.
- Domain failures are typed exceptions with a machine-readable code. Callers
  branch on the code, never on message text.
- Log structured event names with ids in `extra=`. Never tokens, PII, bodies.
- Comments answer *why*. The code answers *what*. Cite the issue or ADR.

## 7. Tests

The test half of the standard is
`.cursor/skills/domain/testing-patterns/python-testing.md`. The short version:
builders and fixtures from `tests/support`, hand-written doubles with real
signatures, one parametrized class per behaviour, names that read as
sentences, and assertions on outcomes rather than on how the code got there.
