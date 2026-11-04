"""P91 D-9, migration 117 on real Postgres: the KOL columns, the gateway marking, the read model.

- ``shopee_order_lines`` gained five nullable KOL columns and one partial index; RLS and the
  ``juli_app`` grants of the table are unchanged (SELECT, INSERT, UPDATE);
- the gateway, as the runtime role under a shop's scope, marks an order line from the affiliate
  lane with the hashed KOL key, the public handle, the channel, the campaign type and an MCN
  flag (never the MCN's name, never a raw affiliate id), and the commission from ``Chi phí(₫)``;
- the KOL read model, as the runtime role, builds the row; the other shop sees nothing;
- last: ``downgrade`` to 116 drops the columns and the index, ``upgrade head`` restores them.

Synthetic tenants and creators only.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.services.ingest.kol_key import kol_key
from juli_backend.services.shopee_analytics import queries
from tests.integration.test_ingest_two_tenant import juli_app_session
from tests.integration.test_shopee_orders_db import _body, _line, _post, _scalar
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

REPO_ROOT = Path(__file__).resolve().parents[2]
LINES = "shopee_order_lines"
KOL_COLUMNS = (
    "kol_key",
    "kol_handle",
    "affiliate_channel",
    "affiliate_campaign_type",
    "affiliate_mcn",
)
INDEX = "ix_shopee_order_lines_kol"
REF = "c" * 32
HANDLE = "kol_alpha"
NOW = datetime(2026, 11, 3, 3, 0)


def test_the_columns_are_nullable_and_the_table_keeps_its_rls_and_grants(owner_engine):
    with owner_engine.connect() as conn:
        cols = {
            r.column_name: r
            for r in conn.execute(
                text(
                    "SELECT column_name, is_nullable, data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t AND column_name = ANY(:c)"
                ),
                {"t": LINES, "c": list(KOL_COLUMNS)},
            )
        }
        assert set(cols) == set(KOL_COLUMNS)
        assert all(c.is_nullable == "YES" for c in cols.values())
        assert cols["affiliate_mcn"].data_type == "boolean"
        index = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :t AND indexname = :i"),
            {"t": LINES, "i": INDEX},
        ).scalar_one()
        assert "kol_key IS NOT NULL" in index
        assert conn.execute(
            text(
                "SELECT relrowsecurity FROM pg_class "
                "WHERE oid = 'public.shopee_order_lines'::regclass"
            )
        ).scalar()
        verbs = {
            v
            for v in ("SELECT", "INSERT", "UPDATE", "DELETE")
            if conn.execute(
                text("SELECT has_table_privilege('juli_app', :t, :v)"),
                {"t": f"public.{LINES}", "v": v},
            ).scalar()
        }
        assert verbs == {"SELECT", "INSERT", "UPDATE"}


async def test_the_gateway_marks_a_line_with_its_kol_and_the_read_model_shows_it(shopee_tenants):
    a, b = shopee_tenants
    await _post(a.shop_id, "order_lines", _body([_line(REF)]))
    marked = {
        "order_ref": REF,
        "item_id": "1001",
        "ordered_at": "2026-10-05T10:15:00",
        "affiliate_account": HANDLE,
        "channel": "Shopee Video",
        "campaign_type": "Chiến dịch mở rộng",
        "mcn": "Agency X",
        "cost": 900,
        "valid": True,
    }
    await _post(a.shop_id, "affiliate_order_lines", _body([marked]))
    (row,) = await _scalar(
        a.shop_id,
        "SELECT affiliate, commission, kol_key, kol_handle, affiliate_channel, "
        "affiliate_campaign_type, affiliate_mcn FROM public.shopee_order_lines",
    )
    assert row.affiliate is True and float(row.commission) == 900.0
    assert (row.kol_key, row.kol_handle) == (kol_key(HANDLE), HANDLE)
    assert (row.affiliate_channel, row.affiliate_campaign_type) == (
        "Shopee Video",
        "Chiến dịch mở rộng",
    )
    assert row.affiliate_mcn is True  # a flag; the MCN's name is stored nowhere
    dump = repr(
        await _scalar(
            a.shop_id, "SELECT row_to_json(l)::text AS j FROM public.shopee_order_lines l"
        )
    )
    assert "Agency X" not in dump

    async with juli_app_session() as session:
        async with with_shop_scope(session, a.shop_id):
            body = await queries.kol_table(session, a.shop_id, period="30d")
    (kol_row,) = body["rows"]
    assert (kol_row["handle"], kol_row["channel"]) == (HANDLE, "Shopee Video")
    assert kol_row["orders"] == 1 and kol_row["commission"] == 900
    assert kol_row["commission_sources"] == {"report": 1}
    assert kol_row["low_data"] is True and kol_row["roi_shopee"] is None
    assert body["totals"]["orders"] == 1

    async with juli_app_session() as session:
        async with with_shop_scope(session, b.shop_id):
            # the other shop has no Shopee numbers at all: nothing of A's is visible to it
            with pytest.raises(queries.NoShopeeData):
                await queries.kol_table(session, b.shop_id, period="30d")


def test_zz_downgrade_drops_the_kol_columns_and_upgrade_restores_them(owner_engine):
    """Last in the module: downgrade to 116, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def state() -> tuple[set[str], bool]:
        with owner_engine.connect() as conn:
            cols = set(
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = :t "
                        "AND column_name = ANY(:c)"
                    ),
                    {"t": LINES, "c": list(KOL_COLUMNS)},
                ).scalars()
            )
            idx = conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{INDEX}"}).scalar()
        return cols, idx is not None

    assert state() == (set(KOL_COLUMNS), True)
    command.downgrade(cfg, "116_shopee_reco_codes")
    try:
        assert state() == (set(), False)
        with owner_engine.connect() as conn:  # the table and its other columns stay
            assert conn.execute(text("SELECT to_regclass('public.shopee_order_lines')")).scalar()
    finally:
        command.upgrade(cfg, "head")
    assert state() == (set(KOL_COLUMNS), True)


def test_the_migration_is_additive_and_chains_after_116():
    import sys

    sys.path.insert(0, str(REPO_ROOT / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    path = (
        REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/117_shopee_kol_lines.py"
    )
    result = evaluate_migration_paths([path])
    assert [f.render() for f in result.findings] == [] and result.accepted
    src = path.read_text("utf-8")
    assert 'revision: str = "117_shopee_kol_lines"' in src and len("117_shopee_kol_lines") <= 32
    assert 'down_revision: str | None = "116_shopee_reco_codes"' in src
    assert uuid.UUID(int=0)  # (keeps the import used when the DB tests are skipped)
