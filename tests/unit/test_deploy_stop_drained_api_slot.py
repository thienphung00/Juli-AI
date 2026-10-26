"""E10 (P68): deploy.sh stops the drained blue/green API slot after the cutover.

Runs the real `stop_drained_api_slot` / `verify_single_api_slot` functions (sliced out
of deploy.sh) under bash with a fake `systemctl` on PATH that logs every call.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "infra" / "scripts" / "deploy.sh"


def _functions() -> str:
    text = DEPLOY_SH.read_text(encoding="utf-8")
    start = text.index("stop_drained_api_slot() {")
    end = text.index("\nrollback_lane() {", start)
    return text[start:end]


def _run(tmp_path: Path, call: str, active: str = "", stop_rc: int = 0):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    fake = bindir / "systemctl"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        'echo "$*" >> "$CALLS_LOG"\n'
        'case "$1" in\n'
        '  is-active) case " $ACTIVE " in *" ${@: -1} "*) exit 0;; *) exit 3;; esac ;;\n'
        '  stop) exit "$STOP_RC" ;;\n'
        '  list-units) for u in $ACTIVE; do echo "$u loaded active running x"; done ;;\n'
        "esac\nexit 0\n"
    )
    fake.chmod(0o755)
    script = (
        "note() { printf '   %s\\n' \"$*\"; }\nrecord_step() { :; }\n"
        "STALE_SLOT_DRAIN_SECS=0\n" + _functions() + "\n" + call
    )
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "CALLS_LOG": str(log),
        "ACTIVE": active,
        "STOP_RC": str(stop_rc),
    }
    proc = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, calls


def test_stops_previous_slot(tmp_path):
    proc, calls = _run(
        tmp_path, "stop_drained_api_slot 8000 8020", active="juli-api-candidate-8000"
    )
    assert proc.returncode == 0
    assert "stop juli-api-candidate-8000" in calls
    assert "stopped drained API slot juli-api-candidate-8000" in proc.stdout


def test_no_previous_slot_is_noop(tmp_path):
    proc, calls = _run(tmp_path, 'stop_drained_api_slot "" 8020')
    assert proc.returncode == 0
    assert calls == []


def test_same_slot_is_noop(tmp_path):
    proc, calls = _run(
        tmp_path, "stop_drained_api_slot 8020 8020", active="juli-api-candidate-8020"
    )
    assert proc.returncode == 0
    assert not any(c.startswith("stop") for c in calls)


def test_inactive_previous_slot_is_not_stopped(tmp_path):
    proc, calls = _run(tmp_path, "stop_drained_api_slot 8000 8020", active="")
    assert proc.returncode == 0
    assert not any(c.startswith("stop") for c in calls)


def test_stop_failure_warns_but_does_not_fail(tmp_path):
    proc, _ = _run(
        tmp_path, "stop_drained_api_slot 8000 8020", active="juli-api-candidate-8000", stop_rc=1
    )
    assert proc.returncode == 0
    assert "WARNING: E10" in proc.stderr


def test_legacy_juli_api_unit_is_never_touched(tmp_path):
    _, calls = _run(
        tmp_path, "stop_drained_api_slot 8000 8020", active="juli-api-candidate-8000 juli-api"
    )
    assert all(not c.endswith(" juli-api") for c in calls)


def test_single_slot_check(tmp_path):
    proc, _ = _run(tmp_path, "verify_single_api_slot", active="juli-api-candidate-8020")
    assert proc.returncode == 0 and "WARNING" not in proc.stderr
    proc, _ = _run(
        tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path,
        "verify_single_api_slot",
        active="juli-api-candidate-8020 juli-api-candidate-8000",
    )
    assert proc.returncode == 0 and "WARNING: E10" in proc.stderr
