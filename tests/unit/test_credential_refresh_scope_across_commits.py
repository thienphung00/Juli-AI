"""RED->GREEN regression test for #1880 (INCIDENT): every TikTok credential
refresh has failed since the RLS cutover.

``core/security/credential_refresh.py::refresh_credential`` is documented
"acquire lock -> commit -> re-read the row". Every caller runs it inside
``with_shop_scope`` (a per-row ``SET LOCAL``), which a ``COMMIT`` discards
(#1627/#1631's defect class, reopened here). The re-read after the first
commit then runs unscoped under ``tiktok_credentials_select_public
(shop_id = app_current_shop_id())`` and raises ``NotFound`` for a row that
plainly exists -- the exact production traceback, on every row, every cycle,
since the 2026-09-07 cutover deploy.

``tests.integration.two_tenant.juli_app_session`` (the shared fixture used
throughout the RLS suite) binds one ``AsyncSession`` to a single,
already-open connection whose own ``SET ROLE`` started an implicit
transaction; under that shape ``session.commit()`` joins a SAVEPOINT rather
than issuing a real Postgres ``COMMIT``, so ``SET LOCAL`` state survives it
regardless of whether the fix is applied -- a false green. Reusing
``tests/unit/test_action_card_refresh_task_scope.py``'s
``_juli_app_engine_session_factory`` instead: each session gets its own
connection lifecycle from an ``AsyncEngine``, so ``session.commit()`` issues
a real ``COMMIT`` and genuinely discards ``app.current_shop_id`` -- the same
shape production's worker session factory uses, and the only shape that
falsifies the defect this issue exists to close.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.core.security.credential_refresh import (
    REFRESH_BUFFER,
    RefreshStatus,
    refresh_credential,
)
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.workers.tasks.credential_refresh_beat import run_credential_refresh_cycle
from tests.unit.test_action_card_refresh_task_scope import _juli_app_engine_session_factory

requires_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").strip().startswith("postgresql"),
    reason="DATABASE_URL is not set to a Postgres instance",
)


@pytest.fixture
def owner_engine():
    """A sync engine connected as the table owner, on the shared database.

    Seeding runs as the owner deliberately (RLS-exempt): it is set-up, not
    the thing under test, so a fixture failure never masquerades as an
    isolation failure. Mirrors
    ``test_action_card_refresh_task_scope.py``'s ``owner_engine``.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    engine = create_engine(sync_database_url(url))
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_expiring_credential(engine, *, label: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed one shop with one credential inside the 24h refresh window.

    Plaintext access/refresh tokens: ``decrypt_token`` "accepts legacy
    plaintext values for reads" (``database/token_crypto.py``), the same
    shortcut ``tests/integration/two_tenant.py``'s seeder takes.

    Returns ``(shop_id, credential_id)``.
    """
    now = datetime.now(UTC).replace(tzinfo=None)
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    credential_id = uuid.uuid4()

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
                "INSERT INTO public.tiktok_credentials "
                "(id, shop_id, access_token, refresh_token, token_expires_at, status, "
                " refresh_count, created_at, updated_at) "
                "VALUES (:id, :shop_id, :access, :refresh, :expires, 'active', 0, :now, :now)"
            ),
            {
                "id": str(credential_id),
                "shop_id": str(shop_id),
                "access": f"access-{credential_id.hex[:8]}",
                "refresh": f"refresh-{credential_id.hex[:8]}",
                "expires": now + timedelta(hours=1),
                "now": now,
            },
        )

    return shop_id, credential_id


def _auth_returning() -> MagicMock:
    auth = MagicMock()
    auth.refresh_access_token = MagicMock(
        return_value={
            "access_token": "new-access-token",
            "refresh_token": "new-refresh-token",
            "access_token_expire_in": 604800,
        }
    )
    return auth


def _read_credential_state(engine, credential_id: uuid.UUID):
    with engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT token_expires_at, last_refreshed_at FROM public.tiktok_credentials "
                "WHERE id = :id"
            ),
            {"id": str(credential_id)},
        ).one()


@requires_postgres
@pytest.mark.asyncio
async def test_refresh_survives_its_own_commit_under_shop_scope(owner_engine):
    """AC1 (#1880): `refresh_credential` must still see its own row after the
    commits inside it discard the caller's shop scope.

    RED on the pre-fix code: `with_shop_scope` sets `app.current_shop_id` via
    `SET LOCAL`; `refresh_credential`'s first `session.commit()` discards it,
    and the very next `_fetch` runs unscoped under
    `tiktok_credentials_select_public` and raises `NotFound` -- the exact
    production traceback.
    """
    shop_id, credential_id = _seed_expiring_credential(owner_engine, label="scope-commit")
    auth = _auth_returning()

    async with _juli_app_engine_session_factory() as factory, factory() as session:
        async with with_shop_scope(session, shop_id):
            outcome = await refresh_credential(session, credential_id, auth=auth, force=False)
        await session.commit()

    assert outcome.status is RefreshStatus.REFRESHED, (
        f"expected REFRESHED, got {outcome.status!r} (error={outcome.error!r})"
    )
    assert outcome.credential.id == credential_id

    row = _read_credential_state(owner_engine, credential_id)
    assert row.token_expires_at > datetime.now(UTC).replace(tzinfo=None) + REFRESH_BUFFER, (
        f"expected token_expires_at to have advanced past the refresh buffer, "
        f"got {row.token_expires_at}"
    )
    assert row.last_refreshed_at is not None, (
        "expected last_refreshed_at to be set after a successful refresh"
    )


@requires_postgres
@pytest.mark.asyncio
async def test_beat_cycle_refreshes_every_enumerated_row(owner_engine):
    """AC2 (#1880): the beat cycle must refresh every enumerated row across
    shops, not fail every single one of them with `NotFound`.

    RED on the pre-fix code: both enumerated rows hit the same
    commit-then-unscoped-reread defect as the single-row test above, so
    `run_credential_refresh_cycle` counts `failed == 2`, `refreshed == 0`.
    """
    shop_a, credential_a = _seed_expiring_credential(owner_engine, label="beat-a")
    shop_b, credential_b = _seed_expiring_credential(owner_engine, label="beat-b")
    auth = _auth_returning()

    async with _juli_app_engine_session_factory() as factory, factory() as session:
        summary = await run_credential_refresh_cycle(session, auth=auth)
        await session.commit()

    assert summary.refreshed == 2, f"expected 2 refreshed, got {summary!r}"
    assert summary.failed == 0, f"expected 0 failed, got {summary!r}"

    for credential_id in (credential_a, credential_b):
        row = _read_credential_state(owner_engine, credential_id)
        assert row.token_expires_at > datetime.now(UTC).replace(tzinfo=None) + REFRESH_BUFFER, (
            f"credential {credential_id} did not advance: {row.token_expires_at}"
        )
        assert row.last_refreshed_at is not None, (
            f"credential {credential_id} was not marked refreshed"
        )
