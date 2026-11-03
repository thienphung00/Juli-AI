"""ADR-120, migration 112 on real Postgres: RLS, grants, CHECKs and the round trip.

- the six new tables have row-level security on;
- grants follow the lanes: append-only tables give ``juli_app`` SELECT, INSERT only, order
  lines add UPDATE, nobody gets DELETE; ``platform_fee_formulas`` is SELECT for ``juli_app``
  and SELECT, INSERT, UPDATE for ``juli_ops``;
- two tenants: a shop sees and writes only its own rows, in every tenant table;
- the fee formulas are readable by ``juli_app`` and writable by it never;
- ``card_events`` accepts ``whatif_adjusted`` (many per card) and still refuses unknown types;
- ``shop_keyword_seeds`` refuses an unknown role;
- the account purge sweeps the new tables (they carry ``shop_id``): the sweep is by column,
  so this proves each table is found by it;
- last: ``downgrade`` to 111 drops the tables and columns, ``upgrade head`` restores them.

Synthetic tenants only.
"""

from __future__ import annotations

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
NOW = "2026-11-03 03:00:00"

APPEND_ONLY = (
    "platform_item_snapshots",
    "product_image_assets",
    "shop_rule_versions",
    "ad_campaign_purposes",
)
TENANT_TABLES = (*APPEND_ONLY, "shopee_order_lines")
FORMULAS = "platform_fee_formulas"


def _verbs(conn, role: str, table: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": role, "t": f"public.{table}", "v": verb},
        ).scalar()
    }


def _role_exists(conn, role: str) -> bool:
    return bool(
        conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _insert(conn, table: str, shop_id: uuid.UUID, tag: str) -> None:
    """One valid row per tenant table; ``tag`` keeps the unique keys apart."""
    if table == "platform_item_snapshots":
        sql = (
            "INSERT INTO public.platform_item_snapshots (id, shop_id, platform, item_id, "
            "captured_at, image_urls, image_hashes, category_path, source, source_rank) "
            "VALUES (:id, :shop, 'shopee', :tag, :now, '[]', '[]', '[]', 'upload', 2)"
        )
    elif table == "product_image_assets":
        sql = (
            "INSERT INTO public.product_image_assets (id, shop_id, image_hash, storage_path, "
            "first_seen_at) VALUES (:id, :shop, :tag, 'p/x.jpg', :now)"
        )
    elif table == "shopee_order_lines":
        sql = (
            "INSERT INTO public.shopee_order_lines (id, shop_id, platform, order_ref, line_no, "
            "ordered_at, status, item_id, qty, original_price, deal_price, source, "
            "source_version) VALUES (:id, :shop, 'shopee', :tag, 1, :now, 'completed', '1', 1, "
            "200000, 190000, 'upload', 't1')"
        )
    elif table == "shop_rule_versions":
        sql = (
            "INSERT INTO public.shop_rule_versions (id, shop_id, rule_key, scope_ref, value, "
            "version, set_by, valid_from) VALUES (:id, :shop, :tag, '', '9', 1, 'seller', :now)"
        )
    else:
        sql = (
            "INSERT INTO public.ad_campaign_purposes (id, shop_id, platform, campaign_key, "
            "purpose, set_by, set_at) VALUES (:id, :shop, 'shopee', :tag, 'hien_thi', 'team', :now)"
        )
    conn.execute(text(sql), {"id": uuid.uuid4(), "shop": shop_id, "tag": tag, "now": NOW})


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def test_every_new_table_has_row_level_security(owner_engine):
    names = [*TENANT_TABLES, FORMULAS]
    with owner_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)"
                ),
                {"t": names},
            ).all()
        )
    assert rows == dict.fromkeys(names, True)


def test_grants_follow_the_lanes(owner_engine):
    with owner_engine.connect() as conn:
        for table in APPEND_ONLY:
            assert _verbs(conn, RUNTIME_ROLE, table) == {"SELECT", "INSERT"}, table
        assert _verbs(conn, RUNTIME_ROLE, "shopee_order_lines") == {"SELECT", "INSERT", "UPDATE"}
        assert _verbs(conn, RUNTIME_ROLE, FORMULAS) == {"SELECT"}
        if _role_exists(conn, "juli_ops"):
            assert _verbs(conn, "juli_ops", FORMULAS) == {"SELECT", "INSERT", "UPDATE"}
            for table in TENANT_TABLES:
                assert _verbs(conn, "juli_ops", table) == set(), table


@pytest.mark.parametrize("table", TENANT_TABLES)
def test_a_shop_sees_and_writes_only_its_own_rows(owner_engine, two_tenants, table):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, table, a.shop_id, f"{table}-a")
        _insert(conn, table, b.shop_id, f"{table}-b")
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(conn.execute(text(f"SELECT shop_id FROM public.{table}")).scalars())  # noqa: S608
        assert shops == {a.shop_id}
        _insert(conn, table, a.shop_id, f"{table}-a2")
        with pytest.raises(DBAPIError):
            _insert(conn, table, b.shop_id, f"{table}-smuggled")
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_append_only_tables_refuse_update_and_delete(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.begin() as conn:
        _insert(conn, "shop_rule_versions", a.shop_id, "append-only")
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE public.shop_rule_versions SET reason = 'x'"))
        conn.rollback()
        _scope(conn, a.shop_id)
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM public.shop_rule_versions"))
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_fee_formulas_are_readable_by_the_app_role_and_never_writable(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.platform_fee_formulas (id, platform, category_path, "
                "effective_from, components) VALUES (:id, 'shopee', '[]', '2026-01-01', "
                "CAST(:c AS jsonb))"
            ),
            {
                "id": uuid.uuid4(),
                "c": json.dumps([{"code": "commission", "kind": "pct", "rate": 0.15}]),
            },
        )
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        assert conn.execute(text(f"SELECT count(*) FROM public.{FORMULAS}")).scalar() >= 1  # noqa: S608
        with pytest.raises(DBAPIError):
            conn.execute(text(f"UPDATE public.{FORMULAS} SET source_note = 'x'"))  # noqa: S608
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_a_fee_formula_components_must_be_a_list(owner_engine):
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError) as refused:
            conn.execute(
                text(
                    "INSERT INTO public.platform_fee_formulas (id, platform, category_path, "
                    "effective_from, components) VALUES (:id, 'shopee', '[\"x\"]', "
                    "'2026-01-01', '{}')"
                ),
                {"id": uuid.uuid4()},
            )
        conn.rollback()
    assert "ck_platform_fee_formulas_components" in str(refused.value)


def test_a_launch_purpose_needs_a_cap_and_an_end_date(owner_engine, two_tenants):
    a, _ = two_tenants
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError) as refused:
            conn.execute(
                text(
                    "INSERT INTO public.ad_campaign_purposes (id, shop_id, platform, "
                    "campaign_key, purpose, set_by, set_at) VALUES (:id, :shop, 'shopee', "
                    "'launch', 'ra_mat', 'team', :now)"
                ),
                {"id": uuid.uuid4(), "shop": a.shop_id, "now": NOW},
            )
        conn.rollback()
    assert "ck_ad_campaign_purposes_launch_capped" in str(refused.value)


def test_card_events_accepts_whatif_adjusted_many_times_per_card(owner_engine, two_tenants):
    a, _ = two_tenants
    card_id = uuid.uuid4()

    def insert(conn, event_type: str, dedup: str) -> None:
        conn.execute(
            text(
                "INSERT INTO public.card_events (id, card_id, shop_id, workflow_key, "
                "subject_type, subject_id, event_type, actor, occurred_at, source, payload, "
                "schema_version, dedup_key) VALUES (:id, :card, :shop, 'price_card', 'item', "
                "'1001', :t, 'seller', :now, 'live', CAST(:p AS jsonb), 1, :dedup)"
            ),
            {
                "id": uuid.uuid4(),
                "card": card_id,
                "shop": a.shop_id,
                "t": event_type,
                "now": NOW,
                "dedup": dedup,
                "p": json.dumps({"from": {"discount_pct": 5}, "to": {"discount_pct": 8}}),
            },
        )

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO public.action_cards (id, shop_id, workflow_key, subject_type, "
                "subject_id, revision, priority, severity, title, description, "
                "recommendation_payload, status, metadata_json, computed_at, surfaced_at) "
                "VALUES (:id, :shop, 'price_card', 'product', '1001', 1, 1, 'high', 'T', 'D', "
                "'{}', 'proposed', '{}', :now, :now)"
            ),
            {"id": card_id, "shop": a.shop_id, "now": NOW},
        )
        insert(conn, "whatif_adjusted", "p112-w1")
        insert(conn, "whatif_adjusted", "p112-w2")  # many per card: no partial unique applies
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError) as unknown:
            insert(conn, "whatif_made_up", "p112-w3")
        conn.rollback()
    assert "ck_card_events_event_type" in str(unknown.value)


def test_a_seed_role_is_checked_and_optional(owner_engine, two_tenants):
    a, _ = two_tenants
    sql = (
        "INSERT INTO public.shop_keyword_seeds (id, shop_id, platform, keyword, pattern, "
        "item_ids, role, item_scope) VALUES (:id, :shop, 'shopee', :kw, 'type_function', "
        "'[]', :role, :scope)"
    )
    with owner_engine.begin() as conn:
        conn.execute(
            text(sql),
            {"id": uuid.uuid4(), "shop": a.shop_id, "kw": "p112 a", "role": None, "scope": None},
        )
        conn.execute(
            text(sql),
            {"id": uuid.uuid4(), "shop": a.shop_id, "kw": "p112 b", "role": "chinh", "scope": "1"},
        )
    with owner_engine.connect() as conn:
        with pytest.raises(IntegrityError) as refused:
            conn.execute(
                text(sql),
                {"id": uuid.uuid4(), "shop": a.shop_id, "kw": "p112 c", "role": "x", "scope": None},
            )
        conn.rollback()
    assert "ck_shop_keyword_seeds_role" in str(refused.value)


def test_the_purge_sweep_finds_every_new_tenant_table(owner_engine):
    """The purge deletes from every base table with a uuid ``shop_id`` (094)."""
    with owner_engine.connect() as conn:
        found = set(
            conn.execute(
                text(
                    "SELECT c.relname FROM pg_class c JOIN pg_attribute a ON a.attrelid = c.oid "
                    "WHERE c.relkind = 'r' AND c.relnamespace = 'public'::regnamespace "
                    "AND a.attname = 'shop_id' AND a.atttypid = 'uuid'::regtype "
                    "AND NOT a.attisdropped AND c.relname = ANY(:t)"
                ),
                {"t": list(TENANT_TABLES)},
            ).scalars()
        )
    assert found == set(TENANT_TABLES)


def test_zz_downgrade_drops_and_upgrade_restores(owner_engine):
    """Last in the module: downgrade to 111, then back to head."""
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def present() -> set[str]:
        with owner_engine.connect() as conn:
            return {
                name
                for name in (*TENANT_TABLES, FORMULAS)
                if conn.execute(text("SELECT to_regclass(:n)"), {"n": f"public.{name}"}).scalar()
                is not None
            }

    def seed_columns() -> set[str]:
        with owner_engine.connect() as conn:
            return set(
                conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'shop_keyword_seeds' "
                        "AND column_name IN ('role', 'item_scope')"
                    )
                ).scalars()
            )

    assert present() == {*TENANT_TABLES, FORMULAS} and seed_columns() == {"role", "item_scope"}
    command.downgrade(cfg, "111_shopee_keywords")
    assert present() == set() and seed_columns() == set()
    command.upgrade(cfg, "head")
    assert present() == {*TENANT_TABLES, FORMULAS} and seed_columns() == {"role", "item_scope"}
