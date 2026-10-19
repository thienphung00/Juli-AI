"""Production rollback, proven without production (fast-track P56, D65).

Runs the real ``infra/scripts/rollback-release.sh`` (which sources the real deploy.sh
and calls the real rollback-demo-release.sh and verify-release-assets.sh) against a
simulated VPS: three release dirs in a temp ``releases/`` pool, nginx upstream includes,
``/etc/juli`` and ``/etc/systemd/system`` stand-ins, and stubbed systemctl / systemd-run /
journalctl / nginx / curl from ``tests/support/rollback_sim_stub.py``.

Start state, as production looks after three good deploys (A, B, C):
  api      C live on :8020 (B's drained instance still on :8000)
  demo     C live on :3021 (B on :3001)
  landing  C live on :3027 (B on :3007)
  worker + beat active, running ~/releases/current (C)

What is proven: the default target and per-lane resolution (including a demo-only
deploy and a pruned release), the back/forward lane order, each lane's candidate-first
cutover, the runtime env + unit files coming from the TARGET release, the worker queue
check, the automatic undo on a failed public check, failure paths that change nothing,
the PASS/FAIL summary, and that nothing ever touches the database or juli-web.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "infra/scripts/rollback-release.sh"
STUB = REPO_ROOT / "tests/support/rollback_sim_stub.py"
STUB_NAMES = (
    "systemctl",
    "systemd-run",
    "journalctl",
    "nginx",
    "curl",
    "sleep",
    "mv",
    "psql",
    "pg_dump",
    "pg_restore",
    "alembic",
)
UNITS = (
    "juli-api",
    "juli-celery-worker",
    "juli-celery-beat",
    "juli-landing",
    "juli-demo",
)

pytestmark = pytest.mark.timeout(120)

SHA = {name: (name * 40)[:40] for name in ("a", "b", "c", "d")}
SHORT = {name: sha[:7] for name, sha in SHA.items()}
ALL = ("api", "demo", "landing")
ARTIFACT = {
    "api": ".venv/bin/uvicorn",
    "demo": "apps/demo/node_modules/.bin/next",
    "landing": "apps/landing/node_modules/.bin/next",
}
LINK = {"api": "current", "demo": "demo-current", "landing": "landing-current"}
UPSTREAM_NAME = {"api": "juli_api", "demo": "juli_demo", "landing": "juli_landing"}


def _exe(path: Path, body: str = "#!/bin/sh\nexit 0\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


@dataclass
class Run:
    code: int
    out: str

    def __repr__(self) -> str:  # pytest shows this on assertion failure
        return f"exit {self.code}\n{self.out}"


class World:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.releases = self.root / "releases"
        self.nginx = self.root / "nginx"
        self.etc = self.root / "etc-juli"
        self.unit_dir = self.root / "systemd"
        self.state = self.root / "state"
        self.bin = self.root / "bin"
        for d in (self.releases, self.nginx, self.etc, self.unit_dir, self.bin):
            d.mkdir(parents=True)
        for d in ("units", "ports", "flags", "nginx-loaded"):
            (self.state / d).mkdir(parents=True)
        for name in STUB_NAMES:
            (self.bin / name).symlink_to(STUB)
        (self.etc / "api.env").write_text("JULI_SIM=1\n")
        (self.etc / "frontend.env").write_text("TIKTOK_EVENTS_API_ACCESS_TOKEN=sim\n")
        self.history: list[str] = []
        self.demo_history: list[str] = []

    # -- building ----------------------------------------------------------------------

    def release(self, name: str, lanes=ALL, migrations: int = 3) -> Path:
        d = self.releases / SHORT[name]
        for lane in lanes:
            _exe(d / ARTIFACT[lane])
        if "api" in lanes:
            _exe(
                d / ".venv/bin/celery", "#!/bin/sh\necho '-> celery@vps: OK'\necho '        pong'\n"
            )
        systemd = d / "infra/systemd"
        systemd.mkdir(parents=True, exist_ok=True)
        for unit in UNITS:
            text = (REPO_ROOT / f"infra/systemd/{unit}.service").read_text()
            (systemd / f"{unit}.service").write_text(text + f"# sim-release {name}\n")
        versions = d / "backend/src/juli_backend/database/migrations/versions"
        versions.mkdir(parents=True, exist_ok=True)
        for i in range(1, migrations + 1):
            (versions / f"{i:03d}_m.py").write_text("")
        return d

    def deployed(self, name: str, lanes=ALL, migrations: int = 3) -> Path:
        d = self.release(name, lanes, migrations)
        self.history.append(f"2026-10-1{len(self.history)}T00:00:00Z {SHA[name]} {d}")
        if "demo" in lanes:
            self.demo_history.append(f"2026-10-1{len(self.history)}T00:00:00Z {SHA[name]} {d}")
        return d

    def upstream(self, lane: str, port: int) -> None:
        text = (
            f"upstream {UPSTREAM_NAME[lane]} {{\n"
            f"    server 127.0.0.1:{port};\n    keepalive 16;\n}}\n"
        )
        (self.nginx / f"{lane}-upstream.conf").write_text(text)
        (self.state / "nginx-loaded" / f"{lane}-upstream.conf").write_text(text)

    def running(self, unit: str, lane: str, port: int | None, release: Path | None) -> None:
        data = {
            "lane": lane,
            "port": port,
            "release": str(release) if release else None,
            "active": True,
        }
        data["invocation"] = f"boot-{unit}"
        (self.state / "units" / f"{unit}.json").write_text(json.dumps(data))
        if port:
            (self.state / "ports" / str(port)).write_text(unit)

    def link(self, lane: str, release: Path) -> None:
        (self.releases / LINK[lane]).symlink_to(release)

    def install_units(self, release: Path) -> None:
        for unit in UNITS:
            shutil.copyfile(
                release / f"infra/systemd/{unit}.service", self.unit_dir / f"{unit}.service"
            )

    def write_logs(self) -> None:
        (self.releases / "deploy-history.log").write_text("".join(f"{x}\n" for x in self.history))
        (self.releases / "demo-deploy-history.log").write_text(
            "".join(f"{x}\n" for x in self.demo_history)
        )

    def standard(self, pruned_a: bool = False) -> World:
        """A, B, C all full deploys; C live, B's instances drained on the other slots."""
        self.deployed("a")
        b = self.deployed("b")
        c = self.deployed("c")
        if pruned_a:
            shutil.rmtree(self.releases / SHORT["a"])
        self.go_live(c, b)
        return self

    def go_live(self, live: Path, drained: Path | None, ports=None) -> None:
        ports = ports or {"api": (8020, 8000), "demo": (3021, 3001), "landing": (3027, 3007)}
        for lane in ALL:
            live_port, peer = ports[lane]
            self.upstream(lane, live_port)
            self.link(lane, live)
            self.running(f"juli-{lane}-candidate-{live_port}", lane, live_port, live)
            if drained:
                self.running(f"juli-{lane}-candidate-{peer}", lane, peer, drained)
        self.running("juli-celery-worker", "celery", None, None)
        self.running("juli-celery-beat", "celery", None, None)
        self.install_units(live)
        self.write_logs()

    def set_flag(self, name: str) -> None:
        (self.state / "flags" / name).write_text("")

    def behave(self, name: str, *settings: str) -> None:
        (self.releases / SHORT[name] / ".sim-behaviour").write_text("\n".join(settings) + "\n")

    # -- running -----------------------------------------------------------------------

    def run(self, *args: str, **env_overrides: str) -> Run:
        env = {
            "PATH": f"{self.bin}:{os.environ['PATH']}",
            "HOME": str(self.root),
            "SIM_STATE": str(self.state),
            "RELEASES_ROOT": str(self.releases),
            "NGINX_UPSTREAM_DIR": str(self.nginx),
            "ETC_JULI_DIR": str(self.etc),
            "SYSTEMD_UNIT_DIR": str(self.unit_dir),
            "API_ENV_FILE": str(self.etc / "api.env"),
            "DEMO_RUNTIME_ENV": str(self.etc / "demo-runtime.env"),
            "CANDIDATE_TIMEOUT_SECS": "1",
            "PUBLIC_CHECK_TIMEOUT_SECS": "1",
            "HEALTH_TIMEOUT_SECS": "1",
            "CELERY_VERIFY_TIMEOUT_SECS": "1",
            "CELERY_VERIFY_POLL_SECS": "0",
            "DEMO_PUBLIC_CHECK_TIMEOUT_SECS": "1",
        }
        env.update(env_overrides)
        proc = subprocess.run(
            ["bash", str(SCRIPT), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=110,
        )
        return Run(proc.returncode, proc.stdout + proc.stderr)

    # -- observing ---------------------------------------------------------------------

    def live_dir(self, lane: str) -> str:
        return os.path.realpath(self.releases / LINK[lane])

    def live_port(self, lane: str, loaded: bool = False) -> int:
        conf = (self.state / "nginx-loaded" if loaded else self.nginx) / f"{lane}-upstream.conf"
        return int(re.search(r"127\.0\.0\.1:(\d+);", conf.read_text()).group(1))

    def serving(self, lane: str) -> str:
        """The release the public site would show: loaded upstream -> port -> unit."""
        port = self.live_port(lane, loaded=True)
        unit = (self.state / "ports" / str(port)).read_text()
        return json.loads((self.state / "units" / f"{unit}.json").read_text())["release"]

    def calls(self) -> str:
        path = self.state / "calls.log"
        return path.read_text() if path.exists() else ""

    def snapshot(self) -> dict:
        return {
            "links": {lane: self.live_dir(lane) for lane in ALL},
            "upstreams": {lane: self.live_port(lane) for lane in ALL},
            "history": (self.releases / "deploy-history.log").read_text(),
            "units": sorted(p.name for p in self.unit_dir.iterdir()),
            "unit_text": (self.unit_dir / "juli-api.service").read_text(),
        }


@pytest.fixture
def world(tmp_path: Path) -> World:
    return World(tmp_path)


def rel(world: World, name: str) -> str:
    return str(world.releases / SHORT[name])


def assert_never_touched_db_or_juli_web(world: World) -> None:
    calls = world.calls()
    assert "DB-TOUCH" not in calls, calls
    assert "juli-web" not in calls, calls
    assert ":3000" not in calls, calls
    assert "PORT-CONFLICT" not in calls, calls


# ---------------------------------------------------------------------------------------
# --plan and target resolution
# ---------------------------------------------------------------------------------------


def test_plan_resolves_the_previous_deploy_and_changes_nothing(world: World):
    world.standard()
    before = world.snapshot()
    run = world.run("--plan")
    assert run.code == 0, run
    assert f"target   : deploy #1 {SHA['b'][:12]}" in run.out, run
    for lane in ALL:
        assert re.search(
            rf"{lane}\s*: {re.escape(rel(world, 'c'))} -> {re.escape(rel(world, 'b'))}", run.out
        ), run
    assert "back: landing -> demo -> api" in run.out
    assert "database : NOT touched" in run.out
    assert world.snapshot() == before
    assert "systemd-run" not in world.calls()


def test_plan_names_migrations_the_target_code_does_not_know(world: World):
    world.deployed("a")
    world.deployed("b", migrations=3)
    c = world.deployed("c", migrations=5)
    world.go_live(c, None)
    run = world.run("--plan")
    assert run.code == 0, run
    assert (
        "WARN: the database schema stays ahead of the target's code by: 004_m.py 005_m.py"
        in run.out
    ), run


def test_plan_after_a_demo_only_deploy_restores_each_lanes_state_at_the_target(world: World):
    """B shipped only the demo lane (no venv, no landing artifact): rolling back from C to
    B means API and Landing as they were after B -- i.e. A's -- and Demo from B."""
    a = world.deployed("a")
    world.deployed("b", lanes=("demo",))
    c = world.deployed("c")
    world.go_live(c, a)
    run = world.run("--plan")
    assert run.code == 0, run
    assert re.search(rf"api\s*: {re.escape(str(c))} -> {re.escape(str(a))}", run.out), run
    assert re.search(rf"demo\s*: {re.escape(str(c))} -> {re.escape(rel(world, 'b'))}", run.out), run
    assert re.search(rf"landing\s*: {re.escape(str(c))} -> {re.escape(str(a))}", run.out), run


def test_a_pruned_release_on_the_way_down_fails_the_plan_instead_of_guessing(world: World):
    a = world.deployed("a")
    world.deployed("b", lanes=("demo",))
    c = world.deployed("c")
    world.go_live(c, a)
    shutil.rmtree(world.releases / SHORT["b"])
    before = world.snapshot()
    run = world.run()
    assert run.code == 1, run
    assert "no longer exists (pruned)" in run.out
    assert "nothing was changed" in run.out
    assert world.snapshot() == before
    assert "systemd-run" not in world.calls()


@pytest.mark.parametrize("bad", ["main", "../etc", "abc", "HEAD~1", "fasttrack-deploy-x", "a" * 41])
def test_a_target_that_is_not_hex_is_refused(world: World, bad: str):
    world.standard()
    run = world.run(bad)
    assert run.code == 2, run
    assert "systemd-run" not in world.calls()


def test_an_unknown_sha_lists_the_deploys_and_changes_nothing(world: World):
    world.standard()
    run = world.run("d" * 7)
    assert run.code == 1, run
    assert "matches no deploy" in run.out
    assert f"#0 {SHA['a'][:12]}" in run.out


def test_no_history_log_fails_cleanly(world: World):
    run = world.run()
    assert run.code == 1, run
    assert "deploy-history.log found" in run.out


# ---------------------------------------------------------------------------------------
# Rollback success, then the drill's way forward again
# ---------------------------------------------------------------------------------------


def test_rollback_moves_all_three_lanes_to_the_previous_deploy(world: World):
    world.standard()
    run = world.run()
    assert run.code == 0, run
    b = rel(world, "b")

    for lane in ALL:
        assert world.live_dir(lane) == b, (lane, run)
        assert world.serving(lane) == b, (lane, run)
    # Each lane took the free slot of its pair; nginx was reloaded onto it.
    assert {lane: world.live_port(lane, loaded=True) for lane in ALL} == {
        "api": 8000,
        "demo": 3001,
        "landing": 3007,
    }
    # Reboot durability and unit files come from the TARGET release.
    assert "API_LIVE_PORT=8000" in (world.etc / "api-runtime.env").read_text()
    assert "LANDING_LIVE_PORT=3007" in (world.etc / "landing-runtime.env").read_text()
    assert "DEMO_LIVE_PORT=3001" in (world.etc / "demo-runtime.env").read_text()
    for unit in ("juli-api", "juli-landing", "juli-celery-worker", "juli-celery-beat"):
        assert (world.unit_dir / f"{unit}.service").read_text().endswith("# sim-release b\n"), unit

    calls = world.calls()
    # Going back: landing, then demo, then api.
    order = [calls.index(f"--unit=juli-{lane}-candidate-") for lane in ("landing", "demo", "api")]
    assert order == sorted(order), calls
    assert "systemctl restart juli-celery-worker" in calls
    assert "systemctl restart juli-celery-beat" in calls
    assert "systemctl stop juli-api" in calls  # the durable unit never holds a slot
    assert_never_touched_db_or_juli_web(world)

    history = (world.releases / "deploy-history.log").read_text().splitlines()
    assert re.fullmatch(
        rf"\S+ ROLLBACK-TO {re.escape(b)} {SHA['b']} lanes=landing,demo,api", history[-1]
    )
    assert "RESULT: PASS" in run.out
    assert re.search(r"juli-celery-worker\s+PASS", run.out)
    assert re.search(r"public\s+https://api.app-juli.com/health\s+PASS", run.out)
    records = list((world.releases / "records").glob("rollback-*-bbbbbbb.json"))
    assert len(records) == 1 and '"result": "completed"' in records[0].read_text()


def test_the_drill_back_and_forward_again_ends_where_it_started(world: World):
    world.standard()
    assert world.run().code == 0
    (world.state / "calls.log").unlink()
    run = world.run(SHORT["c"])
    assert run.code == 0, run
    c = rel(world, "c")
    for lane in ALL:
        assert world.live_dir(lane) == c
        assert world.serving(lane) == c
    assert {lane: world.live_port(lane, loaded=True) for lane in ALL} == {
        "api": 8020,
        "demo": 3021,
        "landing": 3027,
    }
    assert "forward: api -> demo -> landing" in run.out
    calls = world.calls()
    order = [calls.index(f"--unit=juli-{lane}-candidate-") for lane in ("api", "demo", "landing")]
    assert order == sorted(order)
    assert (world.unit_dir / "juli-api.service").read_text().endswith("# sim-release c\n")
    assert_never_touched_db_or_juli_web(world)


def test_a_second_default_rollback_goes_one_deploy_further_back(world: World):
    world.standard()
    assert world.run().code == 0
    run = world.run("--plan")
    assert f"target   : deploy #0 {SHA['a'][:12]}" in run.out, run
    assert f"live now : deploy #1 {SHA['b'][:12]}" in run.out, run


def test_rolling_back_to_the_live_state_is_a_no_op_with_a_health_summary(world: World):
    world.standard()
    run = world.run(SHORT["c"])
    assert run.code == 0, run
    assert "nothing to do" in run.out
    assert "RESULT: PASS" in run.out
    assert "systemd-run" not in world.calls()


# ---------------------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------------------


def test_landing_target_never_ready_fails_first_and_nothing_moves(world: World):
    world.standard()
    world.behave("b", "start=fail")
    before = world.snapshot()
    run = world.run()
    assert run.code == 1, run
    assert "rollback FAILED in lane landing" in run.out
    assert "Moved to the target: nothing" in run.out
    snap = world.snapshot()
    assert snap["links"] == before["links"] and snap["upstreams"] == before["upstreams"]
    for lane in ALL:
        assert world.serving(lane) == rel(world, "c")
    assert "ROLLBACK" not in snap["history"]
    assert_never_touched_db_or_juli_web(world)


def test_api_shape_failure_leaves_the_api_where_it_was_and_reports_the_partial_move(world: World):
    world.standard()
    world.behave("b", "shape=bad")
    run = world.run()
    assert run.code == 1, run
    assert "response shape check failed" in run.out
    assert "rollback FAILED in lane api" in run.out
    assert "Moved to the target: landing demo" in run.out
    assert world.live_dir("api") == rel(world, "c")
    assert world.serving("api") == rel(world, "c")
    assert world.live_port("api") == 8020
    assert world.serving("landing") == rel(world, "b")
    assert world.serving("demo") == rel(world, "b")
    assert "systemctl restart juli-celery" not in world.calls()
    assert "ROLLBACK" not in (world.releases / "deploy-history.log").read_text()
    assert "RESULT:" in run.out


def test_public_check_failure_after_api_cutover_undoes_the_api_switch(world: World):
    world.standard()
    world.set_flag("public-api-fail")
    run = world.run("--lanes", "api")
    assert run.code == 1, run
    assert "automatic undo" in run.out
    assert world.live_port("api", loaded=True) == 8020
    assert world.live_dir("api") == rel(world, "c")
    assert world.serving("api") == rel(world, "c")
    assert "API_LIVE_PORT=8020" in (world.etc / "api-runtime.env").read_text()


def test_a_durable_unit_on_the_free_slot_is_stopped_before_the_target_starts(world: World):
    """After a reboot the durable juli-api can hold the slot the target needs; the
    loopback checks must hit the target, not it."""
    world.standard()
    (world.state / "ports" / "8000").unlink()
    (world.state / "units" / "juli-api-candidate-8000.json").unlink()
    world.running("juli-api", "api", 8000, world.releases / SHORT["c"])
    run = world.run("--lanes", "api")
    assert run.code == 0, run
    assert "stopping juli-api" in run.out
    assert world.serving("api") == rel(world, "b")
    assert_never_touched_db_or_juli_web(world)


def test_an_unknown_process_on_the_free_slot_fails_without_switching(world: World):
    world.standard()
    (world.state / "units" / "juli-api-candidate-8000.json").unlink()
    (world.state / "units" / "stray.json").write_text(
        json.dumps({"lane": "api", "port": 8000, "release": rel(world, "a"), "active": True})
    )
    (world.state / "ports" / "8000").write_text("stray")
    run = world.run("--lanes", "api")
    assert run.code == 1, run
    assert "still taken by an unknown process" in run.out
    assert world.serving("api") == rel(world, "c")
    assert world.live_port("api") == 8020


def test_nginx_refusing_the_switch_leaves_traffic_on_the_live_slot(world: World):
    world.standard()
    world.set_flag("nginx-t-fail")
    run = world.run()
    assert run.code == 1, run
    for lane in ALL:
        assert world.serving(lane) == rel(world, "c")
        assert world.live_dir(lane) == rel(world, "c")


def test_worker_missing_a_routed_queue_fails_the_rollback(world: World):
    world.standard()
    world.set_flag("banner-omit-content_analysis")
    run = world.run()
    assert run.code == 1, run
    assert "did not subscribe to routed queue(s): content_analysis" in run.out
    assert "rollback FAILED in lane api" in run.out


def test_beat_restart_refused_fails_the_rollback(world: World):
    world.standard()
    world.set_flag("restart-fail-juli-celery-beat")
    run = world.run()
    assert run.code == 1, run
    assert "systemctl restart juli-celery-beat failed" in run.out


# ---------------------------------------------------------------------------------------
# --verify and the summary
# ---------------------------------------------------------------------------------------


def test_verify_passes_on_a_healthy_host_and_changes_nothing(world: World):
    world.standard()
    before = world.snapshot()
    run = world.run("--verify", ROLLBACK_CELERY_PING="1")
    assert run.code == 0, run
    assert "RESULT: PASS (9 checks)" in run.out, run
    assert re.search(r"api\s+127.0.0.1:8020/health\s+PASS\s+status=ok", run.out)
    assert re.search(r"demo\s+127.0.0.1:3021/decisions\s+PASS", run.out)
    assert re.search(r"landing\s+127.0.0.1:3027/\s+PASS", run.out)
    assert re.search(r"celery inspect ping\s+PASS", run.out)
    assert world.snapshot() == before
    assert_never_touched_db_or_juli_web(world)


def test_verify_fails_when_beat_is_down(world: World):
    world.standard()
    (world.state / "units" / "juli-celery-beat.json").unlink()
    run = world.run("--verify")
    assert run.code == 1, run
    assert re.search(r"juli-celery-beat\s+FAIL", run.out)
    assert "RESULT: FAIL (1 of 8 checks failed)" in run.out


def test_verify_fails_when_the_live_api_slot_does_not_answer(world: World):
    world.standard()
    (world.state / "ports" / "8020").unlink()
    run = world.run("--verify", ROLLBACK_PUBLIC_CHECKS="0")
    assert run.code == 1, run
    assert re.search(r"api\s+127.0.0.1:8020/health\s+FAIL", run.out)


# ---------------------------------------------------------------------------------------
# Static guards on the script itself
# ---------------------------------------------------------------------------------------


def test_script_has_no_database_or_juli_web_path():
    body = "\n".join(
        line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#")
    )
    for needle in ("alembic", "psql", "pg_restore", "pg_dump", "safe-alembic", "juli-web", ":3000"):
        assert needle not in body, needle
    assert "ROLLBACK_INTERFACE=2" in SCRIPT.read_text()


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
def test_shellcheck_is_clean():
    proc = subprocess.run(
        ["shellcheck", "-x", "infra/scripts/rollback-release.sh"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
