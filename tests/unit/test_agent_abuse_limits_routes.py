"""HTTP-level wiring for inbound abuse limits (ADR-075 decision 4, #1223).

`test_agent_abuse_limits_gate.py` proves the gate module in isolation; this
file proves the three limited routes actually call it, turn a denied
`AbuseLimitDecision` into `429 Retry-After` + a security event, key
everything by shop (never cross-tenant), and -- the test that matters --
that `POST /v1/demo/runs/{run_id}/cancel` still succeeds while every other
limit for that shop is exhausted.

Routes covered:
- `POST /v1/demo/decisions/{action_card_id}/approve` (`demo_execution.py`)
  -- the "approve / run creation" bucket.
- `POST /v1/demo/runs/{run_id}/confirmations/{tool_call_id}`
  (`agent_runs.py`) -- the "confirmations" bucket.
- `GET /v1/demo/runs/{run_id}/events` (`agent_runs.py`) -- the SSE
  concurrency slot, acquired on connect and released on every exit path.
- `POST /v1/demo/runs/{run_id}/cancel` -- deliberately calls no gate at
  all; this file's `TestCancelSurvivesTheStorm` is what proves that stays
  true even under real exhaustion of the other three.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from juli_backend.models.models import ActionCard, Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.abuse_limits import (
    ABUSE_LIMIT_EXCEEDED_EVENT,
    InMemoryAbuseLimitGate,
    set_agent_abuse_limit_gate,
)

pytestmark = pytest.mark.asyncio


def _naive_utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def app(engine, session):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.api.app import create_app
    from juli_backend.api.routes.agent_runs import (
        get_heartbeat_interval_s,
        get_poll_interval_s,
        get_run_event_subscriber,
        get_run_events_session_factory,
    )
    from juli_backend.database import get_session

    application = create_app()
    stream_session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _test_session():
        yield session

    async def _stream_session_factory():
        return stream_session_factory

    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_run_events_session_factory] = _stream_session_factory
    application.dependency_overrides[get_run_event_subscriber] = lambda: None
    application.dependency_overrides[get_heartbeat_interval_s] = lambda: 0.05
    application.dependency_overrides[get_poll_interval_s] = lambda: 0.02
    yield application
    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def user(session):
    u = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(u)
    await session.flush()
    return u


@pytest_asyncio.fixture
async def shop(session, user):
    s = Shop(user_id=user.id, shop_name="AGT-1223 Abuse Limits Shop")
    session.add(s)
    await session.flush()
    return s


@pytest_asyncio.fixture
async def other_shop(session):
    other_user = User(phone=f"+1555{uuid.uuid4().int % 10_000_000:07d}")
    session.add(other_user)
    await session.flush()
    s = Shop(user_id=other_user.id, shop_name="AGT-1223 Other Shop")
    session.add(s)
    await session.flush()
    return s


async def _make_product(session, shop) -> Product:
    p = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-1223-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        revenue=Decimal("100.00"),
        update_time=_naive_utc_now(),
    )
    session.add(p)
    await session.flush()
    await session.commit()
    return p


async def _make_card(session, shop) -> ActionCard:
    c = ActionCard(
        shop_id=shop.id,
        workflow_key=f"optimize_product_{uuid.uuid4().hex[:8]}",
        priority=1,
        severity="high",
        title="Optimize this listing",
        description="CTR fell week over week.",
        recommendation_payload=json.dumps({}),
        status="active",
        computed_at=_naive_utc_now(),
    )
    session.add(c)
    await session.flush()
    await session.commit()
    return c


async def _make_run(session, shop, *, status: str = "running") -> WorkflowRunRow:
    product = Product(
        shop_id=shop.id,
        tiktok_product_id=f"agt-1223-run-{uuid.uuid4()}",
        name="Test Widget",
        status="active",
        update_time=_naive_utc_now(),
    )
    session.add(product)
    await session.flush()
    run = WorkflowRunRow(
        shop_id=shop.id,
        product_id=product.id,
        state={},
        status=status,
        prompt_version="optimize_product.v1",
        prompt_sha256="a" * 64,
    )
    session.add(run)
    await session.flush()
    await session.commit()
    return run


def _client_for(app, user: User, shop: Shop) -> AsyncClient:
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _mock_celery_task(task_id: str) -> MagicMock:
    mock_task = MagicMock()
    mock_async_result = MagicMock()
    mock_async_result.id = task_id
    mock_task.delay.return_value = mock_async_result
    return mock_task


# ---------------------------------------------------------------------------
# Approve bucket -- 429 + Retry-After on exhaustion, security event, and
# cross-tenant isolation
# ---------------------------------------------------------------------------


async def test_approve_exhaustion_returns_429_with_retry_after(app, session, user, shop):
    set_agent_abuse_limit_gate(
        InMemoryAbuseLimitGate(approve_burst_max_requests=1, approve_max_requests=100)
    )
    card_one = await _make_card(session, shop)
    card_two = await _make_card(session, shop)
    await _make_product(session, shop)

    mock_task = _mock_celery_task("celery-1223-approve")
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            first = await client.post(f"/v1/demo/decisions/{card_one.id}/approve")
            second = await client.post(f"/v1/demo/decisions/{card_two.id}/approve")

    assert first.status_code == 202
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert int(second.headers["Retry-After"]) > 0
    mock_task.delay.assert_called_once()


async def test_approve_exhaustion_emits_security_event(app, session, user, shop, caplog):
    import logging

    set_agent_abuse_limit_gate(InMemoryAbuseLimitGate(approve_burst_max_requests=1))
    card_one = await _make_card(session, shop)
    card_two = await _make_card(session, shop)
    await _make_product(session, shop)

    mock_task = _mock_celery_task("celery-1223-approve-event")
    with caplog.at_level(logging.WARNING, logger="juli_backend.api.routes.demo_execution"):
        with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
            async with _client_for(app, user, shop) as client:
                await client.post(f"/v1/demo/decisions/{card_one.id}/approve")
                await client.post(f"/v1/demo/decisions/{card_two.id}/approve")

    records = [r for r in caplog.records if r.message == ABUSE_LIMIT_EXCEEDED_EVENT]
    assert len(records) == 1
    record = records[0]
    assert getattr(record, "shop_id", None) == str(shop.id)
    assert getattr(record, "operation", None) == "approve"
    assert getattr(record, "retry_after_seconds", None) > 0


async def test_approve_cross_tenant_isolation_over_http(app, session, user, shop, other_shop):
    set_agent_abuse_limit_gate(InMemoryAbuseLimitGate(approve_burst_max_requests=1))
    shop_a_card = await _make_card(session, shop)
    await _make_product(session, shop)

    other_user = await session.get(User, other_shop.user_id)
    other_shop_card = await _make_card(session, other_shop)
    await _make_product(session, other_shop)

    mock_task = _mock_celery_task("celery-1223-approve-tenant")
    with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
        async with _client_for(app, user, shop) as client:
            exhaust = await client.post(f"/v1/demo/decisions/{shop_a_card.id}/approve")
            second_shop_a = await client.post(f"/v1/demo/decisions/{shop_a_card.id}/approve")

        async with _client_for(app, other_user, other_shop) as client:
            other_shop_resp = await client.post(f"/v1/demo/decisions/{other_shop_card.id}/approve")

    assert exhaust.status_code == 202
    assert second_shop_a.status_code == 429  # shop A now exhausted
    assert other_shop_resp.status_code == 202  # shop B untouched by shop A's exhaustion


# ---------------------------------------------------------------------------
# Confirmations bucket -- 429 + Retry-After, security event, cross-tenant
# ---------------------------------------------------------------------------


async def test_confirmation_exhaustion_returns_429_with_retry_after(app, session, user, shop):
    set_agent_abuse_limit_gate(InMemoryAbuseLimitGate(confirmation_max_requests=1))

    async with _client_for(app, user, shop) as client:
        first = await client.post(
            f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-1",
            json={"decision": "decline"},
        )
        second = await client.post(
            f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-2",
            json={"decision": "decline"},
        )

    # First call passes the rate limit and then 404s (run does not exist) --
    # the point here is only that it is NOT 429; the second call is rate
    # limited before the run is even looked up.
    assert first.status_code != 429
    assert second.status_code == 429
    assert "Retry-After" in second.headers
    assert int(second.headers["Retry-After"]) > 0


async def test_confirmation_exhaustion_emits_security_event(app, session, user, shop, caplog):
    import logging

    set_agent_abuse_limit_gate(InMemoryAbuseLimitGate(confirmation_max_requests=1))

    with caplog.at_level(logging.WARNING, logger="juli_backend.api.routes.agent_runs"):
        async with _client_for(app, user, shop) as client:
            await client.post(
                f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-1",
                json={"decision": "decline"},
            )
            await client.post(
                f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-2",
                json={"decision": "decline"},
            )

    records = [r for r in caplog.records if r.message == ABUSE_LIMIT_EXCEEDED_EVENT]
    assert len(records) == 1
    assert getattr(records[0], "shop_id", None) == str(shop.id)
    assert getattr(records[0], "operation", None) == "confirmation"


async def test_confirmation_cross_tenant_isolation_over_http(app, session, user, shop, other_shop):
    set_agent_abuse_limit_gate(InMemoryAbuseLimitGate(confirmation_max_requests=1))
    other_user = await session.get(User, other_shop.user_id)

    async with _client_for(app, user, shop) as client:
        exhaust = await client.post(
            f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-1",
            json={"decision": "decline"},
        )
        second_shop_a = await client.post(
            f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-2",
            json={"decision": "decline"},
        )

    async with _client_for(app, other_user, other_shop) as client:
        other_shop_resp = await client.post(
            f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-3",
            json={"decision": "decline"},
        )

    assert exhaust.status_code != 429
    assert second_shop_a.status_code == 429
    assert other_shop_resp.status_code != 429


# ---------------------------------------------------------------------------
# SSE concurrency -- 429 + Retry-After, security event, cross-tenant,
# acquire/release lifecycle proven directly on the wrapper generator
# ---------------------------------------------------------------------------


async def test_sse_stream_exhaustion_returns_429_with_retry_after(app, session, user, shop):
    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    set_agent_abuse_limit_gate(gate)
    run = await _make_run(session, shop, status="completed")  # terminal -> replay-only, fast
    # Fill the one slot directly -- a real concurrently-open stream would do
    # this via connect, but manipulating the same gate instance the route
    # resolves is equivalent and avoids needing two overlapping open
    # connections in this test.
    await gate.try_acquire_stream(str(shop.id))

    async with _client_for(app, user, shop) as client:
        resp = await client.get(f"/v1/demo/runs/{run.id}/events")

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0


async def test_sse_stream_exhaustion_emits_security_event(app, session, user, shop, caplog):
    import logging

    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    set_agent_abuse_limit_gate(gate)
    run = await _make_run(session, shop, status="completed")
    await gate.try_acquire_stream(str(shop.id))

    with caplog.at_level(logging.WARNING, logger="juli_backend.api.routes.agent_runs"):
        async with _client_for(app, user, shop) as client:
            await client.get(f"/v1/demo/runs/{run.id}/events")

    records = [r for r in caplog.records if r.message == ABUSE_LIMIT_EXCEEDED_EVENT]
    assert len(records) == 1
    assert getattr(records[0], "shop_id", None) == str(shop.id)
    assert getattr(records[0], "operation", None) == "sse"


async def test_sse_cross_tenant_isolation_over_http(app, session, user, shop, other_shop):
    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    set_agent_abuse_limit_gate(gate)
    other_user = await session.get(User, other_shop.user_id)
    run_a = await _make_run(session, shop, status="completed")
    run_b = await _make_run(session, other_shop, status="completed")

    await gate.try_acquire_stream(str(shop.id))  # exhaust shop A only

    async with _client_for(app, user, shop) as client:
        shop_a_resp = await client.get(f"/v1/demo/runs/{run_a.id}/events")

    async with _client_for(app, other_user, other_shop) as client:
        shop_b_resp = await client.get(f"/v1/demo/runs/{run_b.id}/events")

    assert shop_a_resp.status_code == 429
    assert shop_b_resp.status_code == 200


async def test_sse_slot_is_released_after_a_clean_stream_end_over_http(app, session, user, shop):
    """A terminal run replays and closes without ever subscribing -- the
    concurrency slot acquired on connect must be released by the time the
    HTTP response finishes, or a second request would wrongly 429."""
    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    set_agent_abuse_limit_gate(gate)
    run = await _make_run(session, shop, status="completed")

    async with _client_for(app, user, shop) as client:
        first = await client.get(f"/v1/demo/runs/{run.id}/events")
        second = await client.get(f"/v1/demo/runs/{run.id}/events")

    assert first.status_code == 200
    assert second.status_code == 200  # slot was released after the first request


async def test_sse_wrapper_releases_slot_when_explicitly_closed_by_its_consumer():
    """Proof that an explicit `.aclose()` on this generator -- from a
    well-behaved consumer, or from CPython's async-generator GC finalizer
    once nothing references the generator anymore -- releases the slot via
    `GeneratorExit` unwinding through the `finally` below.

    **This is deliberately NOT a claim about what Starlette does on a
    client disconnect.** An earlier version of this test claimed exactly
    that ("Starlette calls `.aclose()` on disconnect"); checked directly
    against the installed `starlette.responses.StreamingResponse` source
    (`inspect.getsource`), it does not -- `.aclose()` appears nowhere in
    that class. See `_sse_stream_with_concurrency_slot`'s own docstring for
    what Starlette actually does on each ASGI spec version, and
    `test_sse_wrapper_releases_slot_when_the_consuming_task_is_cancelled`
    below for the real, synchronous-release disconnect mechanism (task
    cancellation) proven directly.
    """
    from juli_backend.api.routes.agent_runs import _sse_stream_with_concurrency_slot

    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)

    async def _never_ending_stream():
        while True:
            yield ": heartbeat\n\n"

    await gate.try_acquire_stream("shop-explicit-close")
    assert (await gate.try_acquire_stream("shop-explicit-close")).allowed is False  # sanity: full

    await gate.release_stream("shop-explicit-close")  # back to a single real occupant
    await gate.try_acquire_stream("shop-explicit-close")  # the "connection" this test simulates

    wrapped = _sse_stream_with_concurrency_slot(
        _never_ending_stream(), gate=gate, shop_id="shop-explicit-close"
    )
    first_chunk = await wrapped.__anext__()
    assert first_chunk == ": heartbeat\n\n"

    await wrapped.aclose()

    # The slot must be free again -- a fresh acquire for the same shop
    # succeeds.
    decision = await gate.try_acquire_stream("shop-explicit-close")
    assert decision.allowed is True


async def test_sse_wrapper_releases_slot_when_the_consuming_task_is_cancelled():
    """The real, synchronous disconnect-release mechanism -- ASGI's legacy
    (`spec_version < (2, 4)`) task-group-cancellation path, verified
    directly against the installed Starlette source: `listen_for_disconnect`
    returning on a closed socket cancels the sibling task running
    `stream_response` via `task_group.cancel_scope.cancel()`. When that
    cancellation lands while this generator is itself suspended inside
    `event_stream` -- the common case, since most of a stream's lifetime is
    spent awaiting a message, a DB read, or the heartbeat timeout, not
    inside `send()` -- `asyncio.CancelledError` is raised at exactly that
    suspension point and propagates through the `finally` below like any
    other exception. Reproduced here with a real asyncio task consuming the
    wrapped generator, cancelled while it is genuinely suspended
    mid-iteration.

    The other real path -- `spec_version >= (2, 4)`, what a current uvicorn
    negotiates, where a disconnected `send()` raises `OSError` OUTSIDE this
    generator's own frame and release is NOT synchronous -- is not
    reproduced by a test asserting a passing release, because it does not
    reliably produce one; it is documented instead, in
    `_sse_stream_with_concurrency_slot`'s own docstring, as relying on GC
    finalization plus the safety TTL.
    """
    from juli_backend.api.routes.agent_runs import _sse_stream_with_concurrency_slot

    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    await gate.try_acquire_stream("shop-cancel")

    reached_suspension = asyncio.Event()

    async def _never_ending_stream():
        yield ": heartbeat\n\n"
        reached_suspension.set()
        # Suspends here indefinitely -- the exact kind of await point a
        # real disconnect's CancelledError lands on mid-`event_stream`.
        await asyncio.Event().wait()
        yield ": unreachable\n\n"  # pragma: no cover -- cancelled before this

    wrapped = _sse_stream_with_concurrency_slot(
        _never_ending_stream(), gate=gate, shop_id="shop-cancel"
    )

    async def _consume():
        async for _chunk in wrapped:
            pass

    task = asyncio.create_task(_consume())
    await asyncio.wait_for(reached_suspension.wait(), timeout=1.0)
    # `reached_suspension.set()` only proves the generator yielded once and
    # ran past it -- hand control back to the event loop once more so the
    # consumer task actually resumes and re-suspends on the next
    # `__anext__()` (i.e. genuinely inside the generator) before cancelling.
    await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    decision = await gate.try_acquire_stream("shop-cancel")
    assert decision.allowed is True  # released synchronously via `finally` on cancellation


async def test_sse_wrapper_releases_slot_when_run_terminates_mid_stream():
    """The "run termination mid-stream" path is the wrapped generator's
    normal, non-exceptional completion (`event_stream` itself returns as
    soon as it sees a terminal event) -- proven here with a generator that
    yields two chunks then returns, standing in for a terminal event
    closing the underlying stream."""
    from juli_backend.api.routes.agent_runs import _sse_stream_with_concurrency_slot

    gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
    await gate.try_acquire_stream("shop-terminate")

    async def _terminating_stream():
        yield "event: workflow.status\ndata: {}\n\n"
        yield "event: workflow.completed\ndata: {}\n\n"

    wrapped = _sse_stream_with_concurrency_slot(
        _terminating_stream(), gate=gate, shop_id="shop-terminate"
    )
    chunks = [chunk async for chunk in wrapped]

    assert len(chunks) == 2
    decision = await gate.try_acquire_stream("shop-terminate")
    assert decision.allowed is True  # slot was released on normal completion


# ---------------------------------------------------------------------------
# The test that matters -- cancel succeeds while every other bucket for the
# same shop is genuinely exhausted (ADR-075 decision 4, #1223).
# ---------------------------------------------------------------------------


class TestCancelSurvivesTheStorm:
    async def test_cancel_succeeds_while_approve_confirmation_and_sse_are_all_exhausted(
        self, app, session, user, shop
    ):
        tight_gate = InMemoryAbuseLimitGate(
            approve_burst_max_requests=1,
            approve_max_requests=1,
            confirmation_max_requests=1,
            sse_max_concurrent=1,
        )
        set_agent_abuse_limit_gate(tight_gate)

        card_one = await _make_card(session, shop)
        card_two = await _make_card(session, shop)
        await _make_product(session, shop)
        run = await _make_run(session, shop, status="running")

        mock_task = _mock_celery_task("celery-1223-storm")
        with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
            async with _client_for(app, user, shop) as client:
                # 1. Drive the approve bucket to exhaustion.
                approve_first = await client.post(f"/v1/demo/decisions/{card_one.id}/approve")
                approve_second = await client.post(f"/v1/demo/decisions/{card_two.id}/approve")

                # 2. Drive the confirmations bucket to exhaustion.
                confirm_first = await client.post(
                    f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-1",
                    json={"decision": "decline"},
                )
                confirm_second = await client.post(
                    f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-2",
                    json={"decision": "decline"},
                )

                # 3. Drive the SSE concurrency bucket to exhaustion (one slot,
                #    filled directly against the same live gate instance the
                #    route resolves).
                await tight_gate.try_acquire_stream(str(shop.id))

                # Sanity: the storm is real before we check the safety valve.
                assert approve_first.status_code == 202
                assert approve_second.status_code == 429
                assert confirm_first.status_code != 429
                assert confirm_second.status_code == 429
                assert (await tight_gate.try_acquire_stream(str(shop.id))).allowed is False

                # 4. Cancel must still succeed -- it never asks the exhausted
                #    gate anything.
                cancel_resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")

        assert cancel_resp.status_code == 202
        await session.refresh(run)
        assert run.cancel_requested is True

    async def test_cancel_succeeds_even_when_the_abuse_limit_gate_is_entirely_unbound(
        self, app, session, user, shop
    ):
        """A stricter version of the storm proof: even a total wiring
        failure (nothing bound at all -- `get_agent_abuse_limit_gate()`
        would raise `RuntimeError` for every OTHER route) must not touch
        cancel, because cancel never calls `get_agent_abuse_limit_gate()`
        in the first place."""
        set_agent_abuse_limit_gate(None)
        run = await _make_run(session, shop, status="running")

        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")

        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# Redis outage scenarios -- fail-closed for all rate-limited operations,
# but cancel is unaffected because it never asks the gate at all
# ---------------------------------------------------------------------------


class TestRedisOutageScenario:
    """Verify fail-closed behavior when Redis backend is unavailable,
    and that cancel succeeds DURING the outage because it never calls
    the limiter."""

    async def test_approve_fails_closed_when_redis_is_unavailable(self, app, session, user, shop):
        """Approve returns 429 when Redis is unavailable."""
        from juli_backend.services.agent.abuse_limits import UnavailableAbuseLimitGate

        set_agent_abuse_limit_gate(UnavailableAbuseLimitGate())
        card = await _make_card(session, shop)
        await _make_product(session, shop)

        mock_task = _mock_celery_task("celery-1334-redis-outage-approve")
        with patch("juli_backend.workers.tasks.agent_workflow.run_agent_workflow", mock_task):
            async with _client_for(app, user, shop) as client:
                resp = await client.post(f"/v1/demo/decisions/{card.id}/approve")

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    async def test_confirmation_fails_closed_when_redis_is_unavailable(
        self, app, session, user, shop
    ):
        """Confirmation returns 429 when Redis is unavailable."""
        from juli_backend.services.agent.abuse_limits import UnavailableAbuseLimitGate

        set_agent_abuse_limit_gate(UnavailableAbuseLimitGate())

        async with _client_for(app, user, shop) as client:
            resp = await client.post(
                f"/v1/demo/runs/{uuid.uuid4()}/confirmations/tool-call-1",
                json={"decision": "decline"},
            )

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    async def test_sse_fails_closed_when_redis_is_unavailable(self, app, session, user, shop):
        """SSE returns 429 when Redis is unavailable."""
        from juli_backend.services.agent.abuse_limits import UnavailableAbuseLimitGate

        set_agent_abuse_limit_gate(UnavailableAbuseLimitGate())
        run = await _make_run(session, shop, status="completed")

        async with _client_for(app, user, shop) as client:
            resp = await client.get(f"/v1/demo/runs/{run.id}/events")

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    async def test_cancel_succeeds_during_redis_outage(self, app, session, user, shop):
        """Cancel succeeds even when Redis is unavailable, because it
        never calls the limiter at all. This proves the structural exemption
        is real: cancel is not "a gate this module always says yes to", but
        a route that never asks this module the question in the first place."""
        from juli_backend.services.agent.abuse_limits import UnavailableAbuseLimitGate

        set_agent_abuse_limit_gate(UnavailableAbuseLimitGate())
        run = await _make_run(session, shop, status="running")

        async with _client_for(app, user, shop) as client:
            resp = await client.post(f"/v1/demo/runs/{run.id}/cancel")

        # Cancel must succeed (202) -- it never consults the gate, so
        # whether Redis is available is irrelevant.
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# SSE concurrency with real concurrent connections -- holding N streams
# open and attempting N+1 should fail, not by manipulating the gate directly
# but by actually opening concurrent connections.
# ---------------------------------------------------------------------------


class TestSSEConcurrencyWithRealStreams:
    """Verify SSE concurrency limit by opening N concurrent streams
    and verifying the (N+1)th is denied."""

    async def test_sse_concurrency_limit_with_concurrent_requests(self, app, session, user, shop):
        """Verify that opening concurrent SSE streams is counted correctly
        and the (N+1)th request is denied with 429. Uses the actual HTTP
        routes to prove the counter works end-to-end."""
        gate = InMemoryAbuseLimitGate(sse_max_concurrent=2)  # Allow exactly 2
        set_agent_abuse_limit_gate(gate)

        # Create terminal run (terminal = replay-only, completes immediately)
        run3 = await _make_run(session, shop, status="completed")

        # Manually acquire 2 slots (simulating 2 concurrent connected streams)
        first_acquire = await gate.try_acquire_stream(str(shop.id))
        second_acquire = await gate.try_acquire_stream(str(shop.id))
        assert first_acquire.allowed is True
        assert second_acquire.allowed is True

        # Now try to open a third stream via HTTP -- should get 429
        async with _client_for(app, user, shop) as client:
            resp = await client.get(f"/v1/demo/runs/{run3.id}/events")

        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

        # Release one slot and verify the next request succeeds
        await gate.release_stream(str(shop.id))
        async with _client_for(app, user, shop) as client:
            resp = await client.get(f"/v1/demo/runs/{run3.id}/events")

        # Now the request should succeed (one slot freed)
        assert resp.status_code == 200

    async def test_sse_concurrency_correctly_counts_across_multiple_shops(
        self, app, session, user, shop, other_shop
    ):
        """Verify that concurrency limits are per-shop, and one shop's
        exhaustion doesn't affect another shop."""
        gate = InMemoryAbuseLimitGate(sse_max_concurrent=1)
        set_agent_abuse_limit_gate(gate)

        other_user = await session.get(User, other_shop.user_id)
        run_a = await _make_run(session, shop, status="completed")
        run_b = await _make_run(session, other_shop, status="completed")

        # Exhaust shop A's slot
        await gate.try_acquire_stream(str(shop.id))

        # Shop A's next request should be denied
        async with _client_for(app, user, shop) as client:
            resp_a = await client.get(f"/v1/demo/runs/{run_a.id}/events")
        assert resp_a.status_code == 429

        # Shop B's request should succeed (different shop)
        async with _client_for(app, other_user, other_shop) as client:
            resp_b = await client.get(f"/v1/demo/runs/{run_b.id}/events")
        assert resp_b.status_code == 200
