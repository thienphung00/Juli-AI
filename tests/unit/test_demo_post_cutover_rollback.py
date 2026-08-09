"""#840 — post-cutover public check with automatic rollback.

The candidate checks (#833) prove the release on loopback; they cannot prove the
cutover. These tests exercise the deploy script's real bash functions in library
mode, with local HTTP servers standing in for the public address and the loopback
instances — the same conventions as test_demo_candidate_verification.py.
"""

from __future__ import annotations

import http.server
import os
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "deploy-demo-release.sh"


def run_sourced(
    body: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source the deploy script in library mode and run ``body`` against its functions."""
    assert DEPLOY_SCRIPT.is_file(), f"{DEPLOY_SCRIPT} is missing"
    snippet = (
        f'set -uo pipefail\nexport DEMO_DEPLOY_SOURCE_ONLY=1\nsource "{DEPLOY_SCRIPT}"\n{body}\n'
    )
    full_env = {**os.environ, "DEMO_DEPLOY_SOURCE_ONLY": "1"}
    if env:
        full_env.update(env)
    return subprocess.run(
        ["bash", "-c", snippet],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=full_env,
        cwd=str(REPO_ROOT),
    )


def output_of(result: subprocess.CompletedProcess[str]) -> str:
    return f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def _make_handler(routes: dict[str, int]) -> type[http.server.BaseHTTPRequestHandler]:
    class _FixtureHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server API
            status = routes.get(self.path, 404)
            self.send_response(status)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>fixture</html>")

        def log_message(self, *args: object) -> None:
            pass

    return _FixtureHandler


@contextmanager
def fixture_server(routes: dict[str, int]) -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(routes))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


FAST = {"DEMO_PUBLIC_CHECK_TIMEOUT_SECS": "1"}


def test_the_840_functions_exist() -> None:
    result = run_sourced(
        "declare -F demo_public_check previous_instance_ready "
        "restart_previous_release rollback_demo_cutover"
    )
    assert result.returncode == 0, output_of(result)


def test_public_check_passes_when_every_route_answers_2xx() -> None:
    with fixture_server({"/": 200, "/decisions": 200}) as base:
        result = run_sourced(f'demo_public_check "{base}"', env=FAST)
    assert result.returncode == 0, output_of(result)


def test_public_check_fails_when_any_route_is_not_2xx() -> None:
    """A healthy homepage must not mask a broken /decisions — every route counts."""
    with fixture_server({"/": 200, "/decisions": 500}) as base:
        result = run_sourced(f'demo_public_check "{base}"', env=FAST)
    assert result.returncode != 0, output_of(result)
    assert "/decisions" in result.stderr


def test_public_check_fails_when_nothing_answers_at_all() -> None:
    """Connection refused (HTTP 000) is a cutover fault, not a skipped check."""
    result = run_sourced('demo_public_check "http://127.0.0.1:1"', env=FAST)
    assert result.returncode != 0, output_of(result)


def test_previous_instance_ready_decides_the_tier() -> None:
    with fixture_server({"/decisions": 200}) as base:
        port = base.rsplit(":", 1)[1]
        up = run_sourced(f'previous_instance_ready "{port}"')
    down = run_sourced('previous_instance_ready "1"')
    assert up.returncode == 0, output_of(up)
    assert down.returncode != 0, output_of(down)


def test_rollback_refuses_without_a_retained_definition(tmp_path: Path) -> None:
    """No .prev file means no undo exists — rolling back must fail loudly, not guess."""
    result = run_sourced(
        f'rollback_demo_cutover "3001" "{tmp_path}"',
        env={"DEMO_UPSTREAM_CONF": str(tmp_path / "absent" / "demo-upstream.conf")},
    )
    assert result.returncode != 0, output_of(result)
    assert "no retained definition" in result.stderr


def test_rollback_refuses_a_missing_previous_release(tmp_path: Path) -> None:
    """demo-current must never be repointed at a directory that does not exist."""
    prev = tmp_path / "demo-upstream.conf.prev"
    prev.write_text("upstream juli_demo { server 127.0.0.1:3001; }\n")
    result = run_sourced(
        f'rollback_demo_cutover "3001" "{tmp_path}/pruned-away"',
        env={"DEMO_UPSTREAM_CONF": str(tmp_path / "demo-upstream.conf")},
    )
    assert result.returncode != 0, output_of(result)
    assert "does not exist" in result.stderr


def test_restart_refuses_a_release_without_a_runnable_build(tmp_path: Path) -> None:
    """Tier 2 must fail fast on a pruned or gutted release, before touching systemd."""
    result = run_sourced(f'restart_previous_release "{tmp_path}" "3001"')
    assert result.returncode != 0, output_of(result)
    assert "no runnable Demo build" in result.stderr


def test_main_flow_wires_the_public_check_and_the_rollback() -> None:
    """Wiring pin: the functions must actually run in the deploy path — a helper that
    exists but is never called would pass every test above and protect nothing."""
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    # The negated guard form is the deploy-path call specifically. The rollback helper
    # also calls demo_public_check (to re-verify after restoring), so a bare substring
    # check would stay green with the deploy-path call deleted — proven by mutation.
    assert 'if ! demo_public_check "${DEMO_PUBLIC_BASE_URL}"; then' in source
    assert source.count('abort_with_rollback "') >= 2, (
        "both post-cutover failures (loopback health, public check) must roll back"
    )
    assert 'rollback_demo_cutover "${live_port}" "${live_before}"' in source


def test_migrations_are_never_touched_by_rollback() -> None:
    """AC: migrations are never automatically reverted — safety comes from additivity."""
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = source.index("rollback_demo_cutover() {")
    end = source.index("\n}", start)
    body = source[start:end]
    for forbidden in ("alembic", "downgrade", "migration"):
        assert forbidden not in body.lower(), f"rollback must not touch {forbidden}"


def test_public_defaults_target_the_public_address() -> None:
    result = run_sourced('echo "${DEMO_PUBLIC_BASE_URL}"; echo "${DEMO_PUBLIC_CHECK_ROUTES}"')
    assert result.returncode == 0, output_of(result)
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "https://demo.app-juli.com"
    assert "/decisions" in lines[1]
