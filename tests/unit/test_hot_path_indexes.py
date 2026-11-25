"""batch-1125-idx (owner #68): migration 139's two indexes and the reads that stop full scans.

- 139 chains on 138, its id fits alembic, the tree keeps ONE head, the additive gate accepts it;
- the models carry the same two indexes (name, table, columns) as the migration, so the ORM schema
  the SQLite tests build matches Postgres;
- upgrade creates exactly these two (``IF NOT EXISTS``) and drops the duplicate
  ``ix_stock_history_sku`` (same columns as ``uq_stock_history_read``); downgrade drops exactly
  the two and recreates the duplicate; the model no longer declares it;
- ``latest_per_item(shop, item_ids)`` filters the grouping subquery too (it used to group the
  shop's whole snapshot history to answer for one item) and still returns the newest per variation;
- ``load_skus`` bounds ``read_at`` in SQL and keeps a read from the first minutes of the oldest
  kept GMT+7 day (the padding);
- the Connector fill poll (``jobs_for_shop``) and the card checklist (``jobs_of_card``) run the
  voucher capture once, not twice.

The plans themselves (the indexes are used) are proved on Postgres in
``tests/integration/test_hot_path_indexes_db.py``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.models.shopee_profit import PlatformItemSnapshot
from juli_backend.models.stock_alert import ShopeeStockHistory
from juli_backend.repositories import PlatformItemSnapshotsRepo
from juli_backend.services.shopee_analytics.catalog import Catalog
from juli_backend.services.shopee_recommendations import fill_queue
from juli_backend.services.stock_alert import data as stock_data
from juli_backend.services.stock_alert.forecast import HISTORY_DAYS

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/139_hot_path_indexes.py"
MODELS = {"platform_item_snapshots": PlatformItemSnapshot, "platform_promotions": PlatformPromotion}


def _module():
    spec = importlib.util.spec_from_file_location("m139", MIGRATION)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _body(fn: str) -> str:
    text = MIGRATION.read_text("utf-8")
    return text.split(f"def {fn}")[1].split("\ndef ")[0]


# =========================================================================== migration


def test_139_chains_on_138_and_the_tree_keeps_one_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    mig = _module()
    assert mig.revision == "139_hot_path_indexes" and len(mig.revision) <= 32
    assert mig.down_revision == "138_juli_agent_spend"
    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert len(script.get_heads()) == 1
    assert mig.revision in {r.revision for r in script.walk_revisions()}


def test_the_additive_gate_accepts_139():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True


def test_upgrade_creates_the_two_drops_the_duplicate_and_downgrade_reverses_exactly_that():
    mig = _module()
    up, down = _body("upgrade"), _body("downgrade")
    created = re.findall(r"CREATE INDEX IF NOT EXISTS (\w+) \"\s*\"ON public\.(\w+) \((.*?)\)", up)
    assert {(n, t, tuple(c.split(", "))) for n, t, c in created} == set(mig.INDEXES)
    assert set(re.findall(r"DROP INDEX IF EXISTS public\.(\w+)", up)) == {
        name for name, _, _ in mig.DROPPED
    }
    assert up.count("op.execute(") == 3 and "CONCURRENTLY" not in up
    dropped = set(re.findall(r"DROP INDEX IF EXISTS public\.(\w+)", down))
    assert dropped == {name for name, _, _ in mig.INDEXES}
    # the duplicate comes back exactly as 129 / 134 left it
    recreated = re.findall(
        r"CREATE INDEX (\w+) ON public\.(\w+) \"\s*\"USING btree \((.*?)\)", down
    )
    assert {(n, t, tuple(c.split(", "))) for n, t, c in recreated} == set(mig.DROPPED)
    assert down.count("op.execute(") == 3


def test_the_dropped_index_duplicates_the_unique_key():
    from sqlalchemy import UniqueConstraint

    ((_, table, columns),) = _module().DROPPED
    assert ShopeeStockHistory.__tablename__ == table
    unique = next(
        c
        for c in ShopeeStockHistory.__table__.constraints
        if isinstance(c, UniqueConstraint) and c.name == "uq_stock_history_read"
    )
    assert tuple(c.name for c in unique.columns) == columns


def test_the_models_carry_the_migrations_indexes():
    mig = _module()
    for name, table, columns in mig.INDEXES:
        index = next(i for i in MODELS[table].__table__.indexes if i.name == name)
        assert tuple(c.name for c in index.columns) == columns
        assert not index.unique
    for name, _, _ in mig.DROPPED:
        assert name not in {i.name for i in ShopeeStockHistory.__table__.indexes}


# =========================================================================== reads


async def _snapshot(session, shop_id, item_id, variation_id, at, price):
    session.add(
        PlatformItemSnapshot(
            shop_id=shop_id,
            platform="shopee",
            item_id=item_id,
            variation_id=variation_id,
            captured_at=at,
            current_price=price,
            source="extension",
            source_rank=3,
        )
    )


async def test_latest_per_item_for_some_items_groups_only_their_rows(session, shop, monkeypatch):
    t0 = datetime(2026, 11, 20, 3, 0)
    for item in ("a", "b"):
        for var in ("", "v1"):
            for k in range(3):
                await _snapshot(session, shop.id, item, var, t0 + timedelta(hours=k), 10 + k)
    await session.flush()
    repo = PlatformItemSnapshotsRepo(session)

    rows = await repo.latest_per_item(shop.id, ["a"])
    assert {(r.item_id, r.variation_id, r.captured_at) for r in rows} == {
        ("a", "", t0 + timedelta(hours=2)),
        ("a", "v1", t0 + timedelta(hours=2)),
    }
    assert len(await repo.latest_per_item(shop.id)) == 4

    seen = []
    real = repo._all

    async def spy(stmt):
        seen.append(str(stmt))
        return await real(stmt)

    monkeypatch.setattr(repo, "_all", spy)
    await repo.latest_per_item(shop.id, ["a", "b"])
    grouped = seen[0].split("GROUP BY")[0].split("FROM platform_item_snapshots")[-1]
    assert "platform_item_snapshots.item_id IN" in grouped  # inside the grouping subquery


async def test_load_skus_keeps_the_first_minutes_of_the_oldest_kept_day(session, shop):
    today = date(2026, 11, 25)
    oldest_kept = today - timedelta(days=2 * HISTORY_DAYS)
    # 00:30 GMT+7 on the oldest kept day = 17:30 UTC the day before
    kept = datetime.combine(oldest_kept - timedelta(days=1), datetime.min.time()) + timedelta(
        hours=17, minutes=30
    )
    dropped = kept - timedelta(hours=1)  # 23:30 GMT+7 the day before: outside
    for at, stock in ((dropped, 1), (kept, 2), (datetime(2026, 11, 24, 3), 3)):
        session.add(
            ShopeeStockHistory(
                shop_id=shop.id, item_id="i", variation_id="", read_at=at, available=stock
            )
        )
    await session.flush()

    skus = await stock_data.load_skus(session, shop.id, Catalog(), today)
    assert [r.stock for r in skus["i"].reads] == [2, 3]


async def test_the_fill_poll_and_the_checklist_capture_vouchers_once(session, monkeypatch):
    calls: list[uuid.UUID] = []

    async def counting(_session, shop_id):
        calls.append(shop_id)
        return 0

    monkeypatch.setattr(fill_queue, "resolve_voucher_captures", counting)
    shop_id = uuid.uuid4()
    await fill_queue.jobs_for_shop(session, shop_id)
    assert calls == [shop_id]
    await fill_queue.jobs_of_card(session, shop_id, uuid.uuid4())
    assert calls == [shop_id, shop_id]
