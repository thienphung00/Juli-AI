"""Doc contract tests for local safe-alembic wrapper (#420)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_readme_local_setup_uses_safe_alembic_local_wrapper_not_bare_upgrade():
    """README and backend README must not document a bare alembic upgrade head."""
    for rel in ("README.md", "backend/README.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "safe-alembic-upgrade-local.sh" in text, rel
        assert "alembic upgrade head" not in text, rel
