"""Runtime packaging contract for Demo static assets (Issue #499, DEMO-ASSET-1).

Asserts one consistent Next.js production model across next.config, systemd,
build script, and nginx. Matches App Review (juli-web): standard ``next build``
output with ``next start`` run from ``apps/demo`` — not ``output: standalone``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
NEXT_CONFIG_PATH = REPO_ROOT / "apps/demo/next.config.ts"
SYSTEMD_DEMO_PATH = REPO_ROOT / "infra/systemd/juli-demo.service"
SYSTEMD_WEB_PATH = REPO_ROOT / "infra/systemd/juli-web.service"
NGINX_DEMO_PATH = REPO_ROOT / "infra/nginx/demo.app-juli.com.conf"
BUILD_DEMO_PATH = REPO_ROOT / "infra/scripts/build-demo.sh"

pytestmark = pytest.mark.demo_contract

DEMO_PORT = "3001"
RELEASE_APP_DIR = "releases/demo-current/apps/demo"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Remove # and // line comments so documentation does not trip config checks."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "//" in line:
            line = line.split("//", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _has_standalone_output(text: str) -> bool:
    return bool(re.search(r"""output\s*:\s*['"]standalone['"]""", _strip_comments(text)))


@pytest.fixture
def next_config_text() -> str:
    return _read(NEXT_CONFIG_PATH)


@pytest.fixture
def systemd_demo_text() -> str:
    return _read(SYSTEMD_DEMO_PATH)


@pytest.fixture
def build_demo_text() -> str:
    return _read(BUILD_DEMO_PATH)


def test_next_config_uses_standard_build_not_standalone(next_config_text: str):
    assert NEXT_CONFIG_PATH.is_file()
    assert not _has_standalone_output(next_config_text), (
        "Demo must not use output: standalone — use next start from apps/demo like juli-web"
    )


def test_systemd_demo_runs_next_start_from_app_directory(systemd_demo_text: str):
    assert SYSTEMD_DEMO_PATH.is_file()
    assert RELEASE_APP_DIR in systemd_demo_text, (
        "WorkingDirectory must be the built app dir under demo-current, not monorepo root"
    )
    assert "next start" in systemd_demo_text
    assert "node_modules/.bin/next" in systemd_demo_text, (
        "ExecStart must invoke the local next binary — corepack pnpm fails under systemd"
    )
    assert "--filter @juli/demo" not in systemd_demo_text, (
        "pnpm --filter from release root mismatches non-standalone next start cwd"
    )
    config_lines = [
        line
        for line in systemd_demo_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    config_body = "\n".join(config_lines).lower()
    assert "corepack" not in config_body
    assert "pnpm" not in config_body
    assert "standalone" not in config_body
    assert "server.js" not in config_body


def test_systemd_demo_matches_juli_web_loopback_start_pattern(systemd_demo_text: str):
    web = _read(SYSTEMD_WEB_PATH)
    assert "run start" in web or "next" in web.lower(), (
        "juli-web reference must start the Next production server"
    )
    assert f"--port {DEMO_PORT}" in systemd_demo_text or f":{DEMO_PORT}" in systemd_demo_text
    assert "127.0.0.1" in systemd_demo_text


def test_build_demo_validates_next_static_output(build_demo_text: str):
    assert BUILD_DEMO_PATH.is_file()
    assert ".next/static" in build_demo_text, (
        "build-demo.sh must verify hashed static assets exist in the artifact"
    )
    assert "node_modules/.bin/next" in build_demo_text, (
        "build-demo.sh must verify the next binary is present before deploy cutover"
    )
    # Two assertions here previously pinned server-side build mechanics: a guard
    # against building in the canonical checkout while juli-demo served
    # demo-current, and TURBO_FORCE to defeat a shared worktree cache hit. ADR-058
    # and #837 moved the build into CI, so neither has anything left to protect —
    # nothing writes .next on the server any more. They are replaced by the
    # invariant that succeeded them, not dropped, so this cannot regress silently.
    executable = "\n".join(
        line for line in build_demo_text.splitlines() if not line.lstrip().startswith("#")
    )
    for compile_step in ("pnpm install", "turbo run build", "pnpm build:demo", "next build"):
        assert compile_step not in executable, (
            f"build-demo.sh runs {compile_step!r} on the server; ADR-058 moved both the "
            "build and the dependency resolution into CI (#837)"
        )


def test_deploy_demo_reinstalls_systemd_and_dumps_logs_on_failure() -> None:
    deploy = _read(REPO_ROOT / "infra/scripts/deploy-demo-release.sh")
    # DEMO_RELEASE_BUILD=1 used to tell build-demo.sh "this is a release build,
    # force a rebuild". #837 left it nothing to switch on. What must still hold is
    # that the deploy invokes the verification step at all.
    assert "build-demo.sh" in deploy
    assert "juli-demo.service" in deploy
    assert "journalctl -u juli-demo" in deploy
    assert "node_modules/.bin/next" in deploy


def test_nginx_proxies_all_paths_to_next_upstream():
    conf = _read(NGINX_DEMO_PATH)
    assert NGINX_DEMO_PATH.is_file()
    assert f"127.0.0.1:{DEMO_PORT}" in conf
    directive_lines = [
        line for line in conf.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]
    directives = "\n".join(directive_lines).lower()
    assert " alias " not in f" {directives} ", (
        "/_next/static must be served by next start upstream, not a filesystem alias"
    )


def test_runtime_model_documented_in_systemd_or_next_config(
    next_config_text: str, systemd_demo_text: str
):
    combined = (next_config_text + systemd_demo_text).lower()
    documented = any(
        phrase in combined
        for phrase in (
            "next start",
            "juli-web",
            "standard build",
            "not standalone",
            "non-standalone",
        )
    )
    assert documented, "Document chosen runtime model in next.config.ts and/or juli-demo.service"
