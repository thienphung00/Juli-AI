"""P91 D-12, migration 119: ``shopee_order_income`` and ``shopee_order_lines.variation_name``.

On the unit substrate (source text): the chain (revision fits ``alembic_version``, sits on 118), the
additive gate accepts it, ``upgrade`` only adds and ``downgrade``
drops what it added, every model column is created, the table is tenant-direct with
SELECT / INSERT / UPDATE for the runtime role, and no column can hold a buyer's data.

The Postgres proof (RLS, grants, the gateway as ``juli_app``, up / down) is
``tests/integration/test_shopee_income_db.py``.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from juli_backend.database.tenant_scoped_tables import (
    TABLE_CLASSIFICATION_MAP,
    get_tenant_scoped_tables,
)
from juli_backend.models import shopee_profit as models
from juli_backend.models.shopee_profit import ShopeeOrderIncome, ShopeeOrderLine
from juli_backend.services.ingest.income import AMOUNT_FIELDS, COLUMN_OF, ORDER_LINE_FIELDS
from juli_backend.services.ingest.schemas import ShopeeOrderIncomeRow
from tests.support.shopee_analytics import pre_t5_columns

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
MIGRATION = MIGRATIONS / "versions/119_shopee_order_income.py"
BACKFILL = MIGRATIONS / "deferred/101_write_mode_backfill.py"


def _module():
    spec = importlib.util.spec_from_file_location("mig119", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_119_fits_alembic():
    mig = _module()
    assert mig.revision == "119_shopee_order_income" and len(mig.revision) <= 32
    assert mig.down_revision == "118_shopee_kol_lines"


def test_the_additive_gate_accepts_migration_119():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([MIGRATION])
    assert [finding.render() for finding in result.findings] == []
    assert result.accepted is True


def test_upgrade_only_adds_and_downgrade_drops_what_it_added():
    source = MIGRATION.read_text("utf-8")
    up = source.split("def upgrade")[1].split("def downgrade")[0]
    for verb in (
        "op.drop_",
        "op.alter_column",
        "UPDATE public",
        "DELETE FROM",
        "DROP ",
        "INSERT INTO",
    ):
        assert verb not in up, verb
    down = source.split("def downgrade")[1]
    assert "op.drop_table(TABLE)" in down and 'op.drop_column(LINES, "variation_name")' in down
    assert re.search(r"add_column\(LINES, sa.Column\(\"variation_name\"", up)


def test_every_model_column_is_created_by_the_migration():
    mig = _module()
    created = {
        "id",
        "shop_id",
        "platform",
        "order_ref",
        "ordered_on",
        "paid_on",
        *mig.MONEY_COLUMNS,
    }
    created |= {
        "transaction_fee_rate",
        "source",
        "source_rank",
        "source_version",
        "raw_payload_id",
        "created_at",
        "updated_at",
    }
    assert pre_t5_columns(ShopeeOrderIncome) == created  # T5 (134) renamed / added since
    assert "variation_name" in ShopeeOrderLine.__table__.columns
    assert ShopeeOrderLine.__table__.columns["variation_name"].nullable is True


def test_the_ingest_row_the_writer_and_the_table_name_the_same_amounts():
    row_fields = set(ShopeeOrderIncomeRow.model_fields) - {
        "extra",
        "order_ref",
        "ordered_on",
        "paid_on",
    }
    table_columns = set(ShopeeOrderIncome.__table__.columns.keys())
    line_columns = set(ShopeeOrderLine.__table__.columns.keys())
    # every row field is either a settlement amount or an order_lines fill, never both
    assert row_fields == set(AMOUNT_FIELDS) | set(ORDER_LINE_FIELDS)
    assert not set(AMOUNT_FIELDS) & set(ORDER_LINE_FIELDS)
    # the wire keeps ship_shopee_subsidy; migration 134 named its column ship_platform_subsidy
    assert {COLUMN_OF.get(f, f) for f in AMOUNT_FIELDS} <= table_columns
    assert COLUMN_OF == {"ship_shopee_subsidy": "ship_platform_subsidy"}
    # batch-1124-a S1 / #49: the order's voucher amounts and code feed order_lines (split), so no
    # order_settlements column carries them, and each names a real order_lines column
    assert set(ORDER_LINE_FIELDS.values()) <= line_columns
    assert not {COLUMN_OF.get(f, f) for f in ORDER_LINE_FIELDS} & table_columns


def test_migration_vocabularies_match_the_models():
    assert _module().PLATFORMS == models.PLATFORMS


def test_the_table_is_tenant_direct_and_the_runtime_role_may_not_delete():
    tenant = {table for _schema, table in get_tenant_scoped_tables()}
    # migration 134 (T5) renamed the table
    assert TABLE_CLASSIFICATION_MAP[("public", "order_settlements")] == "tenant_direct"
    assert "order_settlements" in tenant and "shop_id" in ShopeeOrderIncome.__table__.columns
    source = MIGRATION.read_text("utf-8")
    assert (
        "GRANT SELECT, INSERT, UPDATE ON" in source
        and "DELETE" not in source.split("def upgrade")[1].split("def downgrade")[0]
    )
    assert "ENABLE ROW LEVEL SECURITY" in source


def test_no_column_can_hold_a_buyer_or_an_order_id():
    forbidden = (
        "phone",
        "address",
        "email",
        "recipient",
        "customer",
        "comment",
        "note",
        "name",
        "tax_code",
    )
    bad = [c for c in ShopeeOrderIncome.__table__.columns.keys() if any(w in c for w in forbidden)]
    assert bad == []
    assert "order_id" not in ShopeeOrderIncome.__table__.columns
