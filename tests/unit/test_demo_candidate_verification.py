"""Candidate verify-and-discard contract for the Demo deploy (Issue #838, P0-DEL-CANDIDATE).

The script under test is ``infra/scripts/deploy-demo-release.sh``. Before this slice it
mutated first and verified second: it flipped ``demo-current`` and restarted ``juli-demo``,
then health-checked. A failed check therefore left the broken release public. This slice
inverts that — the release starts as a *candidate* on a loopback-bound port, the #833
verification harness runs against it, and only a pass proceeds to cutover.

What can honestly be tested here
--------------------------------
systemd and a real VPS are not available, so nothing below pretends to start a real
candidate. What *is* exercised for real:

  * ``place_release_artifact`` against a real tarball in the #837 artifact shape,
    including the symlinked dependency tree and the commit-traceability refusal.
  * ``run_migration_gate`` shelling out to the real ``migration_additive_gate.py`` with
    real additive and real destructive migration files.
  * ``verify_candidate`` shelling out to the real ``verify-release-assets.sh`` against
    local fixture HTTP servers — healthy, missing-asset, and broken-API-shape.
  * ``fail_candidate`` with a recording ``systemctl`` stub on PATH: it must stop the
    candidate, must never restart ``juli-demo``, and must exit non-zero.

The remaining property — *ordering* — is source order in a shell script, so it is asserted
against the source with comments stripped. Every such test first asserts the marker exists,
because ``bash <missing-script>`` also exits non-zero and would otherwise prove nothing
(the vacuous-pass trap from #837).
"""

from __future__ import annotations

import http.server
import json
import os
import re
import stat
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "deploy-demo-release.sh"
VERIFY_HARNESS = REPO_ROOT / "infra" / "scripts" / "verify-release-assets.sh"
MIGRATION_GATE = REPO_ROOT / "infra" / "scripts" / "migration_additive_gate.py"

FULL_SHA = "1234567890abcdef1234567890abcdef12345678"
SHORT_SHA = FULL_SHA[:7]
OTHER_SHA = "fedcba0987654321fedcba0987654321fedcba09"

CSS_BODY = b"/* juli */\n" + b".juli-card{display:flex;gap:12px;padding:16px}\n" * 6
JS_BODY = b"// juli\n" + b"window.__juli=window.__juli||{};\n" * 10
ERROR_HTML = (
    b"<!DOCTYPE html><html><head><title>404 Not Found</title></head>"
    b"<body><center><h1>404 Not Found</h1></center>"
    b"<hr><center>nginx/1.24.0</center></body></html>"
)
PAGE = (
    b"<!DOCTYPE html><html><head>"
    b'<link rel="stylesheet" href="/static/app.css"/>'
    b'<script src="/static/app.js" defer=""></script>'
    b"</head><body><main>Juli</main></body></html>"
)


# --------------------------------------------------------------------------------------
# Fixture HTTP server (same shape as tests/unit/test_verify_release_assets.py)
# --------------------------------------------------------------------------------------


def _make_handler(routes: dict[str, tuple[int, str, bytes]]) -> type:
    class _FixtureHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            path = self.path.split("?", 1)[0]
            status, content_type, body = routes.get(path, (404, "text/html", ERROR_HTML))
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            return

    return _FixtureHandler


@contextmanager
def serve(routes: dict[str, tuple[int, str, bytes]]) -> Iterator[str]:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(routes))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def healthy_pages() -> dict[str, tuple[int, str, bytes]]:
    return {
        "/": (200, "text/html; charset=utf-8", PAGE),
        "/decisions": (200, "text/html; charset=utf-8", PAGE),
        "/static/app.css": (200, "text/css; charset=utf-8", CSS_BODY),
        "/static/app.js": (200, "application/javascript", JS_BODY),
    }


# --------------------------------------------------------------------------------------
# Sourcing the deploy script as a library
# --------------------------------------------------------------------------------------


def run_sourced(
    body: str,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
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
        timeout=180,
        env=full_env,
        cwd=str(cwd) if cwd else str(REPO_ROOT),
    )


def output_of(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def non_comment_source() -> str:
    """Script source with comment-only lines removed.

    Ordering and 'is it actually called' assertions must not be satisfiable by the
    header comment, which names every collaborating script.
    """
    lines = DEPLOY_SCRIPT.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def first_index(haystack: str, needle: str) -> int:
    idx = haystack.find(needle)
    assert idx != -1, f"{needle!r} never appears in the executable body of {DEPLOY_SCRIPT}"
    return idx


def main_body() -> str:
    """The body of ``main()`` — where deploy *step order* actually lives.

    Ordering must be asserted on call sites, not on where functions happen to be
    defined, or moving a definition would silently satisfy the test.
    """
    body = non_comment_source()
    start = first_index(body, "main() {")
    end = body.index("\n}", start)
    return body[start:end]


def assert_defined(*names: str) -> None:
    """Precondition for every 'this fails' test: the function must exist.

    A call to a function that does not exist also exits non-zero, so without this a
    failure assertion proves nothing (the vacuous pass that slipped through in #837).
    """
    result = run_sourced("declare -F " + " ".join(names))
    assert result.returncode == 0, (
        f"{names} are not all defined by {DEPLOY_SCRIPT}: {output_of(result)}"
    )


# --------------------------------------------------------------------------------------
# Artifact fixtures — the #837 shape
# --------------------------------------------------------------------------------------


def build_artifact_tarball(tmp_path: Path, commit: str = FULL_SHA) -> Path:
    """Build a tarball matching build-release-artifact.sh output, symlinks included."""
    stage_root = tmp_path / "stage"
    stage = stage_root / f"juli-demo-{commit[:7]}"
    (stage / ".next" / "static" / "chunks").mkdir(parents=True)
    (stage / ".next" / "server" / "app").mkdir(parents=True)
    (stage / ".next" / "BUILD_ID").write_text("build-id-838\n", encoding="utf-8")
    (stage / ".next" / "static" / "chunks" / "main.js").write_bytes(JS_BODY)
    (stage / ".next" / "server" / "app" / "index.html").write_bytes(PAGE)
    (stage / ".next" / "server" / "app" / "decisions.html").write_bytes(PAGE)
    (stage / "public").mkdir()
    (stage / "public" / "favicon.ico").write_bytes(b"\x00" * 128)
    (stage / "package.json").write_text(
        json.dumps({"name": "@juli/demo", "version": "0.1.0"}), encoding="utf-8"
    )
    (stage / "release-artifact.json").write_text(
        json.dumps(
            {
                "schema": "juli.release-artifact/v1",
                "app": "demo",
                "commit": commit,
                "commitShort": commit[:7],
                "startCommand": "node_modules/.bin/next start",
            }
        ),
        encoding="utf-8",
    )
    # The dependency tree is a symlink farm. If placement dereferences it the release
    # arrives duplicated or broken, which is exactly what ADR-058 packages a tarball to
    # avoid — so the fixture must contain a real symlink.
    real_bin = stage / "node_modules" / "next" / "dist" / "bin"
    real_bin.mkdir(parents=True)
    next_bin = real_bin / "next"
    next_bin.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    next_bin.chmod(next_bin.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    dot_bin = stage / "node_modules" / ".bin"
    dot_bin.mkdir(parents=True)
    (dot_bin / "next").symlink_to(Path("../next/dist/bin/next"))

    tarball = tmp_path / f"juli-demo-{commit[:7]}.tar.gz"
    subprocess.run(
        ["tar", "-czf", str(tarball), "-C", str(stage_root), stage.name],
        check=True,
    )
    return tarball


def make_release_dir(tmp_path: Path) -> Path:
    """A release worktree as `git worktree add` leaves it: source, no build output."""
    release_dir = tmp_path / "releases" / SHORT_SHA
    demo = release_dir / "apps" / "demo"
    demo.mkdir(parents=True)
    (demo / "next.config.ts").write_text("export default {};\n", encoding="utf-8")
    (demo / "src").mkdir()
    return release_dir


def recording_systemctl(tmp_path: Path) -> tuple[Path, Path]:
    """A PATH-shadowing ``systemctl``/``systemd-run`` that records its argv."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "systemctl.log"
    for name in ("systemctl", "systemd-run"):
        stub = bindir / name
        stub.write_text(
            f'#!/usr/bin/env bash\nprintf "{name} %s\\n" "$*" >> "{log}"\nexit 0\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
    return bindir, log


# --------------------------------------------------------------------------------------
# Preconditions — guard against vacuous passes
# --------------------------------------------------------------------------------------


def test_collaborating_scripts_exist() -> None:
    """Every failure assertion below depends on these being invocable, not missing."""
    assert DEPLOY_SCRIPT.is_file(), f"{DEPLOY_SCRIPT} is missing"
    assert DEPLOY_SCRIPT.stat().st_mode & 0o111, f"{DEPLOY_SCRIPT} is not executable"
    assert VERIFY_HARNESS.is_file(), "the #833 harness this slice wires in is missing"
    assert MIGRATION_GATE.is_file(), "the #834 gate this slice wires in is missing"


def test_deploy_script_parses() -> None:
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, output_of(result)


def test_script_can_be_sourced_without_deploying() -> None:
    """Library mode must define the functions and touch nothing."""
    result = run_sourced("declare -F place_release_artifact verify_candidate fail_candidate")
    assert result.returncode == 0, output_of(result)
    assert "place_release_artifact" in result.stdout


# --------------------------------------------------------------------------------------
# AC: the candidate binds a loopback port
# --------------------------------------------------------------------------------------


def test_candidate_binds_loopback_only() -> None:
    result = run_sourced("demo_candidate_argv /srv/rel 3021")
    assert result.returncode == 0, output_of(result)
    argv = result.stdout.split()
    assert "--hostname" in argv, output_of(result)
    assert argv[argv.index("--hostname") + 1] == "127.0.0.1", (
        "the candidate must bind loopback; #835 proved that alone makes it unreachable "
        f"on the external interface. got: {result.stdout}"
    )
    assert argv[argv.index("--port") + 1] == "3021"
    assert "0.0.0.0" not in result.stdout


def test_candidate_port_is_not_the_live_port() -> None:
    result = run_sourced('echo "${DEMO_CANDIDATE_PORT}"; echo "${DEMO_PORT}"')
    assert result.returncode == 0, output_of(result)
    candidate_port, live_port = result.stdout.split()
    assert candidate_port != live_port, "a candidate on the live port would be a cutover"


def test_only_the_candidate_helper_spawns_next() -> None:
    """Anti-drift: nothing may start `next` except the argv helper under test."""
    body = non_comment_source()
    assert body.count("node_modules/.bin/next") == 1, (
        "the demo `next` binary must be named exactly once, inside demo_candidate_argv, "
        "so the argv these tests assert on cannot drift from what systemd-run launches"
    )
    argv_at = first_index(body, "demo_candidate_argv() {")
    argv_end = body.index("\n}", argv_at)
    assert "node_modules/.bin/next" in body[argv_at:argv_end]
    assert "demo_candidate_argv" in body[body.index("start_candidate() {") :], (
        "start_candidate must build its argv from demo_candidate_argv"
    )


# --------------------------------------------------------------------------------------
# AC: the CI artifact is fetched and placed (closing the #837 deploy freeze)
# --------------------------------------------------------------------------------------


def test_place_release_artifact_populates_the_release_dir(tmp_path: Path) -> None:
    tarball = build_artifact_tarball(tmp_path)
    release_dir = make_release_dir(tmp_path)
    result = run_sourced(f'place_release_artifact "{tarball}" "{release_dir}" "{FULL_SHA}"')
    assert result.returncode == 0, output_of(result)
    demo = release_dir / "apps" / "demo"
    assert (demo / ".next" / "BUILD_ID").is_file()
    assert (demo / ".next" / "static" / "chunks" / "main.js").is_file()
    assert (demo / "public" / "favicon.ico").is_file()
    assert (demo / "node_modules" / ".bin" / "next").exists()
    # Source the worktree already carried must survive the overlay.
    assert (demo / "next.config.ts").is_file()


def test_place_release_artifact_keeps_the_dependency_tree_symlinked(
    tmp_path: Path,
) -> None:
    tarball = build_artifact_tarball(tmp_path)
    release_dir = make_release_dir(tmp_path)
    result = run_sourced(f'place_release_artifact "{tarball}" "{release_dir}" "{FULL_SHA}"')
    assert result.returncode == 0, output_of(result)
    bin_next = release_dir / "apps" / "demo" / "node_modules" / ".bin" / "next"
    assert bin_next.is_symlink(), (
        "placement dereferenced the pnpm symlink farm; ADR-058 ships a tarball "
        "precisely so the tree survives being moved"
    )
    assert os.access(bin_next.resolve(), os.X_OK)


def test_place_release_artifact_refuses_a_foreign_commit(tmp_path: Path) -> None:
    """release-artifact.json is the traceability record; a mismatch must not be placed."""
    tarball = build_artifact_tarball(tmp_path, commit=OTHER_SHA)
    release_dir = make_release_dir(tmp_path)
    result = run_sourced(f'place_release_artifact "{tarball}" "{release_dir}" "{FULL_SHA}"')
    assert result.returncode != 0, output_of(result)
    assert OTHER_SHA in output_of(result), "the mismatching commit must be named"
    assert not (release_dir / "apps" / "demo" / ".next").exists(), (
        "a refused artifact must leave the release directory unpopulated"
    )


def test_missing_artifact_is_a_named_failure_not_a_silent_build(tmp_path: Path) -> None:
    assert_defined("place_release_artifact")
    release_dir = make_release_dir(tmp_path)
    missing = tmp_path / "juli-demo-nope.tar.gz"
    result = run_sourced(f'place_release_artifact "{missing}" "{release_dir}" "{FULL_SHA}"')
    assert result.returncode != 0, output_of(result)
    assert "pnpm install" not in output_of(result)
    assert not (release_dir / "apps" / "demo" / ".next").exists()


# --------------------------------------------------------------------------------------
# AC: the #834 migration gate runs, and refuses, before any candidate starts
# --------------------------------------------------------------------------------------


ADDITIVE_MIGRATION = '''"""add a nullable column"""
revision = "aaaa1111"
down_revision = "0000"


def upgrade() -> None:
    op.add_column("orders", sa.Column("note", sa.String(), nullable=True))


def downgrade() -> None:
    pass
'''

DESTRUCTIVE_MIGRATION = '''"""drop a column"""
revision = "bbbb2222"
down_revision = "aaaa1111"


def upgrade() -> None:
    op.drop_column("orders", "note")


def downgrade() -> None:
    pass
'''


def _versions_dir(tmp_path: Path, files: dict[str, str]) -> Path:
    versions = tmp_path / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (versions / name).write_text(text, encoding="utf-8")
    return versions


def test_migration_gate_accepts_additive_change(tmp_path: Path) -> None:
    versions = _versions_dir(tmp_path, {"aaaa1111_add_note.py": ADDITIVE_MIGRATION})
    result = run_sourced(
        f'run_migration_gate --migration-file "{versions / "aaaa1111_add_note.py"}"'
    )
    assert result.returncode == 0, output_of(result)
    assert "ACCEPTED" in output_of(result)


def test_migration_gate_refuses_destructive_change(tmp_path: Path) -> None:
    versions = _versions_dir(
        tmp_path,
        {
            "aaaa1111_add_note.py": ADDITIVE_MIGRATION,
            "bbbb2222_drop_note.py": DESTRUCTIVE_MIGRATION,
        },
    )
    result = run_sourced(
        f'run_migration_gate --migration-file "{versions / "bbbb2222_drop_note.py"}"'
    )
    assert result.returncode != 0, output_of(result)
    assert "REFUSED" in output_of(result)
    assert "drop_column" in output_of(result) or "orders" in output_of(result)


def test_gate_argv_carries_the_empty_revisions_value_when_nothing_is_pending() -> None:
    """A release with no schema change must still produce a real ACCEPTED verdict.

    ``--revisions`` needs an explicit empty value. If that trailing empty token is lost,
    argparse errors and every clean release is misreported as a refusal.
    """
    assert_defined("migration_gate_args", "run_migration_gate")
    result = run_sourced(f'migration_gate_args "{REPO_ROOT}" "" "HEAD"')
    assert result.returncode == 0, output_of(result)
    assert result.stdout.endswith("--revisions\n\n"), (
        "the empty --revisions value was dropped; argparse would then error and every "
        f"clean release would look like a refusal. got: {result.stdout!r}"
    )

    piped = run_sourced(
        'args=(); while IFS= read -r t; do args+=("$t"); done '
        f'< <(migration_gate_args "{REPO_ROOT}" "" "HEAD"); '
        'run_migration_gate "${args[@]}"'
    )
    assert piped.returncode == 0, output_of(piped)
    assert "ACCEPTED" in output_of(piped)


def test_an_unresolvable_baseline_is_a_failure_not_an_empty_pending_set() -> None:
    """A shallow clone must not turn the additive-only gate into a no-op.

    ``git diff`` against a commit this checkout does not have exits non-zero and prints
    nothing. Reading that as 'no pending schema change' would accept every release without
    inspecting a single migration.
    """
    assert_defined("migration_gate_args")
    missing = "0" * 40
    result = run_sourced(f'migration_gate_args "{REPO_ROOT}" "{missing}" "HEAD"')
    assert result.returncode != 0, output_of(result)
    assert "--migrations-dir" not in result.stdout, (
        "an unresolvable baseline emitted an empty pending set, which the gate would "
        f"accept vacuously: {result.stdout!r}"
    )
    assert missing in output_of(result), "the unresolvable baseline must be named"


def test_migration_gate_precedes_the_candidate_in_the_deploy(tmp_path: Path) -> None:
    """Journey `migration-gate-refuses`: no candidate is started at all."""
    body = main_body()
    gate_at = first_index(body, "run_migration_gate ")
    candidate_at = first_index(body, "start_candidate ")
    assert gate_at < candidate_at, (
        "the #834 gate must run before any candidate starts, so a refusal means no "
        "candidate was ever started"
    )


# --------------------------------------------------------------------------------------
# AC: the #833 harness runs against the candidate, before any traffic moves
# --------------------------------------------------------------------------------------


def test_verify_candidate_passes_a_healthy_candidate() -> None:
    with serve(healthy_pages()) as base_url:
        result = run_sourced(f'verify_candidate "{base_url}"')
    assert result.returncode == 0, output_of(result)
    assert "/decisions" in output_of(result), "the /decisions route must be verified"


def test_verify_candidate_names_a_missing_stylesheet() -> None:
    """Journey `candidate-serves-a-page-with-a-missing-asset`."""
    routes = healthy_pages()
    del routes["/static/app.css"]
    with serve(routes) as base_url:
        result = run_sourced(f'verify_candidate "{base_url}"')
    assert result.returncode != 0, output_of(result)
    assert "/static/app.css" in output_of(result), "the failing asset must be named"


def test_verify_candidate_fails_a_dead_candidate() -> None:
    """Journey `candidate-fails-readiness` — nothing is listening at all."""
    assert_defined("verify_candidate")
    with serve({}) as base_url:
        pass  # server is now closed; the port is dead
    result = run_sourced(f'verify_candidate "{base_url}"')
    assert result.returncode != 0, output_of(result)


def test_verify_candidate_fails_an_api_path_on_shape_not_status() -> None:
    """Journey `candidate-fails-an-api-path`: 200 with the wrong body is still a failure."""
    routes = healthy_pages()
    routes["/v1/health"] = (200, "application/json", b'{"ok": true}')
    with serve(routes) as base_url:
        result = run_sourced(
            f'verify_candidate "{base_url}"',
            env={
                "DEMO_CANDIDATE_API_BASE_URL": base_url,
                "DEMO_CANDIDATE_API_CHECKS": "/v1/health:status,version",
            },
        )
    assert result.returncode != 0, output_of(result)
    combined = output_of(result)
    assert "/v1/health" in combined
    assert "status" in combined and "version" in combined


def test_verify_candidate_passes_a_correctly_shaped_api_path() -> None:
    routes = healthy_pages()
    routes["/v1/health"] = (
        200,
        "application/json",
        b'{"status": "ok", "version": "1.2.3"}',
    )
    with serve(routes) as base_url:
        result = run_sourced(
            f'verify_candidate "{base_url}"',
            env={
                "DEMO_CANDIDATE_API_BASE_URL": base_url,
                "DEMO_CANDIDATE_API_CHECKS": "/v1/health:status,version",
            },
        )
    assert result.returncode == 0, output_of(result)


def test_verification_precedes_every_live_mutation() -> None:
    """The whole point of the slice: mutate second, verify first."""
    body = main_body()
    verify_at = first_index(body, "verify_candidate ")
    for mutation in (
        # `systemctl restart juli-demo` used to head this list. #839 deleted that step:
        # the restart *was* the outage. Its successor as the first publicly visible
        # mutation is the upstream switch, and it is gated on verification exactly the
        # same way.
        "switch_demo_upstream ",
        "prune_release_worktrees ",
        "/etc/systemd/system/juli-demo.service",
        "mv -Tf",
    ):
        assert verify_at < first_index(body, mutation), (
            f"{mutation!r} runs before verification in main() — a failed check would "
            "already have reached visitors"
        )


def test_candidate_starts_before_verification() -> None:
    body = main_body()
    assert first_index(body, "start_candidate ") < first_index(body, "verify_candidate "), (
        "the harness must run against the candidate, not against the live instance"
    )


# --------------------------------------------------------------------------------------
# AC: every failure path stops the candidate, exits non-zero, leaves live serving
# --------------------------------------------------------------------------------------


def test_fail_candidate_stops_the_candidate_and_exits_non_zero(tmp_path: Path) -> None:
    bindir, log = recording_systemctl(tmp_path)
    result = run_sourced(
        'fail_candidate "readiness never came"',
        env={"PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0, output_of(result)
    assert "readiness never came" in output_of(result)
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "stop juli-demo-candidate" in calls, (
        f"the candidate must be stopped on every failure path; calls were: {calls!r}"
    )


def test_fail_candidate_never_touches_the_live_service(tmp_path: Path) -> None:
    """Journeys 2-5: 'the previously live version is still serving, unmodified'."""
    assert_defined("fail_candidate")
    bindir, log = recording_systemctl(tmp_path)
    result = run_sourced(
        'fail_candidate "boom"',
        env={"PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0, output_of(result)
    calls = log.read_text(encoding="utf-8") if log.exists() else ""
    assert "restart juli-demo\n" not in calls, f"live service was restarted: {calls!r}"
    assert re.search(r"\brestart juli-demo\b", calls) is None, (
        f"live service was restarted on a failure path: {calls!r}"
    )


def test_no_failure_path_prunes_release_worktrees() -> None:
    """~/releases is one pool shared by every deploy lane; a prune has cost the live release."""
    body = non_comment_source()
    # Precondition: both the prune and the failure handler must exist, or the
    # containment assertion below would hold vacuously.
    first_index(body, "prune_release_worktrees ")
    fail_at = first_index(body, "fail_candidate() {")
    fail_body = body[fail_at : body.index("\n}", fail_at)]
    for forbidden in ("prune_release_worktrees", "rm -rf", "git worktree remove"):
        assert forbidden not in fail_body, (
            f"fail_candidate must never {forbidden!r} — ~/releases is shared across lanes"
        )


def test_failure_paths_route_through_fail_candidate() -> None:
    """Once the candidate is up, no bare `exit 1` may bypass stopping it."""
    body = main_body()
    after_start = body[first_index(body, "start_candidate ") :]
    assert "fail_candidate" in after_start, (
        "the post-start section must fail through fail_candidate so the candidate is always stopped"
    )


# --------------------------------------------------------------------------------------
# Documentation of the operator contract
# --------------------------------------------------------------------------------------


def test_header_documents_the_candidate_contract() -> None:
    header = DEPLOY_SCRIPT.read_text(encoding="utf-8")[:6000]
    lowered = header.lower()
    for token in ("candidate", "127.0.0.1", "#838"):
        assert token in lowered or token in header, f"header does not mention {token}"
