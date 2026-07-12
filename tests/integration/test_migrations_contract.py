"""Contract checks for Alembic migration integration test wiring — Issue #365."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
INTEGRATION_DIR = REPO_ROOT / "tests" / "integration"
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"


def test_migrations_module_lives_under_tests_integration():
    """New test file lives in tests/integration/test_migrations.py."""
    path = INTEGRATION_DIR / "test_migrations.py"
    assert path.is_file(), f"missing {path}"


def test_pr_test_job_provisions_postgres_database_url_for_migrations():
    """Test runs in the CI test job (Postgres service via DATABASE_URL)."""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")
    assert "DATABASE_URL: postgresql://postgres:test@localhost:5432/test_db" in workflow


def test_uses_same_postgres_connection_pattern_from_database_url_environment(monkeypatch):
    """Uses the same Postgres connection pattern as other integration tests (env DATABASE_URL)."""
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://postgres:test@localhost:5432/test_db",
    )

    from tests.integration import test_migrations

    url = test_migrations.sync_database_url(test_migrations._database_url())
    assert url == test_migrations._alembic_config().get_main_option("sqlalchemy.url")


def test_migration_integration_skips_when_postgres_unavailable(monkeypatch):
    """Tests skip when DATABASE_URL is not a reachable Postgres instance."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    from tests.integration import test_migrations

    assert test_migrations._postgres_reachable() is False
