"""Tests for worker task database URL conversion (issue #741).

Ensures all worker tasks convert sync DATABASE_URL to async asyncpg form
before passing to create_async_engine, and that the sqlite fallback still works.
"""

import re
from pathlib import Path


class TestSharedDatabaseURLHelper:
    """Test the shared get_async_database_url helper."""

    def test_shared_helper_converts_postgres_to_asyncpg(self, monkeypatch):
        """Test that get_async_database_url converts postgresql to asyncpg."""
        from juli_backend.workers.tasks.database import get_async_database_url

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
        result = get_async_database_url()
        assert result.startswith("postgresql+asyncpg://"), f"Expected asyncpg form, got: {result}"

    def test_shared_helper_fallback_sqlite(self, monkeypatch):
        """Test that get_async_database_url falls back to sqlite when DATABASE_URL unset."""
        from juli_backend.workers.tasks.database import get_async_database_url

        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = get_async_database_url()
        assert result == "sqlite+aiosqlite:///:memory:"


class TestDatabaseURLConversion:
    """Test database URL conversion in worker tasks."""

    def test_mock_analytics_reconcile_database_url_with_postgres(self, monkeypatch):
        """Test that mock_analytics_reconcile._database_url() converts postgresql to asyncpg."""
        from juli_backend.workers.tasks.mock_analytics_reconcile import _database_url

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
        result = _database_url()
        assert result.startswith("postgresql+asyncpg://"), f"Expected asyncpg form, got: {result}"

    def test_mock_analytics_reconcile_database_url_fallback_sqlite(self, monkeypatch):
        """Test that mock_analytics_reconcile._database_url() falls back to sqlite."""
        from juli_backend.workers.tasks.mock_analytics_reconcile import _database_url

        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = _database_url()
        assert result == "sqlite+aiosqlite:///:memory:"

    def test_material_analytics_precompute_database_url_with_postgres(self, monkeypatch):
        """Test material_analytics_precompute._database_url() converts postgresql to asyncpg."""
        from juli_backend.workers.tasks.material_analytics_precompute import _database_url

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
        result = _database_url()
        assert result.startswith("postgresql+asyncpg://"), f"Expected asyncpg form, got: {result}"

    def test_material_analytics_precompute_database_url_fallback_sqlite(self, monkeypatch):
        """Test material_analytics_precompute._database_url() falls back to sqlite."""
        from juli_backend.workers.tasks.material_analytics_precompute import _database_url

        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = _database_url()
        assert result == "sqlite+aiosqlite:///:memory:"

    def test_tool_execution_database_url_with_postgres(self, monkeypatch):
        """Test that tool_execution._database_url() converts postgresql to asyncpg."""
        from juli_backend.workers.tasks.tool_execution import _database_url

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
        result = _database_url()
        assert result.startswith("postgresql+asyncpg://"), f"Expected asyncpg form, got: {result}"

    def test_tool_execution_database_url_fallback_sqlite(self, monkeypatch):
        """Test that tool_execution._database_url() falls back to sqlite when DATABASE_URL unset."""
        from juli_backend.workers.tasks.tool_execution import _database_url

        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = _database_url()
        assert result == "sqlite+aiosqlite:///:memory:"

    def test_action_card_refresh_database_url_with_postgres(self, monkeypatch):
        """Test that action_card_refresh._database_url() converts postgresql to asyncpg."""
        from juli_backend.workers.tasks.action_card_refresh import _database_url

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/db")
        result = _database_url()
        assert result.startswith("postgresql+asyncpg://"), f"Expected asyncpg form, got: {result}"

    def test_action_card_refresh_database_url_fallback_sqlite(self, monkeypatch):
        """Test action_card_refresh._database_url() falls back to sqlite."""
        from juli_backend.workers.tasks.action_card_refresh import _database_url

        monkeypatch.delenv("DATABASE_URL", raising=False)
        result = _database_url()
        assert result == "sqlite+aiosqlite:///:memory:"


class TestWorkerDatabaseURLContract:
    """Contract test for unconverted DATABASE_URL usage in worker modules."""

    def test_no_unconverted_database_url_passed_to_create_async_engine(self):
        """Scan worker task modules for unconverted DATABASE_URL usage.

        Prevents regression from new tasks bypassing async_database_url() conversion.
        """
        workers_dir = (
            Path(__file__).parent.parent.parent
            / "backend"
            / "src"
            / "juli_backend"
            / "workers"
            / "tasks"
        )

        # Find all .py files in the workers/tasks directory
        task_files = sorted(workers_dir.glob("*.py"))

        violations = []

        for task_file in task_files:
            # Skip __init__.py and other utility files
            if task_file.name.startswith("_"):
                continue

            content = task_file.read_text()

            # Look for the problematic pattern:
            # create_async_engine(...os.getenv("DATABASE_URL"...)
            # We want to catch cases where create_async_engine is called with:
            # - os.getenv("DATABASE_URL", ...) directly, OR
            # - a _database_url() that returns os.getenv("DATABASE_URL", ...)
            #
            # Check 1: create_async_engine called with os.getenv directly
            if re.search(r'create_async_engine\s*\(\s*os\.getenv\s*\(\s*"DATABASE_URL"', content):
                msg = (
                    f"{task_file.name}: create_async_engine called with "
                    "os.getenv('DATABASE_URL') directly"
                )
                violations.append(msg)

            # Check 2: _database_url() function that returns os.getenv without conversion
            # Look for pattern: def _database_url(): return os.getenv("DATABASE_URL", ...)
            if re.search(
                r'def\s+_database_url\s*\(\s*\)\s*:\s*return\s+os\.getenv\s*\(\s*"DATABASE_URL"',
                content,
            ):
                msg = (
                    f"{task_file.name}: _database_url() returns unconverted "
                    "os.getenv('DATABASE_URL')"
                )
                violations.append(msg)

        assert not violations, (
            "Found unconverted DATABASE_URL usage in worker tasks:\n" + "\n".join(violations)
        )
