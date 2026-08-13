"""Exactly one Alembic head after Wave 1 — issue #996 (W1 close), acceptance criterion 3.

No migrations are expected in Wave 1 (the tool registry, sanitizer, and LLM service
slices are all pure Python — none touch `models/models.py` or
`database/migrations/`). This asserts that, rather than assuming it: a second head
would mean two migration branches exist that Alembic cannot linearly order, and that
must fail loudly here rather than surface later as a deploy-time surprise.

Pure filesystem introspection of the migration scripts directory — no database
connection, so this runs in every tier (not `migration_heavy`, which is reserved for
seeded round-trips against a real Postgres instance).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"


def _script_directory() -> ScriptDirectory:
    cfg = Config(str(ALEMBIC_INI))
    return ScriptDirectory.from_config(cfg)


def test_exactly_one_alembic_head_after_wave_1():
    heads = _script_directory().get_heads()
    assert len(heads) == 1, (
        f"expected exactly one Alembic head after Wave 1, found {len(heads)}: {heads!r} "
        "— Wave 1 (tool registry / sanitizer / LLM service) introduces no migrations, "
        "so a second head here means an unresolved migration branch."
    )


def test_get_current_head_agrees_with_the_single_head():
    """`get_current_head()` raises on multiple heads — a second, independent
    confirmation of the single-head invariant above, via a different Alembic API."""
    script = _script_directory()
    assert script.get_current_head() == script.get_heads()[0]
