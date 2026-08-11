#!/usr/bin/env python3
"""Create a throwaway `public` table with no explicit GRANT, for the #929 decisive
proof that migration 029's `ALTER DEFAULT PRIVILEGES` clause is load-bearing.

Run this AFTER `alembic upgrade head` in the migration-check CI job, then rerun
``check_public_schema_privileges.py``. Its reachability depends entirely on which
default privileges were in force at ``CREATE TABLE`` time: the Supabase-equivalent
bootstrap grant ``ensure_postgrest_client_roles.py`` seeds before migrations run
(if 029's `ALTER DEFAULT PRIVILEGES ... REVOKE ALL` clause did nothing to reverse
it), or the closed default that clause installs (if it ran correctly).

Usage:
    DATABASE_URL=postgresql://... python agent-runtime/scripts/ci/create_post_head_scratch_table.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "backend" / "src"))

from sqlalchemy import create_engine, text  # noqa: E402

from juli_backend.core.config.runtime import sync_database_url  # noqa: E402

SCRATCH_TABLE = "ci_929_table_created_after_head"


def create_scratch_table(database_url: str) -> None:
    engine = create_engine(sync_database_url(database_url))
    try:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE TABLE {SCRATCH_TABLE} (id uuid PRIMARY KEY)"))
    finally:
        engine.dispose()


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("create_post_head_scratch_table: DATABASE_URL is not set", file=sys.stderr)
        return 1
    create_scratch_table(database_url)
    print(f"create_post_head_scratch_table: created public.{SCRATCH_TABLE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
