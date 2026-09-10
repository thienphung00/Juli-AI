"""The demo lane measures pending migrations from the API lane's release (#1882).

The demo lane never applies a migration — the API lane does. Measuring from the
demo lane's OWN live release therefore asks a question the answer to which says
nothing about the database, and the error is unbounded: every release that
leaves `apps/demo` untouched skips the lane, so its baseline drifts further from
what has actually been applied.

That is not hypothetical. Every release from 2026-09-07 skipped the demo lane.
When W6 finally touched `apps/demo`, the lane looked back four days and
re-proposed `056_series_source_column` — data-moving and NOT NULL-adding, and
already applied. The gate refused the release, `demo.app-juli.com` stayed on a
four-day-old build, and the W6 exit gate (#1322) could not be walked at all.

A lane became undeployable purely by not being deployed.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "deploy-demo-release.sh"


def run_sourced(body: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Source the deploy script in library mode and run `body` against its functions."""
    assert DEPLOY_SCRIPT.is_file(), f"{DEPLOY_SCRIPT} is missing"
    snippet = (
        f'set -uo pipefail\nexport DEMO_DEPLOY_SOURCE_ONLY=1\nsource "{DEPLOY_SCRIPT}"\n{body}\n'
    )
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env={**os.environ, "DEMO_DEPLOY_SOURCE_ONLY": "1", **env},
        cwd=str(REPO_ROOT),
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def lanes(tmp_path: Path) -> dict[str, str]:
    """Two release worktrees of one repo: an API lane ahead, a demo lane behind.

    This is the production shape that broke — `current` (api) at a commit whose
    migrations are applied, `demo-current` several commits behind it.
    """
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")

    versions = repo / "backend/src/juli_backend/database/migrations/versions"
    versions.mkdir(parents=True)
    (versions / "001_base.py").write_text("def upgrade():\n    pass\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    stale = _git(repo, "rev-parse", "HEAD")

    # A destructive migration lands and is applied by the API lane.
    (versions / "056_series_source.py").write_text(
        'def upgrade():\n    op.execute("UPDATE t SET c = 1")\n', encoding="utf-8"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "056")
    applied = _git(repo, "rev-parse", "HEAD")

    # A later commit touches only the demo app — no new migration.
    (repo / "apps").mkdir()
    (repo / "apps/demo.txt").write_text("w6\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "w6 demo change")
    target = _git(repo, "rev-parse", "HEAD")

    releases = tmp_path / "releases"
    releases.mkdir()
    for name, sha in (("api", applied), ("demo", stale)):
        wt = releases / sha[:8] if name == "api" else releases / f"{sha[:8]}-demo"
        _git(repo, "worktree", "add", "--force", "-q", str(wt), sha)
    (releases / "current").symlink_to(releases / applied[:8])
    (releases / "demo-current").symlink_to(releases / f"{stale[:8]}-demo")

    return {
        "RELEASES_ROOT": str(releases),
        "_repo": str(repo),
        "_stale": stale,
        "_applied": applied,
        "_target": target,
    }


def test_baseline_is_the_api_lane_not_this_lane(lanes: dict[str, str]) -> None:
    """The regression itself: the baseline must come from the lane that applies
    migrations, not from the one that never does."""
    result = run_sourced("migration_baseline_commit", {"RELEASES_ROOT": lanes["RELEASES_ROOT"]})

    assert result.returncode == 0, result.stderr
    resolved = result.stdout.strip()
    assert resolved == lanes["_applied"], (
        f"resolved {resolved[:9]}, expected the API lane's {lanes['_applied'][:9]}. "
        f"The demo lane's own release is {lanes['_stale'][:9]} — measuring from it "
        f"re-proposes every migration applied since, which is the #1882 defect."
    )
    assert resolved != lanes["_stale"]


def test_falls_back_to_this_lane_when_no_api_release_exists(lanes: dict[str, str]) -> None:
    """A fresh box has no API release. Falling back to the demo lane's own is
    narrower than nothing, and is what shipped before this fix — so the fallback
    cannot be worse than the previous behaviour."""
    os.remove(Path(lanes["RELEASES_ROOT"]) / "current")

    result = run_sourced("migration_baseline_commit", {"RELEASES_ROOT": lanes["RELEASES_ROOT"]})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == lanes["_stale"]


def test_an_explicit_operator_override_still_wins(lanes: dict[str, str]) -> None:
    """`DEMO_MIGRATION_GATE_BASE_SHA` is the break-glass an operator used to get
    the blocked W6 release out. It must keep working, and must beat the
    automatic baseline."""
    body = (
        'base="${DEMO_MIGRATION_GATE_BASE_SHA:-}"\n'
        'if [ -z "$base" ]; then base="$(migration_baseline_commit || true)"; fi\n'
        'printf "%s\\n" "$base"'
    )
    result = run_sourced(
        body,
        {
            "RELEASES_ROOT": lanes["RELEASES_ROOT"],
            "DEMO_MIGRATION_GATE_BASE_SHA": lanes["_stale"],
        },
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == lanes["_stale"]
