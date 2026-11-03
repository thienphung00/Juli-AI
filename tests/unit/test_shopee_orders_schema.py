"""P90 step 2, migration 113: order-export columns, ``shop_health_daily``, ``ads_change_log``.

On the unit substrate (source text + SQLite):

- the chain: revision id fits ``alembic_version`` (32), sits on 112, the deferred tail moved
  onto it, the additive gate accepts it;
- every model column is created by the migration; vocabularies match the models;
- the two new tables are tenant-direct and append-only (SELECT, INSERT only);
- no new column can hold a buyer's data;
- the ad change log is written append-only through the gateway (a re-read inserts nothing).

The Postgres proof (RLS, grants, up / down) is ``tests/integration/test_shopee_orders_db.py``.
Synthetic fixtures only.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from datetime import datetime
from pathlib import Path

import pytest

from juli_backend.database.tenant_scoped_tables import (
    TABLE_CLASSIFICATION_MAP,
    get_tenant_scoped_tables,
)
from juli_backend.models import shopee_profit as models
from juli_backend.models.shopee_profit import AdsChangeLog, ShopeeOrderLine, ShopHealthDaily
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/113_shopee_orders_and_logs.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"

NEW_TABLES = {"shop_health_daily": ShopHealthDaily, "ads_change_log": AdsChangeLog}
NEW_LINE_COLUMNS = {
    "buyer_shipping_fee",
    "bank_promo",
    "ad_attributed",
    "seller_subsidy",
    "shopee_subsidy",
    "returned_qty",
    "completed_at",
    "paid_at",
    "sku",
    "variation_sku",
}


def _module():
    spec = importlib.util.spec_from_file_location("mig113", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _created_columns(source: str) -> set[str]:
    found = set(re.findall(r'sa\.Column\(\s*"(\w+)"', source))
    if "_shop_column()" in source:
        found.add("shop_id")
    if "_created_at()" in source:
        found.add("created_at")
    return found


def test_migration_113_fits_alembic_and_the_deferred_tail_moved_onto_it():
    mig = _module()
    assert mig.revision == "113_shopee_orders_and_logs" and len(mig.revision) <= 32
    assert mig.down_revision == "112_shopee_profit_and_history"
    # P90 step 6's 114 went on 113 and took the deferred tail.
    assert 'down_revision: str | None = "115_shopee_recommendations"' in BACKFILL.read_text("utf-8")


def test_the_additive_gate_accepts_migration_113():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True


def test_upgrade_only_adds_and_downgrade_drops_every_new_object():
    source = MIGRATION.read_text("utf-8")
    up = source.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("op.drop_", "op.alter_column", "UPDATE public", "DELETE FROM", "DROP "):
        assert verb not in up, verb
    mig = _module()
    assert set(mig.LINE_COLUMNS) == NEW_LINE_COLUMNS
    down = source.split("def downgrade")[1]
    assert "op.drop_table(table)" in down and "for column in reversed(LINE_COLUMNS)" in down
    # Every added column really is added in upgrade.
    added = set(re.findall(r'op\.add_column\(\s*LINES_TABLE,\s*sa\.Column\(\s*"(\w+)"', source))
    assert added == NEW_LINE_COLUMNS


def test_every_model_column_is_created_by_the_migration():
    source = MIGRATION.read_text("utf-8")
    for name, model in NEW_TABLES.items():
        block = source.split(f"def _create_{'health' if 'health' in name else 'log'}")[1]
        block = block.split("\ndef ")[0]
        assert set(model.__table__.columns.keys()) == _created_columns(block), name
    for column in NEW_LINE_COLUMNS:
        assert column in ShopeeOrderLine.__table__.columns


def test_migration_vocabularies_match_the_models():
    mig = _module()
    assert mig.PLATFORMS == models.PLATFORMS
    assert mig.ACTOR_KINDS == ("system", "user")


def test_the_new_tables_are_tenant_direct_and_append_only():
    mig = _module()
    tenant = {table for _schema, table in get_tenant_scoped_tables()}
    for name, model in NEW_TABLES.items():
        assert TABLE_CLASSIFICATION_MAP[("public", name)] == "tenant_direct", name
        assert name in tenant and "shop_id" in model.__table__.columns
    assert mig.TENANT_VERBS == {
        "shop_health_daily": "SELECT, INSERT",
        "ads_change_log": "SELECT, INSERT",
    }
    source = MIGRATION.read_text("utf-8")
    assert "UPDATE" not in source.split("def _secure_tenant")[0].split("_CLAUSES")[1]


def test_no_new_column_can_hold_a_buyer():
    forbidden = ("phone", "address", "email", "recipient", "customer", "comment", "note")
    for model in (*NEW_TABLES.values(), ShopeeOrderLine):
        bad = [c for c in model.__table__.columns.keys() if any(w in c for w in forbidden)]
        assert bad == [], model.__tablename__


def test_ad_attributed_is_nullable_because_no_export_says_it():
    column = ShopeeOrderLine.__table__.columns["ad_attributed"]
    assert column.nullable is True and column.default is None and column.server_default is None


def _log_body(rows: list[dict], **over) -> dict:
    body = {
        "source": "file",
        "source_version": "seller-centre-xlsx-1",
        "captured_at": "2026-10-29T09:30:00+07:00",
        "period": {"start": "2026-10-05", "end": "2026-10-06", "granularity": "period"},
        "rows": rows,
    }
    body.update(over)
    return body


ROWS = [
    {
        "campaign_id": "555000111",
        "occurred_at": "2026-10-05T10:00:00",
        "actor_kind": "user",
        "actor": "ory.shop",
        "event_type": "Thay đổi ngân sách",
        "detail": "Ngân sách hàng ngày: ₫100.000 -> ₫150.000",
        "budget_from": 100000,
        "budget_to": 150000,
    },
    {
        "campaign_id": "555000111",
        "item_id": "1001",
        "occurred_at": "2026-10-06T10:00:00",
        "actor_kind": "system",
        "event_type": "Tối ưu tự động",
        "products_from": 3,
        "products_to": 4,
    },
]


async def test_the_ad_change_log_is_appended_and_an_overlapping_reread_adds_only_new_lines(session):
    shop = await _shop(session)
    await _ingest(session, shop, "ads_change_log", _log_body(ROWS))
    stored = await _rows(session, AdsChangeLog, shop)
    assert len(stored) == 2
    budget = next(s for s in stored if s.item_id == "")
    assert (budget.budget_from, budget.budget_to, budget.actor_kind) == (100000, 150000, "user")
    assert budget.occurred_at == datetime(2026, 10, 5, 10, 0)
    product = next(s for s in stored if s.item_id == "1001")
    assert (product.products_from, product.products_to) == (3, 4)

    # A later export of an overlapping window: the old lines again plus one new one.
    newer = {
        "campaign_id": "555000111",
        "occurred_at": "2026-10-07T10:00:00",
        "actor_kind": "system",
        "event_type": "Tối ưu tự động",
    }
    await _ingest(
        session,
        shop,
        "ads_change_log",
        _log_body(
            [*ROWS, newer],
            period={"start": "2026-10-05", "end": "2026-10-07", "granularity": "period"},
            captured_at="2026-10-29T09:45:00+07:00",
        ),
    )
    assert len(await _rows(session, AdsChangeLog, shop)) == 3


@pytest.mark.parametrize("dataset", ["ads_change_log"])
async def test_a_buyer_field_on_a_log_row_is_refused(session, dataset):
    from juli_backend.services.ingest.gateway import IngestRejected

    shop = await _shop(session)
    with pytest.raises(IngestRejected) as refused:
        await _ingest(
            session, shop, dataset, _log_body([{**ROWS[0], "buyer_name": "CANARY-buyer"}])
        )
    assert refused.value.code == "invalid_rows"
