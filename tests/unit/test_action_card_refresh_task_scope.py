"""On-demand action-card refresh never sets tenant scope (#1860).

`_refresh_async` opened a worker session and called `sync_sandbox_write_products`,
`check_sandbox_write_catalog_identity_mismatch` and `run_action_card_refresh`
with no `with_shop_scope`. Since migration 053
(`shops_shop_scope_select`, `id = app_current_shop_id()`) an unscoped worker
session sees no shop row, so `run_action_card_refresh` -> `run_daily_scoring_for_shop`
-> `build_feature_aggregates` raises `NotFound('Shop <id> not found')` for
every shop. Every other worker task that touches tenant rows scopes its
session (`reaper.py`, `credential_refresh_beat.py`, `mock_analytics_reconcile.py`,
`analytics_backfill_topup.py`) — this task did not.

Test 1 proves the runtime behaviour against real Postgres, as `juli_app`
(the deployed runtime role), with RLS actually in force -- an owner
connection is exempt from RLS and would pass whether or not the scope is
applied, proving nothing. `tests.integration.two_tenant.juli_app_session`
is reused rather than reinvented, the same way `test_mock_analytics_reconcile_
two_tenant.py` and `test_credential_refresh_beat_two_tenant.py` use it.

Test 2 proves the structural claim: `_refresh_async` enters
`with_shop_scope` -- the real symbol, not a double -- before any of the
three collaborator calls.
"""

from __future__ import annotations

import ast
import inspect
import os
import textwrap
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from juli_backend.core.config.runtime import async_database_url, sync_database_url
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.action_cards.refresh import run_action_card_refresh
from juli_backend.workers.tasks import action_card_refresh
from tests.integration.two_tenant import RUNTIME_ROLE, juli_app_session

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)


@asynccontextmanager
async def _juli_app_engine_session_factory():
    """A real ``async_sessionmaker`` bound to an ENGINE, running as `juli_app`.

    `tests.integration.two_tenant.juli_app_session` binds one `AsyncSession`
    to a single, already-open `AsyncConnection` (`session = AsyncSession(bind=conn)`
    over a connection that already has an implicit transaction started by its
    own `SET ROLE` statement). Verified empirically against real Postgres:
    under that shape, `session.commit()` does NOT end the underlying
    transaction -- SQLAlchemy joins an externally-supplied, already-active
    connection as a SAVEPOINT, so `SET LOCAL` state SURVIVES the "commit".
    That fixture is exactly right for proving initial-state RLS behaviour
    (the existing two tests above), but reusing it here would make these two
    new tests pass whether or not the reapply fix is applied -- the
    fake-collaborator trap this reopen exists to close.

    Here each session gets its OWN connection lifecycle from the engine, the
    same shape as production's `_ensure_session_factory` ->
    `ensure_worker_session_factory`: `session.commit()` issues a real
    Postgres COMMIT, discarding `app.current_shop_id` -- confirmed
    empirically against this same database (`before commit: <value>`,
    `after commit: <empty>`). `SET ROLE` is applied on the driver's
    `connect` event so every physical connection the pool opens runs as
    `juli_app`, mirroring `juli_app_session`'s own `SET ROLE {RUNTIME_ROLE}`.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    engine = create_async_engine(async_database_url(url))

    @event.listens_for(engine.sync_engine, "connect")
    def _set_runtime_role(dbapi_connection: Any, connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute(f"SET ROLE {RUNTIME_ROLE}")
        cursor.close()

    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


@pytest.fixture
def owner_engine():
    """A sync engine connected as the table owner, on the shared database.

    `tests/conftest.py`'s `_shared_database_at_head` fixture has already put
    the shared database at head before any test runs, so this fixture only
    needs to connect -- unlike `tests/integration/conftest.py`'s
    `owner_engine`, which also migrates a private, isolated database.
    Seeding runs as the owner deliberately: it is set-up, not the thing
    under test, and doing it under RLS would make a fixture failure look
    like an isolation failure.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    engine = create_engine(sync_database_url(url))
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_shop_with_scoreable_commerce_data(engine, *, label: str) -> uuid.UUID:
    """Seed one shop with enough Product/Order data for scoring to persist a card.

    Mirrors `tests/unit/test_action_cards_contract.py`'s
    `test_integration_two_consecutive_refreshes_same_row_count` fixture --
    that shape is proven (`first_count >= 1`) to make
    `run_action_card_refresh` persist at least one `ActionCard`. Seeded as
    the owner (RLS-exempt), which is set-up, not the thing under test.
    """
    now = datetime.now(UTC)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()

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
                "name": f"{label} shop",
                "tiktok_id": f"tt-{shop_id.hex[:10]}",
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO public.products "
                "(id, shop_id, tiktok_product_id, name, status, revenue, "
                " units_sold, update_time, created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, :name, 'ACTIVE', :revenue, "
                " :units, :now, :now, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop_id": str(shop_id),
                "tiktok_id": f"prod-{shop_id.hex[:8]}",
                "name": f"{label} widget",
                "revenue": Decimal("800000"),
                "units": 40,
                "now": now,
            },
        )
        conn.execute(
            text(
                "INSERT INTO silver.orders "
                "(id, shop_id, tiktok_order_id, status, total_amount, currency, "
                " update_time, created_at, updated_at) "
                "VALUES (:id, :shop_id, :tiktok_id, 'COMPLETED', :total, 'VND', "
                " :now, :now, :now)"
            ),
            {
                "id": str(uuid.uuid4()),
                "shop_id": str(shop_id),
                "tiktok_id": f"ord-{shop_id.hex[:8]}",
                "total": Decimal("150000"),
                "now": now,
            },
        )

    return shop_id


# ---------------------------------------------------------------------------
# Test 1: the real runtime behaviour, as `juli_app`, against real Postgres.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_refresh_task_runs_under_the_shop_scope(owner_engine, monkeypatch):
    """AC1: `refresh_action_cards_sync`'s task reaches `run_action_card_refresh`
    with a session already scoped to the shop, and the run completes.

    The sandbox-sync and identity-mismatch collaborators are stubbed to
    no-ops at their import site in `action_card_refresh` -- both hit the
    vendor and are unrelated to this defect. `run_action_card_refresh` is
    wrapped, not replaced: the wrapper has the REAL signature
    (`session, shop_id, *, poll, poll_hook`), snapshots the shop GUC the
    moment it is called, then delegates to the real implementation with
    `poll=False` (deterministic; avoids depending on unset TikTok/Redis env
    vars). What is proven is the real resolve-score-persist path, not a
    stand-in for it.

    Confirmed to fail on the pre-fix code: without `with_shop_scope`, the
    unscoped `juli_app` session sees no `shops` row and
    `build_feature_aggregates` raises `NotFound('Shop <id> not found')`.
    """
    shop_id = _seed_shop_with_scoreable_commerce_data(owner_engine, label="refresh-scope")

    monkeypatch.setattr(action_card_refresh, "sync_sandbox_write_products", AsyncMock())
    monkeypatch.setattr(
        action_card_refresh, "check_sandbox_write_catalog_identity_mismatch", AsyncMock()
    )

    real_run_action_card_refresh = action_card_refresh.run_action_card_refresh
    captured: dict[str, str | None] = {}

    async def _spy_run_action_card_refresh(session, shop_id, *, poll=True, poll_hook=None):
        guc = await session.execute(text("SELECT current_setting('app.current_shop_id', true)"))
        captured["shop_guc"] = guc.scalar()
        return await real_run_action_card_refresh(session, shop_id, poll=False)

    monkeypatch.setattr(
        action_card_refresh, "run_action_card_refresh", _spy_run_action_card_refresh
    )

    # `_ensure_session_factory` normally builds a factory from `DATABASE_URL`
    # bound as the table owner (RLS-exempt, and would pass whether or not
    # the fix is applied). `juli_app_session` substitutes for `factory()`
    # directly -- an async context manager taking no required argument --
    # and runs as `juli_app`, the deployed runtime role, with NO shop GUC
    # set: the exact starting state the fix must establish scope from
    # itself. Same substitution `test_mock_analytics_reconcile_two_tenant.py`
    # uses for `mock_analytics_reconcile._ensure_session_factory`.
    monkeypatch.setattr(action_card_refresh, "_ensure_session_factory", lambda: juli_app_session)

    # No NotFound: this is the regression this issue exists to close.
    await action_card_refresh._refresh_async(shop_id)

    assert captured.get("shop_guc") == str(shop_id), (
        f"run_action_card_refresh ran with app.current_shop_id={captured.get('shop_guc')!r}, "
        f"expected {shop_id!s}: the scope must be active before this call is reached"
    )

    with owner_engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM action_cards WHERE shop_id = :shop_id"),
            {"shop_id": str(shop_id)},
        ).scalar()
    assert count and count > 0, (
        f"expected at least one ActionCard persisted for {shop_id}, found {count}"
    )


@requires_postgres
@pytest.mark.asyncio
async def test_refresh_task_raises_not_found_without_the_fix_applied(owner_engine, monkeypatch):
    """The pre-fix shape, reproduced directly: calling `run_action_card_refresh`
    on an UNSCOPED `juli_app` session raises `NotFound`, proving RLS is what
    stood between the seller's 202 and their cards -- and that test 1 above
    is not passing for some unrelated reason.
    """
    shop_id = _seed_shop_with_scoreable_commerce_data(owner_engine, label="refresh-noscope")

    async with juli_app_session() as session:
        with pytest.raises(NotFound) as excinfo:
            await action_card_refresh.run_action_card_refresh(session, shop_id, poll=False)

    assert str(shop_id) in str(excinfo.value), (
        f"expected the unresolved shop id {shop_id} in the NotFound message, got: {excinfo.value!s}"
    )


# ---------------------------------------------------------------------------
# Test 1b/1c: `with_shop_scope` is `SET LOCAL` (transaction-scoped) -- a
# COMMIT inside the scope discards it, and #1861 never crossed one. Reopened
# 2026-09-10 (#1860): the sandbox sync's own credential-refresh path commits
# via `refresh_credential` (`core/security/credential_refresh.py:352`), and
# the poll path commits the same way through
# `resolve_production_read_credential`. Both doubles below commit on the
# REAL session to reproduce that, rather than mocking the collaborator away
# -- the exact fake-collaborator gap the reopen diagnosis names.
# ---------------------------------------------------------------------------


@requires_postgres
@pytest.mark.asyncio
async def test_refresh_task_survives_a_commit_inside_the_sandbox_sync(owner_engine, monkeypatch):
    """The task must re-apply the shop scope after `sync_sandbox_write_products`
    commits, so `run_action_card_refresh` still sees the shop.

    RED on the current code: `_refresh_async` enters `with_shop_scope` once
    on entry and never re-applies it, so the sandbox-sync double's COMMIT
    below discards `app.current_shop_id` before `run_action_card_refresh`
    runs and `build_feature_aggregates` raises `NotFound`.
    """
    shop_id = _seed_shop_with_scoreable_commerce_data(owner_engine, label="refresh-sync-commit")

    async def _sandbox_sync_that_commits(session, shop_id: uuid.UUID) -> None:
        # Real signature, real session -- mirrors what
        # `resolve_sandbox_write_credential` -> `refresh_credential` does in
        # production when the token needs no refresh (`is_fresh` branch,
        # `credential_refresh.py:352`).
        await session.commit()

    async def _identity_check_noop(session, shop_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(
        action_card_refresh, "sync_sandbox_write_products", _sandbox_sync_that_commits
    )
    monkeypatch.setattr(
        action_card_refresh, "check_sandbox_write_catalog_identity_mismatch", _identity_check_noop
    )

    real_run_action_card_refresh = action_card_refresh.run_action_card_refresh
    captured: dict[str, str | None] = {}

    async def _spy_run_action_card_refresh(session, shop_id, *, poll=True, poll_hook=None):
        guc = await session.execute(text("SELECT current_setting('app.current_shop_id', true)"))
        captured["shop_guc"] = guc.scalar()
        return await real_run_action_card_refresh(session, shop_id, poll=False)

    monkeypatch.setattr(
        action_card_refresh, "run_action_card_refresh", _spy_run_action_card_refresh
    )

    async with _juli_app_engine_session_factory() as factory:
        monkeypatch.setattr(action_card_refresh, "_ensure_session_factory", lambda: factory)

        # No NotFound: the scope must survive the sandbox-sync's commit.
        await action_card_refresh._refresh_async(shop_id)

    assert captured.get("shop_guc") == str(shop_id), (
        f"run_action_card_refresh ran with app.current_shop_id={captured.get('shop_guc')!r}, "
        f"expected {shop_id!s}: the scope must be re-applied after the sandbox sync's commit"
    )

    with owner_engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM action_cards WHERE shop_id = :shop_id"),
            {"shop_id": str(shop_id)},
        ).scalar()
    assert count and count > 0, (
        f"expected at least one ActionCard persisted for {shop_id}, found {count}"
    )


@requires_postgres
@pytest.mark.asyncio
async def test_refresh_survives_a_commit_inside_the_poll_step(owner_engine):
    """`run_action_card_refresh` must re-apply the shop scope after its poll
    step commits, so scoring still resolves the shop.

    RED on the current code: `run_action_card_refresh` calls
    `runner(session, shop_id)` and goes straight to
    `run_daily_scoring_for_shop` with no re-apply in between; the poll
    double's COMMIT discards `app.current_shop_id` and
    `build_feature_aggregates` raises `NotFound`.
    """
    shop_id = _seed_shop_with_scoreable_commerce_data(owner_engine, label="refresh-poll-commit")

    async def _poll_hook_that_commits(session, shop_id: uuid.UUID) -> None:
        # Real signature, real session -- mirrors what
        # `resolve_production_read_credential` -> `refresh_credential` does
        # for the production-read shop's poll (`credential_refresh.py:352`).
        await session.commit()

    async with _juli_app_engine_session_factory() as factory, factory() as session:
        async with with_shop_scope(session, shop_id):
            persisted_cards = await run_action_card_refresh(
                session, shop_id, poll=True, poll_hook=_poll_hook_that_commits
            )

    assert persisted_cards, (
        f"expected at least one ActionCard persisted for {shop_id}, got {persisted_cards!r}"
    )

    with owner_engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM action_cards WHERE shop_id = :shop_id"),
            {"shop_id": str(shop_id)},
        ).scalar()
    assert count and count > 0, (
        f"expected at least one ActionCard persisted for {shop_id}, found {count}"
    )


@requires_postgres
@pytest.mark.asyncio
async def test_refresh_survives_a_commit_before_the_emission_budget(owner_engine):
    """`run_action_card_refresh`'s own commit after persisting candidates
    (the "own boundary" commit right before `apply_emission_budget`) discards
    the shop GUC exactly like the sandbox-sync and poll-step commits above.
    `action_cards` is a shop-GUC-gated table (migration 045, direct
    ``shop_id = current_setting('app.current_shop_id', true)::uuid``, with
    "unset denies... rather than raising" by design), so the scope must be
    re-applied before `apply_emission_budget` runs -- or its SELECT comes
    back empty under RLS and nothing is ever surfaced.

    RED on the pre-fix code, but NOT as a `NotFound`: `persist_scoring_result`
    runs and commits *while still scoped* (the commit is the last statement
    inside the scoped section, ordered after the write), so persisting
    succeeds. It is `apply_emission_budget`'s read immediately after that
    commit, now unscoped, that silently sees zero candidate rows -- RLS's
    documented "unset denies (NULL comparison, no rows) rather than raising"
    behaviour. So the pre-fix failure mode here is silent data loss (every
    persisted card's `surfaced_at` stays NULL forever), not an exception --
    which is exactly why this needs its own test rather than trusting the
    two `NotFound`-shaped tests above to have covered it.
    """
    shop_id = _seed_shop_with_scoreable_commerce_data(owner_engine, label="refresh-emission-commit")

    async with _juli_app_engine_session_factory() as factory, factory() as session:
        async with with_shop_scope(session, shop_id):
            persisted_cards = await run_action_card_refresh(session, shop_id, poll=False)
            # `run_action_card_refresh` only flushes the emission-budget's
            # writes (`apply_emission_budget`'s own docstring: "performs no
            # commit... the caller controls the transaction") -- the caller
            # here, exactly like `_refresh_async` at the production call
            # site, commits once at the very end.
            await session.commit()

    assert persisted_cards, (
        f"expected at least one ActionCard persisted for {shop_id}, got {persisted_cards!r}"
    )

    with owner_engine.connect() as conn:
        surfaced_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM action_cards "
                "WHERE shop_id = :shop_id AND surfaced_at IS NOT NULL"
            ),
            {"shop_id": str(shop_id)},
        ).scalar()
    assert surfaced_count and surfaced_count > 0, (
        f"expected at least one surfaced ActionCard for {shop_id} after "
        f"apply_emission_budget, found {surfaced_count}: the shop scope must "
        f"survive the commit that precedes the emission-budget step"
    )


# ---------------------------------------------------------------------------
# Test 2: the structural claim -- scope entered before any tenant read.
# ---------------------------------------------------------------------------

_SCOPED_CALL_NAMES = frozenset(
    {
        "sync_sandbox_write_products",
        "check_sandbox_write_catalog_identity_mismatch",
        "run_action_card_refresh",
    }
)


def _call_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name):
            names.add(child.func.id)
    return names


def test_refresh_task_scopes_before_the_first_tenant_read():
    """AC2: `_refresh_async` enters `with_shop_scope` before any of the three
    calls, bound to the real `juli_backend.database.tenant_context.with_shop_scope`
    symbol.

    Structural, not behavioural: parses the real source of `_refresh_async`
    and asserts (a) it imports `with_shop_scope` from
    `juli_backend.database.tenant_context` -- the real symbol, not a
    same-named local double -- (b) none of the three collaborator calls
    appears in the function body OUTSIDE an `AsyncWith` whose context
    manager is a call to `with_shop_scope`, and (c) that `AsyncWith`'s body
    contains all three.
    """
    source = textwrap.dedent(inspect.getsource(action_card_refresh._refresh_async))
    tree = ast.parse(source)
    func = tree.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)
    assert func.name == "_refresh_async"

    # (a) the real symbol, imported from the real module -- never a
    # locally-defined double with the same name.
    import_nodes = [n for n in ast.walk(func) if isinstance(n, ast.ImportFrom)]
    scope_imports = [
        n
        for n in import_nodes
        if n.module == "juli_backend.database.tenant_context"
        and any(alias.name == "with_shop_scope" and alias.asname is None for alias in n.names)
    ]
    assert scope_imports, (
        "_refresh_async must import the real with_shop_scope from "
        "juli_backend.database.tenant_context, not a double"
    )

    # (b)/(c) find the with_shop_scope AsyncWith anywhere in the function
    # (it may be nested inside `async with factory() as session:`, not a
    # direct top-level statement), then partition every Call node in the
    # function by node IDENTITY into "inside that AsyncWith's body" and
    # "everywhere else" -- identity rather than a shallower structural walk,
    # so nesting depth cannot hide a call that leaked outside the scope.
    def _is_shop_scope_with(stmt: ast.AST) -> bool:
        if not isinstance(stmt, ast.AsyncWith):
            return False
        for item in stmt.items:
            call = item.context_expr
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name):
                if call.func.id == "with_shop_scope":
                    return True
        return False

    scope_with = next((n for n in ast.walk(func) if _is_shop_scope_with(n)), None)
    assert scope_with is not None, (
        "_refresh_async must enter `async with with_shop_scope(session, shop_id):` "
        "somewhere in its body"
    )

    inside_ids = {id(n) for stmt in scope_with.body for n in ast.walk(stmt)}

    names_inside_scope: set[str] = set()
    names_outside_scope: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if id(node) in inside_ids:
                names_inside_scope.add(node.func.id)
            else:
                names_outside_scope.add(node.func.id)

    assert _SCOPED_CALL_NAMES <= names_inside_scope, (
        f"expected {_SCOPED_CALL_NAMES} inside the with_shop_scope block, "
        f"found {names_inside_scope}"
    )

    leaked = _SCOPED_CALL_NAMES & names_outside_scope
    assert not leaked, (
        f"{leaked} called outside the with_shop_scope block -- a tenant read "
        "must never run unscoped"
    )
