"""Tests for worker task database URL conversion (issue #741).

Ensures all worker tasks convert sync DATABASE_URL to async asyncpg form
before passing to create_async_engine, and that the sqlite fallback still works.
"""

import ast
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

    def test_getenv_database_url_only_in_database_helper(self):
        """Ensure os.getenv("DATABASE_URL") only appears in database.py.

        Within workers/tasks/, os.getenv("DATABASE_URL") is ONLY allowed in
        database.py (the shared helper). Any other module using it directly
        is a regression (AC5).

        Uses AST parsing to catch violations regardless of formatting,
        annotations, line breaks, or comments. This catches both:
        - Direct calls: os.getenv("DATABASE_URL", ...)
        - Indirect returns: def _database_url() -> str: return os.getenv(...)
        """
        workers_dir = (
            Path(__file__).parent.parent.parent
            / "backend"
            / "src"
            / "juli_backend"
            / "workers"
            / "tasks"
        )

        violations = []

        for task_file in sorted(workers_dir.glob("*.py")):
            # Only check real task modules (not private __init__.py or underscore-prefixed)
            if task_file.name.startswith("_") or task_file.name == "__init__.py":
                continue

            # database.py is the allowed location for os.getenv("DATABASE_URL")
            if task_file.name == "database.py":
                continue

            try:
                tree = ast.parse(task_file.read_text())
            except SyntaxError:
                continue

            # Walk AST looking for os.getenv("DATABASE_URL") calls
            for node in ast.walk(tree):
                # Pattern: os.getenv("DATABASE_URL", ...)
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "getenv"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "os"
                    and len(node.args) >= 1
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "DATABASE_URL"
                ):
                    violations.append(f"{task_file.name}: os.getenv('DATABASE_URL') call found")

        assert not violations, "DATABASE_URL must not appear outside database.py:\n" + "\n".join(
            violations
        )
