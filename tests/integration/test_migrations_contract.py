"""Behavioral helpers for Alembic migration integration tests — Issue #365.

File-existence / pr.yml substring checks removed (ADR-040 lean-out #4).
"""

from __future__ import annotations


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
