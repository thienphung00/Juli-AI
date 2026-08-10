"""Release-worktree pruning must never delete a directory a service is live on.

Regression for the 2026-08-07 `demo.app-juli.com` incident: the Demo page kept
returning 200 while 9 of its 11 hashed chunks returned 500, because
``deploy-release.sh`` pruned the release worktree that ``~/releases/demo-current``
pointed at while ``juli-demo`` was still serving from it. ``next start`` answers
500 (not 404) for a chunk that is in the build manifest but missing on disk, so
the page rendered with no CSS and no JavaScript.

Two independent defects produced it, and both are covered here:

1. ``deploy-release.sh`` protected only its own new ``release_dir`` -- not
   ``~/releases/current`` and not ``~/releases/demo-current``.
2. Both scripts picked prune victims with ``sort -r`` over the *path*, i.e.
   lexicographic short-SHA order rather than deploy recency, so "keep the last
   3" kept an arbitrary 3 and could delete the newest release or the previous
   one that ``rollback-release.sh`` resolves as its default target.
"""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_PATH = REPO_ROOT / "infra/scripts/lib/prune-releases.sh"
DEPLOY_SCRIPT = REPO_ROOT / "infra/scripts/deploy.sh"
DEMO_DEPLOY_SCRIPT = REPO_ROOT / "infra/scripts/deploy-demo-release.sh"

# Deliberately chosen so lexicographic order disagrees with deploy order:
# the live Demo release sorts *first* (so `sort -r | tail` prunes it first),
# and the newest App Review release sorts in the middle.
DEMO_LIVE = "aaa111"
OLDEST = "bbb222"
STALE = "ccc333"
WEB_PREVIOUS = "ddd444"
WEB_LIVE = "eee555"

GIT_STUB = """\
#!/usr/bin/env bash
# Minimal `git worktree` stub: lists real directories under RELEASES_ROOT and
# removes them on `worktree remove`. Mirrors how the real command behaves for
# the two subcommands the prune helper uses.
set -euo pipefail
if [ "${1:-}" = "-C" ]; then shift 2; fi
[ "${1:-}" = "worktree" ] || exit 0
case "${2:-}" in
    list)
        for d in "${RELEASES_ROOT}"/*; do
            [ -d "${d}" ] || continue
            [ -L "${d}" ] && continue
            printf 'worktree %s\\n\\n' "${d}"
        done
        ;;
    remove)
        target="${4:-}"
        printf '%s\\n' "${target}" >> "${STUB_REMOVE_LOG}"
        rm -rf "${target}"
        ;;
esac
"""


@pytest.fixture
def releases_root(tmp_path: Path) -> Path:
    """A fake ~/releases with five worktrees and two live symlinks."""
    root = tmp_path / "releases"
    root.mkdir()

    for name in (DEMO_LIVE, OLDEST, STALE, WEB_PREVIOUS, WEB_LIVE):
        # A file per release stands in for the built .next/static chunks whose
        # disappearance produced the 500s.
        (root / name / "apps").mkdir(parents=True)
        (root / name / "apps" / "chunk.js").write_text("built", encoding="utf-8")

    (root / "current").symlink_to(root / WEB_LIVE)
    (root / "demo-current").symlink_to(root / DEMO_LIVE)

    # App Review history: oldest -> newest.
    (root / "deploy-history.log").write_text(
        "".join(
            f"2026-08-0{i}T00:00:00Z sha{name} {root / name}\n"
            for i, name in enumerate((OLDEST, STALE, WEB_PREVIOUS, WEB_LIVE), start=1)
        ),
        encoding="utf-8",
    )
    # Demo history: the live Demo release is the only entry, and it is the
    # lexicographically smallest directory in the whole set.
    (root / "demo-deploy-history.log").write_text(
        f"2026-08-01T00:00:00Z sha{DEMO_LIVE} {root / DEMO_LIVE}\n",
        encoding="utf-8",
    )
    return root


def _run_prune(releases_root: Path, tmp_path: Path, keep: int = 2, new_release: str = "") -> str:
    """Source the shared helper and run one prune against the fake releases root."""
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    git_stub = bindir / "git"
    git_stub.write_text(GIT_STUB, encoding="utf-8")
    git_stub.chmod(0o755)

    remove_log = tmp_path / "removed.txt"
    remove_log.write_text("", encoding="utf-8")

    release_dir = str(releases_root / new_release) if new_release else ""
    driver = tmp_path / "driver.sh"
    driver.write_text(
        textwrap.dedent(f"""\
            set -euo pipefail
            export PATH="{bindir}:$PATH"
            export RELEASES_ROOT="{releases_root}"
            export STUB_REMOVE_LOG="{remove_log}"
            source "{LIB_PATH}"
            prune_release_worktrees "{tmp_path}" "{releases_root}" "{keep}" "{release_dir}"
        """),
        encoding="utf-8",
    )

    result = subprocess.run(["/bin/bash", str(driver)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"prune failed ({result.returncode}): {result.stderr}"
    return result.stdout


def test_prune_helper_exists():
    assert LIB_PATH.is_file(), f"{LIB_PATH} does not exist"


def test_prune_never_removes_the_live_demo_release(releases_root: Path, tmp_path: Path):
    """The incident itself: pruning must not delete ~/releases/demo-current's target.

    DEMO_LIVE sorts first lexicographically, so the old `sort -r | tail` logic
    selected it as the oldest victim even though juli-demo was serving from it.
    """
    _run_prune(releases_root, tmp_path)

    live = releases_root / DEMO_LIVE
    assert live.is_dir(), "pruned the release worktree juli-demo is live on"
    assert (live / "apps" / "chunk.js").is_file(), (
        "live Demo release lost its built assets -- this is the state that made "
        "next start return 500 for every hashed chunk still in the build manifest"
    )


def test_prune_never_removes_the_live_web_release(releases_root: Path, tmp_path: Path):
    """~/releases/current's target backs juli-api and juli-web."""
    _run_prune(releases_root, tmp_path)
    assert (releases_root / WEB_LIVE).is_dir(), "pruned the live App Review release"


def test_prune_keeps_the_default_rollback_target(releases_root: Path, tmp_path: Path):
    """rollback-release.sh with no argument resolves the previous history entry.

    If pruning deletes it, rollback fails exactly when it is needed most.
    """
    _run_prune(releases_root, tmp_path)
    assert (releases_root / WEB_PREVIOUS).is_dir(), (
        "pruned the previous release; `rollback-release.sh` with no argument "
        "would resolve a directory that no longer exists"
    )


def test_prune_still_removes_genuinely_stale_releases(releases_root: Path, tmp_path: Path):
    """Retention must stay real -- protection must not mean 'never delete'."""
    _run_prune(releases_root, tmp_path)
    assert not (releases_root / OLDEST).exists(), (
        "nothing was pruned; retention must still bound disk growth"
    )


def test_prune_protects_a_newly_deployed_release_absent_from_history(
    releases_root: Path, tmp_path: Path
):
    """The just-built release is passed explicitly and is not yet in any log."""
    fresh = "fff666"
    (releases_root / fresh / "apps").mkdir(parents=True)
    _run_prune(releases_root, tmp_path, new_release=fresh)
    assert (releases_root / fresh).is_dir(), "pruned the release that was just deployed"


def test_prune_protects_every_current_symlink_including_future_lanes(
    releases_root: Path, tmp_path: Path
):
    """Protection is derived from the *-current symlinks, not a hardcoded list.

    apps/landing gets a `landing-current` symlink when it is deployed; the
    helper must protect it without another edit to this logic.
    """
    (releases_root / "landing-current").symlink_to(releases_root / OLDEST)
    _run_prune(releases_root, tmp_path)
    assert (releases_root / OLDEST).is_dir(), "a new lane's *-current symlink was not protected"


def test_prune_is_a_no_op_when_no_history_log_exists(releases_root: Path, tmp_path: Path):
    """A box with no deploy history has no recency signal, so deleting is unsafe."""
    (releases_root / "deploy-history.log").unlink()
    (releases_root / "demo-deploy-history.log").unlink()

    output = _run_prune(releases_root, tmp_path)

    for name in (DEMO_LIVE, OLDEST, STALE, WEB_PREVIOUS, WEB_LIVE):
        assert (releases_root / name).is_dir(), f"{name} pruned without any deploy history"
    assert "SKIP" in output.upper(), "a skipped prune must say so"


def test_prune_reports_what_it_keeps_and_removes(releases_root: Path, tmp_path: Path):
    """Operators reading deploy logs need the retention decision to be visible."""
    output = _run_prune(releases_root, tmp_path)
    assert "KEEP" in output.upper()
    assert DEMO_LIVE in output and OLDEST in output


@pytest.mark.parametrize("script", [DEPLOY_SCRIPT, DEMO_DEPLOY_SCRIPT])
def test_deploy_scripts_use_the_shared_helper_and_not_lexicographic_sort(script: Path):
    """Neither script may keep its own path-sorted prune loop."""
    text = script.read_text(encoding="utf-8")
    assert "lib/prune-releases.sh" in text, f"{script.name} does not source the shared helper"
    assert "prune_release_worktrees" in text, f"{script.name} does not call the shared helper"
    assert "sort -r" not in text, (
        f"{script.name} still orders prune candidates lexicographically by path; "
        "short SHAs do not sort by deploy time"
    )


@pytest.mark.parametrize("script", [DEPLOY_SCRIPT, DEMO_DEPLOY_SCRIPT, LIB_PATH])
def test_shell_sources_parse(script: Path):
    result = subprocess.run(
        ["/bin/bash", "-n", str(script)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, f"{script.name} is not valid bash: {result.stderr}"
