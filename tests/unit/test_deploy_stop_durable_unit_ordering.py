"""#1069: cutover must stop the durable `juli-api` unit, and only AFTER it is safe to.

`deploy.sh`'s api lane runs the app as a *transient* `systemd-run` unit per deploy
(`juli-api-candidate-<port>`), health-checks it, flips nginx's upstream to it, then
`write_runtime_env` rewrites `/etc/juli/api-runtime.env` and reinstalls the durable
`juli-api.service` unit file. It never stopped the durable unit itself. If that unit is
ever running outside a fresh boot, cutover leaves it as an orphan bound to a stale port —
invisible to nginx but still holding a port and a process slot, and live/candidate ports
alternate 8000<->8020 every deploy, so a later candidate can collide with it.

The fix (see the issue) is to stop and reset-failed the durable unit inside
`write_runtime_env`'s api-lane branch, strictly AFTER the unit file and runtime env are
rewritten. Order is the crux: stopping first would widen the window in which a reboot
racing the deploy starts the API on the stale, not-yet-updated port.

Testing approach: this repo's prior art for deploy.sh (test_deploy_uvicorn_flag_parity.py)
tests the script by statically slicing out the relevant function/command text and
asserting on it, rather than executing deploy.sh — `write_runtime_env` writes to
`/etc/juli/...` and shells out to real `systemctl`/`install`, which cannot be run
un-mocked in a test sandbox without root and a running systemd, and the paths are not
parameterized for override. This test follows the same static-slicing pattern, but goes
further than a grep-for-presence check: it locates the byte offsets of the operations
inside `write_runtime_env`'s source and asserts their relative ORDER, which is what this
bug is actually about.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "infra" / "scripts" / "deploy.sh"


def _write_runtime_env_body() -> str:
    """The source text of write_runtime_env(), from its def to the next function's def.

    Slicing to just this function (rather than the whole file) is what lets
    test_durable_unit_stop_is_scoped_to_the_api_lane below tell "the fix lives in the
    right function" apart from "the fix exists somewhere in the file."
    """
    text = DEPLOY_SH.read_text(encoding="utf-8")
    start = text.index("write_runtime_env() {")
    end = text.index("\nrollback_lane() {", start)
    return text[start:end]


def test_the_extractor_is_not_vacuous():
    """Guards the slice above: a parser that returns nothing would pass everything below
    for the worst possible reason."""
    body = _write_runtime_env_body()
    assert "case " in body
    assert "systemctl daemon-reload" in body


def test_durable_unit_is_stopped_after_env_file_and_unit_file_are_rewritten():
    body = _write_runtime_env_body()

    assert "systemctl stop juli-api " in body, (
        "write_runtime_env must stop the durable juli-api unit at cutover (#1069) — "
        "otherwise it can survive as an orphan bound to a stale port."
    )

    idx_env_write = body.index('mv -f "${tmp}" "${file}"')
    idx_unit_install = body.index("install -m 0644")
    idx_daemon_reload = body.index("systemctl daemon-reload")
    idx_stop = body.index("systemctl stop juli-api ")

    assert idx_env_write < idx_stop, (
        "systemctl stop juli-api must run AFTER /etc/juli/api-runtime.env is rewritten. "
        "Stopping first widens the window in which a reboot racing this deploy starts "
        "the API on the stale, not-yet-updated port."
    )
    assert idx_unit_install < idx_stop, (
        "systemctl stop juli-api must run AFTER the juli-api.service unit file is "
        "reinstalled, so a reboot after the stop uses the current unit definition."
    )
    assert idx_daemon_reload < idx_stop, (
        "systemctl stop juli-api must run AFTER systemctl daemon-reload has picked up "
        "the reinstalled unit file, not before."
    )


def test_durable_unit_stop_and_reset_failed_tolerate_not_running():
    body = _write_runtime_env_body()

    stop_idx = body.index("systemctl stop juli-api ")
    stop_line = body[stop_idx : body.index("\n", stop_idx)]
    assert "|| true" in stop_line, (
        "stopping a durable unit that is not already running must not fail the deploy"
    )

    assert "systemctl reset-failed juli-api " in body, (
        "a unit that exited non-zero (e.g. crashed before this deploy) must have its "
        "failed state cleared, or a later `systemctl start juli-api` (e.g. at boot) "
        "could be refused"
    )
    reset_idx = body.index("systemctl reset-failed juli-api ")
    reset_line = body[reset_idx : body.index("\n", reset_idx)]
    assert "|| true" in reset_line, (
        "reset-failed on a unit with no failed state must not fail the deploy"
    )

    assert reset_idx > stop_idx, "reset-failed only makes sense after the stop attempt"


def test_durable_unit_stop_is_scoped_to_the_api_lane():
    """write_runtime_env is shared by the api and landing lanes (case lane in ...). The
    orphan risk in #1069 is specific to juli-api — landing's durable unit must not be
    touched by this fix."""
    body = _write_runtime_env_body()
    assert "systemctl stop juli-landing " not in body
    assert "systemctl reset-failed juli-landing " not in body
