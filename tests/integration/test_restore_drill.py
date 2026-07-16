"""Integration tests for restore-drill.sh against throwaway Postgres."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
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
    reason="restore-drill integration tests require reachable Postgres DATABASE_URL",
)


def _alembic_config() -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", sync_database_url(_database_url()))
    return cfg


def _reset_database(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))


def _seed_encrypted_credential(engine) -> None:
    user_id = uuid.uuid4()
    shop_id = uuid.uuid4()
    cred_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    token = encrypt_token("restore-drill-integration-token")

    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO users (id, phone, display_name)
                VALUES (:id, :phone, :display_name)
                """
            ),
            {"id": user_id, "phone": "+84936506666", "display_name": "Restore Drill User"},
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
                "shop_name": "Restore Drill Shop",
                "tiktok_shop_id": "restore_drill_shop",
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
    for tool in ("pg_dump", "pg_restore", "psql"):
        if _pg_client_major_version(tool) != 16:
            pytest.skip(
                "pg_dump/pg_restore/psql 16 required — start safe-alembic-pg container "
                "or install postgresql-client-16"
            )
    bin_dir = tmp_path_factory.mktemp("pg16cli")
    for tool in ("pg_dump", "pg_restore", "psql"):
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
docker exec {DOCKER_PG_CONTAINER} pg_dump -Fc -f /tmp/restore-drill.dump "$internal"
docker cp {DOCKER_PG_CONTAINER}:/tmp/restore-drill.dump "$out"
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
docker cp "$file" {DOCKER_PG_CONTAINER}:/tmp/restore-drill-restore.dump
docker exec {DOCKER_PG_CONTAINER} pg_restore --no-owner --no-acl -d "$internal" --clean --if-exists /tmp/restore-drill-restore.dump
""",
        encoding="utf-8",
    )
    pg_restore.chmod(0o755)

    psql = bin_dir / "psql"
    psql.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
url=""
sql=""
args=("$@")
for i in "${{!args[@]}}"; do
  case "${{args[i]}}" in
    -d) url="${{args[i+1]}}" ;;
    -c) sql="${{args[i+1]}}" ;;
    postgresql://*) url="${{args[i]}}" ;;
  esac
done
if [ -z "$url" ] || [ -z "$sql" ]; then
  echo "psql wrapper expects -d URL and -c SQL" >&2
  exit 1
fi
internal="${{url/localhost:5433/localhost:5432}}"
docker exec {DOCKER_PG_CONTAINER} psql -d "$internal" -c "$sql"
""",
        encoding="utf-8",
    )
    psql.chmod(0o755)
    return bin_dir


def _admin_url() -> str:
    helper = SCRIPTS_DIR / "safe_alembic_helpers.py"
    result = subprocess.run(
        [sys.executable, str(helper), "admin-db-url"],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "DATABASE_URL": _database_url(),
            "PYTHONPATH": str(SCRIPTS_DIR),
        },
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _list_scratch_databases(psql_bin: Path | None = None) -> list[str]:
    admin = _admin_url()
    psql = str(psql_bin or shutil.which("psql") or "")
    if not psql:
        pytest.skip("psql not on PATH")
    result = subprocess.run(
        [
            psql,
            admin,
            "-At",
            "-c",
            "SELECT datname FROM pg_database WHERE datname LIKE 'juli_restore_drill_%'",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _run_restore_drill(
    *,
    env: dict[str, str],
    backup_dir: Path,
    api_env_file: Path,
    pg_cli_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    script = SCRIPTS_DIR / "restore-drill.sh"
    run_env = os.environ.copy()
    run_env.update(env)
    run_env["RELEASE_DIR"] = str(REPO_ROOT)
    run_env["BACKUP_DIR"] = str(backup_dir)
    run_env["API_ENV_FILE"] = str(api_env_file)
    run_env["VENV_PYTHON"] = sys.executable
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


@pytest.fixture
def postgres_at_head():
    cfg = _alembic_config()
    engine = create_engine(sync_database_url(_database_url()), pool_pre_ping=True)
    _reset_database(engine)
    command.upgrade(cfg, "head")
    yield engine
    _reset_database(engine)
    engine.dispose()


@pytest.fixture
def api_env_file(tmp_path: Path):
    key = Fernet.generate_key().decode()
    env_file = tmp_path / "api.env"
    env_file.write_text(
        f"DATABASE_URL={_database_url()}\nTIKTOK_TOKEN_ENCRYPTION_KEY={key}\n",
        encoding="utf-8",
    )
    return env_file, key


@requires_postgres
def test_restore_drill_passes_and_cleans_up_scratch_db(
    postgres_at_head,
    api_env_file: tuple[Path, str],
    tmp_path: Path,
    postgres16_cli: Path,
):
    env_file, key = api_env_file
    os.environ["TIKTOK_TOKEN_ENCRYPTION_KEY"] = key
    _seed_encrypted_credential(postgres_at_head)

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    dump_file = backup_dir / "juli-pre-migrate-20260101T000000Z.dump"
    migration_url = sync_database_url(_database_url())
    dump = subprocess.run(
        [
            str(postgres16_cli / "pg_dump"),
            "-Fc",
            "-f",
            str(dump_file),
            migration_url,
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{postgres16_cli}:{os.environ.get('PATH', '')}"},
    )
    assert dump.returncode == 0, dump.stderr
    assert dump_file.stat().st_size > 0

    result = _run_restore_drill(
        env={
            "DATABASE_URL": _database_url(),
            "TIKTOK_TOKEN_ENCRYPTION_KEY": key,
        },
        backup_dir=backup_dir,
        api_env_file=env_file,
        pg_cli_dir=postgres16_cli,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "RESTORE DRILL PASS" in combined
    assert "decrypt ok" in combined or "no rows in tiktok_credentials" in combined
    assert _list_scratch_databases(postgres16_cli / "psql") == []


@requires_postgres
def test_restore_drill_fails_on_corrupted_dump(
    postgres_at_head,
    api_env_file: tuple[Path, str],
    tmp_path: Path,
    postgres16_cli: Path,
):
    env_file, key = api_env_file
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    corrupt = backup_dir / "juli-pre-migrate-20260102T000000Z.dump"
    corrupt.write_bytes(b"NOT_A_VALID_PG_DUMP_HEADER_TRUNCATED")

    result = _run_restore_drill(
        env={
            "DATABASE_URL": _database_url(),
            "TIKTOK_TOKEN_ENCRYPTION_KEY": key,
        },
        backup_dir=backup_dir,
        api_env_file=env_file,
        pg_cli_dir=postgres16_cli,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "RESTORE DRILL FAIL" in combined
    assert _list_scratch_databases(postgres16_cli / "psql") == []
