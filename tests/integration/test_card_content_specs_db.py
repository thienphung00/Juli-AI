"""P100 E.7, migration 127 on real Postgres: ``card_content_specs`` -- RLS, append-only grants,
checks, up / down.

- row-level security is on; ``juli_app`` has SELECT and INSERT only (no UPDATE, no DELETE: the
  newest row wins), ``juli_ops`` nothing;
- two tenants: a shop sees and writes only its own rows; a smuggled insert for another shop fails;
- an unknown type or source, a short hash, or a style profile tied to a card or product is refused;
- the purge sweep finds the table (uuid ``shop_id``);
- last: ``downgrade`` to 126 drops the table, ``upgrade head`` restores it.

Synthetic tenants only; specs hold card text, no buyer data.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
TABLE = "card_content_specs"
HASH = hashlib.sha256(b"inputs").hexdigest()


def _verbs(conn, role: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{TABLE}", "v": verb},
        ).scalar()
    }


def _role_exists(conn, role: str) -> bool:
    return bool(
        conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _insert(
    conn,
    shop_id: uuid.UUID,
    *,
    spec_type: str = "title",
    item: str | None = "1001",
    source: str = "seeded",
    inputs_hash: str = HASH,
) -> uuid.UUID:
    row_id = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO public.card_content_specs (id, shop_id, spec_type, item_id, inputs_hash, "
            "spec, source) VALUES (:id, :shop, :type, :item, :hash, CAST(:spec AS jsonb), :source)"
        ),
        {
            "id": row_id,
            "shop": shop_id,
            "type": spec_type,
            "item": item,
            "hash": inputs_hash,
            "spec": json.dumps({"candidates": [], "chosen": None}),
            "source": source,
        },
    )
    return row_id


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def test_the_table_has_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        on = conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE relnamespace = 'public'::regnamespace AND relname = :t"
            ),
            {"t": TABLE},
        ).scalar()
    assert on is True


def test_grants_are_append_only_for_the_runtime_role_and_none_for_ops(owner_engine):
    with owner_engine.connect() as conn:
        assert _verbs(conn, RUNTIME_ROLE) == {"SELECT", "INSERT"}
        if _role_exists(conn, "juli_ops"):
            assert _verbs(conn, "juli_ops") == set()


def test_a_shop_sees_and_writes_only_its_own_rows(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, a.shop_id)
        _insert(conn, b.shop_id)
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(conn.execute(text(f"SELECT shop_id FROM public.{TABLE}")).scalars())  # nosec B608
        assert shops == {a.shop_id}
        mine = _insert(conn, a.shop_id, source="seller")
        with pytest.raises(DBAPIError):
            conn.execute(
                text(f"UPDATE public.{TABLE} SET source = 'llm' WHERE id = :id"),  # nosec B608
                {"id": mine},
            )
        conn.rollback()
        _scope(conn, a.shop_id)
        with pytest.raises(DBAPIError):
            _insert(conn, b.shop_id)
        conn.rollback()
        conn.execute(text("RESET ROLE"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"spec_type": "video"},
        {"source": "guess"},
        {"inputs_hash": "abc"},
        {"spec_type": "style_profile", "item": "1001"},
    ],
)
def test_the_checks_refuse_bad_rows(owner_engine, two_tenants, kwargs):
    a, _ = two_tenants
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError):
            _insert(conn, a.shop_id, **kwargs)
        conn.rollback()


def test_a_style_profile_belongs_to_the_shop(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.begin() as conn:
        row_id = _insert(conn, a.shop_id, spec_type="style_profile", item=None)
        stored = conn.execute(
            text("SELECT shop_id, item_id FROM public.card_content_specs WHERE id = :id"),
            {"id": row_id},
        ).one()
    assert stored.shop_id == a.shop_id and stored.item_id is None


def test_the_purge_sweep_finds_the_table(owner_engine):
    """The purge deletes from every base table with a uuid ``shop_id`` (094)."""
    with owner_engine.connect() as conn:
        found = conn.execute(
            text(
                "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                "AND a.attname = 'shop_id' AND a.atttypid = 'uuid'::regtype "
                "AND NOT a.attisdropped AND c.relname = :t"
            ),
            {"t": TABLE},
        ).scalar()
    assert found == TABLE


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 126, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def exists() -> bool:
        with owner_engine.connect() as conn:
            found = conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{TABLE}"}).scalar()
            return found is not None

    assert exists()
    command.downgrade(cfg, "126_shopee_source_funnel")
    try:
        assert not exists()
    finally:
        command.upgrade(cfg, "head")
    assert exists()
