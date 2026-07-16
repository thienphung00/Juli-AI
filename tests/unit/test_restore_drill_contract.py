"""Doc and systemd contract tests for weekly restore drill (#421)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSTEMD_DIR = REPO_ROOT / "infra/systemd"
RUNBOOK_PATH = REPO_ROOT / "docs/runbooks/app-review-runbook.md"


@pytest.fixture
def runbook_text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def test_restore_drill_systemd_units_follow_juli_api_service_pattern():
    """Restore-drill systemd units mirror the juli-api.service structure."""
    service_path = SYSTEMD_DIR / "juli-restore-drill.service"
    timer_path = SYSTEMD_DIR / "juli-restore-drill.timer"
    api_path = SYSTEMD_DIR / "juli-api.service"
    assert service_path.is_file()
    assert timer_path.is_file()
    assert api_path.is_file()

    service = service_path.read_text(encoding="utf-8")
    timer = timer_path.read_text(encoding="utf-8")
    api = api_path.read_text(encoding="utf-8")

    for text in (service, api):
        assert "[Unit]" in text
        assert "[Service]" in text
        assert "After=network-online.target" in text

    assert "Type=oneshot" in service
    assert "EnvironmentFile=" in service
    assert "restore-drill.sh" in service
    assert "[Timer]" in timer
    assert "OnCalendar=" in timer
    assert "juli-restore-drill.service" in timer


def test_runbook_documents_restore_drill_schedule_log_and_rotation_guard(
    runbook_text: str,
):
    """Runbook documents drill schedule, journalctl logs, and backup rotation guard."""
    assert "juli-restore-drill.timer" in runbook_text
    assert "RESTORE DRILL PASS" in runbook_text
    assert "journalctl" in runbook_text
    lowered = runbook_text.lower()
    assert "backup rotation" in lowered or "backup_retention_days" in lowered
    assert "once at start" in lowered or "once at drill start" in lowered
