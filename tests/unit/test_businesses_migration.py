"""Migration 130 (P101 W1 businesses): static checks, grants, the ORM, the automatic backfill."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
PATH = MIGRATIONS / "versions/130_businesses.py"
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
    # The backfill is a worker job now (owner rule T2), never a deferred alembic step.
    assert not (MIGRATIONS / "deferred/130_businesses_backfill.py").exists()


def test_single_head_descends_from_130():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(REPO / "alembic.ini")))
    assert len(script.get_heads()) == 1
    ancestry = {r.revision for r in script.walk_revisions(base="base", head="head")}
    assert "130_businesses" in ancestry


def test_the_migration_passes_the_additive_gate():
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([PATH])
    assert [f.render() for f in result.findings] == [] and result.accepted


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


def test_backfill_function_maps_shops_members_and_sandbox_kind():
    text = PATH.read_text("utf-8")
    body = text[text.index("businesses_backfill_batch(p_limit integer)") :]
    body = body[: body.index("$fn$;")]
    assert "INSERT INTO public.businesses" in body and "FOR UPDATE SKIP LOCKED" in body
    assert "'owner'" in body and "'member'" in body and "'backfill'" in body
    assert "capability = 'sandbox_write'" in body and "production_write_shops" in body
    assert "m.removed_at IS NULL" in body  # a removed person is never re-added
    # NOT NULL as a CHECK added NOT VALID then validated, only once no NULL is left
    assert "CHECK (business_id IS NOT NULL) NOT VALID" in text
    assert "VALIDATE CONSTRAINT" in text and "SET NOT NULL" not in text
    # no shop id anywhere: the sandbox shop is found from its credentials
    import re

    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)


def test_grant_shape_juli_ops_reads_shops_only_through_functions():
    """2026-11-15: ``members_of_shop_business`` read ``shops.business_id`` as ``juli_ops`` and
    Postgres answered ``permission denied for table shops`` -- juli_ops holds no grant on shops
    (083 / 110: Ops reads shops only through reviewed SECURITY DEFINER functions)."""
    import re

    mod = _module(PATH, "m130g")
    text = PATH.read_text("utf-8")
    up = text.split("def downgrade")[0]
    assert not re.search(r"GRANT [A-Z, ]+ ON (TABLE )?public\.shops\b", up)
    assert set(mod.OPS_FUNCTIONS) == {
        "public.ops_shop_business(uuid)",
        "public.ops_business_first_shop(uuid)",
        "public.businesses_backfill_batch(integer)",
        "public.businesses_require_shop_business()",
    }
    assert 'f"GRANT EXECUTE ON FUNCTION {fn} TO {OPS_ROLE}"' in up
    assert 'f"REVOKE ALL ON FUNCTION {fn} FROM PUBLIC"' in up
    for fn in mod.OPS_FUNCTIONS:
        name = fn.split("(")[0]
        assert f"CREATE OR REPLACE FUNCTION {name}(" in up and "SECURITY DEFINER" in up
    # juli_app's shops grants are table-level, so they already cover business_id and kind
    granted = (MIGRATIONS / "versions/043_juli_app_role.py").read_text("utf-8")
    assert '"shops": ("SELECT", "INSERT"),' in granted
    update = (MIGRATIONS / "versions/058_juli_app_update_grants.py").read_text("utf-8")
    assert '"shops": ("UPDATE",)' in update
    for path in sorted((MIGRATIONS / "versions").glob("*.py")):
        assert not re.search(r"ON public\.shops\s*\(", path.read_text("utf-8")), path.name


def test_the_service_reads_shops_as_juli_ops_only_through_the_functions():
    source = (REPO / "backend/src/juli_backend/services/businesses/service.py").read_text("utf-8")
    assert "public.ops_shop_business(" in source and "public.ops_business_first_shop(" in source
    for block in source.split("async with ops_role(session):")[1:]:
        head = block.split("\n\n")[0]
        assert "select(Shop" not in head, head


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


async def test_the_backfill_job_does_nothing_on_sqlite(session):
    from juli_backend.services.businesses.backfill import run_backfill

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc):
            return False

    result = await run_backfill(_Factory())
    assert result.skipped == "sqlite" and result.shops == 0


def test_the_backfill_job_is_registered_scheduled_and_runs_at_worker_start():
    from celery.signals import worker_ready

    from juli_backend.workers.celery_app import celery_app
    from juli_backend.workers.tasks import businesses_backfill as task_module

    entry = celery_app.conf.beat_schedule["businesses-backfill"]
    assert (
        entry["task"] == task_module.BUSINESSES_BACKFILL_TASK == "juli_backend.businesses_backfill"
    )
    assert sorted(entry["schedule"].minute) == [6, 16, 26, 36, 46, 56]
    receivers = [r[1]() for r in worker_ready.receivers]
    assert task_module._backfill_at_worker_start in receivers
