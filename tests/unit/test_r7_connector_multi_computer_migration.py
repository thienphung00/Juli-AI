"""Migration 135 (batch-1118e R7): fill-job lease, per-token Connector state, install id.

Static checks plus the ORM; upgrade/downgrade on Postgres runs in the deploy gate.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PATH = (
    REPO / "backend/src/juli_backend/database/migrations/versions/135_connector_multi_computer.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("m135", PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_fits_alembic():
    mod = _module()
    assert mod.revision == "135_connector_multi_computer" and len(mod.revision) <= 32


def test_single_head_and_it_descends_from_135():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert len(script.get_heads()) == 1
    ancestry = {r.revision for r in script.walk_revisions(base="base", head="head")}
    assert "135_connector_multi_computer" in ancestry


def test_additive_gate_accepts_it_and_downgrade_undoes_upgrade():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([PATH])
    assert [f.render() for f in result.findings] == [] and result.accepted
    up, down = PATH.read_text("utf-8").split("def downgrade")
    assert "drop_" not in up and "DELETE" not in up
    assert up.count("op.add_column(") == 3 and down.count("op.drop_column(") == 3
    assert up.count("create_table(") == 1 and down.count("drop_table(") == 1
    assert up.count("create_index(") == 2 and down.count("drop_index(") == 2
    assert "ENABLE ROW LEVEL SECURITY" in up and up.count("app_current_shop_id()") == 4
    assert "GRANT SELECT, INSERT, UPDATE" in up and "DELETE ON" not in up
    assert "REVOKE ALL" in down


def test_columns_match_the_models():
    from juli_backend.models.ingest import IngestToken
    from juli_backend.models.shopee_connector import ShopeeConnectorTokenState
    from juli_backend.models.shopee_fill import ShopeeFillJob

    jobs = ShopeeFillJob.__table__.columns
    assert jobs["claimed_by_token_id"].nullable and jobs["lease_until"].nullable
    tokens = IngestToken.__table__
    assert tokens.columns["install_id"].nullable and tokens.columns["install_id"].type.length == 64
    assert any(
        [c.name for c in ix.columns] == ["shop_id", "platform", "install_id"]
        for ix in tokens.indexes
    )
    state = ShopeeConnectorTokenState.__table__
    assert [c.name for c in state.primary_key.columns] == ["token_id"]
    assert {fk.target_fullname for fk in state.foreign_keys} == {"ingest_tokens.id", "shops.id"}
    assert set(state.columns.keys()) == {
        "token_id",
        "shop_id",
        "heartbeat_at",
        "connector_version",
        "seller_centre_open",
        "reader_blocks",
        "reader_blocks_at",
        "updated_at",
    }
    assert state.columns["connector_version"].type.length == 32


def test_token_state_is_classified_tenant_direct():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    assert TABLE_CLASSIFICATION_MAP[("public", "shopee_connector_token_state")] == "tenant_direct"
