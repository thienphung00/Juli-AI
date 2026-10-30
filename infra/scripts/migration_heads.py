#!/usr/bin/env python3
"""Alembic heads of a migrations directory, read without importing anything (P62-A, D72.1).

The fast-track deploy workflow decides on the GitHub runner whether a deploy
carries a migration, i.e. whether production's ``alembic current`` differs from
the target SHA's head. The runner has no backend install, and alembic's own
``ScriptDirectory`` imports every migration module (which imports the backend).
This reads ``revision`` / ``down_revision`` from each file's AST instead, using
only the standard library. tests/unit/test_backup_dump_policy.py pins it to
alembic's own answer on the real migrations directory.

Usage:
    migration_heads.py heads  --migrations-dir DIR
    migration_heads.py decide --migrations-dir DIR --production-revision REV [--force]

``decide`` prints ``backup=true|false`` and ``reason=<text>`` (GITHUB_OUTPUT
lines). Since P62-C ``backup=true`` means only "force_backup requested": a pending
migration is protected by safe-alembic-upgrade.sh's pre-migrate dump inside
deploy.sh, which already fails toward a dump (an unreadable revision dumps). The
workflow's own dump on top of it was a second full copy of production per
migration deploy. ``reason`` still names the migration state, for the run log.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_FIELDS = ("revision", "down_revision")


def _literal(node: ast.expr) -> object:
    return ast.literal_eval(node)


def read_revision(path: Path) -> tuple[str, tuple[str, ...]] | None:
    """(revision, parents) declared at module level in *path*, or None if it is not a migration."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target, value = node.target, node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id in _FIELDS:
            found[target.id] = _literal(value)
    revision = found.get("revision")
    if not isinstance(revision, str):
        return None
    down = found.get("down_revision")
    if down is None:
        parents: tuple[str, ...] = ()
    elif isinstance(down, str):
        parents = (down,)
    elif isinstance(down, (tuple, list)) and all(isinstance(p, str) for p in down):
        parents = tuple(down)
    else:
        raise ValueError(f"{path}: unsupported down_revision {down!r}")
    return revision, parents


def script_heads(migrations_dir: Path) -> list[str]:
    """Revisions in *migrations_dir* that no other revision names as a parent (sorted)."""
    if not migrations_dir.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {migrations_dir}")
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(migrations_dir.glob("*.py")):
        if path.name.startswith("__"):
            continue
        parsed = read_revision(path)
        if parsed is None:
            continue
        revision, down = parsed
        revisions.add(revision)
        parents.update(down)
    return sorted(revisions - parents)


def decide_backup(heads: list[str], production_revision: str, *, force: bool) -> tuple[bool, str]:
    """Whether the workflow's backup job must run, and why.

    Only when forced (P62-C). A migration is dumped once, by safe-alembic-upgrade.sh
    right before ``alembic upgrade``; the reason says which case this deploy is.
    """
    production_revision = production_revision.strip()
    if not production_revision:
        state = "production alembic revision unknown (safe-alembic dumps)"
    elif len(heads) != 1:
        state = f"target has {len(heads)} alembic heads ({', '.join(heads) or 'none'}) (safe-alembic dumps)"
    elif production_revision == heads[0]:
        state = f"no new migration: production is at the target head {heads[0]}"
    else:
        state = (
            f"migration pending: production at {production_revision}, target head {heads[0]} "
            "(safe-alembic dumps)"
        )
    if force:
        return True, f"force_backup requested; {state}"
    return False, state


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_heads = sub.add_parser("heads")
    p_heads.add_argument("--migrations-dir", required=True, type=Path)
    p_decide = sub.add_parser("decide")
    p_decide.add_argument("--migrations-dir", required=True, type=Path)
    p_decide.add_argument("--production-revision", required=True)
    p_decide.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    heads = script_heads(args.migrations_dir)
    if args.command == "heads":
        print("\n".join(heads))
        return 0
    backup, reason = decide_backup(heads, args.production_revision, force=args.force)
    print(f"backup={'true' if backup else 'false'}")
    print(f"reason={reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
