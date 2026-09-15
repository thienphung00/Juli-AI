"""`PersistingEventSink` must be safe by construction under RLS (#1890).

`emit` opens a session per call from an injected factory and commits it
(ADR-074 decision 3). A bare factory's session carries no tenant GUC, so
`workflow_run_events`' INSERT policy (migration 045: a VIA_PARENT `EXISTS`
against `workflow_runs.shop_id = app_current_shop_id()`) refuses every row
under `juli_app`. #1889 worked around this for the agent-run path only, by
handing the sink a factory pre-wrapped in `with_sticky_shop_scope`
(`workers/tasks/agent_workflow.py::_shop_scoped_session_factory`) -- the sink
itself stayed unsafe for any other caller.

The fix: the sink now accepts an optional `shop_id` at construction and
enters `with_shop_scope` (not the sticky variant -- `emit` commits exactly
once per call, so there is no second transaction for a sticky listener to
survive into) around its own insert. `shop_id` defaults to `None` so the
pre-existing suite (`test_persisting_event_sink.py`), which proves sink
*behavior* on an owner-role connection RLS never applies to, keeps
constructing the sink with exactly the two arguments it always has and
stays green untouched. Every RLS-enforcing caller must now pass `shop_id`,
and gets correctness the sink itself guarantees rather than the caller's
own diligence.

Real Postgres only, under the `juli_app` role via
`tests/support/postgres.py`'s `juli_app_async_sessionmaker` (its own
docstring: the on-connect `SET ROLE` shape only holds for the first session
out of a pool). Seeding and read-back both go through an owner-role sync
engine -- set-up and verification should not lean on the same scope the
fix under test applies.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from juli_backend.services.agent.events.envelope import WorkflowStatusEvent
from juli_backend.services.agent.events.payloads import WorkflowStatusPayload
from juli_backend.services.agent.events.persisting_sink import PersistingEventSink
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)


class _NoopPublisher:
    """Publish is not this slice's concern -- the insert is."""

    async def publish(self, channel: str, message: str) -> None:
        return None


def _status_event(run_id: uuid.UUID, seq: int, narration: str) -> WorkflowStatusEvent:
    return WorkflowStatusEvent(
        workflow_run_id=run_id,
        sequence_number=seq,
        event_type="workflow.status",
        timestamp=datetime.now(UTC),
        payload=WorkflowStatusPayload(phase_narration=narration),
        v=1,
    )


def _seed_shop_and_run(engine) -> tuple[uuid.UUID, uuid.UUID]:
    """One user, one shop, one product and one `running` `workflow_runs`
    row -- the minimal FK chain `workflow_run_events`' INSERT policy walks
    (migration 045: `EXISTS (... workflow_runs.shop_id = app_current_shop_id())`).
    Owner-side, deliberately: seeding is set-up, not the thing under test."""
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    product_id = uuid.uuid4()
    run_id = uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
        )
        conn.execute(
            text(
                "INSERT INTO public.shops "
                "(id, user_id, shop_name, tiktok_shop_id, created_at, updated_at) "
                "VALUES (:id, :user_id, :name, :tiktok_id, :now, :now)"
            ),
            {
                "id": str(shop_id),
                "user_id": str(user_id),
                "name": "AGT-1890 test shop",
                "tiktok_id": f"tt-1890-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products "
                "(id, shop_id, tiktok_product_id, name, status, update_time, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, :name, 'ACTIVE', :now, :now, :now)"
            ),
            {
                "id": str(product_id),
                "shop_id": str(shop_id),
                "tiktok_id": f"agt-1890-{uuid.uuid4().hex[:10]}",
                "name": "AGT-1890 test widget",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_runs "
                "(id, shop_id, product_id, state, status, prompt_version, prompt_sha256, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :product_id, CAST('{}' AS jsonb), 'running', "
                " :prompt_version, :prompt_sha256, :now, :now)"
            ),
            {
                "id": str(run_id),
                "shop_id": str(shop_id),
                "product_id": str(product_id),
                "prompt_version": "optimize_product.v1",
                "prompt_sha256": "a" * 64,
                "now": now,
            },
        )
    return run_id, shop_id


@requires_postgres
async def test_emit_persists_under_rls_with_a_bare_factory():
    """RED on pre-#1890 code: the sink's constructor has no `shop_id` seam at
    all, so a caller can only hand it a bare factory -- and a bare factory's
    session, run as `juli_app`, gets its `workflow_run_events` INSERT refused
    by RLS (no row satisfies the `EXISTS` check with no `app.current_shop_id`
    set). GREEN: passing `shop_id` at construction (the way a naive caller
    who read the constructor signature would) is enough -- no wrapping
    factory required from the caller, unlike #1889's workaround."""
    with owner_sync_engine() as owner_engine:
        run_id, shop_id = _seed_shop_and_run(owner_engine)

    async with juli_app_async_sessionmaker() as factory:
        sink = PersistingEventSink(factory, _NoopPublisher(), shop_id=shop_id)
        event = _status_event(run_id, 0, "bare factory + shop id")

        await sink.emit(event)

    with owner_sync_engine() as owner_engine, owner_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT payload ->> 'phase_narration' AS narration "
                "FROM public.workflow_run_events "
                "WHERE workflow_run_id = :run_id AND sequence_number = 0"
            ),
            {"run_id": str(run_id)},
        ).one_or_none()

    assert row is not None, (
        "the workflow_run_events row must be persisted and readable -- a bare factory "
        "plus a shop id at construction must be enough for emit to pass RLS"
    )
    assert row.narration == "bare factory + shop id"


@requires_postgres
async def test_the_scope_does_not_leak_after_a_failed_emit():
    """An emit whose event belongs to a DIFFERENT shop than the sink was
    constructed with must be refused by RLS's `WITH CHECK`, not silently
    swallowed the way a unique-index replay collision is (`emit`'s own
    `except IntegrityError` is a no-op path for a different, expected
    condition -- an `insufficient_privilege` policy violation is neither
    integrity-related nor expected, and must propagate). After that failure,
    a fresh session drawn from the SAME factory/engine must carry neither
    GUC forward -- `with_shop_scope`'s `SET LOCAL` dies with the aborted
    transaction, and it registers no listener at all (unlike
    `with_sticky_shop_scope`), so there is nothing session- or
    connection-level left to leak."""
    with owner_sync_engine() as owner_engine:
        _, shop_a = _seed_shop_and_run(owner_engine)
        run_b_id, _shop_b = _seed_shop_and_run(owner_engine)

    async with juli_app_async_sessionmaker() as factory:
        sink = PersistingEventSink(factory, _NoopPublisher(), shop_id=shop_a)
        cross_shop_event = _status_event(run_b_id, 0, "must not land")

        with pytest.raises(DBAPIError):
            await sink.emit(cross_shop_event)

        async with factory() as fresh:
            gucs = (
                await fresh.execute(
                    text(
                        "SELECT current_setting('app.current_shop_id', true), "
                        "current_setting('app.current_user_id', true)"
                    )
                )
            ).one()

    assert (gucs[0] or "") == "", (
        f"a failed emit left app.current_shop_id={gucs[0]!r} set for the next session "
        "drawn from the same pool"
    )
    assert (gucs[1] or "") == "", (
        f"a failed emit left app.current_user_id={gucs[1]!r} set for the next session "
        "drawn from the same pool"
    )


def _construct_sink_with_only(*args, **kwargs) -> PersistingEventSink:
    """A thin, deliberately untyped forwarding shim. `shop_id` is a required
    keyword-only argument now, so a literal `PersistingEventSink(factory,
    publisher)` call at this test's own call site would be a *static* mypy
    error, caught before the test ever ran -- which would prove nothing about
    the runtime `TypeError` this test exists to observe. Routing the call
    through `*args, **kwargs` defers the check to here, where it belongs: at
    the constructor mypy cannot see through, exactly where a real caller who
    forgot the argument would also be caught."""
    return PersistingEventSink(*args, **kwargs)


def test_constructing_without_shop_id_is_a_type_error():
    """`shop_id` is keyword-only with NO default: the fix's whole point is
    that omission is impossible, not merely unwise. Constructing the sink
    without it must fail immediately, before the session factory is ever
    called -- there must be no way to end up with a `PersistingEventSink`
    that silently carries no tenancy decision at all."""

    class _UncallableFactory:
        def __call__(self):  # pragma: no cover - must never be reached
            raise AssertionError("construction must fail before the factory is ever called")

    with pytest.raises(TypeError) as excinfo:
        _construct_sink_with_only(_UncallableFactory(), _NoopPublisher())

    assert "shop_id" in str(excinfo.value), (
        f"the TypeError must name the missing keyword-only argument, got: {excinfo.value!r}"
    )
