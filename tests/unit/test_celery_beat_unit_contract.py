"""Contract tests for the Celery Beat systemd unit.

Beat's persistent schedule records when each entry last ran. Celery writes it to
`celerybeat-schedule` in the working directory unless `--schedule` says otherwise.

The unit's WorkingDirectory is `/root/releases/current`, a symlink into a
per-release directory that flips on every deploy and is pruned by KEEP_RELEASES.
Leaving the schedule there puts beat's state inside a directory that disappears
underneath it — and a beat that stops firing produces no error at all. It simply
does nothing, which is indistinguishable from "nothing was due".
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
UNIT_PATH = REPO_ROOT / "infra/systemd/juli-celery-beat.service"


@pytest.fixture
def unit_text() -> str:
    return UNIT_PATH.read_text(encoding="utf-8")


def test_unit_exists():
    assert UNIT_PATH.exists(), f"{UNIT_PATH} is missing"


def test_schedule_path_is_explicit(unit_text: str):
    assert "--schedule=" in unit_text, (
        "beat must be given an explicit --schedule path; the default lands in "
        "WorkingDirectory, which is a release directory"
    )


def test_schedule_path_is_outside_the_release_tree(unit_text: str):
    """The whole point: release dirs are flipped and pruned, so state cannot live there."""
    line = next(ln for ln in unit_text.splitlines() if "--schedule=" in ln)
    path = line.split("--schedule=", 1)[1].split()[0].rstrip("\\").strip()
    assert not path.startswith("/root/releases"), (
        f"schedule path {path} is inside the release tree and will be pruned"
    )
    assert path.startswith("/"), "schedule path must be absolute"


def test_schedule_directory_is_created_before_start(unit_text: str):
    """A missing directory would make beat fail to start after a fresh provision."""
    line = next(ln for ln in unit_text.splitlines() if "--schedule=" in ln)
    path = line.split("--schedule=", 1)[1].split()[0].rstrip("\\").strip()
    parent = str(Path(path).parent)
    assert f"mkdir -p {parent}" in unit_text, (
        f"unit must create {parent} in an ExecStartPre before beat starts"
    )


def test_mkdir_precedes_the_secrets_fetch(unit_text: str):
    """ExecStartPre runs in order; the directory must exist before anything needs it."""
    lines = [ln for ln in unit_text.splitlines() if ln.startswith("ExecStartPre=")]
    assert len(lines) >= 2, "expected both the mkdir and the secrets ExecStartPre"
    assert "mkdir" in lines[0], "mkdir should be the first ExecStartPre"


def test_still_restarts_on_failure(unit_text: str):
    """Guard the existing behaviour while changing the schedule path."""
    assert "Restart=on-failure" in unit_text
    assert "EnvironmentFile=/etc/juli/api.env" in unit_text
