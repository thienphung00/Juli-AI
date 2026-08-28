"""The juli_app downgrade survives a grant it cannot reach (#1405).

A ROLE is cluster-wide. `DROP OWNED BY` is database-local (it also covers
*shared* objects — databases, tablespaces — but never another database's tables).
A migration runs in ONE database, so if a sibling database in the same cluster
holds a grant on `juli_app`, `DROP ROLE juli_app` fails and the migration cannot
do anything about it.

Before #1405 that failure aborted the whole downgrade. Because
`command.downgrade` runs the chain as a single transaction, the abort rolled
everything back and left the database **at head with every table present**,
while the caller carried on as though it had reached base. The next operation
then hit `workflow_runs` still carrying W7's foreign keys:

    cannot drop table workflow_runs because other objects depend on it
    DETAIL: production_write_authorizations_consumed_by_run_id_fkey
            production_write_audit_run_id_fkey

That is how one unreachable grant became 19 failing schema tests in
`full-regression`, and why it only ever reproduced there: it needs a second
database in the cluster, which a single-file test run never creates.

This test builds that condition on purpose. Without the fix it fails on the
downgrade; with the fix the downgrade completes, `alembic_version` is empty,
and the role is deliberately left behind — NOLOGIN, owning nothing, with every
privilege it held *here* already removed. A stranded NOLOGIN role is strictly
safer than a downgrade that reports success from head.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.migration_heavy

REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _sync_url(url: str) -> str:
    from juli_backend.core.config.runtime import sync_database_url

    return sync_database_url(url)


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            _sync_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Requires a reachable local Postgres DATABASE_URL",
)


def _assert_local_database_url(url: str) -> None:
    """Same discipline as the other migration tests (#734): only ever downgrade
    a throwaway local database."""
    hostname = urlparse(url).hostname
    if hostname is not None and hostname.lower() not in _LOCAL_HOSTS:
        raise RuntimeError(
            "Refusing a destructive Alembic downgrade against a non-local "
            f"DATABASE_URL host ({hostname})."
        )


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(REPO_ROOT / "backend/src/juli_backend/database/migrations"),
    )
    cfg.set_main_option("sqlalchemy.url", _sync_url(_database_url()))
    return cfg


def _url_for_database(url: str, dbname: str) -> str:
    parts = urlparse(_sync_url(url))
    return urlunparse(parts._replace(path=f"/{dbname}"))


@pytest.fixture
def sibling_database_holding_a_grant():
    """A second database in the same cluster that grants juli_app a privilege
    the migration's `DROP OWNED BY` cannot reach."""
    url = _database_url()
    _assert_local_database_url(url)
    sibling = f"juli_xdb_{uuid.uuid4().hex[:12]}"

    admin = create_engine(_sync_url(url), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{sibling}"'))
    admin.dispose()

    try:
        sib = create_engine(_url_for_database(url, sibling), isolation_level="AUTOCOMMIT")
        with sib.connect() as conn:
            # The role must exist before it can be granted to; the migration
            # under test creates it, so create it here only if absent.
            conn.execute(
                text(
                    "DO $$ BEGIN IF NOT EXISTS ("
                    "SELECT 1 FROM pg_roles WHERE rolname='juli_app') "
                    "THEN CREATE ROLE juli_app NOLOGIN; END IF; END $$;"
                )
            )
            conn.execute(text("CREATE TABLE unreachable_by_the_migration (id int)"))
            conn.execute(text("GRANT SELECT ON unreachable_by_the_migration TO juli_app"))
        sib.dispose()
        yield sibling
    finally:
        # Drop the dependent object first, then the database, so the cluster is
        # left able to drop juli_app again.
        try:
            sib = create_engine(_url_for_database(url, sibling), isolation_level="AUTOCOMMIT")
            with sib.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS unreachable_by_the_migration"))
            sib.dispose()
        except Exception:
            pass
        admin = create_engine(_sync_url(url), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{sibling}" WITH (FORCE)'))
        admin.dispose()


@requires_postgres
def test_downgrade_to_base_completes_when_a_sibling_database_holds_a_grant(
    sibling_database_holding_a_grant,
):
    """The whole point: the downgrade must REACH base, not roll back to head.

    Asserting on `alembic_version` being empty rather than on the absence of an
    exception is deliberate — the pre-fix failure mode was a transaction that
    rolled back to head, and a caller that believed it was at base. An assertion
    on the exception alone would not have caught that.
    """
    from alembic import command

    _assert_local_database_url(_database_url())
    cfg = _alembic_config()
    engine = create_engine(_sync_url(_database_url()))

    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        with engine.connect() as conn:
            versions = conn.execute(
                text(
                    "SELECT count(*) FROM information_schema.tables "
                    "WHERE table_name = 'alembic_version'"
                )
            ).scalar_one()
            if versions:
                remaining = conn.execute(text("SELECT count(*) FROM alembic_version")).scalar_one()
                assert remaining == 0, (
                    "downgrade did not reach base — alembic_version still has a row, "
                    "which means the chain rolled back and the database is at head"
                )

            for table in (
                "workflow_runs",
                "production_write_authorizations",
                "production_write_audit",
            ):
                assert (
                    conn.execute(
                        text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}
                    ).scalar_one()
                    is None
                ), f"{table} survived a downgrade that claimed to reach base"
    finally:
        engine.dispose()


@requires_postgres
def test_the_role_is_kept_rather_than_the_downgrade_failing(
    sibling_database_holding_a_grant,
):
    """Keeping a NOLOGIN role is the deliberate trade, so pin it.

    If someone later 'fixes' this by force-dropping the role, they would be
    dropping a cluster-wide object still in use by another database. This test
    says that is not the intended behaviour.
    """
    from alembic import command

    _assert_local_database_url(_database_url())
    cfg = _alembic_config()
    engine = create_engine(_sync_url(_database_url()))

    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")

        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'juli_app'")
            ).fetchone()
            assert row is not None, (
                "juli_app was dropped even though another database still "
                "depends on it — that drop cannot have been safe"
            )
            assert row[0] is False, "a retained juli_app must remain NOLOGIN"
    finally:
        engine.dispose()


def test_downgrade_tolerates_the_one_error_it_cannot_prevent():
    """Source-level guard, so the intent survives even where no Postgres runs."""
    migration = (
        REPO_ROOT / "backend/src/juli_backend/database/migrations/versions/043_juli_app_role.py"
    )
    text_ = migration.read_text(encoding="utf-8")
    assert "dependent_objects_still_exist" in text_, (
        "the downgrade must tolerate a cross-database dependency it cannot reach; "
        "without this it aborts the chain and silently leaves the database at head"
    )
    assert "DROP OWNED BY" in text_, (
        "the downgrade must still remove every privilege the role holds in THIS database"
    )
