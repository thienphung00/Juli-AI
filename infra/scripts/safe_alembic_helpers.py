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

# Tables that must have at least one row in production/drill
# Do NOT include tables that are legitimately empty (e.g., orders on fresh installs)
FLOORED_TABLES: tuple[str, ...] = ("users", "shops")

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


def current_revision(url: str | None = None) -> str | None:
    """The database's stamped revision, or None if it cannot be read.

    Takes an optional url so the restore drill can ask the RESTORED copy for
    its revision and compare it against the source (#1553). Without it the
    drill could only ever ask the live database about itself.
    """
    with _engine(url).connect() as conn:
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


def verify_rls_enforced(url: str | None = None) -> dict[str, str | bool]:
    """Verify RLS is enforced by checking juli_app can't read tenant-scoped tables.

    Returns dict with checked=True/False and reason. Raises on test failure.
    """
    with _engine(url).connect() as conn:
        # Check if a tenant-scoped table exists
        shops_exist = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_name = 'shops'")
        ).scalar()
        if not shops_exist:
            return {"checked": False, "reason": "shops table does not exist"}

        # Count rows in shops as superuser
        shops_count = conn.execute(text("SELECT count(*) FROM shops")).scalar_one()
        if shops_count == 0:
            return {"checked": False, "reason": "shops table is empty"}

        # Try to read as juli_app with no tenant context
        # This should return 0 rows if RLS is working
        # SET ROLE needs no LOGIN attribute — an earlier version granted it here
        # as a side effect of a read-only check, which permanently widened the
        # runtime role every time the drill ran.

        # Now set role and try to read
        conn.execute(text("SET ROLE juli_app"))
        conn.execute(text("SET app.current_shop_id = ''"))
        shops_as_juli_app = conn.execute(text("SELECT count(*) FROM shops")).scalar_one()

        if shops_as_juli_app == 0:
            return {"checked": True, "reason": "RLS enforced: juli_app without context sees 0 rows"}
        else:
            raise RuntimeError(
                f"RLS IS INERT: juli_app without tenant context read {shops_as_juli_app} rows "
                f"from shops (should be 0). Tables may be owned by juli_app, "
                f"exempting them from RLS policies."
            )


def verify_runtime_role_owns_nothing(url: str | None = None) -> dict[str, object]:
    """The runtime role must own no table and no SECURITY DEFINER function.

    Two silent restore defects share one symptom, and this is the cheapest query
    that sees both:

    * Tables owned by the runtime role are exempt from their own RLS policies.
      The policies restore, are visible in `pg_policies`, and are inert — a
      cross-tenant read simply succeeds.
    * `pg_restore --no-owner` reassigns FUNCTIONS too. A SECURITY DEFINER
      enumeration owned by the runtime role executes AS a non-owner, so RLS
      applies inside its body and it returns the empty set forever. Every
      existing assertion still passes: prosecdef is true, PUBLIC still lacks
      EXECUTE, and the isolation proof is green. `credential_refresh_beat` then
      refreshes nothing and every tenant's tokens quietly expire.

    Must be run AS THE RUNTIME ROLE. Run as the owner against a correct database
    it returns a large number, which inverts the check.
    """
    with _engine(url).connect() as conn:
        owned = conn.execute(
            text(
                "SELECT count(*) FROM ("
                "  SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                "   WHERE c.relkind = 'r'"
                "     AND n.nspname IN ('public','bronze','silver','gold','ops')"
                "     AND c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
                "  UNION ALL"
                "  SELECT 1 FROM pg_proc"
                "   WHERE prosecdef"
                "     AND proowner = (SELECT oid FROM pg_roles WHERE rolname = current_user)"
                ") x"
            )
        ).scalar_one()
        role = conn.execute(text("SELECT current_user")).scalar_one()

    if owned:
        raise RuntimeError(
            f"the runtime role '{role}' owns {owned} table(s) and/or SECURITY DEFINER "
            "function(s). Tables it owns are exempt from their own RLS policies, and a "
            "SECURITY DEFINER function it owns runs as a non-owner and returns nothing. "
            "Restore as the OWNER without --no-owner."
        )
    return {"checked": True, "role": role, "owned": 0}


def estimate_database_bytes() -> int:
    with _engine().connect() as conn:
        return int(
            conn.execute(text("SELECT pg_database_size(current_database())")).scalar_one()
        )


def verify_backup_size_floor(backup_bytes: int, min_mb: int = 1) -> bool:
    """Return True if backup size is >= min_mb (default 1 MB)."""
    min_bytes = min_mb * 1024 * 1024
    return backup_bytes >= min_bytes


def verify_restored_row_counts(counts_after: dict[str, int]) -> tuple[bool, list[str]]:
    """Verify restored row counts meet minimum expectations.

    Checks that:
    - Floored tables (users, shops) have at least 1 row after restore
    """
    errors: list[str] = []
    for table in FLOORED_TABLES:
        count = counts_after.get(table, 0)
        if count == 0:
            errors.append(f"{table}: has 0 rows after restore (floor is 1 row)")
    return len(errors) == 0, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="safe-alembic-upgrade helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    p_row_counts = sub.add_parser("row-counts")
    p_row_counts.add_argument(
        "--url",
        help="Postgres URL to inspect (defaults to DATABASE_URL / DATABASE_DIRECT_URL)",
    )

    p_rev = sub.add_parser("current-revision")
    p_rev.add_argument("--url", help="Postgres URL to read the revision from")
    sub.add_parser("estimate-db-bytes")
    sub.add_parser("migration-db-url")

    p_verify = sub.add_parser("verify-token-decrypt")
    p_verify.add_argument(
        "--url",
        help="Postgres URL to inspect (defaults to DATABASE_URL / DATABASE_DIRECT_URL)",
    )

    p_owns = sub.add_parser("runtime-role-owns-nothing")
    p_owns.add_argument(
        "--url",
        help="Postgres URL to inspect. MUST authenticate as the runtime role — "
        "run as the owner it inverts and always reports failure.",
    )

    p_rls = sub.add_parser("verify-rls-enforced")
    p_rls.add_argument(
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

    p_compare = sub.add_parser("verify-restored-row-counts")
    p_compare.add_argument("--counts", required=True, help="JSON row counts from restored DB")

    p_backup = sub.add_parser("verify-backup-size-floor")
    p_backup.add_argument("--bytes", type=int, required=True)
    p_backup.add_argument("--min-mb", type=int, default=1)

    args = parser.parse_args()

    if args.command == "row-counts":
        print(json.dumps(row_counts(args.url)))
        return 0
    if args.command == "current-revision":
        print(current_revision(getattr(args, "url", None)) or "")
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
    if args.command == "runtime-role-owns-nothing":
        try:
            result = verify_runtime_role_owns_nothing(args.url)
        except Exception as exc:
            print(f"runtime role ownership check failed: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(result))
        return 0
    if args.command == "verify-rls-enforced":
        try:
            result = verify_rls_enforced(args.url)
        except Exception as exc:
            print(f"rls verification failed: {exc}", file=sys.stderr)
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
    if args.command == "verify-restored-row-counts":
        counts = json.loads(args.counts)
        is_valid, errors = verify_restored_row_counts(counts)
        if not is_valid:
            for error in errors:
                print(error, file=sys.stderr)
            return 1
        return 0
    if args.command == "verify-backup-size-floor":
        if verify_backup_size_floor(args.bytes, args.min_mb):
            return 0
        print(
            f"backup size {args.bytes} bytes < {args.min_mb} MB",
            file=sys.stderr,
        )
        return 1

    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
