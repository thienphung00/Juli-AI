#!/usr/bin/env python3
"""Git merge driver for wave manifests, whose only conflict is a union (#1731).

Every slice appends its own issue id to
``agent-runtime/artifacts/waves/wave-<id>.json``, so any two concurrent slices
conflict there and the resolution is always the same: the sorted union of both
``issues`` lists, with the rest of the document unchanged. That resolution was
performed by hand at least six times in one working day, and getting it wrong
silently drops a slice out of the wave -- the manifest is what
``policy-checks`` reads to decide whether an issue belongs.

Registered as a merge driver rather than a hook so it runs wherever git merges:
locally, in a rebase, and in whatever tool the operator happens to use.

Exit codes follow the merge-driver contract: 0 resolved, 1 left conflicted for a
human. Anything it cannot understand -- unreadable JSON, a missing ``issues``
list, a disagreement about which wave the file describes -- is left conflicted
rather than guessed at, because a manifest silently merged wrong is worse than
one that stops the merge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def merge_manifests(
    base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]
) -> dict[str, Any] | None:
    """The union, or ``None`` when the difference is not one this driver owns."""
    for side in (ours, theirs):
        if not isinstance(side.get("issues"), list):
            return None
    # Only the issues list may differ. A disagreement anywhere else -- waveId,
    # branch, schemaVersion -- is a real conflict about what this file is, and
    # unioning it would paper over it.
    for key in set(ours) | set(theirs):
        if key == "issues":
            continue
        if ours.get(key) != theirs.get(key):
            return None

    merged = dict(ours)
    ids = set(ours["issues"]) | set(theirs["issues"])
    if not all(isinstance(i, int) for i in ids):
        return None
    merged["issues"] = sorted(ids)
    return merged


def install(repo: Path | None = None) -> int:
    """Register the driver in this clone's git config.

    .gitattributes names the driver; git will not run it until the clone also
    knows what "wave-manifest" means. Keeping the two apart is deliberate --
    a repository cannot make a checkout execute a script just by committing an
    attributes file, so registration is an explicit local step.
    """
    import subprocess

    root = repo or Path(__file__).resolve().parents[3]
    script = Path(__file__).resolve()
    for key, value in (
        ("merge.wave-manifest.name", "union of a wave manifest's issues list (#1731)"),
        ("merge.wave-manifest.driver", f"{sys.executable} {script} %O %A %B"),
    ):
        subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
    print(f"registered merge driver 'wave-manifest' in {root}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--install":
        return install()
    if len(argv) < 4:
        print("usage: merge_wave_manifest.py <base> <ours> <theirs>", file=sys.stderr)
        return 1
    base_path, ours_path, theirs_path = (Path(p) for p in argv[1:4])

    base = _load(base_path) or {}
    ours = _load(ours_path)
    theirs = _load(theirs_path)
    if ours is None or theirs is None:
        return 1

    merged = merge_manifests(base, ours, theirs)
    if merged is None:
        return 1

    # git takes the resolved content from the "ours" path.
    ours_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
