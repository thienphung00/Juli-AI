"""Unit tests for safe-alembic-upgrade helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from safe_alembic_helpers import (  # noqa: E402
    is_decrease_allowed,
    load_allowlist_file,
    scan_migration_comments,
)

ALLOWLIST = SCRIPTS_DIR / "safe-migrate-allowlist.txt"
MIGRATIONS_DIR = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
)


def test_load_allowlist_file_ignores_comments_and_blanks(tmp_path: Path):
    path = tmp_path / "allowlist.txt"
    path.write_text(
        "# comment\n\nabc123 users\n# another\n def456  shops \n",
        encoding="utf-8",
    )
    allowed = load_allowlist_file(path)
    assert ("abc123", "users") in allowed
    assert ("def456", "shops") in allowed


def test_scan_migration_comments_finds_allow_decrease(tmp_path: Path):
    migration = tmp_path / "001_test.py"
    migration.write_text(
        '''"""test"""
revision = "001_test"
down_revision = None

def upgrade():
    pass

# safe-migrate: allow-decrease users
''',
        encoding="utf-8",
    )
    allowed = scan_migration_comments(tmp_path, ["001_test"])
    assert ("001_test", "users") in allowed


def test_is_decrease_allowed_from_file(tmp_path: Path):
    allowlist = tmp_path / "allowlist.txt"
    allowlist.write_text("rev_a users\n", encoding="utf-8")
    assert is_decrease_allowed("users", ["rev_a"], allowlist, tmp_path)
    assert not is_decrease_allowed("shops", ["rev_a"], allowlist, tmp_path)


def test_is_decrease_allowed_from_migration_comment(tmp_path: Path):
    migration = tmp_path / "010_purge.py"
    migration.write_text(
        'revision = "010_purge"\n# safe-migrate: allow-decrease orders\n',
        encoding="utf-8",
    )
    assert is_decrease_allowed("orders", ["010_purge"], tmp_path / "missing.txt", tmp_path)


def test_compare_script_regression_exit_code():
    compare_script = SCRIPTS_DIR / "safe_alembic_compare.py"
    pre = json.dumps({"users": 5, "shops": 1})
    post = json.dumps({"users": 3, "shops": 1})
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            str(compare_script),
            "--pre",
            pre,
            "--post",
            post,
            "--revisions",
            '["missing_rev"]',
            "--allowlist-file",
            str(ALLOWLIST),
            "--migrations-dir",
            str(MIGRATIONS_DIR),
        ],
        capture_output=True,
        text=True,
        cwd=str(SCRIPTS_DIR),
        check=False,
    )
    assert result.returncode == 2
    assert "REGRESSION" in result.stdout
    assert "users" in result.stdout
