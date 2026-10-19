"""P19: deploy.sh refuses a release whose Juli Ops would be dead on arrival.

Two incidents, one check each, both inside the API lane before the candidate starts:

* 2A — api.env regenerated from the AWS secret without CF_ACCESS_TEAM_DOMAIN /
  CF_ACCESS_AUD, so every /v1/ops/* request became 403 "Cloudflare Access is not
  configured". `require_cf_access_env` refuses that env file, naming only the keys.
* 4A — the runtime role lacked juli_ops membership, so SET LOCAL ROLE juli_ops failed
  on every Ops request. `require_ops_role_grant` (via safe_alembic_helpers.py
  verify-ops-role-grant) refuses and prints the exact GRANT line.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "infra" / "scripts" / "deploy.sh"
SCRIPTS_DIR = REPO_ROOT / "infra" / "scripts"


def _helpers():
    """infra/scripts/safe_alembic_helpers.py, imported once its directory is on sys.path."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    return importlib.import_module("safe_alembic_helpers")


_decide_ops_role_grant = _helpers()._decide_ops_role_grant
verify_ops_role_grant = _helpers().verify_ops_role_grant

SECRET_VALUE = "aud-value-that-must-never-be-printed"


def run_sourced(body: str) -> subprocess.CompletedProcess[str]:
    snippet = f'set -euo pipefail\nexport DEPLOY_SOURCE_ONLY=1\nsource "{DEPLOY}"\n{body}\n'
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={**os.environ, "DEPLOY_SOURCE_ONLY": "1"},
        cwd=str(REPO_ROOT),
    )


def _env_file(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "api.env"
    path.write_text(text, encoding="utf-8")
    return path


# -- 2A: Cloudflare Access keys -----------------------------------------------------


@pytest.mark.parametrize(
    ("content", "missing"),
    [
        ("CF_ACCESS_TEAM_DOMAIN=juli\nCF_ACCESS_AUD=abc\n", []),
        ("export CF_ACCESS_TEAM_DOMAIN=\"juli\"\nCF_ACCESS_AUD='abc'\n", []),
        ("DATABASE_URL=postgresql://u:p@h/db\n", ["CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD"]),
        ("CF_ACCESS_TEAM_DOMAIN=\nCF_ACCESS_AUD=abc\n", ["CF_ACCESS_TEAM_DOMAIN"]),
        ('CF_ACCESS_TEAM_DOMAIN=juli\nCF_ACCESS_AUD=""\n', ["CF_ACCESS_AUD"]),
        (
            "CF_ACCESS_TEAM_DOMAIN=REPLACE_TEAM\nCF_ACCESS_AUD=REPLACE_AUD_TAG\n",
            ["CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD"],
        ),
        ("# CF_ACCESS_TEAM_DOMAIN=juli\nCF_ACCESS_AUD=abc\n", ["CF_ACCESS_TEAM_DOMAIN"]),
        # last assignment wins, as with `source`
        ("CF_ACCESS_TEAM_DOMAIN=juli\nCF_ACCESS_AUD=abc\nCF_ACCESS_AUD=\n", ["CF_ACCESS_AUD"]),
        # a longer key with the same prefix is not the key
        ("CF_ACCESS_TEAM_DOMAIN=juli\nCF_ACCESS_AUD_OLD=abc\n", ["CF_ACCESS_AUD"]),
    ],
)
def test_cf_access_missing_keys(tmp_path: Path, content: str, missing: list[str]):
    env = _env_file(tmp_path, content)
    result = run_sourced(f'cf_access_missing_keys "{env}"')
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == missing


def test_missing_env_file_counts_as_missing(tmp_path: Path):
    result = run_sourced(f'cf_access_missing_keys "{tmp_path / "nope.env"}"')
    assert result.stdout.split() == ["CF_ACCESS_TEAM_DOMAIN", "CF_ACCESS_AUD"]


def test_require_cf_access_env_refuses_with_the_secret_fix_and_no_values(tmp_path: Path):
    env = _env_file(
        tmp_path,
        f"DATABASE_URL=postgresql://juli_app:hunter2@db/x\nCF_ACCESS_AUD={SECRET_VALUE}\n",
    )
    result = run_sourced(f'require_cf_access_env "{env}"')
    assert result.returncode == 1
    out = result.stdout + result.stderr
    assert "FAIL:" in out
    assert "has no usable CF_ACCESS_TEAM_DOMAIN —" in out
    assert "AWS secret juli/api/production" in out
    assert "never hand-edit api.env" in out
    assert SECRET_VALUE not in out
    assert "hunter2" not in out
    assert "postgresql://" not in out


def test_require_cf_access_env_passes_and_prints_no_values(tmp_path: Path):
    env = _env_file(tmp_path, f"CF_ACCESS_TEAM_DOMAIN=juli\nCF_ACCESS_AUD={SECRET_VALUE}\n")
    result = run_sourced(f'require_cf_access_env "{env}"')
    assert result.returncode == 0, result.stdout + result.stderr
    assert SECRET_VALUE not in result.stdout + result.stderr


# -- 4A: juli_ops membership --------------------------------------------------------


def _fake_release(tmp_path: Path, exit_code: int, stderr: str) -> Path:
    """A release dir whose .venv/bin/python stands in for the helper."""
    release = tmp_path / "release"
    bindir = release / ".venv" / "bin"
    bindir.mkdir(parents=True)
    message = release / "message.txt"
    message.write_text(stderr, encoding="utf-8")
    python = bindir / "python"
    python.write_text(
        "#!/usr/bin/env bash\n"
        '[ "$2" = "verify-ops-role-grant" ] || exit 99\n'
        f'cat "{message}" >&2\n'
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return release


def test_require_ops_role_grant_prints_the_grant_line(tmp_path: Path):
    message = (
        "the runtime database role 'juli_app' (the user in DATABASE_URL) is not a member "
        "of juli_ops ...\nGRANT juli_ops TO juli_app;\n"
    )
    release = _fake_release(tmp_path, 1, message)
    result = run_sourced(f'require_ops_role_grant "{release}"')
    assert result.returncode == 1
    assert "FAIL: juli_ops grant check refused the release" in result.stdout
    assert "GRANT juli_ops TO juli_app;" in result.stderr.splitlines()


def test_require_ops_role_grant_passes(tmp_path: Path):
    release = _fake_release(tmp_path, 0, "")
    result = run_sourced(f'require_ops_role_grant "{release}"')
    assert result.returncode == 0, result.stdout + result.stderr
    assert "member of juli_ops" in result.stdout


def test_decide_ops_role_grant_message_ends_with_the_exact_grant():
    with pytest.raises(RuntimeError) as caught:
        _decide_ops_role_grant("juli_app", ops_role_exists=True, is_member=False)
    assert str(caught.value).splitlines()[-1] == "GRANT juli_ops TO juli_app;"


def test_decide_ops_role_grant_missing_role_and_pass():
    with pytest.raises(RuntimeError, match="does not exist"):
        _decide_ops_role_grant("juli_app", ops_role_exists=False, is_member=False)
    _decide_ops_role_grant("juli_app", ops_role_exists=True, is_member=True)


def test_verify_ops_role_grant_needs_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="DATABASE_URL must be set"):
        verify_ops_role_grant()


def test_verify_ops_role_grant_hides_connection_details():
    url = "postgresql://juli_app:hunter2@127.0.0.1:1/nope"
    with pytest.raises(RuntimeError) as caught:
        verify_ops_role_grant(url)
    assert "hunter2" not in str(caught.value)
    assert "127.0.0.1" not in str(caught.value)


# -- ordering inside deploy_lane_api ------------------------------------------------


def test_preflights_run_in_the_api_lane_in_order():
    text = DEPLOY.read_text(encoding="utf-8")
    lane = text[text.index("deploy_lane_api() {") : text.index("deploy_lane_demo() {")]
    source_env = lane.index('source "${API_ENV_FILE}"')
    cf = lane.index('require_cf_access_env "${API_ENV_FILE}"')
    gate = lane.index("current-revision")
    upgrade = lane.index('"${CANONICAL_ROOT}/infra/scripts/safe-alembic-upgrade.sh"')
    grant = lane.index('require_ops_role_grant "${release_dir}"')
    candidate = lane.index('systemd-run --unit="juli-api-candidate-')
    assert source_env < cf < gate < upgrade < grant < candidate
