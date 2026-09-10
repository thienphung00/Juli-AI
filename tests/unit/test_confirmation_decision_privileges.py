"""A seller's approve/decline must actually land, as `juli_app`, on real Postgres (#1897).

`transition_confirmation_or_none` issues

    UPDATE run_confirmations SET status=..., selected_option_id=..., decided_at=...
    WHERE id=... AND status='pending'

and `run_confirmations` granted `juli_app` only INSERT and SELECT. Production,
2026-09-10 06:34:03Z, request `07cb7ab2-40d7-4d26-aa2a-556428e8f884`:

    asyncpg.exceptions.InsufficientPrivilegeError:
    permission denied for table run_confirmations

Every confirmation raised since the 2026-09-07 role cutover was therefore
un-decidable, and the whole human-in-the-loop write path was dead.

WHY THIS RUNS AS `juli_app` AND NOT AS THE OWNER. A missing GRANT is invisible
to the table owner: Postgres never checks table privileges for it, so the same
UPDATE that 500s in production passes silently on an owner connection. Every
unit test of this service ran on SQLite or as the owner, which is exactly why a
dead production write path shipped with a green suite.

WHY `juli_app_async_sessionmaker` AND NOT AN ON-CONNECT `SET ROLE`. The
`SET ROLE` shape runs inside the implicit transaction and is undone by the
pool's reset-on-return, so only the FIRST pooled session is really `juli_app`
(#1891). The factory here puts the role in the connection's startup packet.

WHY THE SHOP SCOPE IS SET. `run_confirmations` carries
`run_confirmations_update_public`, keyed on the owning run's shop. Without a
scope the UPDATE would match zero rows and this test could go green for the
wrong reason -- a policy denial silently standing in for a privilege denial.
The two are distinguishable and this test needs the privilege one: RLS returns
zero rows, a missing GRANT raises.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.agent_runs.confirmations import transition_confirmation_or_none
from tests.support.postgres import (
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

_READ_BACK = text(
    "SELECT status, selected_option_id, decided_at FROM public.run_confirmations WHERE id = :id"
)


@pytest.fixture
def owner_engine():
    """A sync engine as the table owner, for seeding and for reading back.

    `tests/conftest.py::_shared_database_at_head` has already migrated the
    shared database, so this only needs to connect.
    """
    with owner_sync_engine() as engine:
        yield engine


def _seed_pending_confirmation(engine) -> tuple[uuid.UUID, uuid.UUID]:
    """One tenant with a run parked in `waiting_approval` and a pending confirmation.

    Seeded owner-side on purpose: the fixture is set-up, not the thing under
    test, and building it under RLS would make a fixture failure look like an
    isolation failure.
    """
    now = datetime.now(UTC)
    naive_now = now.replace(tzinfo=None)
    user_id, shop_id = uuid.uuid4(), uuid.uuid4()
    product_id, run_id, confirmation_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.users (id, phone, created_at, updated_at) "
                "VALUES (:id, :phone, :now, :now)"
            ),
            {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": naive_now},
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
                "name": "confirmation privileges shop",
                "tiktok_id": f"tt-{shop_id.hex[:10]}",
                "now": naive_now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products "
                "(id, shop_id, tiktok_product_id, name, status, update_time, "
                " created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, :name, 'ACTIVATE', :now, :now, :now)"
            ),
            {
                "id": str(product_id),
                "shop_id": str(shop_id),
                "tiktok_id": f"p-{product_id.hex[:10]}",
                "name": "listing under review",
                "now": naive_now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.workflow_runs "
                "(id, shop_id, product_id, state, status, prompt_version, prompt_sha256, "
                " running_seconds_elapsed, cancel_requested, created_at) "
                "VALUES (:id, :shop_id, :product_id, '{}'::jsonb, 'waiting_approval', "
                "        'v1', :sha, 0, false, :now)"
            ),
            {
                "id": str(run_id),
                "shop_id": str(shop_id),
                "product_id": str(product_id),
                "sha": "0" * 64,
                "now": naive_now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.run_confirmations "
                "(id, workflow_run_id, tool_call_id, options, status, created_at, expires_at) "
                "VALUES (:id, :run_id, :tool_call_id, CAST(:options AS jsonb), "
                "        'pending', :now, :expires)"
            ),
            {
                "id": str(confirmation_id),
                "run_id": str(run_id),
                "tool_call_id": f"call_{confirmation_id.hex[:12]}",
                "options": '[{"option_id": "opt-1", "label": "Apply the proposed price"}]',
                "now": naive_now,
                "expires": now + timedelta(hours=4),
            },
        )
    return shop_id, confirmation_id


async def _decide_as_juli_app(
    shop_id: uuid.UUID,
    confirmation_id: uuid.UUID,
    *,
    new_status: str,
    option_id: str | None,
) -> bool:
    """Run the real service function on a real `juli_app` session, and COMMIT.

    The commit is load-bearing: `transition_confirmation_or_none` never commits
    (its caller does), and the read-back below is what proves the row moved
    rather than merely that nothing raised.
    """
    async with juli_app_async_sessionmaker() as sessionmaker:
        async with sessionmaker() as session:
            async with with_shop_scope(session, shop_id):
                won = await transition_confirmation_or_none(
                    session,
                    confirmation_id,
                    new_status=new_status,
                    selected_option_id=option_id,
                )
                await session.commit()
            return won


def _read_back(engine, confirmation_id: uuid.UUID) -> tuple[str, str | None, object]:
    with engine.connect() as conn:
        row = conn.execute(_READ_BACK, {"id": str(confirmation_id)}).one()
    return row.status, row.selected_option_id, row.decided_at


@requires_postgres
async def test_a_pending_confirmation_can_be_decided_as_juli_app(owner_engine):
    """The acceptance criterion: the row transitions to `approved`.

    RED before migration 058 with `permission denied for table
    run_confirmations`; green after it.
    """
    shop_id, confirmation_id = _seed_pending_confirmation(owner_engine)

    won = await _decide_as_juli_app(
        shop_id, confirmation_id, new_status="approved", option_id="opt-1"
    )

    assert won is True, "the UPDATE matched no row -- the transition did not land"
    status, selected_option_id, decided_at = _read_back(owner_engine, confirmation_id)
    assert status == "approved"
    assert selected_option_id == "opt-1"
    assert decided_at is not None, "an approved confirmation must carry the instant it was decided"


@requires_postgres
async def test_a_pending_confirmation_can_be_declined_as_juli_app(owner_engine):
    """The other half of the dead path. Decline writes the same columns through
    the same UPDATE, so it fails for the same reason and must be proven too."""
    shop_id, confirmation_id = _seed_pending_confirmation(owner_engine)

    won = await _decide_as_juli_app(shop_id, confirmation_id, new_status="declined", option_id=None)

    assert won is True, "the UPDATE matched no row -- the decline did not land"
    status, selected_option_id, decided_at = _read_back(owner_engine, confirmation_id)
    assert status == "declined"
    assert selected_option_id is None
    assert decided_at is not None


@requires_postgres
async def test_a_second_decision_on_the_same_confirmation_loses(owner_engine):
    """`WHERE status='pending'` is what makes the transition atomic. With the
    grant in place the first call must win and the second must lose, rather
    than both raising (no privilege) or both winning (no guard)."""
    shop_id, confirmation_id = _seed_pending_confirmation(owner_engine)

    first = await _decide_as_juli_app(
        shop_id, confirmation_id, new_status="approved", option_id="opt-1"
    )
    second = await _decide_as_juli_app(
        shop_id, confirmation_id, new_status="declined", option_id=None
    )

    assert (first, second) == (True, False)
    status, _selected, _decided = _read_back(owner_engine, confirmation_id)
    assert status == "approved", "the losing decision must not overwrite the winner"
