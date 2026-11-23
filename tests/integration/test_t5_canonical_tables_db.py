"""T5, migrations 134 + 136 on real Postgres: the canonical fact tables, their times, and the
compat views 134 created and 136 dropped.

- T1 / 136 M-1: the seven new names are tables; the seven old names are gone at head (136);
- T3: no constraint, index or policy of the seven tables still carries a ``shopee_`` name;
- T4: RLS stays on, the policies still compare with ``app_current_shop_id()``, ``juli_app`` keeps
  the same verbs (stock_history SELECT, INSERT; the others SELECT, INSERT, UPDATE); two tenants
  on ``order_lines``;
- 136 M-2 / T5: a downgrade below 136 recreates the views as 134 did: ``security_invoker``, the
  table's columns, the table's verbs; tenant A neither reads B's rows nor writes one for B
  through ``shopee_order_lines``, and an insert through the view lands in ``order_lines``;
  upgrading to 136 again drops exactly the views and leaves the tables (same oid, same rows);
- T6 / T10: the time columns are ``timestamptz``; ``stock_history`` has its (shop_id, read_at)
  index;
- last, T6 + T11: rows seeded at 133 (naive Vietnam-local order times, naive UTC read times, an
  unknown status) come up converted (03:00 VN -- the previous UTC date -- stays on its VN day;
  17:00 UTC is the next VN day), normalised and ranked; a downgrade to 135 restores the names
  (tables, constraints, indexes, policies), the grants, the columns and the naive times;
  ``upgrade head`` again.

Synthetic tenants only.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS = REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
MIGRATION = VERSIONS / "134_canonical_tables.py"
MIGRATION_136 = VERSIONS / "136_drop_t5_compat_views.py"
VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
NOW = datetime(2026, 11, 18, 3, 0)


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = _module(MIGRATION, "m134_db")
M136 = _module(MIGRATION_136, "m136_db")


def _verbs(conn, relation: str) -> set[str]:
    return {
        verb
        for verb in VERBS
        if conn.execute(
            text("SELECT has_table_privilege(:r, :t, :v)"),
            {"r": RUNTIME_ROLE, "t": f"public.{relation}", "v": verb},
        ).scalar()
    }


def _relkind(conn, name: str) -> str | None:
    return conn.execute(
        text(
            "SELECT relkind::text FROM pg_class "
            "WHERE relnamespace = 'public'::regnamespace AND relname = :n"
        ),
        {"n": name},
    ).scalar()


def _scope(conn, shop_id: uuid.UUID) -> None:
    conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
    conn.execute(text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shop_id)})


def _line_sql(relation: str) -> str:
    return (
        f"INSERT INTO public.{relation} (id, shop_id, platform, order_ref, line_no, ordered_at, "
        "day, status, item_id, qty, original_price, deal_price, source, source_version) "
        "VALUES (:id, :shop, 'shopee', :ref, 0, :at, :day, 'delivered', '1001', 1, 100000, "
        "90000, 'file', 't5')"
    )


def _line(conn, relation: str, shop_id: uuid.UUID, ref: str) -> None:
    conn.execute(
        text(_line_sql(relation)),
        {"id": uuid.uuid4(), "shop": shop_id, "ref": ref, "at": NOW, "day": NOW.date()},
    )


def test_new_names_are_tables_and_old_names_are_gone_at_head(owner_engine):
    with owner_engine.connect() as conn:
        kinds = {(old, new): (_relkind(conn, old), _relkind(conn, new)) for old, new, _ in M.TABLES}
    assert len(kinds) == 7
    assert kinds == {pair: (None, "r") for pair in kinds}


def test_no_constraint_index_or_policy_keeps_the_old_name(owner_engine):
    found: list[str] = []
    with owner_engine.connect() as conn:
        for _old, new, _verbs_ in M.TABLES:
            found += (
                conn.execute(
                    text(
                        "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) "
                        "UNION ALL SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = 'public' AND tablename = :n "
                        "UNION ALL SELECT polname FROM pg_policy "
                        "WHERE polrelid = CAST(:t AS regclass)"
                    ),
                    {"t": f"public.{new}", "n": new},
                )
                .scalars()
                .all()
            )
    assert found, "the seven tables have no constraint, index or policy at all"
    assert [name for name in found if "shopee_" in name] == []


def test_rls_policies_and_verbs_are_unchanged_on_the_tables(owner_engine):
    with owner_engine.connect() as conn:
        for old, new, verbs in M.TABLES:
            expected = {v.strip() for v in verbs.split(",")}
            on = conn.execute(
                text("SELECT relrowsecurity FROM pg_class WHERE oid = CAST(:t AS regclass)"),
                {"t": f"public.{new}"},
            ).scalar()
            assert on is True, new
            assert _verbs(conn, new) == expected, new
            policies = conn.execute(
                text(
                    "SELECT cmd, coalesce(qual, '') || ' ' || coalesce(with_check, '') "
                    "FROM pg_policies WHERE schemaname = 'public' AND tablename = :n"
                ),
                {"n": new},
            ).all()
            assert {cmd for cmd, _ in policies} >= expected, (new, policies)
            assert all("app_current_shop_id()" in clause for _, clause in policies), policies


def test_a_tenant_sees_and_writes_only_its_own_lines(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _line(conn, "order_lines", a.shop_id, "a" * 32)
        _line(conn, "order_lines", b.shop_id, "b" * 32)
    with owner_engine.connect() as conn:
        _scope(conn, a.shop_id)
        shops = set(conn.execute(text("SELECT shop_id FROM public.order_lines")).scalars())
        assert shops == {a.shop_id}
        with pytest.raises(DBAPIError):
            _line(conn, "order_lines", b.shop_id, "d" * 32)
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_times_are_timestamptz_and_stock_history_has_the_read_index(owner_engine):
    with owner_engine.connect() as conn:
        types = {
            (table, column): conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :t AND column_name = :c"
                ),
                {"t": table, "c": column},
            ).scalar()
            for table, column, _zone in M.TIMES
        }
        index = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' AND indexname = 'ix_stock_history_read'"
            )
        ).scalar()
    assert set(types.values()) == {"timestamp with time zone"}, types
    assert index is not None and "(shop_id, read_at)" in index


# =========================================================================== conversion, down, up
# (the tests below walk the chain; they run last in the module, zy before zz)


def _cfg():
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))
    return cfg


def _seed_at_133(conn, shop_id: uuid.UUID) -> None:
    """Rows in the 133 shape: naive order times (Vietnam local) and read times (UTC)."""
    for ref, status, paid in (("1" * 32, "shipped", True), ("2" * 32, "weird", False)):
        conn.execute(
            text(
                "INSERT INTO public.shopee_order_lines (id, shop_id, platform, order_ref, "
                "line_no, ordered_at, paid_at, status, item_id, qty, original_price, deal_price, "
                "shopee_subsidy, source, source_version) VALUES (:id, :shop, 'shopee', :ref, 0, "
                "'2026-10-01 03:00:00', :paid, :status, '1001', 1, 100000, 90000, 5000, 'file', "
                "'t5')"
            ),
            {
                "id": uuid.uuid4(),
                "shop": shop_id,
                "ref": ref,
                "status": status,
                "paid": datetime(2026, 10, 1, 3, 2) if paid else None,
            },
        )
    conn.execute(
        text(
            "INSERT INTO public.shopee_affiliate_lines (id, shop_id, platform, order_ref, line_no, "
            "item_id, model_id, order_status, ordered_at, source, source_version) VALUES "
            "(:id, :shop, 'shopee', :ref, 0, '1001', '55', 'Đã hoàn thành', "
            "'2026-10-01 03:00:00', 'extension', 't5')"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "ref": "3" * 32},
    )
    conn.execute(
        text(
            "INSERT INTO public.shopee_stock_history (id, shop_id, item_id, model_id, read_at, "
            "available) VALUES (:id, :shop, '1001', '55', '2026-10-01 17:00:00', 4)"
        ),
        {"id": uuid.uuid4(), "shop": shop_id},
    )


def _converted(conn, shop_id: uuid.UUID) -> dict:
    lines = conn.execute(
        text(
            "SELECT order_ref, ordered_at = TIMESTAMPTZ '2026-09-30 20:00:00+00', day, status, "
            "platform_subsidy, source_rank FROM public.order_lines WHERE shop_id = :s "
            "ORDER BY order_ref"
        ),
        {"s": shop_id},
    ).all()
    affiliate = conn.execute(
        text(
            "SELECT variation_id, status, day, ordered_at = TIMESTAMPTZ '2026-09-30 20:00:00+00', "
            "source_rank FROM public.affiliate_lines WHERE shop_id = :s"
        ),
        {"s": shop_id},
    ).one()
    stock = conn.execute(
        text(
            "SELECT variation_id, read_at = TIMESTAMPTZ '2026-10-01 17:00:00+00', "
            "(read_at AT TIME ZONE 'Asia/Ho_Chi_Minh')::date FROM public.stock_history "
            "WHERE shop_id = :s"
        ),
        {"s": shop_id},
    ).one()
    return {
        "lines": [tuple(r) for r in lines],
        "affiliate": tuple(affiliate),
        "stock": tuple(stock),
    }


def _object_names(conn, table: str) -> list[str]:
    """The constraint, index and policy names of ``public.<table>``."""
    return list(
        conn.execute(
            text(
                "SELECT conname FROM pg_constraint WHERE conrelid = CAST(:t AS regclass) "
                "UNION ALL SELECT indexname FROM pg_indexes "
                "WHERE schemaname = 'public' AND tablename = :n "
                "UNION ALL SELECT polname FROM pg_policy WHERE polrelid = CAST(:t AS regclass)"
            ),
            {"t": f"public.{table}", "n": table},
        ).scalars()
    )


def _restored(conn, shop_id: uuid.UUID) -> dict:
    lines = conn.execute(
        text(
            "SELECT order_ref, ordered_at, shopee_subsidy FROM public.shopee_order_lines "
            "WHERE shop_id = :s ORDER BY order_ref"
        ),
        {"s": shop_id},
    ).all()
    affiliate = conn.execute(
        text(
            "SELECT model_id, order_status, ordered_at FROM public.shopee_affiliate_lines "
            "WHERE shop_id = :s"
        ),
        {"s": shop_id},
    ).one()
    stock = conn.execute(
        text("SELECT model_id, read_at FROM public.shopee_stock_history WHERE shop_id = :s"),
        {"s": shop_id},
    ).one()
    kinds = {old: _relkind(conn, old) for old, _new, _verbs_ in M.TABLES}
    types = set(
        conn.execute(
            text(
                "SELECT data_type FROM information_schema.columns WHERE table_schema = 'public' "
                "AND table_name = 'shopee_order_lines' AND column_name IN ('ordered_at', 'paid_at')"
            )
        ).scalars()
    )
    return {
        "lines": [tuple(r) for r in lines],
        "affiliate": tuple(affiliate),
        "stock": tuple(stock),
        "kinds": kinds,
        "types": types,
        "new_gone": all(_relkind(conn, new) is None for _old, new, _v in M.TABLES),
        "new_named": [
            name
            for old, new, _v in M.TABLES
            for name in _object_names(conn, old)
            if new in name and old not in name
        ],
        "named": all(_object_names(conn, old) for old, _new, _v in M.TABLES),
        "verbs": {old: _verbs(conn, old) for old, _new, _v in M.TABLES},
    }


def _columns(conn, relation: str) -> list[str]:
    return list(
        conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = :t ORDER BY ordinal_position"
            ),
            {"t": relation},
        ).scalars()
    )


def _tables_state(conn) -> dict[str, tuple[int, int]]:
    """(oid, row count) of each of the seven tables: 136 must leave both unchanged."""
    return {
        new: (
            conn.execute(text("SELECT CAST(:t AS regclass)::oid"), {"t": f"public.{new}"}).scalar(),
            conn.execute(text(f"SELECT count(*) FROM public.{new}")).scalar(),  # nosec B608
        )
        for _old, new, _v in M.TABLES
    }


def test_zy_136_downgrade_recreates_the_134_views_and_upgrade_drops_only_them(
    owner_engine, two_tenants
):
    """head -> below 136 (views back, exactly as 134 made them) -> 136 (views gone, tables
    untouched) -> head."""
    from alembic import command

    a, b = two_tenants
    cfg = _cfg()
    with owner_engine.begin() as conn:
        _line(conn, "order_lines", a.shop_id, "e" * 32)
        _line(conn, "order_lines", b.shop_id, "f" * 32)
    command.downgrade(cfg, M136.down_revision)
    try:
        with owner_engine.connect() as conn:
            version = int(conn.execute(text("SHOW server_version_num")).scalar())
            assert version >= 150000
            for old, new, verbs in M.TABLES:
                assert _relkind(conn, old) == "v", old
                options = conn.execute(
                    text("SELECT reloptions FROM pg_class WHERE oid = CAST(:t AS regclass)"),
                    {"t": f"public.{old}"},
                ).scalar()
                assert "security_invoker=true" in (options or []), (old, options)
                assert _columns(conn, old) == _columns(conn, new), old  # SELECT * of the table
                assert _verbs(conn, old) == {v.strip() for v in verbs.split(",")}, old
            # security_invoker: the invoker's RLS applies through the view
            _scope(conn, a.shop_id)
            shops = set(
                conn.execute(text("SELECT shop_id FROM public.shopee_order_lines")).scalars()
            )
            assert shops == {a.shop_id}
            _line(conn, "shopee_order_lines", a.shop_id, "c" * 32)  # through the view
            landed = conn.execute(
                text("SELECT count(*) FROM public.order_lines WHERE order_ref = :r"),
                {"r": "c" * 32},
            ).scalar()
            assert landed == 1
            with pytest.raises(DBAPIError):
                _line(conn, "shopee_order_lines", b.shop_id, "d" * 32)
            conn.rollback()
            conn.execute(text("RESET ROLE"))
            before = _tables_state(conn)
            conn.rollback()

        command.upgrade(cfg, M136.revision)
        with owner_engine.connect() as conn:
            assert {old: _relkind(conn, old) for old, _n, _v in M.TABLES} == {
                old: None for old, _n, _v in M.TABLES
            }
            assert _tables_state(conn) == before
            for _old, new, verbs in M.TABLES:
                assert _relkind(conn, new) == "r", new
                assert _verbs(conn, new) == {v.strip() for v in verbs.split(",")}, new
    finally:
        command.upgrade(cfg, "head")


def test_zz_rows_convert_up_and_back_down(owner_engine, two_tenants):
    """Last in the module: rows at 135 (the 133 shape of the seven tables) -> 134 (converted)
    -> 135 (restored) -> head."""
    from alembic import command

    shop_id = two_tenants[0].shop_id
    cfg = _cfg()
    command.downgrade(cfg, "135_connector_multi_computer")
    try:
        with owner_engine.begin() as conn:
            conn.execute(
                text("DELETE FROM public.shopee_order_lines WHERE shop_id = :s"), {"s": shop_id}
            )
            _seed_at_133(conn, shop_id)
        command.upgrade(cfg, "134_canonical_tables")
        with owner_engine.connect() as conn:
            up = _converted(conn, shop_id)
        assert up["lines"] == [
            ("1" * 32, True, date(2026, 10, 1), "in_transit", 5000, 2),  # file
            ("2" * 32, True, date(2026, 10, 1), "pending", 5000, 2),
        ]
        assert up["affiliate"] == ("55", "Đã hoàn thành", date(2026, 10, 1), True, 3)  # extension
        assert up["stock"] == ("55", True, date(2026, 10, 2))

        command.downgrade(cfg, "135_connector_multi_computer")
        with owner_engine.connect() as conn:
            down = _restored(conn, shop_id)
        assert down["kinds"] == {old: "r" for old, _new, _v in M.TABLES}
        assert down["new_gone"] is True
        # constraint / index / policy names carry the old table names again, grants as at 135
        assert down["named"] is True and down["new_named"] == []
        assert down["verbs"] == {
            old: {v.strip() for v in verbs.split(",")} for old, _new, verbs in M.TABLES
        }
        assert down["types"] == {"timestamp without time zone"}
        assert down["lines"] == [
            ("1" * 32, datetime(2026, 10, 1, 3, 0), 5000),
            ("2" * 32, datetime(2026, 10, 1, 3, 0), 5000),
        ]
        assert down["affiliate"] == ("55", "Đã hoàn thành", datetime(2026, 10, 1, 3, 0))
        assert down["stock"] == ("55", datetime(2026, 10, 1, 17, 0))
    finally:
        command.upgrade(cfg, "head")
    with owner_engine.connect() as conn:
        assert _relkind(conn, "order_lines") == "r" and _relkind(conn, "shopee_order_lines") is None
