"""Unit and contract tests for Demo static asset integrity (Issue #499, DEMO-ASSET-2).

Proves build-time verification fails when HTML references missing /_next/static
CSS/JS on disk, and that public smoke scripts discover assets from HTML for /
and /decisions — mirroring App Review build-frontend-review / smoke-test patterns.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "infra/scripts"
VERIFY_SCRIPT_PATH = SCRIPTS_DIR / "verify-demo-static-assets.sh"
SMOKE_DEMO_PATH = SCRIPTS_DIR / "smoke-test-demo.sh"

HOME_JS = "/_next/static/chunks/home-abc123.js"
HOME_CSS = "/_next/static/css/home-abc123.css"
DECISIONS_JS = "/_next/static/chunks/decisions-def456.js"
DECISIONS_CSS = "/_next/static/css/decisions-def456.css"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write_fixture(tmp_path: Path, *, omit_asset: str | None = None) -> Path:
    """Minimal Next.js build tree with home + /decisions HTML and static assets."""
    demo_dir = tmp_path / "apps" / "demo"
    next_dir = demo_dir / ".next"
    app_html = next_dir / "server" / "app"
    chunks_dir = next_dir / "static" / "chunks"
    css_dir = next_dir / "static" / "css"
    app_html.mkdir(parents=True)
    chunks_dir.mkdir(parents=True)
    css_dir.mkdir(parents=True)

    assets = {
        HOME_JS: chunks_dir / "home-abc123.js",
        HOME_CSS: css_dir / "home-abc123.css",
        DECISIONS_JS: chunks_dir / "decisions-def456.js",
        DECISIONS_CSS: css_dir / "decisions-def456.css",
    }
    for _url, disk_path in assets.items():
        if omit_asset and disk_path == assets[omit_asset]:
            continue
        disk_path.write_text(f"/* {disk_path.name} */", encoding="utf-8")

    home_html = f"""<!DOCTYPE html><html><head>
<link rel="stylesheet" href="{HOME_CSS}" />
<script src="{HOME_JS}" async=""></script>
</head><body><main>Demo home</main></body></html>"""
    decisions_html = f"""<!DOCTYPE html><html><head>
<link rel="stylesheet" href="{DECISIONS_CSS}" />
<script src="{DECISIONS_JS}" async=""></script>
</head><body><main>Decisions</main></body></html>"""

    (app_html / "index.html").write_text(home_html, encoding="utf-8")
    (app_html / "decisions.html").write_text(decisions_html, encoding="utf-8")
    return demo_dir


def _run_verify(demo_dir: Path, repo_root: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DEMO_DIR": str(demo_dir), "REPO_ROOT": str(repo_root)}
    return subprocess.run(
        [str(VERIFY_SCRIPT_PATH)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        cwd=str(repo_root),
    )


def test_verify_script_exists_and_is_executable():
    assert VERIFY_SCRIPT_PATH.is_file()
    assert VERIFY_SCRIPT_PATH.stat().st_mode & 0o111


def test_verify_script_checks_home_and_decisions_html_routes():
    script = _read(VERIFY_SCRIPT_PATH)
    assert "index.html" in script
    assert "decisions.html" in script
    assert "/_next/static" in script
    assert ".css" in script
    assert ".js" in script


def test_verify_passes_when_all_referenced_assets_exist(tmp_path: Path):
    demo_dir = _write_fixture(tmp_path)
    result = _run_verify(demo_dir, tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_verify_fails_when_referenced_js_missing(tmp_path: Path):
    demo_dir = _write_fixture(tmp_path, omit_asset=DECISIONS_JS)
    result = _run_verify(demo_dir, tmp_path)
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "fail" in combined or "missing" in combined
    assert "decisions" in combined or DECISIONS_JS in result.stdout + result.stderr


def test_verify_fails_when_referenced_css_missing(tmp_path: Path):
    demo_dir = _write_fixture(tmp_path, omit_asset=HOME_CSS)
    result = _run_verify(demo_dir, tmp_path)
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "fail" in combined or "missing" in combined


def test_smoke_demo_discovers_css_js_from_html_for_home_and_decisions():
    script = _read(SMOKE_DEMO_PATH)
    assert "/decisions" in script
    assert "/_next/static" in script
    assert ".css" in script
    assert ".js" in script
    assert "--dns-tls-only" in script
    lowered = script.lower()
    assert "discover" in lowered or "grep" in script
    assert "200" in script


def test_smoke_demo_preserves_dns_tls_only_mode():
    script = _read(SMOKE_DEMO_PATH)
    assert "DNS_TLS_ONLY" in script
    assert script.count("--dns-tls-only") >= 2
