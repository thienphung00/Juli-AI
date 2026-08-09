"""#843/#844 — paired slots for every deployable, behind one deploy command.

Contract tests over infra/scripts/deploy.sh in library mode, following the demo
lane's test conventions. Runtime behaviour (real cutovers) is verified live.
"""

from __future__ import annotations

import http.server
import json
import os
import subprocess
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "infra" / "scripts" / "deploy.sh"


def run_sourced(body: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    snippet = f'set -uo pipefail\nexport DEPLOY_SOURCE_ONLY=1\nsource "{DEPLOY}"\n{body}\n'
    full_env = {**os.environ, "DEPLOY_SOURCE_ONLY": "1"}
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


# --- #843: fixed slots, known in advance ------------------------------------------------


def test_every_deployable_has_two_distinct_slots_and_no_port_is_shared() -> None:
    result = run_sourced('for l in api demo landing; do lane_ports "$l"; done')
    assert result.returncode == 0, result.stderr
    ports = result.stdout.split()
    assert ports == ["8000", "8020", "3001", "3021", "3007", "3027"]
    assert len(set(ports)) == 6, "slot ports must be unique host-wide"


def test_peer_port_math_and_refusal() -> None:
    ok = run_sourced('peer_port_of api "8000"; peer_port_of landing "3027"')
    assert ok.returncode == 0 and ok.stdout.split() == ["8020", "3007"], ok.stderr
    bad = run_sourced('peer_port_of api "9999"')
    assert bad.returncode != 0, "an out-of-pair live port must refuse, not guess"


def test_rendered_upstream_carries_the_lane_name_and_one_server() -> None:
    result = run_sourced('render_upstream api "8020"')
    assert result.returncode == 0, result.stderr
    assert "upstream juli_api {" in result.stdout
    assert result.stdout.count("server 127.0.0.1:") == 1


def test_api_verification_asserts_response_shape_not_only_status() -> None:
    """#843 AC: a healthy process serving the wrong shape must fail."""
    good = {
        "/health": {"status": "ok"},
        "/v1/demo/analytics": {
            "computed_at": "2026-08-09T00:00:00Z",
            "kpis": {
                k: {} for k in ("gmv_tiktok", "aov", "ctor", "live_hours", "cancellation_rate")
            },
        },
    }
    bad = {"/health": {"status": "ok"}, "/v1/demo/analytics": {"kpis": {"gmv_tiktok": {}}}}

    def serve(routes: dict) -> tuple[http.server.ThreadingHTTPServer, str]:
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = json.dumps(routes.get(self.path, {})).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{server.server_address[1]}"

    server, base = serve(good)
    try:
        assert run_sourced(f'verify_api_shape "{base}"').returncode == 0
    finally:
        server.shutdown()
    server, base = serve(bad)
    try:
        result = run_sourced(f'verify_api_shape "{base}"')
        assert result.returncode != 0, "a 200 with a broken envelope must fail verification"
        assert "missing" in (result.stdout + result.stderr)
    finally:
        server.shutdown()


# --- #844: one command, change detection, ordering, record ------------------------------


def test_lane_order_releases_api_before_demo() -> None:
    result = run_sourced('echo "${LANE_ORDER}"')
    order = result.stdout.split()
    assert order.index("api") < order.index("demo"), (
        "the API must release before a dependent Demo change"
    )


def test_lanes_run_sequentially() -> None:
    """One transient duplicate at a time on a 4GB box: no lane may background."""
    source = DEPLOY.read_text(encoding="utf-8")
    loop = source[
        source.index("for lane in ${lanes}") : source.index(
            'if [ -n "${failed}" ]; then\n        record_close'
        )
    ]
    assert "&" not in loop.replace("&&", ""), "lanes must not run in the background"


def test_a_landing_only_change_touches_no_other_lane(tmp_path: Path) -> None:
    """AC: change detection over a real git history."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            env={**os.environ, **env},
        )

    git("init", "-q")
    (repo / "apps" / "landing").mkdir(parents=True)
    (repo / "backend").mkdir()
    (repo / "apps" / "landing" / "page.tsx").write_text("v1")
    (repo / "backend" / "api.py").write_text("v1")
    git("add", "-A")
    git("commit", "-qm", "base")
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    (repo / "apps" / "landing" / "page.tsx").write_text("v2 copy edit")
    git("add", "-A")
    git("commit", "-qm", "landing copy edit")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()

    # live release worktrees: every lane live on `base`
    releases = tmp_path / "releases"
    live = releases / "live"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-f", str(live), base],
        check=True,
        capture_output=True,
    )
    for link in ("current", "demo-current", "landing-current"):
        (releases / link).symlink_to(live)

    body = f'''
CANONICAL_ROOT="{repo}"
RELEASES_ROOT="{releases}"
for l in api demo landing; do
    if lane_changed "$l" "{head}"; then echo "$l:changed"; else echo "$l:unchanged"; fi
done'''
    result = run_sourced(body)
    assert result.returncode == 0, result.stderr
    assert "landing:changed" in result.stdout
    assert "api:unchanged" in result.stdout
    assert "demo:unchanged" in result.stdout


def test_release_record_carries_only_observed_outcomes(tmp_path: Path) -> None:
    """AC: a defaulted or assumed success cannot be recorded."""
    body = f'''
RECORDS_DIR="{tmp_path}"
record_open "shaX" "short"
record_step api candidate "ready" "HTTP 200"
record_step api verify_shape "failed"
record_close "failed:api"
cat "${{RECORD_FILE}}"'''
    result = run_sourced(body)
    assert result.returncode == 0, result.stderr
    record = json.loads(result.stdout[result.stdout.index("{") :])
    steps = {(s["lane"], s["step"]): s["result"] for s in record["steps"]}
    assert steps[("api", "candidate")] == "ready"
    assert steps[("api", "verify_shape")] == "failed"
    assert steps[("-", "deploy")] == "failed:api"
    # No step exists that was never observed:
    assert ("api", "public_check") not in steps
    # And the recorder has no default result parameter:
    source = DEPLOY.read_text(encoding="utf-8")
    assert 'local lane="$1" step="$2" result="$3"' in source


def test_demo_lane_delegates_to_the_proven_script() -> None:
    source = DEPLOY.read_text(encoding="utf-8")
    assert 'deploy-demo-release.sh" "${sha}"' in source


def test_landing_lane_reuses_the_841_artifact_helpers() -> None:
    source = DEPLOY.read_text(encoding="utf-8")
    assert "fetch_landing_artifact" in source
    assert "place_landing_artifact" in source


def test_a_failed_lane_stops_the_run() -> None:
    """A Demo depending on new API capabilities must not ship over a failed API."""
    source = DEPLOY.read_text(encoding="utf-8")
    loop_at = source.index("for lane in ${lanes}")
    assert "break" in source[loop_at : source.index("record_close", loop_at)]


def test_migrations_run_before_candidates_and_rollback_never_reverts() -> None:
    source = DEPLOY.read_text(encoding="utf-8")
    api_lane = source[source.index("deploy_lane_api()") : source.index("deploy_lane_demo()")]
    assert api_lane.index("safe-alembic-upgrade.sh") < api_lane.index("systemd-run")
    rollback = source[source.index("rollback_lane()") : source.index("wait_2xx()")]
    for forbidden in ("alembic", "downgrade", "migration"):
        assert forbidden not in rollback.lower()
