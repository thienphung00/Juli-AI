"""Migration 129: the stock alert tables (Part S). Static checks plus the ORM."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATH = REPO / "backend/src/juli_backend/database/migrations/versions/129_stock_alert.py"
TABLES = (
    "shopee_stock_history",
    "shopee_sku_tracking",
    "shopee_stock_alert_unsubscribes",
    "shopee_stock_alert_sends",
)


def _module():
    spec = importlib.util.spec_from_file_location("m129", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_fits_alembic_and_follows_128():
    mod = _module()
    assert mod.revision == "129_stock_alert" and len(mod.revision) <= 32
    assert mod.down_revision == "128_connector_state"


def test_single_head_descends_from_129():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert len(script.get_heads()) == 1
    ancestry = {r.revision for r in script.walk_revisions(base="base", head="head")}
    assert "129_stock_alert" in ancestry


def test_additive_only_rls_and_grants():
    text = PATH.read_text("utf-8")
    up, down = text.split("def downgrade")
    assert "drop_table" not in up and "DROP" not in up and "DELETE" not in up
    assert up.count("create_table(") == 4 and down.count("drop_table(") == 4
    assert "ENABLE ROW LEVEL SECURITY" in up and "app_current_shop_id()" in up
    mod = _module()
    assert mod.VERBS[mod.TRACKING] == ("SELECT", "INSERT", "UPDATE")
    assert all("DELETE" not in v for v in mod.VERBS.values())
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    assert evaluate_migration_paths([PATH]).accepted


def test_tables_are_tenant_direct_and_match_the_orm():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
    from juli_backend.orm_base import Base

    for table in TABLES:
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"
        assert table in Base.metadata.tables
        for column in Base.metadata.tables[table].columns.keys():
            assert f'"{column}"' in PATH.read_text("utf-8"), (table, column)
