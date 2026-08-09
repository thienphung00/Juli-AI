"""Graceful zero-downtime Demo cutover via an owned upstream (Issue #839, P0-DEL-SWITCH).

Before this slice, cutover was ``mv -Tf demo-current`` followed by
``systemctl restart juli-demo``. Nginx proxied straight at ``127.0.0.1:3001``, so the
restart *was* the error window: every in-flight and arriving request failed until the
process came back.

This slice removes the restart from the request path. Nginx proxies to an upstream whose
definition the deployment owns (``/etc/nginx/juli/demo-upstream.conf``). The candidate
started and verified by #838 is already serving on its own loopback port, so cutover is:
atomically replace that one file, validate, and reload nginx gracefully. Nothing is
restarted, so nothing in flight is dropped.

What can honestly be tested here
--------------------------------
There is no nginx and no systemd on this machine, and macOS ``mv`` has no ``-T``. So:

  * ``render_demo_upstream``, ``live_upstream_port``, ``demo_peer_port``,
    ``atomic_replace``, ``write_demo_runtime_env`` and ``switch_demo_upstream`` are all
    executed for real, against real files under ``tmp_path``.
  * ``nginx`` and ``systemctl`` are PATH-shadowing stubs that record their argv, so
    "validated before every reload", "reload never restart", and "an invalid
    configuration reloads nothing and restores the previous definition" are asserted on
    the real call sequence the script makes.
  * Ordering inside ``main()`` is source order in a shell script, so it is asserted
    against the source with comment lines stripped. Every such assertion first proves
    the marker exists (``first_index`` raises otherwise) — ``bash <missing>`` also exits
    non-zero, and that vacuous pass already slipped through once in #837.

NOT covered here, and deliberately not implied: no real nginx ever parsed the generated
upstream definition, and no real reload was ever observed to drain a connection. Those
are the VPS steps in the issue's HITL section.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "scripts" / "deploy-demo-release.sh"
PROVISION_SCRIPT = REPO_ROOT / "infra" / "scripts" / "provision-nginx.sh"
ROLLBACK_SCRIPT = REPO_ROOT / "infra" / "scripts" / "rollback-demo-release.sh"
NGINX_DIR = REPO_ROOT / "infra" / "nginx"
DEMO_VHOST = NGINX_DIR / "demo.app-juli.com.conf"
DEMO_UPSTREAM_SEED = NGINX_DIR / "demo-upstream.conf"
SYSTEMD_DEMO = REPO_ROOT / "infra" / "systemd" / "juli-demo.service"

UPSTREAM_NAME = "juli_demo"
LIVE_UPSTREAM_PATH = "/etc/nginx/juli/demo-upstream.conf"
PORT_A = "3001"
PORT_B = "3021"


# --------------------------------------------------------------------------------------
# Sourcing the deploy script as a library
# --------------------------------------------------------------------------------------


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
    return result.stdout + result.stderr


def non_comment_source(path: Path = DEPLOY_SCRIPT) -> str:
    """Script source with comment-only lines removed.

    Ordering and 'is it actually called' assertions must not be satisfiable by the
    header comment, which names every collaborating file.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def first_index(haystack: str, needle: str) -> int:
    idx = haystack.find(needle)
    assert idx != -1, f"{needle!r} never appears in the executable body under test"
    return idx


def function_body(name: str, source: str | None = None) -> str:
    body = non_comment_source() if source is None else source
    start = first_index(body, f"{name}() {{")
    return body[start : body.index("\n}", start)]


def main_body() -> str:
    """The body of ``main()`` — where deploy *step order* actually lives.

    Ordering is asserted on call sites, not on where functions happen to be defined,
    or moving a definition would silently satisfy the test.
    """
    return function_body("main")


def assert_defined(*names: str) -> None:
    """Precondition for every 'this fails' test: the function must exist.

    Calling a function that does not exist also exits non-zero, so without this a
    failure assertion proves nothing (the vacuous pass that slipped through in #837).
    """
    result = run_sourced("declare -F " + " ".join(names))
    assert result.returncode == 0, (
        f"{names} are not all defined by {DEPLOY_SCRIPT}: {output_of(result)}"
    )


# --------------------------------------------------------------------------------------
# Recording stubs — nginx and systemctl do not exist on this machine
# --------------------------------------------------------------------------------------


def recording_bin(tmp_path: Path, nginx_t_exit: int = 0) -> tuple[Path, Path]:
    """PATH-shadowing ``nginx``/``systemctl``/``systemd-run`` recording argv in call order."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "calls.log"
    for name in ("systemctl", "systemd-run"):
        stub = bindir / name
        stub.write_text(
            f'#!/usr/bin/env bash\nprintf "{name} %s\\n" "$*" >> "{log}"\nexit 0\n',
            encoding="utf-8",
        )
        stub.chmod(0o755)
    nginx = bindir / "nginx"
    nginx.write_text(
        "#!/usr/bin/env bash\n"
        f'printf "nginx %s\\n" "$*" >> "{log}"\n'
        f'if [ "${{1:-}}" = "-t" ]; then exit {nginx_t_exit}; fi\nexit 0\n',
        encoding="utf-8",
    )
    nginx.chmod(0o755)
    return bindir, log


def calls(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


def call_index(recorded: list[str], fragment: str) -> int:
    for i, line in enumerate(recorded):
        if fragment in line:
            return i
    raise AssertionError(f"{fragment!r} was never invoked; calls were: {recorded!r}")


@pytest.fixture
def upstream_env(tmp_path: Path) -> dict[str, str]:
    """A provisioned live upstream definition under tmp_path, serving PORT_A."""
    conf_dir = tmp_path / "nginx-juli"
    conf_dir.mkdir()
    conf = conf_dir / "demo-upstream.conf"
    conf.write_text(
        f"upstream {UPSTREAM_NAME} {{\n    server 127.0.0.1:{PORT_A};\n    keepalive 16;\n}}\n",
        encoding="utf-8",
    )
    return {
        "DEMO_UPSTREAM_CONF": str(conf),
        "DEMO_RUNTIME_ENV": str(tmp_path / "demo-runtime.env"),
    }


def live_conf(env: dict[str, str]) -> Path:
    return Path(env["DEMO_UPSTREAM_CONF"])


def prev_conf(env: dict[str, str]) -> Path:
    return Path(env["DEMO_UPSTREAM_CONF"] + ".prev")


# --------------------------------------------------------------------------------------
# Preconditions — guard against vacuous passes
# --------------------------------------------------------------------------------------


def test_collaborating_files_exist() -> None:
    """Every assertion below depends on these being real, not missing."""
    assert DEPLOY_SCRIPT.is_file(), f"{DEPLOY_SCRIPT} is missing"
    assert DEPLOY_SCRIPT.stat().st_mode & 0o111, f"{DEPLOY_SCRIPT} is not executable"
    assert PROVISION_SCRIPT.is_file(), f"{PROVISION_SCRIPT} is missing"
    assert ROLLBACK_SCRIPT.is_file(), f"{ROLLBACK_SCRIPT} is missing"
    assert DEMO_VHOST.is_file(), f"{DEMO_VHOST} is missing"
    assert SYSTEMD_DEMO.is_file(), f"{SYSTEMD_DEMO} is missing"


def test_deploy_script_parses() -> None:
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, output_of(result)


def test_switch_functions_are_defined() -> None:
    assert_defined(
        "render_demo_upstream",
        "live_upstream_port",
        "demo_peer_port",
        "atomic_replace",
        "switch_demo_upstream",
        "write_demo_runtime_env",
        "free_candidate_port",
    )


# --------------------------------------------------------------------------------------
# AC: the live upstream definition is the single source of truth for what is serving
# --------------------------------------------------------------------------------------


def test_vhost_proxies_through_the_named_upstream_not_a_literal_port() -> None:
    """The old vhost declared an upstream and then bypassed it with a literal port."""
    conf = DEMO_VHOST.read_text(encoding="utf-8")
    body = non_comment_source(DEMO_VHOST)
    assert f"proxy_pass http://{UPSTREAM_NAME};" in body, (
        "the demo vhost must proxy to the named upstream, not to a literal address"
    )
    assert "proxy_pass http://127.0.0.1:" not in body, (
        "a literal proxy_pass bypasses the upstream indirection this slice exists to add"
    )
    assert "app-juli.com" in conf


def test_vhost_delegates_the_upstream_definition_to_the_deployment() -> None:
    body = non_comment_source(DEMO_VHOST)
    assert f"include {LIVE_UPSTREAM_PATH};" in body, (
        f"the vhost must include the deployment-owned definition at {LIVE_UPSTREAM_PATH}"
    )
    assert f"upstream {UPSTREAM_NAME}" not in body, (
        "the vhost must not also define the upstream — two definitions means no single "
        "source of truth for what is serving"
    )


def test_repo_ships_the_seed_upstream_definition() -> None:
    """Provisioning needs something to install; a missing include target fails nginx -t."""
    assert DEMO_UPSTREAM_SEED.is_file(), f"missing seed definition: {DEMO_UPSTREAM_SEED}"
    seed = DEMO_UPSTREAM_SEED.read_text(encoding="utf-8")
    assert f"upstream {UPSTREAM_NAME} {{" in seed
    assert f"server 127.0.0.1:{PORT_A};" in seed


def test_site_configuration_is_otherwise_unchanged() -> None:
    """AC: 'site configuration is otherwise unchanged apart from the indirection'."""
    conf = DEMO_VHOST.read_text(encoding="utf-8")
    for expected in (
        "server_name demo.app-juli.com;",
        "listen 80;",
        # The flag form, not the standalone `http2 on;` directive: the review VPS
        # runs nginx 1.24.0, which rejects the directive form (>= 1.25.1 only) and
        # failed nginx -t on exactly this vhost on 2026-08-09.
        "listen 443 ssl http2;",
        "location /.well-known/acme-challenge/ {",
        "return 301 https://demo.app-juli.com$request_uri;",
        "/etc/letsencrypt/live/demo.app-juli.com/fullchain.pem",
        "/etc/letsencrypt/live/demo.app-juli.com/privkey.pem",
        "ssl_protocols       TLSv1.2 TLSv1.3;",
        "proxy_http_version 1.1;",
        "proxy_set_header Host              $host;",
        "proxy_set_header X-Real-IP         $remote_addr;",
        "proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;",
        "proxy_set_header X-Forwarded-Proto $scheme;",
        "proxy_set_header Upgrade           $http_upgrade;",
        'proxy_set_header Connection        "upgrade";',
    ):
        assert expected in conf, f"the indirection must not disturb: {expected!r}"
    assert "127.0.0.1:3000" not in conf, "demo vhost must not reach the App Review port"
    assert "127.0.0.1:8000" not in conf, "demo vhost must not reach the API port"


# --------------------------------------------------------------------------------------
# AC: what gets written — the generated definition
# --------------------------------------------------------------------------------------


def test_render_names_exactly_the_requested_port() -> None:
    result = run_sourced(f"render_demo_upstream {PORT_B}")
    assert result.returncode == 0, output_of(result)
    rendered = result.stdout
    assert f"upstream {UPSTREAM_NAME} {{" in rendered, rendered
    assert f"server 127.0.0.1:{PORT_B};" in rendered, rendered
    assert f"127.0.0.1:{PORT_A}" not in rendered, (
        "the definition must name one server only — it is the single source of truth"
    )
    assert rendered.count("server 127.0.0.1:") == 1, rendered


def test_render_refuses_a_port_that_is_not_a_number() -> None:
    """A malformed switch must never be able to inject directives into the live config."""
    assert_defined("render_demo_upstream")
    result = run_sourced('render_demo_upstream "3021; server 127.0.0.1:9999"')
    assert result.returncode != 0, output_of(result)
    assert "9999" not in result.stdout, "an injected server directive was rendered"


def test_render_refuses_a_port_out_of_range() -> None:
    assert_defined("render_demo_upstream")
    result = run_sourced("render_demo_upstream 70000")
    assert result.returncode != 0, output_of(result)


# --------------------------------------------------------------------------------------
# AC: the live definition is the single source of truth, and the pair alternates
# --------------------------------------------------------------------------------------


def test_live_port_is_read_from_the_live_definition(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    live_conf(upstream_env).write_text(
        f"upstream {UPSTREAM_NAME} {{\n    server 127.0.0.1:{PORT_B};\n    keepalive 16;\n}}\n",
        encoding="utf-8",
    )
    result = run_sourced("live_upstream_port", env=upstream_env)
    assert result.returncode == 0, output_of(result)
    assert result.stdout.strip() == PORT_B, output_of(result)


def test_live_port_is_a_failure_not_a_guess_when_the_definition_is_missing(
    tmp_path: Path,
) -> None:
    """Guessing here would start a candidate on the port that is already serving."""
    assert_defined("live_upstream_port")
    missing = tmp_path / "nowhere" / "demo-upstream.conf"
    result = run_sourced("live_upstream_port", env={"DEMO_UPSTREAM_CONF": str(missing)})
    assert result.returncode != 0, output_of(result)
    assert result.stdout.strip() == "", "no port may be printed when nothing is provisioned"


def test_the_candidate_takes_the_peer_of_whatever_is_live() -> None:
    for live, peer in ((PORT_A, PORT_B), (PORT_B, PORT_A)):
        result = run_sourced(f"demo_peer_port {live}")
        assert result.returncode == 0, output_of(result)
        assert result.stdout.strip() == peer, (
            f"live {live} must hand the candidate {peer}; got {result.stdout.strip()}"
        )


def test_peer_port_refuses_a_port_outside_the_pair() -> None:
    assert_defined("demo_peer_port")
    result = run_sourced("demo_peer_port 3999")
    assert result.returncode != 0, output_of(result)
    assert result.stdout.strip() == "", output_of(result)


# --------------------------------------------------------------------------------------
# AC: cutover is an atomic replacement followed by a graceful reload
# --------------------------------------------------------------------------------------


def test_switch_replaces_the_definition_atomically(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    bindir, _log = recording_bin(tmp_path)
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, output_of(result)
    live = live_conf(upstream_env).read_text(encoding="utf-8")
    assert f"server 127.0.0.1:{PORT_B};" in live, live
    assert f"127.0.0.1:{PORT_A}" not in live, live
    leftovers = sorted(p.name for p in live_conf(upstream_env).parent.glob("*.tmp*"))
    assert leftovers == [], f"a staged temp file was left in the include directory: {leftovers}"


def test_switch_never_edits_the_live_definition_in_place() -> None:
    """A partially written file that nginx reads is a live outage."""
    body = function_body("switch_demo_upstream")
    assert "atomic_replace" in body, "the switch must go through the atomic replacement helper"
    for in_place in (
        '>"${DEMO_UPSTREAM_CONF}"',
        '> "${DEMO_UPSTREAM_CONF}"',
        '>>"${DEMO_UPSTREAM_CONF}"',
        '>> "${DEMO_UPSTREAM_CONF}"',
        "sed -i",
    ):
        assert in_place not in body, (
            f"switch_demo_upstream writes the live definition in place via {in_place!r}"
        )
    assert "mv -Tf" in function_body("atomic_replace"), (
        "atomic replacement must be a rename, the same discipline demo-current uses"
    )


def test_atomic_replace_refuses_a_directory_destination(tmp_path: Path) -> None:
    """-T is what stops a replacement silently becoming a move-inside."""
    assert_defined("atomic_replace")
    src = tmp_path / "src"
    src.write_text("x\n", encoding="utf-8")
    dest = tmp_path / "dest"
    dest.mkdir()
    result = run_sourced(f'atomic_replace "{src}" "{dest}"')
    assert result.returncode != 0, output_of(result)
    assert src.is_file(), "the source must be left alone when the destination is refused"
    assert not (dest / "src").exists(), "the file was moved *into* the directory"


def test_configuration_is_validated_before_every_reload(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    bindir, log = recording_bin(tmp_path)
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, output_of(result)
    recorded = calls(log)
    assert call_index(recorded, "nginx -t") < call_index(recorded, "reload nginx"), (
        f"nginx -t must precede the reload; calls were: {recorded!r}"
    )


def test_nginx_is_reloaded_never_restarted(tmp_path: Path, upstream_env: dict[str, str]) -> None:
    """reload completes in-flight requests; restart drops them."""
    bindir, log = recording_bin(tmp_path)
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, output_of(result)
    recorded = calls(log)
    call_index(recorded, "reload nginx")
    assert not any("restart nginx" in line for line in recorded), recorded
    assert "systemctl restart nginx" not in non_comment_source()


# --------------------------------------------------------------------------------------
# AC: an invalid configuration is rejected without interrupting what is serving
# --------------------------------------------------------------------------------------


def test_an_invalid_configuration_reloads_nothing(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    assert_defined("switch_demo_upstream")
    bindir, log = recording_bin(tmp_path, nginx_t_exit=1)
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0, output_of(result)
    recorded = calls(log)
    call_index(recorded, "nginx -t")  # precondition: validation really was attempted
    assert not any("reload" in line for line in recorded), (
        f"a rejected configuration must never be reloaded; calls were: {recorded!r}"
    )


def test_an_invalid_configuration_restores_the_previously_serving_definition(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    before = live_conf(upstream_env).read_text(encoding="utf-8")
    bindir, _log = recording_bin(tmp_path, nginx_t_exit=1)
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode != 0, output_of(result)
    assert live_conf(upstream_env).read_text(encoding="utf-8") == before, (
        "the on-disk definition must be back to what is serving after a rejected switch"
    )


# --------------------------------------------------------------------------------------
# AC: the immediately previous definition is retained beside the live one
# --------------------------------------------------------------------------------------


def test_the_previous_definition_is_retained_beside_the_live_one(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    before = live_conf(upstream_env).read_text(encoding="utf-8")
    bindir, _log = recording_bin(tmp_path)
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, output_of(result)
    assert prev_conf(upstream_env).is_file(), "no retained definition to undo with"
    assert prev_conf(upstream_env).read_text(encoding="utf-8") == before


def test_the_retained_definition_is_the_immediately_previous_one(
    tmp_path: Path, upstream_env: dict[str, str]
) -> None:
    """Two releases in a row: the undo must be the last one, not the original."""
    bindir, _log = recording_bin(tmp_path)
    env = {**upstream_env, "PATH": f"{bindir}:{os.environ['PATH']}"}
    assert run_sourced(f"switch_demo_upstream {PORT_B}", env=env).returncode == 0
    after_first = live_conf(upstream_env).read_text(encoding="utf-8")
    assert run_sourced(f"switch_demo_upstream {PORT_A}", env=env).returncode == 0
    assert prev_conf(upstream_env).read_text(encoding="utf-8") == after_first, (
        "the retained definition must be the one that was serving immediately before"
    )


def test_switch_refuses_when_the_indirection_is_not_provisioned(tmp_path: Path) -> None:
    """Creating the include target here would hide that nginx never had it."""
    assert_defined("switch_demo_upstream")
    bindir, log = recording_bin(tmp_path)
    missing = tmp_path / "unprovisioned" / "demo-upstream.conf"
    result = run_sourced(
        f"switch_demo_upstream {PORT_B}",
        env={
            "DEMO_UPSTREAM_CONF": str(missing),
            "PATH": f"{bindir}:{os.environ['PATH']}",
        },
    )
    assert result.returncode != 0, output_of(result)
    assert "provision-nginx.sh" in output_of(result), (
        "the operator must be told the one-time provisioning step by name"
    )
    assert not missing.exists(), "the switch must not provision nginx behind the operator"
    assert calls(log) == [] or not any("reload" in c for c in calls(log))


# --------------------------------------------------------------------------------------
# AC: no request observes an unavailable upstream — ordering inside main()
# --------------------------------------------------------------------------------------


def test_verification_still_precedes_every_live_mutation() -> None:
    """#838 must not regress: verify first, mutate second."""
    body = main_body()
    verify_at = first_index(body, "verify_candidate ")
    for mutation in (
        "switch_demo_upstream ",
        "mv -Tf",
        "prune_release_worktrees ",
        "/etc/systemd/system/juli-demo.service",
    ):
        assert verify_at < first_index(body, mutation), (
            f"{mutation!r} runs before verification in main() — a failed check would "
            "already have reached visitors"
        )


def test_the_switch_is_the_first_publicly_visible_step_of_cutover() -> None:
    """Nothing public may change before the upstream flip; if the flip fails, nothing did."""
    body = main_body()
    switch_at = first_index(body, "switch_demo_upstream ")
    assert first_index(body, "start_candidate ") < switch_at
    assert switch_at < first_index(body, "mv -Tf"), (
        "demo-current is repointed after the flip, so a rejected configuration leaves "
        "the release pointer exactly where it was"
    )


def test_cutover_no_longer_restarts_the_live_demo_service() -> None:
    """The restart *was* the error window. It must be gone from the deploy path."""
    body = non_comment_source()
    first_index(body, "switch_demo_upstream")  # precondition: the replacement exists
    assert "systemctl restart juli-demo" not in body, (
        "restarting juli-demo at cutover is exactly the outage this slice removes"
    )


def test_the_verified_candidate_is_not_stopped_at_cutover() -> None:
    """It is the new live instance; stopping it would take the site down."""
    body = main_body()
    after_switch = body[first_index(body, "switch_demo_upstream ") :]
    assert "stop_candidate" not in after_switch, (
        "the promoted candidate is what is serving after the switch"
    )


def test_the_previous_instance_is_only_stopped_when_its_port_is_needed() -> None:
    """It is the undo; it is freed at the *next* deploy, when it is no longer serving."""
    body = main_body()
    assert first_index(body, "free_candidate_port ") < first_index(body, "start_candidate "), (
        "the candidate port must be freed before a candidate is started on it"
    )


# --------------------------------------------------------------------------------------
# Durability: a reboot must bring the live port back, not the port that used to be live
# --------------------------------------------------------------------------------------


def test_the_durable_unit_takes_its_port_from_the_deployment(tmp_path: Path) -> None:
    unit = SYSTEMD_DEMO.read_text(encoding="utf-8")
    assert "Environment=DEMO_LIVE_PORT=3001" in unit, (
        "a default is required so the unit still starts before the first switch"
    )
    assert "EnvironmentFile=-/etc/juli/demo-runtime.env" in unit, unit
    assert "--port ${DEMO_LIVE_PORT}" in unit, unit
    assert unit.index("Environment=DEMO_LIVE_PORT") < unit.index("EnvironmentFile="), (
        "the deployment-written file must be read after the baked default, or it cannot override it"
    )
    assert "releases/demo-current" in unit


def test_write_demo_runtime_env_records_the_live_port_atomically(tmp_path: Path) -> None:
    target = tmp_path / "etc" / "demo-runtime.env"
    result = run_sourced(f"write_demo_runtime_env {PORT_B}", env={"DEMO_RUNTIME_ENV": str(target)})
    assert result.returncode == 0, output_of(result)
    assert target.read_text(encoding="utf-8").strip().endswith(f"DEMO_LIVE_PORT={PORT_B}")
    assert "atomic_replace" in function_body("write_demo_runtime_env")


def test_main_records_the_live_port_after_the_switch() -> None:
    body = main_body()
    assert first_index(body, "switch_demo_upstream ") < first_index(
        body, "write_demo_runtime_env "
    ), "the port is only durable once it is actually live"


# --------------------------------------------------------------------------------------
# The one-time provisioning step
# --------------------------------------------------------------------------------------


def test_provisioning_installs_the_owned_definition_before_the_vhosts() -> None:
    """A vhost whose include target is missing fails nginx -t for *every* site."""
    body = non_comment_source(PROVISION_SCRIPT)
    # Compared on the install *call sites*, not on the variable declarations at the top
    # of the script — those appear in declaration order and would prove nothing.
    seed_at = first_index(body, 'install -m 0644 "${seed}"')
    assert seed_at < first_index(body, 'install -m 0644 "${src}" "${SITES_AVAILABLE}'), (
        "install the include target before the vhost that includes it"
    )
    assert first_index(body, "nginx -t") < first_index(body, "systemctl reload nginx")
    assert "systemctl restart nginx" not in body


def test_provisioning_never_overwrites_a_live_upstream_definition() -> None:
    """Re-provisioning must not silently repoint the site at the seed port."""
    body = non_comment_source(PROVISION_SCRIPT)
    # #843 generalized the seeding into one loop over demo/api/landing; the
    # never-overwrite guard now protects every lane's live definition at once.
    seed_at = first_index(body, "-upstream.conf")
    window = body[max(0, seed_at - 400) : seed_at + 700]
    assert "-f" in window and "already" in window.lower(), (
        "provisioning must skip an existing live definition, not clobber it: " + window
    )


# --------------------------------------------------------------------------------------
# The undo. Manual for this slice; #840 automates it.
# --------------------------------------------------------------------------------------


def test_rollback_reuses_the_one_switch_implementation() -> None:
    """Two copies of the switch could disagree about what is serving."""
    body = non_comment_source(ROLLBACK_SCRIPT)
    assert "deploy-demo-release.sh" in body, "rollback must source the switch mechanics"
    assert "DEMO_DEPLOY_SOURCE_ONLY=1" in body, "sourcing must not run a deploy"
    assert "switch_demo_upstream" in body
    assert f"upstream {UPSTREAM_NAME} {{" not in body, (
        "rollback must not render its own upstream definition"
    )


def test_rollback_switches_only_after_the_target_is_healthy() -> None:
    body = non_comment_source(ROLLBACK_SCRIPT)
    assert first_index(body, "wait_for_candidate ") < first_index(body, "switch_demo_upstream "), (
        "nothing public may move until the rollback target answers"
    )
    assert first_index(body, "switch_demo_upstream ") < first_index(body, "mv -Tf"), (
        "a refused switch must leave demo-current where it was"
    )


def test_rollback_never_prunes_release_worktrees() -> None:
    """~/releases is one pool shared by every deploy lane."""
    body = non_comment_source(ROLLBACK_SCRIPT)
    first_index(body, "switch_demo_upstream")  # precondition: the script really is wired
    for forbidden in ("prune_release_worktrees", "rm -rf", "git worktree remove"):
        assert forbidden not in body, f"rollback must never {forbidden!r}"


def test_rollback_documents_the_retained_definition_as_the_instant_undo() -> None:
    text = ROLLBACK_SCRIPT.read_text(encoding="utf-8")
    assert "demo-upstream.conf.prev" in text
    assert "systemctl reload nginx" in text


def test_rollback_script_parses() -> None:
    result = subprocess.run(
        ["bash", "-n", str(ROLLBACK_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, output_of(result)


def test_provision_script_parses() -> None:
    result = subprocess.run(
        ["bash", "-n", str(PROVISION_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, output_of(result)
