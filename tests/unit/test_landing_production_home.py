"""#841 — the landing page's first production home, on its own port.

Pins the port contract (unique host-wide, consistent between dev and production),
the unit's lifecycle guarantees, and the deploy script's independence from every
other service. The lane is deliberately simple — paired slots arrive with #843 —
so these tests focus on what #841 actually promises.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT = REPO_ROOT / "infra" / "systemd" / "juli-landing.service"
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "deploy-landing-release.sh"
PACKAGE_JSON = REPO_ROOT / "apps" / "landing" / "package.json"

LANDING_PORT = "3007"
RESERVED_CANDIDATE_PORT = "3027"


def run_sourced(body: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    snippet = (
        f'set -uo pipefail\nexport LANDING_DEPLOY_SOURCE_ONLY=1\nsource "{DEPLOY_SCRIPT}"\n{body}\n'
    )
    full_env = {**os.environ, "LANDING_DEPLOY_SOURCE_ONLY": "1"}
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env=full_env,
        cwd=str(REPO_ROOT),
    )


# --- the port contract -----------------------------------------------------------------


def test_unit_serves_the_port_the_app_already_encodes() -> None:
    """One number everywhere: production adopts the port package.json names, so dev
    and prod cannot disagree about where Landing lives."""
    unit = UNIT.read_text(encoding="utf-8")
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    assert f"--port {LANDING_PORT}" in unit
    assert LANDING_PORT in package["scripts"]["start"], (
        "apps/landing package.json and the systemd unit name different ports"
    )


def test_landing_port_is_unique_across_every_infra_surface() -> None:
    """No other unit, vhost, or deploy script may claim 3007 (or reserved 3027)."""
    claims: list[str] = []
    for path in sorted((REPO_ROOT / "infra").rglob("*")):
        if not path.is_file() or "landing" in path.name:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for port in (LANDING_PORT, RESERVED_CANDIDATE_PORT):
            if re.search(rf"(?<![0-9]){port}(?![0-9])", text):
                claims.append(f"{path.relative_to(REPO_ROOT)}: {port}")
    assert not claims, f"Landing's ports are claimed elsewhere: {claims}"


def test_unit_binds_loopback_only() -> None:
    """#841 gives Landing a port, not a domain — the main-domain repoint is #842."""
    unit = UNIT.read_text(encoding="utf-8")
    assert "--hostname 127.0.0.1" in unit


# --- lifecycle guarantees --------------------------------------------------------------


def test_unit_starts_on_boot_and_restarts_on_failure() -> None:
    unit = UNIT.read_text(encoding="utf-8")
    assert "WantedBy=multi-user.target" in unit
    assert "Restart=on-failure" in unit
    assert "WorkingDirectory=/root/releases/landing-current/apps/landing" in unit


# --- deploy independence ---------------------------------------------------------------


def _non_comment_source() -> str:
    lines = DEPLOY_SCRIPT.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_deploy_never_touches_another_service() -> None:
    """AC: deploys without touching the API or Demo. The only unit this script may
    act on is its own — the host port map in the header may NAME the others, but no
    executable line may reference them."""
    source = _non_comment_source()
    for foreign in ("juli-api", "juli-demo", "juli-web", "juli-celery"):
        assert foreign not in source, f"landing deploy must not reference {foreign}"


def test_deploy_functions_exist_in_library_mode() -> None:
    result = run_sourced("declare -F fetch_landing_artifact place_landing_artifact verify_landing")
    assert result.returncode == 0, result.stderr


def test_artifact_name_matches_what_ci_publishes() -> None:
    """release.yml publishes juli-landing-<short7>; the deploy must ask for exactly
    that, or every deploy dies at download."""
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'name="juli-landing-${short7}"' in source
    workflow = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "juli-${{ matrix.app }}-$short" in workflow
    assert "app: [demo, landing]" in workflow


def test_placement_rejects_a_commit_mismatch(tmp_path: Path) -> None:
    """ADR-058 provenance: an artifact recording a different commit must be refused."""
    import tarfile

    stage = tmp_path / "juli-landing-abc1234"
    stage.mkdir()
    (stage / "release-artifact.json").write_text(json.dumps({"commit": "someone-elses-sha"}))
    tarball = tmp_path / "juli-landing-abc1234.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(stage, arcname=stage.name)

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    result = run_sourced(
        f'place_landing_artifact "{tarball}" "{release_dir}" "the-sha-being-deployed"'
    )
    assert result.returncode != 0, result.stdout
    assert "records commit" in result.stderr
    assert not (release_dir / "apps" / "landing").exists()


def test_placement_rejects_an_artifact_without_a_runnable_build(tmp_path: Path) -> None:
    import tarfile

    stage = tmp_path / "juli-landing-abc1234"
    stage.mkdir()
    (stage / "release-artifact.json").write_text(json.dumps({"commit": "sha-x"}))
    tarball = tmp_path / "juli-landing-abc1234.tar.gz"
    with tarfile.open(tarball, "w:gz") as tar:
        tar.add(stage, arcname=stage.name)

    release_dir = tmp_path / "release"
    release_dir.mkdir()
    result = run_sourced(f'place_landing_artifact "{tarball}" "{release_dir}" "sha-x"')
    assert result.returncode != 0, result.stdout
    assert "no runnable next binary" in result.stderr


def test_main_flow_verifies_before_declaring_success() -> None:
    """Wiring pin: the #833 harness must run in the deploy path, after the restart."""
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert 'verify_landing "http://127.0.0.1:${LANDING_PORT}"' in source
    restart_at = source.index('systemctl restart "${LANDING_UNIT}"')
    verify_at = source.index('verify_landing "http://127.0.0.1:${LANDING_PORT}"')
    assert restart_at < verify_at, "verification must run against the restarted instance"


def test_prune_runs_only_after_a_recorded_success() -> None:
    """The shared release pool's prior corruption came from pruning too eagerly."""
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    record_at = source.index('>> "${HISTORY_LOG}"')
    prune_at = source.index("prune_release_worktrees")
    assert record_at < prune_at
