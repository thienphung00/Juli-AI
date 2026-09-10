"""The agent-run bootstrap must survive a Postgres database that never migrated.

`_resolve_run_shop_id` (`workers/tasks/agent_workflow.py`) breaks the tenancy
circle at the top of every agent run: `_load_context` reads `workflow_runs`,
which is RLS-gated, so it cannot run until a scope is open — and the scope
needs the `shop_id` only that row carries. ADR-089 decision 3's answer is an
enumeration, and `enumerate_active_workflow_runs()` (SECURITY DEFINER,
migration 051, widened by 052) is the one `reaper.py` already uses.

#1883 branched on the DIALECT and assumed that "postgresql" implied "migrated".
It does not. `test_agent_workflow_persisting_sink_wiring.py` builds its schema
straight from `Base.metadata.create_all`, which knows about tables and nothing
about migrations, so the function is simply absent and every run there died on
`UndefinedFunctionError: function public.enumerate_active_workflow_runs() does
not exist`.

WHAT THESE TESTS PIN, AND HOW THEY TELL THE TWO PATHS APART.

No spy, no double, no patched collaborator. The enumeration and the fallback
are OBSERVABLY different implementations: the enumeration filters to the three
active statuses, the direct row read does not. So a run in a terminal status is
a discriminator that costs nothing —

    enumeration answered  ->  a `completed` run resolves to None
    fallback answered     ->  a `completed` run resolves to its shop id

and each test asserts the answer only one of the two could have given.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.database.database import Base

# The MODULE, not its symbols. Importing `_is_undefined_function` by name would
# make this file fail to COLLECT against the pre-fix code, and a collection
# error is not evidence of anything: the two fallback tests below are meant to
# fail on the real `UndefinedFunctionError`, which is what the reader needs to
# see.
from juli_backend.workers.tasks import agent_workflow
from tests.support.postgres import (
    database_url,
    juli_app_async_sessionmaker,
    owner_sync_engine,
    requires_postgres,
)

pytestmark = requires_postgres

_ENUMERATION = "public.enumerate_active_workflow_runs()"


def _seed_run(conn, *, status: str) -> tuple[uuid.UUID, uuid.UUID]:
    """One user, shop, product and `workflow_runs` row in `status`.

    Returns `(run_id, shop_id)`. Raw SQL rather than the ORM so the same
    seeder works on the migrated database and on a bare `create_all` one —
    the columns are identical, which is exactly the point being tested.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id, shop_id, product_id, run_id = (uuid.uuid4() for _ in range(4))

    conn.execute(
        text(
            "INSERT INTO public.users (id, phone, created_at, updated_at) "
            "VALUES (:id, :phone, :now, :now)"
        ),
        {"id": str(user_id), "phone": f"+1555{user_id.hex[:7]}", "now": now},
    )
    conn.execute(
        text(
            # `is_active` is spelled out rather than left to a default: the
            # migrated schema gives it a SERVER default, a `create_all` one
            # gives it only a Python-side default the ORM would apply and raw
            # SQL never sees. Naming it keeps one seeder correct on both.
            "INSERT INTO public.shops "
            "(id, user_id, shop_name, tiktok_shop_id, is_active, created_at, updated_at) "
            "VALUES (:id, :user_id, :name, :tiktok_id, true, :now, :now)"
        ),
        {
            "id": str(shop_id),
            "user_id": str(user_id),
            "name": "Bootstrap shop",
            "tiktok_id": f"tt-{shop_id.hex[:10]}",
            "now": now,
        },
    )
    conn.execute(
        text(
            "INSERT INTO public.products "
            "(id, shop_id, tiktok_product_id, name, status, update_time, "
            " created_at, updated_at) "
            "VALUES (:id, :shop_id, :tiktok_id, 'Bootstrap widget', 'ACTIVE', "
            " :now, :now, :now)"
        ),
        {
            "id": str(product_id),
            "shop_id": str(shop_id),
            "tiktok_id": f"prod-{product_id.hex[:10]}",
            "now": now,
        },
    )
    conn.execute(
        text(
            "INSERT INTO public.workflow_runs "
            "(id, shop_id, product_id, state, status, prompt_version, prompt_sha256, "
            " created_at, updated_at) "
            "VALUES (:id, :shop_id, :product_id, '{}'::jsonb, :status, "
            " 'optimize_product_2/v1', :sha, :now, :now)"
        ),
        {
            "id": str(run_id),
            "shop_id": str(shop_id),
            "product_id": str(product_id),
            "status": status,
            "sha": "0" * 64,
            "now": now,
        },
    )
    return run_id, shop_id


@pytest.fixture
def owner_engine():
    with owner_sync_engine() as engine:
        yield engine


# ---------------------------------------------------------------------------
# An UNMIGRATED Postgres database: schema from `Base.metadata.create_all`, so
# the tables exist and migration 051's function does not. This is the exact
# condition `test_agent_workflow_persisting_sink_wiring.py` runs under, and it
# is reproduced here rather than described, because a description cannot fail.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def unmigrated_database_url():
    admin_url = make_url(sync_database_url(database_url())).set(database="postgres")
    db_name = f"juli_1883_boot_{uuid.uuid4().hex[:10]}"

    admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin_engine.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin_engine.dispose()

    url = make_url(sync_database_url(database_url())).set(database=db_name)
    rendered = url.render_as_string(hide_password=False)

    engine = create_engine(rendered)
    with engine.begin() as conn:
        for schema_name in ("bronze", "silver", "gold", "ops"):
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_name}"))
        Base.metadata.create_all(conn, checkfirst=True)
    engine.dispose()

    try:
        yield rendered
    finally:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            conn.execute(
                text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ),
                {"name": db_name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        admin_engine.dispose()


@pytest.fixture
def unmigrated_sync_engine(unmigrated_database_url: str):
    engine = create_engine(unmigrated_database_url)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest_asyncio.fixture
async def unmigrated_session_factory(unmigrated_database_url: str):
    engine = create_async_engine(async_database_url(unmigrated_database_url))
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


def test_the_unmigrated_fixture_really_lacks_the_enumeration(unmigrated_sync_engine):
    """Non-vacuity for everything below. If `create_all` ever started shipping
    the function, the fallback tests would pass while exercising the
    enumeration and nobody would notice."""
    with unmigrated_sync_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT to_regprocedure(:sig) IS NOT NULL"), {"sig": _ENUMERATION}
        ).scalar()
        tables = conn.execute(text("SELECT to_regclass('public.workflow_runs')")).scalar()

    assert exists is False, (
        "this fixture exists to reproduce a database with the tables but not the "
        "migration; the enumeration must be absent"
    )
    assert tables is not None, "…while `workflow_runs` itself must be present"


# ---------------------------------------------------------------------------
# The fallback fires when the function is absent.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_bootstrap_falls_back_when_the_enumeration_is_absent(
    unmigrated_sync_engine, unmigrated_session_factory
):
    """RED before the fix: `asyncpg.exceptions.UndefinedFunctionError: function
    public.enumerate_active_workflow_runs() does not exist`, raised straight out
    of the task body.

    The run is seeded `completed` deliberately. The enumeration covers only
    `queued`/`running`/`waiting_approval`, so a shop id coming back for a
    terminal run can only have come from the direct row read — this asserts the
    fallback ANSWERED, not merely that nothing raised.
    """
    with unmigrated_sync_engine.begin() as conn:
        run_id, shop_id = _seed_run(conn, status="completed")

    async with unmigrated_session_factory() as session:
        resolved = await agent_workflow._resolve_run_shop_id(session, run_id)

    assert resolved == shop_id, (
        "with no enumeration on the database the bootstrap must fall back to reading "
        f"workflow_runs directly; got {resolved!r}"
    )


@pytest.mark.asyncio
async def test_the_fallback_leaves_the_session_usable(
    unmigrated_sync_engine, unmigrated_session_factory
):
    """Postgres aborts the whole transaction on a failed statement, so a
    fallback that did not roll back first would hand the caller a session on
    which every later statement raises `InFailedSqlTransaction` — the bootstrap
    would "succeed" and `_load_context` would die one line later."""
    with unmigrated_sync_engine.begin() as conn:
        run_id, _shop_id = _seed_run(conn, status="queued")

    async with unmigrated_session_factory() as session:
        await agent_workflow._resolve_run_shop_id(session, run_id)
        still_works = (await session.execute(text("SELECT 1"))).scalar()

    assert still_works == 1, (
        "the session must be usable after the fallback; the aborted transaction "
        "left by the missing function has to be rolled back first"
    )


# ---------------------------------------------------------------------------
# The enumeration is still preferred where it exists.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_enumeration_is_preferred_on_a_migrated_database(owner_engine):
    """On the migrated database the SECURITY DEFINER enumeration answers, and
    its active-status filter is the proof.

    A `queued` run resolves; a `completed` one does not. The fallback is not
    status-filtered, so a shop id for the `completed` run would mean the
    enumeration had been skipped.
    """
    with owner_engine.begin() as conn:
        active_run_id, active_shop_id = _seed_run(conn, status="queued")
        terminal_run_id, _terminal_shop_id = _seed_run(conn, status="completed")

    async with juli_app_async_sessionmaker() as factory:
        async with factory() as session:
            active = await agent_workflow._resolve_run_shop_id(session, active_run_id)
        async with factory() as session:
            terminal = await agent_workflow._resolve_run_shop_id(session, terminal_run_id)
        # The reason the enumeration has to exist at all: as `juli_app` with no
        # scope open, the row itself is invisible.
        async with factory() as session:
            visible = (
                await session.execute(
                    text("SELECT count(*) FROM public.workflow_runs WHERE id = :id"),
                    {"id": str(active_run_id)},
                )
            ).scalar_one()

    assert active == active_shop_id, (
        "an active run must resolve through the enumeration as `juli_app` with no scope"
    )
    assert terminal is None, (
        f"a terminal run must NOT resolve — the enumeration covers active statuses only, "
        f"so {terminal!r} here means the unfiltered fallback answered on a database that "
        f"has the function"
    )
    assert visible == 0, (
        "non-vacuity: an unscoped `juli_app` session cannot read the row directly, which "
        "is why the bootstrap needs a SECURITY DEFINER enumeration in the first place"
    )


# ---------------------------------------------------------------------------
# The catch is narrow: 42883 only.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_only_a_missing_function_is_recognised_as_one(unmigrated_session_factory):
    """`_is_undefined_function` is judged against exceptions the drivers really
    raised, not hand-built ones — a constructed exception can carry whatever
    attribute the assertion wants."""
    async with unmigrated_session_factory() as session:
        with pytest.raises(ProgrammingError) as missing_function:
            await session.execute(text("SELECT public.no_such_function_at_all()"))
        await session.rollback()
        with pytest.raises(ProgrammingError) as missing_table:
            await session.execute(text("SELECT * FROM public.no_such_table_at_all"))
        await session.rollback()

    assert agent_workflow._is_undefined_function(missing_function.value) is True, (
        "42883 undefined_function is the one condition the fallback exists for"
    )
    assert agent_workflow._is_undefined_function(missing_table.value) is False, (
        "42P01 undefined_table is a different fault and must not downgrade to a fallback"
    )


@pytest.mark.asyncio
async def test_a_refusal_from_the_enumeration_propagates_instead_of_falling_back(
    unmigrated_sync_engine, unmigrated_session_factory
):
    """The failure mode a broad `except` would create, made concrete.

    An enumeration that EXISTS but refuses — SQLSTATE 42501, which is what an
    RLS/privilege refusal looks like — must surface. Falling back would answer
    the caller from an unfiltered read and report a permissions fault as a
    missing migration, which are opposite diagnoses.

    Non-vacuous by construction: the row is seeded `completed`, so the fallback
    WOULD have returned a shop id had it been reached.
    """
    with unmigrated_sync_engine.begin() as conn:
        run_id, shop_id = _seed_run(conn, status="completed")

    refusing_function = f"""
    CREATE OR REPLACE FUNCTION {_ENUMERATION}
    RETURNS TABLE (out_run_id uuid, out_shop_id uuid)
      LANGUAGE plpgsql
      AS $fn$
      BEGIN
        RAISE EXCEPTION 'permission denied' USING ERRCODE = 'insufficient_privilege';
      END
      $fn$;
    """
    try:
        with unmigrated_sync_engine.begin() as conn:
            conn.execute(text(refusing_function))

        async with unmigrated_session_factory() as session:
            with pytest.raises(ProgrammingError) as refused:
                await agent_workflow._resolve_run_shop_id(session, run_id)
            await session.rollback()
    finally:
        with unmigrated_sync_engine.begin() as conn:
            conn.execute(text(f"DROP FUNCTION IF EXISTS {_ENUMERATION}"))

    assert agent_workflow._is_undefined_function(refused.value) is False, (
        f"a 42501 refusal must not be mistaken for a missing function, or the "
        f"bootstrap would have quietly answered {shop_id} from an unfiltered read"
    )
