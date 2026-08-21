"""Contract tests for #1250: syncing Celery unit files from the release before restart.

Background: `deploy.sh` installed unit files only for the api/demo/landing lanes
(`write_runtime_env`, `install -m 0644 .../juli-<lane>.service`). The Celery worker and
beat were restarted from whatever unit was already on the host — `systemctl cat` proves
a unit is *loaded*, never that it matches the release. Observed twice (#1205, #1248): the
installed unit's `-Q` flag fell behind the release's, the deploy stayed green, and beat
enqueued into a queue nobody consumed.

This file covers the three functions #1250 introduces:

- `sync_celery_unit` — install the release's unit, reload systemd, confirm the install
  actually took (byte-for-byte). Requires root/`/etc/systemd/system` to execute for
  real, so — like `write_runtime_env` in test_deploy_stop_durable_unit_ordering.py —
  it is covered by static ordering assertions on its source text, not execution.
- `celery_unit_queues` — derive the routed queues from a unit file's own `-Q` flag.
  Takes a file path, touches nothing privileged: fully exercised.
- `verify_celery_worker_queues` — poll the worker's own startup banner (via journalctl)
  and fail when a routed queue never appears. Takes unit + file path, touches nothing
  privileged: fully exercised, including the required red evidence against a
  deliberately stale unit (a banner that omits a queue the unit declares).

Orchestration (does the loop in deploy_lane_api call these in the right order, and only
verify the worker, never beat) is covered by both a static slice of the loop and a
behavioural run with sync_celery_unit/verify_celery_worker_queues stubbed as
pass-throughs — deploy_lane_api's own restart-invocation behaviour is covered by
test_deploy_release_script_contract.py::test_celery_restart_invoked_when_units_exist,
extended in the same change to check the new call order.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SH = REPO_ROOT / "infra" / "scripts" / "deploy.sh"
REAL_WORKER_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-celery-worker.service"
REAL_BEAT_UNIT = REPO_ROOT / "infra" / "systemd" / "juli-celery-beat.service"


@pytest.fixture
def script_text() -> str:
    return DEPLOY_SH.read_text(encoding="utf-8")


def _extract_function(text: str, name: str) -> str:
    """Slice `name() { ... }` out of `text` by brace depth, not regex greediness.

    Brace-depth counting (rather than a `do...done`/greedy regex like the sibling
    contract test file uses) is needed here because these functions contain nested
    `${...}` parameter expansions and an unbounded `while :; do ... done` loop.
    """
    marker = f"{name}() {{"
    start = text.index(marker)
    open_idx = text.index("{", start)
    depth = 0
    i = open_idx
    while True:
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1


def _celery_loop_block(text: str) -> str:
    """The `for unit in juli-celery-worker juli-celery-beat; do ... done` loop body,
    sliced from inside deploy_lane_api (not the whole function)."""
    lane_api = _extract_function(text, "deploy_lane_api")
    start = lane_api.index("for unit in juli-celery-worker juli-celery-beat; do")
    end = lane_api.index("\n    done\n", start) + len("\n    done")
    return lane_api[start:end]


# --------------------------------------------------------------------------------------
# Guard: the extractors themselves must not be vacuous.
# --------------------------------------------------------------------------------------


def test_extractors_are_not_vacuous(script_text: str):
    sync_body = _extract_function(script_text, "sync_celery_unit")
    queues_body = _extract_function(script_text, "celery_unit_queues")
    verify_body = _extract_function(script_text, "verify_celery_worker_queues")
    loop_body = _celery_loop_block(script_text)

    assert "install -m 0644" in sync_body
    assert "-Q" in queues_body
    assert "journalctl" in verify_body
    assert "systemctl restart" in loop_body


# --------------------------------------------------------------------------------------
# sync_celery_unit — static ordering (mirrors test_deploy_stop_durable_unit_ordering.py:
# the destination is a privileged, un-parameterized /etc/systemd/system path, same as
# write_runtime_env, so this is asserted on source text rather than executed).
# --------------------------------------------------------------------------------------


def test_sync_celery_unit_installs_reloads_then_confirms_in_order(script_text: str):
    body = _extract_function(script_text, "sync_celery_unit")

    idx_install = body.index("install -m 0644")
    idx_reload = body.index("systemctl daemon-reload")
    idx_cmp = body.index("cmp -s")

    assert idx_install < idx_reload, (
        "install must run before systemctl daemon-reload, or daemon-reload has "
        "nothing new to pick up"
    )
    assert idx_reload < idx_cmp, (
        "daemon-reload must run before the drift check, matching the acceptance "
        "criterion that daemon-reload happens before any later systemctl restart"
    )


def test_sync_celery_unit_fails_loudly_when_install_is_refused(script_text: str):
    body = _extract_function(script_text, "sync_celery_unit")
    assert "if ! install -m 0644" in body, (
        "the install call's exit status must be checked, not ignored"
    )
    install_if_idx = body.index("if ! install -m 0644")
    next_return_idx = body.index("return 1", install_if_idx)
    next_fi_idx = body.index("fi", install_if_idx)
    assert next_return_idx < next_fi_idx, (
        "a refused install must return 1 from within its own if-block — an "
        "unresolvable install failure must fail the deploy, not continue to restart"
    )


def test_sync_celery_unit_fails_loudly_on_residual_drift_after_install(script_text: str):
    """The install call succeeding is not proof the file now matches the release (e.g.
    a stale bind mount, a symlink pointing elsewhere). This is what makes 'unresolvable
    drift' concrete: install can exit 0 while the byte-for-byte comparison still fails,
    and that must still fail the deploy."""
    body = _extract_function(script_text, "sync_celery_unit")
    assert "if ! cmp -s" in body
    cmp_if_idx = body.index("if ! cmp -s")
    return_idx = body.index("return 1", cmp_if_idx)
    fi_idx = body.index("fi", cmp_if_idx)
    assert return_idx < fi_idx, "residual drift after a successful install must still return 1"


def test_sync_celery_unit_installs_from_the_release_tree(script_text: str):
    body = _extract_function(script_text, "sync_celery_unit")
    assert 'src="${CANONICAL_ROOT}/infra/systemd/${unit}.service"' in body, (
        "the source of the install must be the release's own checkout "
        "(CANONICAL_ROOT), not some other tree"
    )


def test_sync_celery_unit_never_touches_api_env(script_text: str):
    """No secret, token, or api.env value may be read or logged by the sync/verify
    path (#1250 acceptance criterion)."""
    for name in ("sync_celery_unit", "celery_unit_queues", "verify_celery_worker_queues"):
        body = _extract_function(script_text, name)
        assert "API_ENV_FILE" not in body, f"{name} must not read the API env file"
        assert "api.env" not in body, f"{name} must not reference api.env"


# --------------------------------------------------------------------------------------
# celery_unit_queues — derives from the unit's own -Q flag, never a hardcoded list.
# --------------------------------------------------------------------------------------


def test_celery_unit_queues_does_not_hardcode_queue_names(script_text: str):
    """A hardcoded list is exactly the bug this issue fixes, moved one file over.
    Guard that the function derives queues by parsing -Q, not by naming any specific
    queue (which would silently stop tracking a routing change in celery_app.py)."""
    body = _extract_function(script_text, "celery_unit_queues")
    for literal in ("agent_runs", "credentials", '"celery"', "'celery'"):
        assert literal not in body, (
            f"celery_unit_queues must not hardcode {literal!r} — queues must be "
            "derived from the unit file's own -Q flag"
        )
    assert "-Q" in body


def test_celery_unit_queues_parses_a_synthetic_unit_file(script_text: str, tmp_path: Path):
    func = _extract_function(script_text, "celery_unit_queues")
    unit_file = tmp_path / "fake.service"
    unit_file.write_text(
        "ExecStart=/venv/bin/celery -A app worker \\\n"
        "    -Q alpha,beta,gamma \\\n"
        "    --loglevel=info\n"
    )
    script = f"set -euo pipefail\n{func}\ncelery_unit_queues '{unit_file}'\n"
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.split()) == {"alpha", "beta", "gamma"}


def test_celery_unit_queues_fails_loudly_when_no_dash_q_present(script_text: str, tmp_path: Path):
    func = _extract_function(script_text, "celery_unit_queues")
    unit_file = tmp_path / "no-q.service"
    unit_file.write_text("ExecStart=/venv/bin/celery -A app worker --loglevel=info\n")
    script = f"set -uo pipefail\n{func}\ncelery_unit_queues '{unit_file}'\n"
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)
    assert result.returncode != 0
    assert "no -Q flag found" in result.stderr


def test_celery_unit_queues_reads_the_real_production_worker_unit(script_text: str):
    """Sanity check that the parser reads real production content, not just synthetic
    fixtures — pinned loosely (queue is present) rather than to the exact set, so this
    test does not itself become the next hardcoded list."""
    func = _extract_function(script_text, "celery_unit_queues")
    script = f"set -euo pipefail\n{func}\ncelery_unit_queues '{REAL_WORKER_UNIT}'\n"
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    queues = set(result.stdout.split())
    assert "celery" in queues, (
        f"expected the default 'celery' queue to be among the parsed queues, got {queues}"
    )
    assert len(queues) >= 2, (
        "the real worker unit routes more than the default queue (#1205/#1232) — a "
        "parser returning only one queue here would not have caught the real bug"
    )


# --------------------------------------------------------------------------------------
# verify_celery_worker_queues — the post-restart assertion. This is the function the
# issue calls out by name: "the verification test fails against a deliberately stale
# unit... a happy-path-only test does not satisfy this."
# --------------------------------------------------------------------------------------


def _verify_queues_script(script_text: str) -> str:
    """celery_unit_queues + verify_celery_worker_queues, concatenated — verify calls
    the other by name, so both must be in scope."""
    return "\n".join(
        [
            _extract_function(script_text, "celery_unit_queues"),
            _extract_function(script_text, "verify_celery_worker_queues"),
        ]
    )


def _run_verify(
    script_text: str,
    unit_file: Path,
    banner: str,
    tmp_path: Path,
    timeout_secs: int = 0,
    *,
    invocation: str = "current",
    unit_wide_banner: str | None = None,
    since: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Drive `verify_celery_worker_queues` against stubbed systemd.

    The stubs model the distinction the function depends on:

    - `systemctl show -p InvocationID --value <unit>` yields ``invocation``. Pass
      ``invocation=""`` to model a host whose systemd reports no invocation id.
    - `journalctl _SYSTEMD_INVOCATION_ID=<id>` yields only what that *specific*
      invocation logged — ``banner`` for the current one, nothing for any other.
    - `journalctl -u <unit>` yields ``unit_wide_banner``: everything the unit has
      logged across *all* invocations. This defaults to ``banner`` so the unit-wide
      and invocation-scoped views agree, but a crash-loop test sets them apart —
      that gap is what proves the function reads the scoped view.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    journal_dir = tmp_path / "journal"
    journal_dir.mkdir(exist_ok=True)

    if invocation:
        (journal_dir / f"inv-{invocation}").write_text(banner)
    (journal_dir / "unit-wide").write_text(banner if unit_wide_banner is None else unit_wide_banner)

    (bin_dir / "systemctl").write_text(f"#!/bin/bash\nprintf '%s\\n' '{invocation}'\n")
    (bin_dir / "systemctl").chmod(0o755)

    # Dispatch on the argument form, exactly as the real journalctl does: a bare
    # `FIELD=value` match selects one invocation, `-u <unit>` selects the unit.
    (bin_dir / "journalctl").write_text(
        "#!/bin/bash\n"
        "id=''\n"
        'for a in "$@"; do\n'
        '  case "$a" in _SYSTEMD_INVOCATION_ID=*) id="${a#_SYSTEMD_INVOCATION_ID=}";; esac\n'
        "done\n"
        'if [ -n "${id}" ]; then\n'
        f"  cat '{journal_dir}/inv-'\"${{id}}\" 2>/dev/null || true\n"
        "else\n"
        f"  cat '{journal_dir}/unit-wide' 2>/dev/null || true\n"
        "fi\n"
    )
    (bin_dir / "journalctl").chmod(0o755)

    script = (
        "set -uo pipefail\n"
        f"export CELERY_VERIFY_TIMEOUT_SECS={timeout_secs}\n"
        "export CELERY_VERIFY_POLL_SECS=0\n"
        f"CELERY_VERIFY_SINCE='{'' if since is None else since}'\n"
        f"{_verify_queues_script(script_text)}\n"
        f"verify_celery_worker_queues juli-celery-worker '{unit_file}'\n"
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    return subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env)


def test_verify_passes_when_the_banner_reports_every_routed_queue(tmp_path: Path, script_text: str):
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    banner = (
        "[queues]\n"
        "  .> celery           exchange=celery(direct) key=celery\n"
        "  .> agent_runs       exchange=agent_runs(direct) key=agent_runs\n"
        "  .> credentials      exchange=credentials(direct) key=credentials\n"
    )
    result = _run_verify(script_text, unit_file, banner, tmp_path)
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_verify_fails_red_against_a_deliberately_stale_unit(tmp_path: Path, script_text: str):
    """The required red evidence (#1250): reproduces the exact #1248 shape — the unit
    declares three routed queues, but the worker's own startup banner (what actually
    subscribed) is missing one of them, exactly as observed on the host for ~25 minutes
    after #1248 deployed. This must fail, loudly, not log-and-continue."""
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    stale_banner = (
        "[queues]\n"
        "  .> celery           exchange=celery(direct) key=celery\n"
        "  .> agent_runs       exchange=agent_runs(direct) key=agent_runs\n"
        # 'credentials' deliberately absent — the stale-worker scenario.
    )
    result = _run_verify(script_text, unit_file, stale_banner, tmp_path)
    assert result.returncode != 0, (
        "verification must fail when the worker's banner omits a routed queue, "
        f"but it exited 0. stdout={result.stdout!r}"
    )
    assert "credentials" in result.stderr
    assert "FAIL" in result.stderr
    assert "PASS" not in result.stdout


def test_verify_fails_when_worker_never_logged_a_banner(tmp_path: Path, script_text: str):
    """A crashed or still-starting worker: journalctl returns nothing usable. Must fail,
    not pass vacuously."""
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs\n")
    result = _run_verify(script_text, unit_file, banner="", tmp_path=tmp_path)
    assert result.returncode != 0
    assert "celery" in result.stderr and "agent_runs" in result.stderr


def test_verify_fails_loudly_when_unit_has_no_dash_q_flag(tmp_path: Path, script_text: str):
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker --loglevel=info\n")
    result = _run_verify(script_text, unit_file, banner="[queues]\n", tmp_path=tmp_path)
    assert result.returncode != 0
    assert "no -Q flag found" in result.stderr


_HEALTHY_BANNER = (
    "[queues]\n"
    "  .> celery           exchange=celery(direct) key=celery\n"
    "  .> agent_runs       exchange=agent_runs(direct) key=agent_runs\n"
    "  .> credentials      exchange=credentials(direct) key=credentials\n"
)


def test_verify_ignores_a_banner_from_a_previous_invocation(tmp_path: Path, script_text: str):
    """The crash-loop case, found in review of #1250.

    `journalctl -u <unit> -n 200` returns the last 200 lines across *every*
    invocation. So a worker that restarts cleanly, prints a healthy banner, then
    dies and crash-loops leaves that healthy banner sitting in the unit-wide
    window — and an unscoped check reports PASS for a worker that is currently
    down. That is a verification passing for a reason unrelated to its claim,
    which is the precise defect this whole function was added to eliminate.

    Here the unit-wide journal holds a complete healthy banner (invocation 1),
    while the *current* invocation logged only a traceback. Verification must
    fail: it must read the current invocation, not the unit's whole history.
    """
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    result = _run_verify(
        script_text,
        unit_file,
        banner="Traceback (most recent call last):\nKilled\n",
        tmp_path=tmp_path,
        invocation="crashloop-2",
        unit_wide_banner=_HEALTHY_BANNER + "\nTraceback (most recent call last):\nKilled\n",
    )
    assert result.returncode != 0, (
        "verification passed on a crash-looping worker by reading a previous "
        f"invocation's banner. stdout={result.stdout!r}"
    )
    assert "FAIL" in result.stderr
    assert "PASS" not in result.stdout


def test_verify_reads_the_current_invocation_not_the_unit_wide_journal(
    tmp_path: Path, script_text: str
):
    """The inverse pin of the test above, so neither can pass vacuously: when the
    current invocation *is* healthy, an empty unit-wide window must not spoil it."""
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    result = _run_verify(
        script_text,
        unit_file,
        banner=_HEALTHY_BANNER,
        tmp_path=tmp_path,
        invocation="healthy-3",
        unit_wide_banner="",
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_verify_falls_back_to_the_restart_scoped_window_without_an_invocation_id(
    tmp_path: Path, script_text: str
):
    """systemd < 232 reports no InvocationID. The fallback is the restart-scoped
    `--since` window — still bounded, never the unit's whole history."""
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    result = _run_verify(
        script_text,
        unit_file,
        banner="",
        tmp_path=tmp_path,
        invocation="",
        unit_wide_banner=_HEALTHY_BANNER,
        since="2026-08-21 10:00:00",
    )
    assert result.returncode == 0, result.stderr
    assert "PASS" in result.stdout


def test_verify_refuses_to_check_an_unscoped_journal(tmp_path: Path, script_text: str):
    """No InvocationID *and* no restart timestamp means there is no way to tell a
    current banner from a stale one. Fail closed and say why — do not silently
    degrade to the unbounded check, which is the bug this fix removes."""
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    result = _run_verify(
        script_text,
        unit_file,
        banner="",
        tmp_path=tmp_path,
        invocation="",
        unit_wide_banner=_HEALTHY_BANNER,
        since=None,
    )
    assert result.returncode != 0, (
        f"verified against an unscoped journal window. stdout={result.stdout!r}"
    )
    assert "unscoped" in result.stderr
    assert "PASS" not in result.stdout


def test_verify_scopes_the_journal_read_by_invocation(script_text: str):
    """A structural pin: the scoping must come from the invocation id, not from a
    wider `-n` window that happens to be small enough today."""
    body = _extract_function(script_text, "verify_celery_worker_queues")
    assert "_SYSTEMD_INVOCATION_ID" in body
    assert "InvocationID" in body


def test_restart_stamps_the_fallback_window_before_restarting(script_text: str):
    """`CELERY_VERIFY_SINCE` is only sound if it is stamped *before* the restart —
    stamped after, it could exclude the very banner it is meant to bound."""
    api_lane = _extract_function(script_text, "deploy_lane_api")
    stamp = api_lane.index("CELERY_VERIFY_SINCE=")
    restart = api_lane.index('systemctl restart "${unit}"')
    assert stamp < restart, "CELERY_VERIFY_SINCE is stamped after the restart it bounds"


def test_verify_with_zero_timeout_does_not_hang(tmp_path: Path, script_text: str):
    """CELERY_VERIFY_TIMEOUT_SECS=0 must mean exactly one check, not a long poll —
    otherwise every test above (and a real deploy waiting on a truly missing queue)
    would be needlessly slow."""
    unit_file = tmp_path / "worker.service"
    unit_file.write_text("ExecStart=celery worker -Q celery,agent_runs,credentials\n")
    started = time.monotonic()
    result = _run_verify(script_text, unit_file, banner="[queues]\n", tmp_path=tmp_path)
    elapsed = time.monotonic() - started
    assert result.returncode != 0
    assert elapsed < 5, f"verification with a 0s timeout took {elapsed:.1f}s — it polled"


# --------------------------------------------------------------------------------------
# Orchestration: the loop inside deploy_lane_api.
# --------------------------------------------------------------------------------------


def test_loop_preserves_the_systemctl_cat_skip_guard(script_text: str):
    """A host that simply does not have the Celery units installed must still SKIP
    cleanly — this is the existing #751 guard, unchanged in shape."""
    loop = _celery_loop_block(script_text)
    assert 'if systemctl cat "${unit}" >/dev/null 2>&1; then' in loop
    assert 'echo "SKIP: ${unit} not installed on this host"' in loop


def test_loop_calls_sync_before_restart_and_restart_before_verify(script_text: str):
    loop = _celery_loop_block(script_text)
    idx_sync = loop.index("sync_celery_unit")
    idx_restart = loop.index("systemctl restart")
    idx_verify = loop.index("verify_celery_worker_queues")
    assert idx_sync < idx_restart, "sync_celery_unit must run before systemctl restart"
    assert idx_restart < idx_verify, (
        "verify_celery_worker_queues must run after systemctl restart — it is "
        "verifying the process that was just restarted"
    )


def test_loop_only_verifies_queues_for_the_worker_not_beat(script_text: str):
    loop = _celery_loop_block(script_text)
    assert 'if [ "${unit}" = "juli-celery-worker" ]; then' in loop
    guard_idx = loop.index('if [ "${unit}" = "juli-celery-worker" ]; then')
    verify_idx = loop.index("verify_celery_worker_queues")
    assert guard_idx < verify_idx, (
        "verify_celery_worker_queues must be nested under the worker-only guard — "
        "juli-celery-beat has no -Q flag and no queue banner to check"
    )


def test_loop_fails_the_lane_on_sync_or_restart_or_verify_failure(script_text: str):
    loop = _celery_loop_block(script_text)
    # Each of the three failure points must record and return 1 — a stale unit that
    # cannot be resolved must fail the deploy, not log and continue.
    assert loop.count('record_step api celery "failed"') == 3, (
        "expected exactly three distinct failure points (sync, restart, verify) to "
        f"record a failed celery step; found {loop.count(chr(34) + 'failed' + chr(34))}"
    )
    assert loop.count("return 1") >= 3


def test_record_step_celery_restarted_string_was_replaced(script_text: str):
    """#1250 explicitly replaces the old unconditional 'restarted' record with a real
    assertion outcome — guards against silently keeping the old (meaningless) label."""
    assert 'record_step api celery "restarted"' not in script_text
    assert 'record_step api celery "verified"' in script_text


def test_loop_orchestration_behavioural_all_units_present_and_healthy(
    tmp_path: Path, script_text: str
):
    """End-to-end orchestration with sync/verify stubbed as pass-throughs (their own
    internals are covered above): confirms the loop's call sequence and that a
    successful run reaches 'verified' without hitting any failure branch."""
    loop = _celery_loop_block(script_text)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "systemctl").write_text(
        "#!/bin/bash\n"
        'case "$1" in\n'
        "  cat) exit 0 ;;\n"
        '  restart) echo "RESTART: $2"; exit 0 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    (bin_dir / "systemctl").chmod(0o755)

    script = (
        "set -uo pipefail\n"
        'sync_celery_unit() { echo "SYNC: $1"; return 0; }\n'
        'verify_celery_worker_queues() { echo "VERIFY: $1"; return 0; }\n'
        'record_step() { echo "RECORD: $*"; }\n'
        "fake_lane() {\n"
        f"{loop}\n"
        "}\n"
        "fake_lane\n"
        'echo "LOOP_EXIT:$?"\n'
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env)
    assert "LOOP_EXIT:0" in result.stdout, result.stdout + result.stderr
    assert "SYNC: juli-celery-worker" in result.stdout
    assert "SYNC: juli-celery-beat" in result.stdout
    assert "VERIFY: juli-celery-worker" in result.stdout
    assert "VERIFY: juli-celery-beat" not in result.stdout
    assert "RECORD: api celery failed" not in result.stdout


def test_loop_orchestration_behavioural_stale_unit_fails_the_lane(tmp_path: Path, script_text: str):
    """The unresolvable-drift acceptance criterion, at the orchestration level: when
    sync_celery_unit cannot resolve drift, the loop must never reach systemctl restart
    for that unit, and the lane function must return non-zero."""
    loop = _celery_loop_block(script_text)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "systemctl").write_text(
        "#!/bin/bash\n"
        'case "$1" in\n'
        "  cat) exit 0 ;;\n"
        '  restart) echo "RESTART: $2"; exit 0 ;;\n'
        "  *) exit 0 ;;\n"
        "esac\n"
    )
    (bin_dir / "systemctl").chmod(0o755)

    script = (
        "set -uo pipefail\n"
        'sync_celery_unit() { echo "SYNC: $1"; return 1; }\n'  # unresolvable drift
        'verify_celery_worker_queues() { echo "VERIFY: $1"; return 0; }\n'
        'record_step() { echo "RECORD: $*"; }\n'
        "fake_lane() {\n"
        f"{loop}\n"
        "}\n"
        "fake_lane\n"
        'echo "LOOP_EXIT:$?"\n'
    )
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    result = subprocess.run(["/bin/bash", "-c", script], capture_output=True, text=True, env=env)
    assert "LOOP_EXIT:0" not in result.stdout, (
        f"unresolvable drift must fail the lane. stdout={result.stdout!r}"
    )
    assert "RESTART: juli-celery-worker" not in result.stdout, (
        "systemctl restart must never run when sync_celery_unit could not resolve drift"
    )
    assert "RECORD: api celery failed juli-celery-worker drift unresolved" in result.stdout


# --------------------------------------------------------------------------------------
# Deploy trigger: a commit touching only a Celery unit file must not be skipped.
# --------------------------------------------------------------------------------------


def test_api_lane_path_filters_include_both_celery_unit_files(script_text: str):
    body = _extract_function(script_text, "lane_path_filters")
    api_case_start = body.index("api)")
    api_case_end = body.index(";;", api_case_start)
    api_filters = body[api_case_start:api_case_end]
    assert "infra/systemd/juli-celery-worker.service" in api_filters, (
        "a commit touching only the Celery worker unit must trigger the api lane"
    )
    assert "infra/systemd/juli-celery-beat.service" in api_filters, (
        "a commit touching only the Celery beat unit must trigger the api lane"
    )
    # And the pre-existing filters must still be present — this is additive, not a
    # replacement.
    assert "backend/" in api_filters
    assert "requirements.txt" in api_filters
    assert "infra/systemd/juli-api.service" in api_filters


# --------------------------------------------------------------------------------------
# The api lane's public_check and rollback_lane must be untouched by this change.
# --------------------------------------------------------------------------------------


def test_public_check_function_is_unchanged(script_text: str):
    body = _extract_function(script_text, "public_check")
    assert (
        body
        == """public_check() {
    local url="$1" deadline=$((SECONDS + PUBLIC_CHECK_TIMEOUT_SECS)) code="000"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
        code="$(http_code "${url}")"
        [ "${#code}" -eq 3 ] && [ "${code#2}" != "${code}" ] && return 0
        sleep 3
    done
    echo "FAIL: public check ${url} did not pass (last HTTP ${code})" >&2
    return 1
}"""
    ), "public_check must be byte-for-byte unchanged by #1250"


def test_rollback_lane_function_is_unchanged(script_text: str):
    body = _extract_function(script_text, "rollback_lane")
    assert (
        body
        == """rollback_lane() {
    local lane="$1" prev_port="$2"
    log "automatic rollback (${lane}) — returning traffic to :${prev_port}"
    switch_upstream "${lane}" "${prev_port}" || return 1
    write_runtime_env "${lane}" "${prev_port}"
    record_step "${lane}" "rollback" "restored_to_${prev_port}"
}"""
    ), "rollback_lane must be byte-for-byte unchanged by #1250"
