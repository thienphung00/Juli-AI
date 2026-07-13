"""Compare pre/post row counts for safe-alembic-upgrade.sh."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from safe_alembic_helpers import PROTECTED_TABLES, is_decrease_allowed


def compare(
    pre: dict[str, int],
    post: dict[str, int],
    revisions: list[str],
    allowlist_file: Path,
    migrations_dir: Path,
) -> int:
    regressions: list[str] = []
    for table in PROTECTED_TABLES:
        before = int(pre.get(table, 0))
        after = int(post.get(table, 0))
        if after < before:
            if is_decrease_allowed(table, revisions, allowlist_file, migrations_dir):
                print(f"ALLOWED decrease {table}: {before} -> {after}")
            else:
                regressions.append(
                    f"{table}: {before} -> {after} (lost {before - after})"
                )
    if regressions:
        print("REGRESSION")
        for line in regressions:
            print(line)
        return 2
    print("OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", required=True)
    parser.add_argument("--post", required=True)
    parser.add_argument("--revisions", required=True, help="JSON array of revision ids")
    parser.add_argument("--allowlist-file", required=True)
    parser.add_argument("--migrations-dir", required=True)
    args = parser.parse_args()

    pre = json.loads(args.pre)
    post = json.loads(args.post)
    revisions_raw = json.loads(args.revisions)
    if not isinstance(revisions_raw, list):
        raise ValueError("--revisions must be a JSON array")
    return compare(
        pre,
        post,
        [str(r) for r in revisions_raw],
        Path(args.allowlist_file),
        Path(args.migrations_dir),
    )


if __name__ == "__main__":
    raise SystemExit(main())
