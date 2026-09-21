#!/usr/bin/env python3
"""Pre-removal guard: refuse to drop a worktree that still owns unarchived bodies.

The primary fix for the 2026-09-21 loss is archive-on-emit
(``agent-runtime/scripts/ci/artifact_archive.py``): a body is copied to the
repository's shared ``.git/artifact-archive/`` in the same step that writes it,
so worktree removal genuinely loses nothing. This script is the backstop for the
cases archive-on-emit cannot reach:

* bodies written before archive-on-emit existed, still sitting in older worktrees;
* bodies written by hand, or by a tool that does not go through
  ``common.write_json``;
* an archive directory that was moved, emptied, or pointed elsewhere by
  ``JULI_ARTIFACT_ARCHIVE_DIR`` mid-session.

It is deliberately the *weaker* half: it only fires when removal is routed
through it. On its own it would be another procedural request, which is what
already failed. With archive-on-emit in front of it, it is a cheap second
opinion that also happens to repair what it finds (``--archive``).

The question it asks is the one the incident's brief assumed the answer to:
``git status --porcelain --ignored=matching -- agent-runtime/artifacts`` must come
back with no policy-local body that is not already in the archive, byte for byte.

Exit codes: ``0`` nothing at risk; ``1`` unarchived bodies found (or repaired,
with ``--archive``, in which case a second run exits 0); ``2`` usage/environment
error.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

STATUS_SCOPE = "agent-runtime/artifacts"


def _archive_seam():
    """Load ``ci/artifact_archive`` lazily, inside a function.

    A module-level import after the ``sys.path`` insert would need a
    ``# noqa: E402`` that ``tests/unit/test_ratchets.py`` counts as a fresh unit
    of tracked debt. The function-local form is the pattern
    ``tests/unit/test_phase_run_id_derivation.py::_ci_imports`` and
    ``generate_status_records.py::_ref_scheme_seam`` already use.
    """
    ci_dir = str(Path(__file__).resolve().parents[1] / "ci")
    if ci_dir not in sys.path:
        sys.path.insert(0, ci_dir)
    import artifact_archive

    return artifact_archive


class WorktreeScanError(RuntimeError):
    """The worktree could not be inspected, so no verdict is available."""


def _git_status_paths(worktree: Path) -> list[str]:
    """Repo-relative paths git reports under ``agent-runtime/artifacts``.

    ``--ignored=matching`` is the load-bearing flag: without it the five body
    directories are invisible to ``git status`` precisely because ``.gitignore``
    names them, which is how they stayed invisible to the cleanup brief too.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "status",
                "--porcelain",
                "--ignored=matching",
                "--",
                STATUS_SCOPE,
            ],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:  # pragma: no cover - git missing is an env error
        raise WorktreeScanError(f"could not run git in {worktree}: {exc}") from exc
    if proc.returncode != 0:
        raise WorktreeScanError(
            f"git status failed in {worktree}: {proc.stderr.strip() or proc.returncode}"
        )
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        entry = line[3:]
        # Renames read "old -> new"; the new name is the file on disk.
        if " -> " in entry:
            entry = entry.split(" -> ", 1)[1]
        paths.append(entry.strip('"'))
    return paths


def unarchived_bodies(worktree: Path, *, root: Path | None = None) -> list[Path]:
    """Policy-local bodies present in ``worktree`` with no durable copy.

    Untracked-directory entries (``git status`` collapses a wholly-ignored
    directory to ``dir/``) are expanded, so a worktree holding 400 review bodies
    under one collapsed line is not mistaken for holding none.
    """
    archive = _archive_seam()
    worktree = worktree.resolve()
    candidates: list[Path] = []
    for rel in _git_status_paths(worktree):
        target = worktree / rel
        if target.is_dir():
            candidates.extend(sorted(p for p in target.rglob("*") if p.is_file()))
        elif target.is_file():
            candidates.append(target)

    target_root = root if root is not None else archive.archive_root(worktree)
    at_risk: list[Path] = []
    for candidate in candidates:
        body_rel = archive.body_relative_path(candidate)
        if body_rel is None:
            continue
        try:
            digest = archive.sha256_of(candidate)
        except OSError as exc:
            raise WorktreeScanError(f"could not hash {candidate}: {exc}") from exc
        if not archive.archived_copy_path(body_rel, digest, target_root).is_file():
            at_risk.append(candidate)
    return at_risk


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worktree",
        type=Path,
        default=Path.cwd(),
        help="Worktree about to be removed (default: current directory).",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Archive what is missing instead of only reporting it, then exit 1 "
        "so the caller re-runs and sees a clean tree.",
    )
    args = parser.parse_args(argv)

    archive = _archive_seam()
    try:
        at_risk = unarchived_bodies(args.worktree)
        root = archive.archive_root(args.worktree.resolve())
    except (WorktreeScanError, archive.ArtifactArchiveError) as exc:
        print(f"worktree_artifacts_archived: ERROR — {exc}", file=sys.stderr)
        return 2

    if not at_risk:
        print(
            f"worktree_artifacts_archived: PASS — every ADR-003 body in "
            f"{args.worktree} has a durable copy under {root}; removing this "
            "worktree loses nothing."
        )
        return 0

    print(
        f"worktree_artifacts_archived: FAIL — {len(at_risk)} artifact body/bodies in "
        f"{args.worktree} exist on this machine ONLY inside this worktree and have no "
        f"copy under {root}. They are gitignored, so they are not git objects and "
        "`git fsck` will not bring them back after removal.",
        file=sys.stderr,
    )
    for path in at_risk[:20]:
        print(f"  {archive.body_relative_path(path)}", file=sys.stderr)
    if len(at_risk) > 20:
        print(f"  ... and {len(at_risk) - 20} more", file=sys.stderr)

    if args.archive:
        for path in at_risk:
            archive.archive_body(path)
        print(
            f"archived {len(at_risk)} body/bodies to {root}; re-run this check to "
            "confirm a clean tree before removing the worktree.",
            file=sys.stderr,
        )
    else:
        print(
            "Re-run with --archive to copy them to the durable archive, or set "
            f"{archive.ARCHIVE_DIR_ENV} if the archive belongs elsewhere.",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
