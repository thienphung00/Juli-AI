"""P100 E.7 migration 127 (``card_content_specs``): additive, reversible, append-only, the tail.

Shapes: ``fasttrack/contracts/p100-s2-demo.md`` "E.7 card specs". The Postgres half (RLS, grants,
checks, down / up) is ``tests/integration/test_card_content_specs_db.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from juli_backend.models.card_content_specs import SOURCES, SPEC_TYPES, CardContentSpec

REPO = Path(__file__).resolve().parents[2]
MIGRATIONS = REPO / "backend/src/juli_backend/database/migrations"
PATH = MIGRATIONS / "versions/127_card_content_specs.py"


def _migration():
    spec = importlib.util.spec_from_file_location("mig127", PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_migration_127_is_additive_reversible_and_the_tail():
    from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP

    mod = _migration()
    assert mod.revision == "127_card_content_specs" and len(mod.revision) <= 32
    assert mod.down_revision == "126_shopee_source_funnel"
    sys.path.insert(0, str(REPO / "infra/scripts"))
    from migration_additive_gate import evaluate_migration_paths

    result = evaluate_migration_paths([PATH])
    assert [f.render() for f in result.findings] == [] and result.accepted
    src = PATH.read_text("utf-8")
    up = src.split("def upgrade")[1].split("def downgrade")[0]
    for verb in ("UPDATE public", "DELETE FROM", "op.drop_table", "op.drop_column"):
        assert verb not in up, verb
    assert "ENABLE ROW LEVEL SECURITY" in src and "GRANT SELECT, INSERT ON" in src
    assert "UPDATE" not in mod._CLAUSES and "GRANT SELECT, INSERT, UPDATE" not in src
    assert TABLE_CLASSIFICATION_MAP[("public", "card_content_specs")] == "tenant_direct"
    tail = (MIGRATIONS / "deferred/101_write_mode_backfill.py").read_text("utf-8")
    assert 'down_revision: str | None = "127_card_content_specs"' in tail


def test_the_model_and_the_migration_agree():
    src = PATH.read_text("utf-8")
    for column in CardContentSpec.__table__.columns.keys():
        assert f'"{column}"' in src, column
    for value in (*SPEC_TYPES, *SOURCES):
        assert f"'{value}'" in src, value
    names = {c.name for c in CardContentSpec.__table__.constraints if c.name}
    names |= {i.name for i in CardContentSpec.__table__.indexes}
    for name in names - {"pk_card_content_specs"}:
        assert name in src, name
