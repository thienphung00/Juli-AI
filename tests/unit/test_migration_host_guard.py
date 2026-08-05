"""Test migration host guard to prevent destructive operations against production.

Issue #734 — guard against running destructive migrations against non-local databases.
"""

from __future__ import annotations

import pytest

from tests.integration.test_migrations import _validate_destructive_db_url


class TestMigrationHostGuard:
    """Validates that destructive migration tests refuse non-local hosts."""

    def test_non_local_host_raises_error(self):
        """Non-local database URLs must raise an error, not skip silently."""
        url = "postgresql://user:pass@prod.example.com:5432/juli_prod"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    def test_non_local_host_error_names_resolved_host(self):
        """Error message must name the resolved host for operator clarity."""
        url = "postgresql://user:pass@prod.example.com:5432/juli_prod"
        with pytest.raises(RuntimeError) as exc_info:
            _validate_destructive_db_url(url)
        error_msg = str(exc_info.value)
        # Should mention the blast radius
        assert "drops all tables" in error_msg.lower()
        # Should reference the host (or resolved address)
        assert "prod.example.com" in error_msg or "host" in error_msg.lower()

    def test_localhost_passes(self):
        """localhost is a safe target."""
        url = "postgresql://user:pass@localhost:5432/juli_test"
        # Should not raise
        _validate_destructive_db_url(url)

    def test_127_0_0_1_passes(self):
        """127.0.0.1 (localhost IPv4) is a safe target."""
        url = "postgresql://user:pass@127.0.0.1:5432/juli_test"
        # Should not raise
        _validate_destructive_db_url(url)

    def test_unix_socket_path_passes(self):
        """Unix socket paths (no host) are safe for local Postgres."""
        url = "postgresql:////var/run/postgresql/postgresql.sock/juli_test"
        # Should not raise
        _validate_destructive_db_url(url)

    def test_unix_socket_relative_path_passes(self):
        """Relative unix socket paths are safe."""
        url = "postgresql:///./socket/juli_test"
        # Should not raise
        _validate_destructive_db_url(url)

    def test_explicit_opt_in_allows_non_local(self, monkeypatch):
        """ALLOW_DESTRUCTIVE_MIGRATION_TESTS=1 explicitly permits non-local targets."""
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_MIGRATION_TESTS", "1")
        url = "postgresql://user:pass@prod.example.com:5432/juli_prod"
        # Should not raise when opt-in is set
        _validate_destructive_db_url(url)

    def test_opt_in_false_does_not_permit_non_local(self, monkeypatch):
        """ALLOW_DESTRUCTIVE_MIGRATION_TESTS=0 is treated as false."""
        monkeypatch.setenv("ALLOW_DESTRUCTIVE_MIGRATION_TESTS", "0")
        url = "postgresql://user:pass@prod.example.com:5432/juli_prod"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    def test_password_in_url_not_confused_with_host(self):
        """Passwords containing 'localhost' must not fool the guard."""
        url = "postgresql://user:localhost_password@prod.example.com:5432/juli_prod"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    def test_hostname_localhost_substring_fails(self):
        """localhost.prod.example.com is NOT localhost."""
        url = "postgresql://user:pass@localhost.prod.example.com:5432/juli_prod"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    def test_ipv6_localhost_bracketed_passes(self):
        """IPv6 localhost [::1] with port is a safe target (AC2 requirement)."""
        url = "postgresql://[::1]:5432/juli_test"
        # Should not raise — this is a regression test for AC2 violation
        _validate_destructive_db_url(url)

    # Regression tests for adversarial inputs (coordinator verification)
    def test_adversarial_localhost_prod_subdomain_blocked(self):
        """localhost.prod.example.com must be BLOCKED (not allowed)."""
        url = "postgresql://u:p@localhost.prod.example.com:5432/db"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    def test_adversarial_production_internal_blocked(self):
        """db.production.internal must be BLOCKED."""
        url = "postgresql://u:p@db.production.internal:5432/db"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    def test_adversarial_sslocalhost_obfuscation_blocked(self):
        """sslocalhost@10.0.0.5 password obfuscation must be BLOCKED."""
        url = "postgresql://user:p@sslocalhost@10.0.0.5:5432/db"
        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ):
            _validate_destructive_db_url(url)

    # --- AC5 / AC6: the guard must be WIRED, not merely correct in isolation ---
    # Every test above exercises _validate_destructive_db_url as a pure function.
    # None of them prove the guard is actually invoked before a destructive path
    # becomes reachable. These two close that gap: they drive the real
    # pytest_configure hook, so removing the guard call from it, moving it into a
    # fixture, or renaming the hook fails the suite.

    def test_guard_runs_ahead_of_downgrade_via_pytest_configure(self, monkeypatch):
        """AC5: guard fires from pytest_configure, the earliest hook in the session.

        pytest_configure runs before collection, before any fixture, and therefore
        before postgres_at_head can create an engine or reach command.downgrade.
        """
        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@prod.example.com:5432/juli_prod")
        from tests.integration import conftest as integration_conftest

        with pytest.raises(
            RuntimeError, match="Destructive migration tests refuse non-local hosts"
        ) as exc_info:
            integration_conftest.pytest_configure(None)
        assert "prod.example.com" in str(exc_info.value)

    def test_existing_local_runs_unaffected_and_stay_green(self, monkeypatch):
        """AC6: a local DATABASE_URL passes configure untouched."""
        from tests.integration import conftest as integration_conftest

        monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/juli")
        integration_conftest.pytest_configure(None)

        monkeypatch.delenv("DATABASE_URL", raising=False)
        integration_conftest.pytest_configure(None)

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://user:pass@localhost:5432/juli",
            "postgresql://user:pass@127.0.0.1:5432/juli",
            "postgresql://[::1]:5432/juli",
            "postgresql:///var/run/postgresql/juli",
            "postgresql://user:pass@LOCALHOST:5432/juli",
        ],
    )
    def test_allow_localhost_loopback_and_unix_socket_by_default(self, url):
        """AC2: every local target form is permitted with no opt-in set."""
        _validate_destructive_db_url(url)
