"""Integration tests for safe-alembic-upgrade.sh against throwaway Postgres."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.database.token_crypto import ENCRYPTED_TOKEN_PREFIX, encrypt_token

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
ALEMBIC_INI = REPO_ROOT / "alembic.ini"
MIGRATIONS_DIR = (
    REPO_ROOT / "backend/src/juli_backend/database/migrations/versions"
)
TEST_REV = "zzz_safe_alembic_test_delete"
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
    reason="safe-alembic integration tests require reachable Postgres DATABASE_URL",
)


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


@pytest.fixture
def release_layout(tmp_path: Path):
    env_file = tmp_path / "api.env"
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
            """Temporary test migration for safe-alembic-upgrade.sh."""
            from alembic import op

            revision = "{TEST_REV}"
            down_revision = "{head}"
            branch_labels = None
            depends_on = None

            {comment}
            def upgrade() -> None:
                op.execute(
                    "DELETE FROM users WHERE phone = '+84936509999'"
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
                "phone": "+84936509999",
                "display_name": "Safe Alembic Test",
            },
        )


def _seed_encrypted_credential(engine) -> None:
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    cred_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    token = encrypt_token("integration-test-access-token")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, phone, display_name)
                VALUES (:id, :phone, :display_name)
                """
            ),
            {"id": user_id, "phone": "+84936508888", "display_name": "Cred User"},
        )
        conn.execute(
            text(
                """
                INSERT INTO shops (id, user_id, shop_name, tiktok_shop_id, is_active)
                VALUES (:id, :user_id, :shop_name, :tiktok_shop_id, :is_active)
                """
            ),
            {
                "id": shop_id,
                "user_id": user_id,
                "shop_name": "Cred Shop",
                "tiktok_shop_id": "safe_alembic_shop",
                "is_active": True,
            },
        )
        conn.execute(
            text(
                """
                INSERT INTO tiktok_credentials (
                    id, shop_id, access_token, refresh_token, token_expires_at
                )
                VALUES (:id, :shop_id, :access_token, :refresh_token, :token_expires_at)
                """
            ),
            {
                "id": cred_id,
                "shop_id": shop_id,
                "access_token": token,
                "refresh_token": f"{ENCRYPTED_TOKEN_PREFIX}dummy",
                "token_expires_at": now,
            },
        )


DOCKER_PG_CONTAINER = os.environ.get("SAFE_ALEMBIC_PG_CONTAINER", "safe-alembic-pg")


def _docker_pg_url(raw_url: str) -> str:
    """Map host-mapped Postgres URL to in-container localhost URL."""
    return raw_url.replace("@localhost:5433/", "@localhost:5432/")


@pytest.fixture(scope="module")
def postgres16_cli(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Wrap pg_dump/pg_restore via the Postgres 16 container (version-matched)."""
    if shutil.which("docker") is None:
        pytest.skip("docker required for version-matched pg_dump/pg_restore")
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
docker exec {DOCKER_PG_CONTAINER} pg_dump -Fc -f /tmp/safe-alembic.dump "$internal"
docker cp {DOCKER_PG_CONTAINER}:/tmp/safe-alembic.dump "$out"
""",
        encoding="utf-8",
    )
    pg_dump.chmod(0o755)

    pg_restore = bin_dir / "pg_restore"
    pg_restore.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
url=""
file=""
args=("$@")
for i in "${{!args[@]}}"; do
  case "${{args[i]}}" in
    -d) url="${{args[i+1]}}" ;;
    postgresql://*) url="${{args[i]}}" ;;
  esac
done
for arg in "$@"; do
  if [[ "$arg" == *.dump ]]; then
    file="$arg"
  fi
done
if [ -z "$url" ] || [ -z "$file" ]; then
  echo "pg_restore wrapper expects -d URL and a .dump file" >&2
  exit 1
fi
internal="${{url/localhost:5433/localhost:5432}}"
docker cp "$file" {DOCKER_PG_CONTAINER}:/tmp/safe-alembic-restore.dump
docker exec {DOCKER_PG_CONTAINER} pg_restore --no-owner --no-acl -d "$internal" --clean --if-exists /tmp/safe-alembic-restore.dump
""",
        encoding="utf-8",
    )
    pg_restore.chmod(0o755)
    return bin_dir


def _run_safe_upgrade(
    *,
    env: dict[str, str],
    backup_dir: Path,
    release_dir: Path,
    api_env_file: Path,
    pg_cli_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    script = SCRIPTS_DIR / "safe-alembic-upgrade.sh"
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["RELEASE_DIR"] = str(release_dir)
    run_env["BACKUP_DIR"] = str(backup_dir)
    run_env["API_ENV_FILE"] = str(api_env_file)
    run_env["VENV_PYTHON"] = sys.executable
    alembic_bin = shutil.which("alembic")
    if not alembic_bin:
        pytest.skip("alembic CLI not on PATH")
    run_env["ALEMBIC_BIN"] = alembic_bin
    if pg_cli_dir is not None:
        run_env["PATH"] = f"{pg_cli_dir}:{run_env.get('PATH', '')}"
    run_env["PYTHONPATH"] = f"{SCRIPTS_DIR}:{run_env.get('PYTHONPATH', '')}"
    return subprocess.run(
        [str(script)],
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
def test_safe_upgrade_aborts_on_unallowlisted_delete(
    postgres_at_head, release_layout: Path, tmp_path: Path, postgres16_cli: Path
):
    _seed_user(postgres_at_head)
    _write_test_migration(allowlisted=False)
    backup_dir = tmp_path / "backups"

    result = _run_safe_upgrade(
        env={"DATABASE_URL": _database_url()},
        backup_dir=backup_dir,
        release_dir=REPO_ROOT,
        api_env_file=release_layout,
        pg_cli_dir=postgres16_cli,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "REGRESSION" in combined or "protected-table regression" in combined
    assert "pg_restore" in combined
    dumps = list(backup_dir.glob("juli-pre-migrate-*.dump"))
    assert dumps, "expected backup file to be created before abort"


@requires_postgres
def test_safe_upgrade_allows_listed_delete_via_migration_comment(
    postgres_at_head, release_layout: Path, tmp_path: Path, postgres16_cli: Path
):
    _seed_user(postgres_at_head)
    _write_test_migration(allowlisted=True)
    backup_dir = tmp_path / "backups"

    result = _run_safe_upgrade(
        env={"DATABASE_URL": _database_url()},
        backup_dir=backup_dir,
        release_dir=REPO_ROOT,
        api_env_file=release_layout,
        pg_cli_dir=postgres16_cli,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with postgres_at_head.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM users WHERE phone = '+84936509999'")
        ).scalar_one()
    assert count == 0


@requires_postgres
def test_restore_command_restores_deleted_rows(
    postgres_at_head, release_layout: Path, tmp_path: Path, postgres16_cli: Path
):
    _seed_user(postgres_at_head)
    _write_test_migration(allowlisted=False)
    backup_dir = tmp_path / "backups"

    result = _run_safe_upgrade(
        env={"DATABASE_URL": _database_url()},
        backup_dir=backup_dir,
        release_dir=REPO_ROOT,
        api_env_file=release_layout,
        pg_cli_dir=postgres16_cli,
    )
    assert result.returncode != 0

    dump_file = next(backup_dir.glob("juli-pre-migrate-*.dump"))
    restore = subprocess.run(
        [
            str(postgres16_cli / "pg_restore"),
            "--no-owner",
            "--no-acl",
            "-d",
            sync_database_url(_database_url()),
            "--clean",
            "--if-exists",
            str(dump_file),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{postgres16_cli}:{os.environ.get('PATH', '')}"},
    )
    assert restore.returncode == 0, restore.stderr

    with postgres_at_head.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM users WHERE phone = '+84936509999'")
        ).scalar_one()
    assert count == 1


@requires_postgres
def test_disk_space_preflight_aborts_before_migration(
    postgres_at_head, release_layout: Path, tmp_path: Path, postgres16_cli: Path
):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    # Force required bytes above available by setting a huge margin.
    result = _run_safe_upgrade(
        env={
            "DATABASE_URL": _database_url(),
            "DISK_MARGIN_MB": "9999999",
        },
        backup_dir=backup_dir,
        release_dir=REPO_ROOT,
        api_env_file=release_layout,
        pg_cli_dir=postgres16_cli,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "insufficient disk space" in combined
    assert not list(backup_dir.glob("juli-pre-migrate-*.dump"))


@requires_postgres
def test_token_decrypt_check_passes_with_valid_credential(
    postgres_at_head, release_layout: Path, tmp_path: Path, postgres16_cli: Path
):
    key = Fernet.generate_key().decode()
    os.environ["TIKTOK_TOKEN_ENCRYPTION_KEY"] = key
    release_layout.write_text(
        f"DATABASE_URL={_database_url()}\nTIKTOK_TOKEN_ENCRYPTION_KEY={key}\n",
        encoding="utf-8",
    )
    _seed_encrypted_credential(postgres_at_head)

    backup_dir = tmp_path / "backups"
    result = _run_safe_upgrade(
        env={
            "DATABASE_URL": _database_url(),
            "TIKTOK_TOKEN_ENCRYPTION_KEY": key,
        },
        backup_dir=backup_dir,
        release_dir=REPO_ROOT,
        api_env_file=release_layout,
        pg_cli_dir=postgres16_cli,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "decrypt ok" in (result.stdout + result.stderr)
