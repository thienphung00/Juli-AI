"""Migration 130 (P101 W1 businesses) and its deferred backfill. Static checks plus the ORM."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
PATH = MIGRATIONS / "versions/130_businesses.py"
BACKFILL = MIGRATIONS / "deferred/130_businesses_backfill.py"
TABLES = ("businesses", "business_members", "business_invites")


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_revision_fits_alembic_and_follows_129():
    mod = _module(PATH, "m130")
    assert mod.revision == "130_businesses" and len(mod.revision) <= 32
    assert mod.down_revision == "129_stock_alert"
    backfill = _module(BACKFILL, "m130b")
    assert len(backfill.revision) <= 32
    assert backfill.down_revision == "102_shop_members_backfill"


def test_single_head_descends_from_130():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert len(script.get_heads()) == 1
    ancestry = {r.revision for r in script.walk_revisions(base="base", head="head")}
    assert "130_businesses" in ancestry


def test_the_expand_step_passes_the_additive_gate_and_the_backfill_would_not():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    assert evaluate_migration_paths([PATH]).accepted
    # The data step is exactly what the gate refuses, which is why it is deferred.
    assert not evaluate_migration_paths([BACKFILL]).accepted


def test_rls_grants_and_policies():
    text = PATH.read_text("utf-8")
    up, down = text.split("def downgrade")
    assert up.count("create_table(") == 3 and down.count("drop_table(") == 3
    assert "ENABLE ROW LEVEL SECURITY" in up and "app_current_user_id()" in up
    assert "{MEMBERS}_select_own ON public.{MEMBERS}" in up and "TO {OPS_ROLE}" in up
    # juli_app never writes the new tables, and never reads the invites
    assert "GRANT SELECT ON public.{BUSINESSES}, public.{MEMBERS} TO {APP_ROLE}" in up
    mod = _module(PATH, "m130p")
    assert "business_members bm" in mod._ACCESS and "shop_members m" in mod._ACCESS
    assert "AND bm.user_id = app_current_user_id()))" in mod._LEGACY_OWNER
    assert "BEFORE INSERT ON public.shops" in up and "SECURITY DEFINER" in up
    assert "_P93_MEMBER" in down


def test_backfill_maps_shops_members_and_sandbox_kind_and_sets_not_null():
    text = BACKFILL.read_text("utf-8")
    assert "INSERT INTO public.businesses" in text
    assert "'owner'" in text and "'member'" in text and "'backfill'" in text
    assert "capability = 'sandbox_write'" in text and "production_write_shops" in text
    assert "SET NOT NULL" in text
    # no shop id in the step: the sandbox shop is found from its credentials
    import re

    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)


def test_tables_are_classified_and_match_the_orm():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
    from juli_backend.orm_base import Base

    text = PATH.read_text("utf-8")
    assert TABLE_CLASSIFICATION_MAP[("public", "businesses")] == "non_tenant"
    assert TABLE_CLASSIFICATION_MAP[("public", "business_members")] == "non_tenant"
    assert TABLE_CLASSIFICATION_MAP[("public", "business_invites")] == "ops_only"
    for table in TABLES:
        assert table in Base.metadata.tables
        for column in Base.metadata.tables[table].columns.keys():
            assert f'"{column}"' in text, (table, column)
    shops = Base.metadata.tables["shops"].columns
    assert "business_id" in shops and "kind" in shops
