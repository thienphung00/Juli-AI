"""Migration 128: the Connector heartbeat and command tables (P100). Static checks plus the ORM."""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATH = REPO / "backend/src/juli_backend/database/migrations/versions/128_connector_state.py"


def _module():
    spec = importlib.util.spec_from_file_location("m128", PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_fits_alembic_and_follows_127():
    mod = _module()
    assert mod.revision == "128_connector_state" and len(mod.revision) <= 32
    assert mod.down_revision == "127_card_content_specs"


def test_single_head_and_it_descends_from_128():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert len(script.get_heads()) == 1
    ancestry = {r.revision for r in script.walk_revisions(base="base", head="head")}
    assert "128_connector_state" in ancestry


def test_additive_only_rls_and_downgrade_drops_only_what_upgrade_made():
    text = PATH.read_text("utf-8")
    up, down = text.split("def downgrade")
    assert "drop_table" not in up and "DROP" not in up and "DELETE" not in up
    assert up.count("create_table(") == 2 and down.count("drop_table(") == 2
    assert "ENABLE ROW LEVEL SECURITY" in up and "app_current_shop_id()" in up
    assert "GRANT SELECT, INSERT, UPDATE" in up and "DELETE ON" not in up
    assert "uq_shopee_connector_commands_open" in up and "uq_shopee_connector_commands_open" in down


def test_both_tables_are_classified_tenant_direct():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    for table in ("shopee_connector_state", "shopee_connector_commands"):
        assert TABLE_CLASSIFICATION_MAP[("public", table)] == "tenant_direct"
