"""Migration 139 on real Postgres: the hot-path indexes exist and the hot reads use them.

- the two 139 indexes exist with their columns; the duplicate ``ix_stock_history_sku`` is gone,
  ``ix_stock_history_read`` (134) and the unique ``uq_stock_history_read`` are still there;
- on tables seeded across FIVE shops (``ROWS_PER_SHOP`` = 2,000 rows each, 10,000 per table,
  then ``ANALYZE``), ``EXPLAIN`` of each hot read shape names the index it should use:
  - the screens' freshness ``max(captured_at)`` -> ``ix_platform_item_snapshots_capture``;
  - the Connector fill poll's voucher read (newest 400) -> ``ix_platform_promotions_type_capture``,
    also as ``juli_app`` under RLS;
  - the voucher read-back (``captured_at >= since``) -> ``ix_platform_promotions_type_capture``;
  - the stock alert / funnel / Juli-tab stock reads, now bounded on ``read_at`` ->
    ``ix_stock_history_read``;
  - ``stock_alert.cards.variation_keys`` (DISTINCT item, variation) still reads an index without
    the duplicate (``ix_stock_history_read``), the same plan as with it;
- last: ``downgrade`` to 138 drops exactly the two indexes and recreates ``ix_stock_history_sku``
  as 129 / 134 left it; ``upgrade head`` restores the 139 state.

Why five shops and 2,000 rows: with one or two shops owning every row, ``shop_id = X`` matches
half the table or more and a sequential scan of a few dozen pages IS the cheaper plan, so the
planner rightly ignores any index (see ``fasttrack-notes/2026-11-25/idx/EVIDENCE.md``). 10,000
rows over five shops (20 % each) is the smallest seed at which the plans below were stable.

The statements mirror the ORM reads named in each test; the literal ``'shopee'`` stands for
``own_platform(...)``, which Postgres evaluates once as an InitPlan parameter.

Synthetic tenants only.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from tests.integration.two_tenant import RUNTIME_ROLE
from tests.support.postgres import requires_postgres

pytestmark = [requires_postgres, pytest.mark.migration_heavy]

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOPS = 5
ROWS_PER_SHOP = 2_000
NEW_INDEXES = {
    "ix_platform_item_snapshots_capture": (
        "platform_item_snapshots",
        "(shop_id, platform, captured_at)",
    ),
    "ix_platform_promotions_type_capture": (
        "platform_promotions",
        "(shop_id, promo_type, captured_at)",
    ),
}
DROPPED = "ix_stock_history_sku"
DROPPED_DEF = (
    "CREATE INDEX ix_stock_history_sku ON public.stock_history "
    "USING btree (shop_id, item_id, variation_id, read_at)"
)


@pytest.fixture(scope="module")
def shops(owner_engine) -> list[uuid.UUID]:
    """Five synthetic shops, each with ROWS_PER_SHOP rows in each of the three tables."""
    ids = [uuid.uuid4() for _ in range(SHOPS)]
    with owner_engine.begin() as conn:
        for n, shop_id in enumerate(ids):
            user_id = uuid.uuid4()
            conn.execute(
                text(
                    "INSERT INTO public.users (id, phone, display_name, created_at, updated_at) "
                    "VALUES (:id, :phone, 'idx owner', now(), now())"
                ),
                {"id": user_id, "phone": f"+1555{user_id.hex[:7]}"},
            )
            conn.execute(
                text(
                    "INSERT INTO public.shops "
                    "(id, user_id, shop_name, tiktok_shop_id, platform, created_at, updated_at) "
                    "VALUES (:id, :user, :name, :key, 'shopee', now(), now())"
                ),
                {"id": shop_id, "user": user_id, "name": f"idx shop {n}", "key": shop_id.hex},
            )
            p = {"shop": shop_id, "n": ROWS_PER_SHOP}
            # 100 items x 20 captures, one capture an hour back from 2026-11-25
            conn.execute(
                text(
                    "INSERT INTO public.platform_item_snapshots (id, shop_id, platform, item_id, "
                    " variation_id, captured_at, image_urls, image_hashes, category_path, "
                    " stock, source, source_rank) "
                    "SELECT gen_random_uuid(), :shop, 'shopee', 'item-' || (g % 100), '', "
                    " timestamp '2026-11-25 00:00' - make_interval(hours => g), "
                    " '[]', '[]', '[]', g % 50, 'extension', 3 "
                    "FROM generate_series(1, :n) g"
                ),
                p,
            )
            # three promo types; one settings capture per row, newest first going back
            conn.execute(
                text(
                    "INSERT INTO public.platform_promotions (id, shop_id, platform, promo_type, "
                    " program_name, starts_at, ordinal, period_start, period_end, order_type, "
                    " extra, source, source_rank, source_version, captured_at, updated_at) "
                    "SELECT gen_random_uuid(), :shop, 'shopee', "
                    " (ARRAY['voucher', 'bundle', 'discount'])[1 + g % 3], 'p' || g, "
                    " timestamp '2026-06-01', 0, "
                    " date '2026-11-25' - (g / 10), date '2026-11-25' - (g / 10), 'none', "
                    " jsonb_build_object('voucher_id', g), 'extension', 3, 'v1', "
                    " timestamp '2026-11-25 00:00' - make_interval(hours => g), now() "
                    "FROM generate_series(1, :n) g"
                ),
                p,
            )
            # 40 SKUs x 50 reads, one read every 4 h (about 200 days of history)
            conn.execute(
                text(
                    "INSERT INTO public.stock_history (id, shop_id, item_id, variation_id, "
                    " read_at, sellable, available, listing_status) "
                    "SELECT gen_random_uuid(), :shop, 'item-' || (g % 40), '', "
                    " timestamptz '2026-11-25 00:00+00' - make_interval(hours => 4 * (g / 40)), "
                    " 0, g % 7, 'listed' "
                    "FROM generate_series(1, :n) g"
                ),
                p,
            )
        for table in ("platform_item_snapshots", "platform_promotions", "stock_history"):
            conn.execute(text(f"ANALYZE public.{table}"))  # nosec B608 - fixed table names
    return ids


def _plan(conn, sql: str, params: dict) -> list[str]:
    """The index names in the plan of ``sql`` (EXPLAIN, FORMAT JSON; never run here)."""
    plan = conn.execute(text(f"EXPLAIN (FORMAT JSON) {sql}"), params).scalar()  # nosec B608
    if isinstance(plan, str):
        plan = json.loads(plan)
    out: list[str] = []

    def walk(node: dict) -> None:
        if "Index Name" in node:
            out.append(node["Index Name"])
        for child in node.get("Plans", []):
            walk(child)

    walk(plan[0]["Plan"])
    return out


def _indexdef(conn, name: str) -> str | None:
    return conn.execute(
        text("SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND indexname = :n"),
        {"n": name},
    ).scalar()


def test_the_two_indexes_exist_with_their_columns(owner_engine):
    with owner_engine.connect() as conn:
        for name, (table, columns) in NEW_INDEXES.items():
            definition = _indexdef(conn, name)
            assert definition is not None, name
            assert f"ON public.{table} USING btree {columns}" in definition
        assert _indexdef(conn, "ix_stock_history_read") is not None
        assert _indexdef(conn, "uq_stock_history_read") is not None
        assert _indexdef(conn, DROPPED) is None


def test_the_freshness_max_reads_one_index_entry(owner_engine, shops):
    # PlatformItemSnapshotsRepo.latest_capture (loaders.load_freshness, every screen load)
    sql = (
        "SELECT max(captured_at) FROM public.platform_item_snapshots "
        "WHERE shop_id = :shop AND platform = 'shopee'"
    )
    with owner_engine.connect() as conn:
        assert "ix_platform_item_snapshots_capture" in _plan(conn, sql, {"shop": shops[2]})


VOUCHER_POLL = (
    "SELECT * FROM public.platform_promotions "
    "WHERE shop_id = :shop AND promo_type = 'voucher' ORDER BY captured_at DESC LIMIT 400"
)


def test_the_fill_polls_voucher_read_uses_the_type_capture_index(owner_engine, shops):
    # fill_queue.resolve_voucher_captures (every Connector fill poll with a voucher job pending)
    with owner_engine.connect() as conn:
        assert "ix_platform_promotions_type_capture" in _plan(
            conn, VOUCHER_POLL, {"shop": shops[0]}
        )


def test_the_voucher_poll_keeps_the_index_under_rls_as_juli_app(owner_engine, shops):
    with owner_engine.connect() as conn:
        conn.execute(text(f"SET ROLE {RUNTIME_ROLE}"))
        conn.execute(
            text("SELECT set_config('app.current_shop_id', :v, false)"), {"v": str(shops[1])}
        )
        try:
            assert "ix_platform_promotions_type_capture" in _plan(
                conn, VOUCHER_POLL, {"shop": shops[1]}
            )
        finally:
            conn.execute(text("RESET ROLE"))


def test_the_voucher_readback_since_uses_the_type_capture_index(owner_engine, shops):
    # readback_compare / revert_fill / card_events.verification (voucher)
    sql = (
        "SELECT * FROM public.platform_promotions WHERE shop_id = :shop "
        "AND promo_type = 'voucher' AND captured_at >= timestamp '2026-11-23 00:00' "
        "ORDER BY captured_at DESC"
    )
    with owner_engine.connect() as conn:
        assert "ix_platform_promotions_type_capture" in _plan(conn, sql, {"shop": shops[3]})


@pytest.mark.parametrize(
    "where",
    [
        # funnel.load_rows: a 7-day window padded one day each side
        "read_at >= timestamptz '2026-11-17 00:00+00'"
        " AND read_at < timestamptz '2026-11-26 00:00+00'",
        # analytics_agent stock_events, now sargable (was read_at::date BETWEEN)
        "read_at >= cast('2026-11-18' as date) AND read_at < cast('2026-11-24' as date) + 1",
    ],
    ids=["funnel_window", "juli_tab_stock_events"],
)
def test_bounded_stock_reads_use_the_shop_read_index(owner_engine, shops, where):
    sql = f"SELECT * FROM public.stock_history WHERE shop_id = :shop AND {where}"  # nosec B608
    with owner_engine.connect() as conn:
        conn.execute(text("SET TIME ZONE 'UTC'"))
        assert "ix_stock_history_read" in _plan(conn, sql, {"shop": shops[4]})


def test_variation_keys_distinct_keeps_its_plan_without_the_duplicate(owner_engine, shops):
    """stock_alert.cards.variation_keys (recommendations loader, per run; card apply).

    The planner never chose the duplicate for this read: with or without it, the plan is a bitmap
    scan of ``ix_stock_history_read`` on the shop + HashAggregate (local PG 16, this seed; under a
    one-shop skew it is a seq scan both ways). So the drop removes an index write, not a plan:
    the index set the plan reads is the same after recreating the duplicate (rolled back)."""
    sql = "SELECT DISTINCT item_id, variation_id FROM public.stock_history WHERE shop_id = :shop"
    with owner_engine.connect() as conn:
        without = _plan(conn, sql, {"shop": shops[0]})
        assert without and set(without) <= {"ix_stock_history_read", "uq_stock_history_read"}
        conn.rollback()  # end the autobegun read; the DDL below is rolled back too
        try:
            conn.execute(text(DROPPED_DEF))
            conn.execute(text("ANALYZE public.stock_history"))
            with_duplicate = _plan(conn, sql, {"shop": shops[0]})
        finally:
            conn.rollback()
        assert with_duplicate == without
        assert _indexdef(conn, DROPPED) is None


def test_zz_downgrade_drops_exactly_the_two_indexes(owner_engine):
    from alembic import command
    from alembic.config import Config

    from juli_backend.core.config.runtime import sync_database_url

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(REPO_ROOT / "backend/src/juli_backend/database/migrations")
    )
    cfg.set_main_option("sqlalchemy.url", sync_database_url(os.environ["DATABASE_URL"]))

    def names() -> set[str]:
        with owner_engine.connect() as conn:
            return {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND "
                        "tablename IN ('platform_item_snapshots', 'platform_promotions', "
                        "'stock_history')"
                    )
                )
            }

    before = names()
    assert set(NEW_INDEXES) <= before and DROPPED not in before
    command.downgrade(cfg, "138_juli_agent_spend")
    try:
        assert names() == (before - set(NEW_INDEXES)) | {DROPPED}
        with owner_engine.connect() as conn:
            assert _indexdef(conn, DROPPED) == DROPPED_DEF
    finally:
        command.upgrade(cfg, "head")
    assert names() == before
