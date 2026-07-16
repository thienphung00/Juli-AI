"""Helpers for safe-alembic-upgrade.sh — row counts, allowlist, token decrypt."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, urlunparse

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text

from juli_backend.core.config.runtime import sync_database_url
from juli_backend.database.token_crypto import decrypt_token

PROTECTED_TABLES: tuple[str, ...] = (
    "users",
    "shops",
    "tiktok_credentials",
    "orders",
    "products",
    "inventory_items",
    "tiktok_sync_state",
)

MIGRATION_ALLOW_COMMENT = re.compile(
    r"^\s*#\s*safe-migrate:\s*allow-decrease\s+(?P<table>[a-z_]+)\s*$",
    re.IGNORECASE,
)


def migration_db_url() -> str:
    """Prefer direct Postgres URL for pg_dump/migrations; fall back to pooler."""
    direct = os.environ.get("DATABASE_DIRECT_URL", "").strip()
    pooled = os.environ.get("DATABASE_URL", "").strip()
    raw = direct or pooled
    if not raw:
        raise RuntimeError(
            "DATABASE_URL (or DATABASE_DIRECT_URL) must be set for safe migration"
        )
    return sync_database_url(raw)


def resolve_db_identity(raw_url: str | None = None) -> dict[str, str]:
    """Resolve Supabase project ref or local host label from a Postgres URL."""
    url = (raw_url or migration_db_url()).strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required to resolve database identity")

    parsed = urlparse(url)
    hostname = (parsed.hostname or "").strip()
    username = (parsed.username or "").strip()

    if hostname.startswith("db.") and hostname.endswith(".supabase.co"):
        project_ref = hostname.removeprefix("db.").removesuffix(".supabase.co")
        return {
            "kind": "supabase-direct",
            "project_ref": project_ref,
            "host": hostname,
            "display": (
                f"Supabase project ref: {project_ref} "
                f"(direct host {hostname})"
            ),
        }

    if hostname.endswith(".pooler.supabase.com") and username.startswith("postgres."):
        project_ref = username.removeprefix("postgres.")
        return {
            "kind": "supabase-pooler",
            "project_ref": project_ref,
            "host": hostname,
            "display": (
                f"Supabase project ref: {project_ref} "
                f"(pooler {hostname})"
            ),
        }

    if not hostname:
        return {
            "kind": "unknown",
            "project_ref": "",
            "host": "",
            "display": "local/non-Supabase host: <unparseable connection string>",
        }

    if hostname in {"localhost", "127.0.0.1", "::1"}:
        return {
            "kind": "local",
            "project_ref": "",
            "host": hostname,
            "display": f"local/non-Supabase host: {hostname}",
        }

    return {
        "kind": "unknown",
        "project_ref": "",
        "host": hostname,
        "display": f"local/non-Supabase host: {hostname}",
    }


def _engine(url: str | None = None):
    target = url or migration_db_url()
    return create_engine(sync_database_url(target), pool_pre_ping=True)


def replace_database_name(raw_url: str, database: str) -> str:
    """Return a copy of raw_url with the database name replaced."""
    parsed = urlparse(raw_url.strip())
    return urlunparse(parsed._replace(path=f"/{database}"))


def admin_db_url(raw_url: str | None = None) -> str:
    """Connection URL to the postgres maintenance database on the same instance."""
    return replace_database_name(raw_url or migration_db_url(), "postgres")


def find_latest_backup(backup_dir: Path) -> Path:
    """Return the newest juli-pre-migrate-*.dump in backup_dir (by mtime)."""
    if not backup_dir.is_dir():
        raise RuntimeError(f"backup directory not found: {backup_dir}")
    candidates = sorted(
        backup_dir.glob("juli-pre-migrate-*.dump"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise RuntimeError(
            f"no juli-pre-migrate-*.dump backups found in {backup_dir}"
        )
    return candidates[0]


def row_counts(url: str | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    with _engine(url).connect() as conn:
        for table in PROTECTED_TABLES:
            counts[table] = conn.execute(
                text(f"SELECT count(*) FROM {table}")
            ).scalar_one()
    return counts


def current_revision() -> str | None:
    with _engine().connect() as conn:
        try:
            return conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()
        except Exception:
            return None


def head_revision(alembic_ini: Path) -> str:
    cfg = Config(str(alembic_ini))
    script_location = cfg.get_main_option("script_location")
    if script_location:
        cfg.set_main_option("script_location", str(_resolve_script_location(
            alembic_ini.parent, script_location
        )))
    script = ScriptDirectory.from_config(cfg)
    return script.get_current_head()


def pending_revisions(alembic_ini: Path, from_rev: str | None) -> list[str]:
    cfg = Config(str(alembic_ini))
    script_location = cfg.get_main_option("script_location")
    if script_location:
        cfg.set_main_option("script_location", str(_resolve_script_location(
            alembic_ini.parent, script_location
        )))
    script = ScriptDirectory.from_config(cfg)
    if from_rev is None:
        return [rev.revision for rev in script.walk_revisions()]
    pending: list[str] = []
    for rev in script.iterate_revisions("head", from_rev):
        if rev.revision != from_rev:
            pending.append(rev.revision)
    pending.reverse()
    return pending


def _resolve_script_location(ini_dir: Path, script_location: str) -> Path:
    loc = script_location.replace("%(here)s", str(ini_dir))
    path = Path(loc)
    if not path.is_absolute():
        path = (ini_dir / path).resolve()
    return path


def load_allowlist_file(path: Path) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    if not path.is_file():
        return allowed
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            allowed.add((parts[0], parts[1]))
    return allowed


def scan_migration_comments(
    migrations_dir: Path, revisions: list[str]
) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    if not migrations_dir.is_dir():
        return allowed
    rev_set = set(revisions)
    for path in migrations_dir.glob("*.py"):
        text_body = path.read_text(encoding="utf-8")
        rev_match = re.search(r"^revision\s*=\s*['\"]([^'\"]+)['\"]", text_body, re.M)
        if not rev_match:
            continue
        revision = rev_match.group(1)
        if revision not in rev_set:
            continue
        for line in text_body.splitlines():
            match = MIGRATION_ALLOW_COMMENT.match(line)
            if match:
                allowed.add((revision, match.group("table")))
    return allowed


def is_decrease_allowed(
    table: str,
    revisions: list[str],
    allowlist_file: Path,
    migrations_dir: Path,
) -> bool:
    file_allowed = load_allowlist_file(allowlist_file)
    comment_allowed = scan_migration_comments(migrations_dir, revisions)
    combined = file_allowed | comment_allowed
    if not revisions:
        return False
    return any((rev, table) in combined for rev in revisions)


def verify_token_decryption(url: str | None = None) -> dict[str, str | bool]:
    """Return status dict; raises on decrypt failure when rows exist."""
    with _engine(url).connect() as conn:
        row = conn.execute(
            text(
                "SELECT access_token FROM tiktok_credentials "
                "WHERE access_token IS NOT NULL LIMIT 1"
            )
        ).first()
    if row is None:
        return {"checked": False, "reason": "no rows in tiktok_credentials"}
    token = row[0]
    decrypt_token(token)
    return {"checked": True, "reason": "decrypt ok"}


def estimate_database_bytes() -> int:
    with _engine().connect() as conn:
        return int(
            conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="safe-alembic-upgrade helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    p_row_counts = sub.add_parser("row-counts")
    p_row_counts.add_argument(
        "--url",
        help="Postgres URL to inspect (defaults to DATABASE_URL / DATABASE_DIRECT_URL)",
    )

    sub.add_parser("current-revision")
    sub.add_parser("estimate-db-bytes")
    sub.add_parser("migration-db-url")

    p_verify = sub.add_parser("verify-token-decrypt")
    p_verify.add_argument(
        "--url",
        help="Postgres URL to inspect (defaults to DATABASE_URL / DATABASE_DIRECT_URL)",
    )

    p_latest = sub.add_parser("latest-backup")
    p_latest.add_argument("--backup-dir", required=True)

    sub.add_parser("admin-db-url")

    p_db_url = sub.add_parser("database-url-with-name")
    p_db_url.add_argument("--database", required=True)
    p_db_url.add_argument(
        "--url",
        help="Base Postgres URL (defaults to DATABASE_URL / DATABASE_DIRECT_URL)",
    )

    p_identity = sub.add_parser("db-identity")
    p_identity.add_argument(
        "--url",
        help="Postgres URL to inspect (defaults to DATABASE_URL / DATABASE_DIRECT_URL)",
    )

    p_head = sub.add_parser("head-revision")
    p_head.add_argument("--alembic-ini", required=True)

    p_pending = sub.add_parser("pending-revisions")
    p_pending.add_argument("--alembic-ini", required=True)
    p_pending.add_argument("--from-revision", default="")

    p_allowed = sub.add_parser("is-decrease-allowed")
    p_allowed.add_argument("--table", required=True)
    p_allowed.add_argument("--revisions", required=True, help="comma-separated")
    p_allowed.add_argument("--allowlist-file", required=True)
    p_allowed.add_argument("--migrations-dir", required=True)

    args = parser.parse_args()

    if args.command == "row-counts":
        print(json.dumps(row_counts(args.url)))
        return 0
    if args.command == "current-revision":
        print(current_revision() or "")
        return 0
    if args.command == "estimate-db-bytes":
        print(estimate_database_bytes())
        return 0
    if args.command == "migration-db-url":
        print(migration_db_url())
        return 0
    if args.command == "verify-token-decrypt":
        try:
            result = verify_token_decryption(args.url)
        except Exception as exc:
            print(f"decrypt failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result))
        return 0
    if args.command == "latest-backup":
        print(find_latest_backup(Path(args.backup_dir)))
        return 0
    if args.command == "admin-db-url":
        print(admin_db_url())
        return 0
    if args.command == "database-url-with-name":
        base = args.url or migration_db_url()
        print(replace_database_name(base, args.database))
        return 0
    if args.command == "db-identity":
        print(json.dumps(resolve_db_identity(args.url)))
        return 0
    if args.command == "head-revision":
        print(head_revision(Path(args.alembic_ini)))
        return 0
    if args.command == "pending-revisions":
        from_rev = args.from_revision or None
        print(json.dumps(pending_revisions(Path(args.alembic_ini), from_rev)))
        return 0
    if args.command == "is-decrease-allowed":
        revisions = [r for r in args.revisions.split(",") if r]
        allowed = is_decrease_allowed(
            args.table,
            revisions,
            Path(args.allowlist_file),
            Path(args.migrations_dir),
        )
        print("yes" if allowed else "no")
        return 0

    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
