"""Integration tests for safe-alembic-upgrade-local.sh against throwaway Postgres."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from juli_backend.core.config.runtime import sync_database_url

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
)
TEST_REV = "zzz_safe_alembic_local_delete"
TEST_MIGRATION = MIGRATIONS_DIR / f"{TEST_REV}_delete_test_users.py"


def _database_url() -> str:
    return os.environ.get("DATABASE_URL", "").strip()


def _postgres_reachable() -> bool:
    url = _database_url()
    if not url.startswith("postgresql"):
        return False
    try:
        engine = create_engine(
            sync_database_url(url), pool_pre_ping=True, connect_args={"connect_timeout": 3}
        )
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


requires_postgres = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="safe-alembic local integration tests require reachable Postgres DATABASE_URL",
)


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


@pytest.fixture
def repo_env_file(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"DATABASE_URL={_database_url()}\n", encoding="utf-8")
    return env_file


def _write_test_migration(*, allowlisted: bool) -> str:
    cfg = _alembic_config()
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(cfg).get_current_head()
    comment = (
        "    # safe-migrate: allow-decrease users\n" if allowlisted else ""
    )
    TEST_MIGRATION.write_text(
        textwrap.dedent(
            f'''\
            """Temporary test migration for safe-alembic-upgrade-local.sh."""
            from alembic import op

            revision = "{TEST_REV}"
            down_revision = "{head}"
            branch_labels = None
            depends_on = None

            {comment}
            def upgrade() -> None:
                op.execute(
                    "DELETE FROM users WHERE phone = '+84936507777'"
                )

            def downgrade() -> None:
                pass
            '''
        ),
        encoding="utf-8",
    )
    return head


def _remove_test_migration() -> None:
    TEST_MIGRATION.unlink(missing_ok=True)


def _seed_user(engine) -> None:
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, phone, display_name)
                VALUES (:id, :phone, :display_name)
                """
            ),
            {
                "id": user_id,
                "phone": "+84936507777",
                "display_name": "Safe Alembic Local Test",
            },
        )


DOCKER_PG_CONTAINER = os.environ.get("SAFE_ALEMBIC_PG_CONTAINER", "safe-alembic-pg")


def _docker_container_running(name: str) -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", name],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _pg_client_major_version(tool: str) -> int | None:
    path = shutil.which(tool)
    if path is None:
        return None
    result = subprocess.run([path, "--version"], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return None
    for token in result.stdout.split():
        head = token.split(".", maxsplit=1)[0]
        if head.isdigit():
            return int(head)
    return None


def _native_pg16_cli_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    for tool in ("pg_dump", "pg_restore"):
        if _pg_client_major_version(tool) != 16:
            pytest.skip(
                "pg_dump/pg_restore 16 required — start safe-alembic-pg container "
                "or install postgresql-client-16"
            )
    bin_dir = tmp_path_factory.mktemp("pg16cli")
    for tool in ("pg_dump", "pg_restore"):
        src = shutil.which(tool)
        assert src is not None
        (bin_dir / tool).symlink_to(src)
    return bin_dir


@pytest.fixture(scope="module")
def postgres16_cli(tmp_path_factory: pytest.TempPathFactory) -> Path:
    if not _docker_container_running(DOCKER_PG_CONTAINER):
        return _native_pg16_cli_dir(tmp_path_factory)

    bin_dir = tmp_path_factory.mktemp("pg16cli")

    pg_dump = bin_dir / "pg_dump"
    pg_dump.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
out=""
url=""
args=("$@")
for i in "${{!args[@]}}"; do
  case "${{args[i]}}" in
    -f) out="${{args[i+1]}}" ;;
    postgresql://*) url="${{args[i]}}" ;;
  esac
done
if [ -z "$out" ] || [ -z "$url" ]; then
  echo "pg_dump wrapper expects -f and a postgresql:// URL" >&2
  exit 1
fi
internal="${{url/localhost:5433/localhost:5432}}"
docker exec {DOCKER_PG_CONTAINER} pg_dump -Fc -f /tmp/safe-alembic-local.dump "$internal"
docker cp {DOCKER_PG_CONTAINER}:/tmp/safe-alembic-local.dump "$out"
""",
        encoding="utf-8",
    )
    pg_dump.chmod(0o755)
    return bin_dir


def _run_local_safe_upgrade(
    *,
    env: dict[str, str],
    backup_dir: Path,
    env_file: Path,
    pg_cli_dir: Path | None = None,
    extra_args: list[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = SCRIPTS_DIR / "safe-alembic-upgrade-local.sh"
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["RELEASE_DIR"] = str(REPO_ROOT)
    run_env["BACKUP_DIR"] = str(backup_dir)
    run_env["ENV_FILE"] = str(env_file)
    run_env["VENV_PYTHON"] = sys.executable
    alembic_bin = shutil.which("alembic")
    if not alembic_bin:
        pytest.skip("alembic CLI not on PATH")
    run_env["ALEMBIC_BIN"] = alembic_bin
    if pg_cli_dir is not None:
        run_env["PATH"] = f"{pg_cli_dir}:{run_env.get('PATH', '')}"
    run_env["PYTHONPATH"] = f"{SCRIPTS_DIR}:{run_env.get('PYTHONPATH', '')}"
    cmd = [str(script), *(extra_args or ["--yes"])]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=run_env,
        check=False,
    )


def _reset_database(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


@pytest.fixture
def postgres_at_head():
    cfg = _alembic_config()
    _remove_test_migration()
    engine = create_engine(sync_database_url(_database_url()), pool_pre_ping=True)
    _reset_database(engine)
    command.upgrade(cfg, "head")
    yield engine
    try:
        with engine.connect() as conn:
            current_rev = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        if current_rev == TEST_REV:
            command.downgrade(cfg, "-1")
    finally:
        _remove_test_migration()
        _reset_database(engine)
        engine.dispose()


@requires_postgres
def test_local_upgrade_aborts_on_unallowlisted_delete(
    postgres_at_head, repo_env_file: Path, tmp_path: Path, postgres16_cli: Path
):
    _seed_user(postgres_at_head)
    _write_test_migration(allowlisted=False)
    backup_dir = tmp_path / "backups"

    result = _run_local_safe_upgrade(
        env={"DATABASE_URL": _database_url()},
        backup_dir=backup_dir,
        env_file=repo_env_file,
        pg_cli_dir=postgres16_cli,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "REGRESSION" in combined or "protected-table regression" in combined
    assert "pg_restore" in combined
    assert "target database identity:" in combined
    dumps = list(backup_dir.glob("juli-pre-migrate-*.dump"))
    assert dumps, "expected backup file to be created before abort"


@requires_postgres
def test_local_upgrade_succeeds_on_empty_database(
    postgres_at_head, repo_env_file: Path, tmp_path: Path, postgres16_cli: Path
):
    backup_dir = tmp_path / "backups"

    result = _run_local_safe_upgrade(
        env={"DATABASE_URL": _database_url()},
        backup_dir=backup_dir,
        env_file=repo_env_file,
        pg_cli_dir=postgres16_cli,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "target database identity:" in (result.stdout + result.stderr)


def test_local_upgrade_non_interactive_without_yes_fails(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("DATABASE_URL=postgresql://u:p@localhost:5432/db\n", encoding="utf-8")
    script = SCRIPTS_DIR / "safe-alembic-upgrade-local.sh"
    result = subprocess.run(
        [str(script)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "RELEASE_DIR": str(REPO_ROOT),
            "ENV_FILE": str(env_file),
            "VENV_PYTHON": sys.executable,
            "PYTHONPATH": str(SCRIPTS_DIR),
        },
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Non-interactive session" in combined
    assert "--yes" in combined or "SAFE_MIGRATE_YES" in combined
