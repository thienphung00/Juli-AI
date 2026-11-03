"""ADR-119, migration 111 on real Postgres: RLS and grants of the keyword tables.

- both tables have row-level security on;
- ``shop_keyword_seeds`` (client lane): ``juli_app`` SELECT, INSERT, UPDATE, never DELETE;
  a shop sees and writes only its own seeds;
- ``market_keyword_metrics`` (public lane): nothing for ``juli_app`` (``anon`` /
  ``authenticated`` are covered with every ops-only table by ``test_ops_console_db``);
  ``juli_ops`` SELECT, INSERT, UPDATE, no DELETE; a non-``ok`` row with a
  number is refused by the table itself.

Synthetic tenants only; no downgrade, so it runs on the shared database.
"""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres]

VERBS = ("SELECT", "INSERT", "UPDATE", "DELETE")
SEEDS = "shop_keyword_seeds"
METRICS = "market_keyword_metrics"


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


def _insert_seed(conn, shop_id: uuid.UUID, keyword: str) -> None:
    conn.execute(
        text(
            "INSERT INTO public.shop_keyword_seeds (id, shop_id, platform, keyword, pattern, "
            "item_ids) VALUES (:id, :shop, 'shopee', :kw, 'type_function', CAST(:items AS jsonb))"
        ),
        {"id": uuid.uuid4(), "shop": shop_id, "kw": keyword, "items": json.dumps(["1001"])},
    )


def test_both_tables_have_row_level_security(owner_engine):
    with owner_engine.connect() as conn:
        rows = dict(
            conn.execute(
                text(
                    "SELECT relname, relrowsecurity FROM pg_class "
                    "WHERE relnamespace = 'public'::regnamespace AND relname = ANY(:t)"
                ),
                {"t": [SEEDS, METRICS]},
            ).all()
        )
    assert rows == {SEEDS: True, METRICS: True}


def test_grants_follow_the_lanes(owner_engine):
    with owner_engine.connect() as conn:
        assert _verbs(conn, RUNTIME_ROLE, SEEDS) == {"SELECT", "INSERT", "UPDATE"}
        assert _verbs(conn, RUNTIME_ROLE, METRICS) == set()
        # anon / authenticated: test_ops_console_db covers every ops-only table.
        if _role_exists(conn, "juli_ops"):
            assert _verbs(conn, "juli_ops", METRICS) == {"SELECT", "INSERT", "UPDATE"}


def test_a_shop_sees_and_writes_only_its_own_seeds(owner_engine, two_tenants):
    a, b = two_tenants
    with owner_engine.begin() as conn:
        _insert_seed(conn, a.shop_id, "miếng rửa chén")
        _insert_seed(conn, b.shop_id, "nước rửa chén")
    with owner_engine.connect() as conn:
        conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
        conn.execute(
            text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(a.shop_id)}
        )
        keywords = list(
            conn.execute(text("SELECT keyword FROM public.shop_keyword_seeds")).scalars()
        )
        assert keywords == ["miếng rửa chén"]
        updated = conn.execute(text("UPDATE public.shop_keyword_seeds SET enabled = false"))
        assert updated.rowcount == 1
        with pytest.raises(DBAPIError):
            _insert_seed(conn, b.shop_id, "smuggled")
        conn.rollback()
        conn.execute(text("RESET ROLE"))


def test_a_refused_lookup_cannot_carry_numbers(owner_engine):
    with owner_engine.connect() as conn:
        with pytest.raises(DBAPIError) as refused:
            conn.execute(
                text(
                    "INSERT INTO public.market_keyword_metrics (id, platform, source, keyword, "
                    "seed, collected_on, status, volume, extra) VALUES (:id, 'shopee', "
                    "'shopeeanalytics', 'cọ tre', 'cọ tre', '2026-11-03', 'blocked', 0, '{}')"
                ),
                {"id": uuid.uuid4()},
            )
        conn.rollback()
    assert "ck_market_keyword_metrics_no_numbers" in str(refused.value)
