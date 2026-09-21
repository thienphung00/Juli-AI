#!/usr/bin/env python3
"""Archive-on-emit for the five gitignored ADR-003 artifact body directories.

Why this module exists
----------------------
``.gitignore`` keeps five artifact body directories -- ``reviews/``,
``implementations/``, ``intent-reviews/``, ``validation/``, ``optimization/`` --
out of every commit (ADR-052's #670 P1 Option A amendment: *emit is not commit*).
Only the compact record at ``agent-runtime/artifacts/status/issue-<N>.json`` is
tracked, and it cites each body by ``local-only:<path>`` + ``sha256``.

The consequence was never written down as a *mechanism*, only as a fact: those
bodies exist **only inside the worktree that produced them**. A worktree is
otherwise a disposable checkout -- "removing it with the branch intact loses
nothing" is true in almost every repository -- so a routine worktree cleanup on
2026-09-21 removed 21 worktrees and permanently destroyed the bodies behind five
committed status records (#1701, #1748, #1977, #1540, #1608). They were never git
objects, so ``git fsck`` cannot reach them; there were no local snapshots. The
same latent hole had already claimed 99 of the 111 ``local-only:`` records on
``main`` before that cleanup.

A runbook sentence is not a fix for this: the person who wrote the bad cleanup
brief *had* the correct fact recorded and contradicted it anyway. So the property
is made structurally true instead of procedurally requested -- writing a body
through the shared writer archives it outside the worktree in the same step. The
premise "removing a worktree loses nothing" then becomes true rather than
aspirational.

Where the archive lives
-----------------------
``$(git rev-parse --git-common-dir)/artifact-archive/`` -- i.e. the *main*
checkout's ``.git`` directory, which every linked worktree of the repository
shares. Chosen over a home-relative path such as
``~/.juli-backups/worktree-artifacts-<date>/`` (the ad-hoc location used to
salvage what the incident left) because:

* **It is repo-relative, so it is self-locating.** Any checkout, any CI runner,
  any clone finds its own archive with one ``git rev-parse``; nothing has to know
  a machine's home directory or a date stamp.
* **It cannot collide.** Two clones of this repo -- or a clone of another repo
  reusing the same convention -- get separate archives. One shared
  ``~/.juli-backups`` directory would have every clone writing over the same
  names.
* **Its lifetime is the right one.** ``git worktree remove`` deletes the worktree
  and ``.git/worktrees/<name>``; it never touches sibling directories under the
  common ``.git``. The archive therefore outlives every worktree and dies only
  with the repository itself -- which is a deliberate act, not a cleanup.
* **It is not a commit.** ``.git`` is not part of any worktree, so nothing here
  pre-empts the separate, larger decision about whether the bodies should be
  committed (measured at ~18MB against a 387MB ``.git``). This change is
  orthogonal to that decision and blocks neither answer.

``JULI_ARTIFACT_ARCHIVE_DIR`` overrides the location (tests, and any operator who
wants the archive on other media).

Layout is content-addressed: ``<archive>/<body-dir>/<stem>.<sha256[:12]>.json``.
A re-review of the same issue therefore adds a second file instead of
overwriting the first, so the archive holds *every* distinct version a loop ever
emitted -- and a status record's recorded ``sha256`` is enough to find the exact
body it stands behind.

Stdlib only, like every other module under ``agent-runtime/scripts/ci/``.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

#: Env var that relocates the archive. Set to an absolute path.
ARCHIVE_DIR_ENV = "JULI_ARTIFACT_ARCHIVE_DIR"

#: Directory name created under the repository's common git dir.
ARCHIVE_DIR_NAME = "artifact-archive"

#: The directory names under ``agent-runtime/artifacts/`` whose contents
#: ``.gitignore`` keeps out of every commit. Kept in step with
#: ``artifact_ref_resolution.POLICY_LOCAL_BODY_DIRS`` -- a test cross-checks the
#: two lists against each other and against ``git check-ignore`` on the real tree,
#: so neither can drift without going red.
BODY_DIR_NAMES = (
    "reviews",
    "implementations",
    "intent-reviews",
    "validation",
    "optimization",
)

_ARTIFACTS_ANCHOR = ("agent-runtime", "artifacts")


class ArtifactArchiveError(RuntimeError):
    """The archive copy could not be made.

    Raised, never swallowed: a body that could not be archived is exactly the
    data-loss condition this module exists to prevent, and a silent skip would
    reproduce it with a green log. The caller (``common.write_json``) lets it
    propagate so the emitting generator fails loudly at emit time, while the body
    is still reproducible, instead of at worktree-removal time when it is not.
    """


def body_relative_path(path: Path) -> str | None:
    """Return ``path``'s repo-relative posix path if it is a policy-local body.

    The repository root is implied by the path itself -- the
    ``agent-runtime/artifacts/<body-dir>/`` anchor -- rather than by a module
    constant, so this works identically for the real tree, a linked worktree, and
    a synthetic tree built by a test. Returns ``None`` for anything else,
    including ``agent-runtime/artifacts/status/`` (tracked, already durable) and
    the audit/cache outputs that share the writer.
    """
    parts = path.parts
    for index in range(len(parts) - 3):
        if parts[index : index + 2] != _ARTIFACTS_ANCHOR:
            continue
        if parts[index + 2] in BODY_DIR_NAMES:
            return "/".join(parts[index:])
    return None


def repo_root_for_body(path: Path) -> Path | None:
    """Return the checkout root implied by a policy-local body path."""
    rel = body_relative_path(path)
    if rel is None:
        return None
    return Path(str(path)[: -(len(rel) + 1)])


def archive_root(repo_root: Path | None = None) -> Path:
    """Resolve the durable archive directory for ``repo_root``.

    Order: ``JULI_ARTIFACT_ARCHIVE_DIR`` -> the repository's common git dir ->
    ``<repo_root>/.git/<ARCHIVE_DIR_NAME>``. The last is a fallback for a tree
    that is not a git checkout (a tarball, a synthetic fixture); it is still
    outside ``agent-runtime/artifacts`` and still shared by linked worktrees when
    one exists.
    """
    override = os.environ.get(ARCHIVE_DIR_ENV)
    if override:
        return Path(override).expanduser()
    if repo_root is None:
        raise ArtifactArchiveError(
            f"no repo root to resolve an archive for, and {ARCHIVE_DIR_ENV} is unset"
        )
    return _common_git_dir(repo_root) / ARCHIVE_DIR_NAME


#: Memoised per checkout root. A checkout's common git dir cannot change while
#: the process runs, and a generator that emits several bodies would otherwise
#: pay one ``git rev-parse`` subprocess per write.
_COMMON_GIT_DIR_CACHE: dict[str, Path] = {}


def _common_git_dir(repo_root: Path) -> Path:
    """The ``.git`` directory shared by the main checkout and every worktree.

    In a linked worktree ``--git-dir`` is ``.git/worktrees/<name>`` -- which
    ``git worktree remove`` deletes -- so the *common* dir is the load-bearing
    one here. Resolved relative to ``repo_root`` because git prints a relative
    path when run from the main checkout.
    """
    key = str(repo_root)
    cached = _COMMON_GIT_DIR_CACHE.get(key)
    if cached is not None:
        return cached
    resolved = _resolve_common_git_dir(repo_root)
    _COMMON_GIT_DIR_CACHE[key] = resolved
    return resolved


def _resolve_common_git_dir(repo_root: Path) -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, ValueError):
        return repo_root / ".git"
    out = proc.stdout.strip()
    if proc.returncode != 0 or not out:
        return repo_root / ".git"
    candidate = Path(out)
    if not candidate.is_absolute():
        candidate = repo_root / candidate
    return candidate.resolve()


def archived_copy_path(rel: str, digest: str, root: Path) -> Path:
    """Content-addressed destination for one body version inside ``root``."""
    body = Path(rel)
    # Drop the shared "agent-runtime/artifacts" prefix: the archive holds nothing
    # else, so repeating it in every path buys no disambiguation.
    tail = Path(*body.parts[len(_ARTIFACTS_ANCHOR) :])
    return root / tail.parent / f"{tail.stem}.{digest[:12]}{tail.suffix}"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_archived(path: Path, *, root: Path | None = None) -> bool:
    """True when this exact body content already has a durable copy."""
    rel = body_relative_path(path)
    if rel is None:
        return True  # not a policy-local body; nothing to archive
    if not path.is_file():
        return True
    try:
        digest = sha256_of(path)
        target_root = root if root is not None else archive_root(repo_root_for_body(path))
        return archived_copy_path(rel, digest, target_root).is_file()
    except (OSError, ArtifactArchiveError):
        return False


def archive_body(path: Path, *, root: Path | None = None) -> Path | None:
    """Copy one just-emitted artifact body to the durable archive.

    Returns the archived path, or ``None`` when ``path`` is not one of the five
    policy-local body directories (the common case for this writer: status
    records, audit outputs, workflow caches). Idempotent -- re-emitting identical
    content resolves to the same content-addressed name and is a no-op.
    """
    rel = body_relative_path(path)
    if rel is None:
        return None
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ArtifactArchiveError(f"could not read {path} to archive it: {exc}") from exc
    digest = hashlib.sha256(payload).hexdigest()
    target_root = root if root is not None else archive_root(repo_root_for_body(path))
    destination = archived_copy_path(rel, digest, target_root)
    if destination.is_file():
        return destination
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Write via a temp name in the same directory then rename, so a crash
        # mid-copy cannot leave a truncated file sitting at a name that claims
        # to hash to `digest`.
        staging = destination.with_name(f".{destination.name}.partial")
        staging.write_bytes(payload)
        staging.replace(destination)
    except OSError as exc:
        raise ArtifactArchiveError(
            f"could not archive {path} to {destination}: {exc} — the body would exist "
            "only inside this worktree, which is the data-loss condition this check "
            "exists to prevent"
        ) from exc
    return destination
