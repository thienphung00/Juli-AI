"""rollback.yml is the fast-track rollback path (fast-track P56, D65).

Before P56 it ran `git checkout main && git pull` in the VPS clone and then the old
rollback script, which restarted the retired juli-web and waited for :3000 -- it had
never run, and would have failed its health check after moving production's clone to
frozen `main`. These tests pin the replacement: it never moves the clone, shares the
deploy's concurrency group, only passes hex to the VPS, and never touches the database.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ROLLBACK_YML = REPO_ROOT / ".github/workflows/rollback.yml"
DEPLOY_YML = REPO_ROOT / ".github/workflows/fasttrack-deploy.yml"
ROLLBACK_SH = REPO_ROOT / "infra/scripts/rollback-release.sh"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def wf() -> dict:
    return _load(ROLLBACK_YML)


def _triggers(doc: dict) -> dict:
    # PyYAML reads the bare key `on` as boolean True.
    return doc.get("on") or doc.get(True)


def _vps_script(wf: dict) -> str:
    steps = wf["jobs"]["rollback"]["steps"]
    return next(s for s in steps if "ssh-action" in s.get("uses", ""))["with"]["script"]


def test_shares_the_deploy_concurrency_group_and_never_cancels(wf: dict):
    deploy = _load(DEPLOY_YML)
    assert wf["concurrency"] == deploy["concurrency"]
    assert wf["concurrency"]["cancel-in-progress"] is False


def test_triggers_are_a_rollback_tag_or_a_dispatch_never_a_branch_push(wf: dict):
    on = _triggers(wf)
    assert on["push"] == {"tags": ["fasttrack-rollback-*"]}
    assert "workflow_dispatch" in on
    assert on["workflow_dispatch"]["inputs"]["action"]["default"] == "plan"


def test_the_vps_clone_is_never_moved(wf: dict):
    script = _vps_script(wf)
    for forbidden in ("git checkout", "git pull", "git fetch", "git reset", "deploy.sh"):
        assert forbidden not in script, forbidden
    assert "./infra/scripts/rollback-release.sh" in script


def test_refuses_a_clone_with_the_pre_p56_script(wf: dict):
    script = _vps_script(wf)
    assert "grep -q '^ROLLBACK_INTERFACE=2$' infra/scripts/rollback-release.sh" in script
    assert "\nROLLBACK_INTERFACE=2\n" in ROLLBACK_SH.read_text(encoding="utf-8")


def test_runs_in_the_production_environment(wf: dict):
    assert wf["jobs"]["rollback"]["environment"] == "production"


def test_never_touches_the_database_or_juli_web():
    text = ROLLBACK_YML.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    for needle in ("pg_restore", "pg_dump", "psql", "alembic", "juli-web", ":3000"):
        assert needle not in body, needle


# --------------------------------------------------------------------------------------
# The resolve step, executed with a stub git: tag name -> action/target.
# --------------------------------------------------------------------------------------

GIT_STUB = """#!/bin/sh
case "$1" in
  fetch) exit 0 ;;
  merge-base) [ -f "$STUB_NOT_ON_BRANCH" ] && exit 1; exit 0 ;;
  rev-parse)
    for a in "$@"; do
      case "$a" in
        refs/tags/fasttrack-deploy-*) echo 0123456789abcdef0123456789abcdef01234567; exit 0 ;;
      esac
    done
    echo fedcba9876543210fedcba9876543210fedcba98 ;;
esac
"""


def _resolve(wf: dict, tmp_path: Path, **env: str) -> tuple[int, dict, str]:
    step = next(s for s in wf["jobs"]["resolve"]["steps"] if s.get("id") == "resolve")
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    (bindir / "git").write_text(GIT_STUB)
    (bindir / "git").chmod(0o755)
    out = tmp_path / "out"
    out.write_text("")
    full_env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GITHUB_OUTPUT": str(out),
        "FASTTRACK_BRANCH": "fasttrack/optimize-product",
        "STUB_NOT_ON_BRANCH": str(tmp_path / "not-on-branch"),
        "IN_ACTION": "",
        "IN_TARGET": "",
        **env,
    }
    proc = subprocess.run(["bash", "-c", step["run"]], env=full_env, capture_output=True, text=True)
    outputs = dict(line.split("=", 1) for line in out.read_text().splitlines() if "=" in line)
    return proc.returncode, outputs, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("tag", "action", "target"),
    [
        ("fasttrack-rollback-20261019T2200Z", "rollback", ""),
        ("fasttrack-rollback-20261019T2200Z-to-abc1234", "rollback", "abc1234"),
        ("fasttrack-rollback-plan-20261019T2200Z", "plan", ""),
        ("fasttrack-rollback-plan-20261019T2200Z-to-abc1234", "plan", "abc1234"),
        (
            "fasttrack-rollback-20261019T2200Z-to-fasttrack-deploy-20261018T1000Z",
            "rollback",
            "0123456789abcdef0123456789abcdef01234567",
        ),
    ],
)
def test_tag_names_resolve(wf: dict, tmp_path: Path, tag: str, action: str, target: str):
    code, outputs, log = _resolve(wf, tmp_path, REF=f"refs/tags/{tag}", EVENT="push")
    assert code == 0, log
    assert outputs == {"action": action, "target": target}


def test_dispatch_inputs_resolve(wf: dict, tmp_path: Path):
    code, outputs, log = _resolve(
        wf,
        tmp_path,
        REF="refs/heads/fasttrack/optimize-product",
        EVENT="workflow_dispatch",
        IN_ACTION="verify",
        IN_TARGET="",
    )
    assert code == 0, log
    assert outputs == {"action": "verify", "target": ""}


@pytest.mark.parametrize(
    "env",
    [
        {"REF": "refs/heads/main", "EVENT": "workflow_dispatch", "IN_ACTION": "rollback"},
        {
            "REF": "refs/heads/fasttrack/optimize-product",
            "EVENT": "workflow_dispatch",
            "IN_ACTION": "rollback",
            "IN_TARGET": "main; rm -rf /",
        },
        {
            "REF": "refs/heads/fasttrack/optimize-product",
            "EVENT": "workflow_dispatch",
            "IN_ACTION": "destroy",
        },
        {"REF": "refs/tags/fasttrack-rollback-x-to-HEAD", "EVENT": "push"},
    ],
)
def test_bad_refs_actions_and_targets_are_refused(wf: dict, tmp_path: Path, env: dict):
    code, outputs, log = _resolve(wf, tmp_path, **env)
    assert code != 0, log
    assert "action" not in outputs


def test_a_tag_off_the_branch_is_refused(wf: dict, tmp_path: Path):
    (tmp_path / "not-on-branch").write_text("")
    code, _, log = _resolve(wf, tmp_path, REF="refs/tags/fasttrack-rollback-1", EVENT="push")
    assert code != 0, log
    assert "is not on origin/fasttrack/optimize-product" in log
