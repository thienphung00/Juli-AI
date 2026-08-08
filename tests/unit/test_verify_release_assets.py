"""Contract tests for the release asset verification harness (Issue #833, P0-DEL-VERIFY).

The harness under test is ``infra/scripts/verify-release-assets.sh``. It supersedes the
narrower, inline asset checks in ``smoke-test-demo.sh`` and the #835 slot spike: given an
arbitrary base URL it fetches a page, discovers every referenced stylesheet and script,
and fetches each one.

These tests stand up a local fixture HTTP server on 127.0.0.1 with an ephemeral port. That
is the point of the slice — a harness that can only be exercised against a VPS hostname
would not satisfy "runs against an arbitrary base URL".

The target failure mode is a release missing built asset files, where the page loads and
the styling does not. So the decisive cases here are the ones where status alone lies: a
stylesheet served 200 with an empty body, and a stylesheet served 200 with an HTML error
page as its body.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra" / "scripts" / "verify-release-assets.sh"

# Bodies large enough to clear a non-trivial size floor, so size and content checks stay
# independently observable.
CSS_BODY = b"/* juli stylesheet */\n" + b".juli-card{display:flex;gap:12px;padding:16px}\n" * 6
JS_BODY = b"// juli bundle\n" + b"window.__juli=window.__juli||{};\n" * 10

# An nginx-style error page: ~180 bytes, so it clears any sane size floor. Only a content
# assertion rejects this one.
ERROR_HTML = (
    b"<!DOCTYPE html><html><head><title>404 Not Found</title></head>"
    b"<body><center><h1>404 Not Found</h1></center>"
    b"<hr><center>nginx/1.24.0</center></body></html>"
)

HEALTHY_PAGE = (
    b"<!DOCTYPE html><html><head>"
    b'<link rel="stylesheet" href="/static/app.css"/>'
    b'<link rel="stylesheet" href="/static/theme.css"/>'
    b'<script src="/static/app.js" defer=""></script>'
    b"</head><body><main>Juli</main></body></html>"
)

PAGE_WITHOUT_ASSETS = b"<!DOCTYPE html><html><head></head><body><main>Juli</main></body></html>"


def _healthy_routes() -> dict[str, tuple[int, str, bytes]]:
    return {
        "/": (200, "text/html; charset=utf-8", HEALTHY_PAGE),
        "/static/app.css": (200, "text/css; charset=utf-8", CSS_BODY),
        "/static/theme.css": (200, "text/css; charset=utf-8", CSS_BODY),
        "/static/app.js": (200, "application/javascript", JS_BODY),
    }


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

        def log_message(self, *args: object) -> None:  # silence per-request stderr noise
            return

    return _FixtureHandler


@contextmanager
def serve(routes: dict[str, tuple[int, str, bytes]]) -> Iterator[str]:
    """Serve ``routes`` on an ephemeral 127.0.0.1 port; yield the base URL."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(routes))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_harness(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def output_of(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


# --------------------------------------------------------------------------------------
# Shape of the harness itself
# --------------------------------------------------------------------------------------


def test_script_exists_and_is_executable() -> None:
    assert SCRIPT_PATH.is_file(), f"{SCRIPT_PATH} is missing"
    assert SCRIPT_PATH.stat().st_mode & 0o111, f"{SCRIPT_PATH} is not executable"


def test_help_exits_zero_and_documents_base_url() -> None:
    result = run_harness("--help")
    assert result.returncode == 0, output_of(result)
    assert "--base-url" in result.stdout


def test_missing_base_url_is_a_usage_error() -> None:
    result = run_harness()
    assert result.returncode != 0
    assert "--base-url" in output_of(result)


def test_harness_makes_no_vps_specific_assumptions() -> None:
    """No hostname, port, path, or framework of the current deployment may be baked in."""
    script = SCRIPT_PATH.read_text(encoding="utf-8")
    forbidden = [
        "app-juli.com",
        "juli-demo",
        "systemctl",
        "~/releases",
        "/home/",
        "3001",
        "_next/static",
    ]
    for token in forbidden:
        assert token not in script, f"harness hardcodes VPS/framework-specific token: {token}"


def test_harness_documents_the_protocol_versus_browser_boundary() -> None:
    """PRD #820 splits on-server protocol checks from CI browser checks deliberately."""
    header = "\n".join(SCRIPT_PATH.read_text(encoding="utf-8").splitlines()[:40]).lower()
    assert "protocol" in header
    assert "browser" in header
    assert "#837" in header


# --------------------------------------------------------------------------------------
# Healthy page passes
# --------------------------------------------------------------------------------------


def test_healthy_page_passes_and_reports_every_asset() -> None:
    with serve(_healthy_routes()) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
    assert result.returncode == 0, output_of(result)
    out = output_of(result)
    for asset in ("/static/app.css", "/static/theme.css", "/static/app.js"):
        assert asset in out, f"{asset} was never reported as checked"


def test_multiple_routes_are_each_verified() -> None:
    routes = _healthy_routes()
    routes["/decisions"] = (
        200,
        "text/html; charset=utf-8",
        b'<!DOCTYPE html><html><head><link rel="stylesheet" href="/static/decisions.css"/>'
        b'<script src="/static/app.js"></script></head><body>D</body></html>',
    )
    routes["/static/decisions.css"] = (200, "text/css", CSS_BODY)
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/", "--route", "/decisions")
    assert result.returncode == 0, output_of(result)
    assert "/static/decisions.css" in output_of(result)


# --------------------------------------------------------------------------------------
# Broken page fails — the reason this slice exists
# --------------------------------------------------------------------------------------


def test_missing_stylesheet_fails_and_names_the_failing_asset_url() -> None:
    routes = _healthy_routes()
    del routes["/static/theme.css"]  # now 404s
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        expected_url = f"{base_url}/static/theme.css"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result), "the specific failing asset URL must be named"


def test_stylesheet_returning_200_with_html_error_body_fails() -> None:
    """A 200 is not evidence. An HTML error page served as CSS must fail."""
    routes = _healthy_routes()
    routes["/static/theme.css"] = (200, "text/html; charset=utf-8", ERROR_HTML)
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        expected_url = f"{base_url}/static/theme.css"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result)
    assert len(ERROR_HTML) > 100, "fixture must clear the size floor so content is what fails"


def test_stylesheet_with_html_body_but_lying_css_content_type_still_fails() -> None:
    """Sniff the body: a server claiming text/css while serving HTML must not pass."""
    routes = _healthy_routes()
    routes["/static/theme.css"] = (200, "text/css; charset=utf-8", ERROR_HTML)
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        expected_url = f"{base_url}/static/theme.css"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result)


def test_empty_stylesheet_body_fails_on_size() -> None:
    routes = _healthy_routes()
    routes["/static/theme.css"] = (200, "text/css", b"")
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        expected_url = f"{base_url}/static/theme.css"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result)


def test_trivial_stylesheet_body_fails_on_size_floor() -> None:
    routes = _healthy_routes()
    routes["/static/theme.css"] = (200, "text/css", b"\n")
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/", "--min-asset-bytes", "64")
        expected_url = f"{base_url}/static/theme.css"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result)


def test_missing_script_fails_and_names_the_failing_asset_url() -> None:
    routes = _healthy_routes()
    del routes["/static/app.js"]
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        expected_url = f"{base_url}/static/app.js"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result)


def test_page_referencing_no_assets_at_all_fails() -> None:
    """A rendered page with zero CSS/JS is the missing-build symptom, not a healthy page."""
    with serve({"/": (200, "text/html", PAGE_WITHOUT_ASSETS)}) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
    assert result.returncode != 0, output_of(result)


def test_unreachable_route_fails() -> None:
    with serve(_healthy_routes()) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/nope")
    assert result.returncode != 0, output_of(result)


# --------------------------------------------------------------------------------------
# Core API paths — response shape, not only status
# --------------------------------------------------------------------------------------


def _api_routes(payload: object) -> dict[str, tuple[int, str, bytes]]:
    routes = _healthy_routes()
    routes["/v1/health"] = (200, "application/json", json.dumps(payload).encode())
    return routes


def test_api_check_passes_when_required_keys_are_present() -> None:
    with serve(_api_routes({"status": "ok", "version": "1.2.3"})) as base_url:
        result = run_harness(
            "--base-url",
            base_url,
            "--route",
            "/",
            "--api-check",
            "/v1/health:status,version",
        )
    assert result.returncode == 0, output_of(result)
    assert "/v1/health" in output_of(result)


def test_api_check_fails_on_shape_even_though_status_is_200() -> None:
    with serve(_api_routes({"status": "ok"})) as base_url:
        result = run_harness(
            "--base-url",
            base_url,
            "--route",
            "/",
            "--api-check",
            "/v1/health:status,version",
        )
    assert result.returncode != 0, output_of(result)
    out = output_of(result)
    assert "/v1/health" in out
    assert "version" in out, "the missing field must be named in output"


def test_api_check_fails_when_html_is_served_in_place_of_json() -> None:
    routes = _healthy_routes()
    routes["/v1/health"] = (200, "text/html", ERROR_HTML)
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--api-check", "/v1/health:status")
    assert result.returncode != 0, output_of(result)
    assert "/v1/health" in output_of(result)


def test_api_check_fails_on_non_2xx() -> None:
    routes = _healthy_routes()
    routes["/v1/health"] = (503, "application/json", b'{"status":"down"}')
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--api-check", "/v1/health:status")
    assert result.returncode != 0, output_of(result)
    assert "503" in output_of(result)


def test_api_base_url_may_differ_from_page_base_url() -> None:
    """Page host and API host are separate surfaces in this deployment."""
    api_routes = {"/v1/health": (200, "application/json", b'{"status":"ok"}')}
    with serve(_healthy_routes()) as page_url, serve(api_routes) as api_url:
        result = run_harness(
            "--base-url",
            page_url,
            "--route",
            "/",
            "--api-base-url",
            api_url,
            "--api-check",
            "/v1/health:status",
        )
    assert result.returncode == 0, output_of(result)


def test_api_checks_alone_run_without_any_html_route() -> None:
    api_routes = {"/v1/health": (200, "application/json", b'{"status":"ok"}')}
    with serve(api_routes) as api_url:
        result = run_harness("--api-base-url", api_url, "--api-check", "/v1/health:status")
    assert result.returncode == 0, output_of(result)


# --------------------------------------------------------------------------------------
# Failure reporting
# --------------------------------------------------------------------------------------


def test_all_failing_assets_are_reported_not_just_the_first() -> None:
    routes = _healthy_routes()
    del routes["/static/theme.css"]
    routes["/static/app.js"] = (200, "application/javascript", b"")
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        css_url = f"{base_url}/static/theme.css"
        js_url = f"{base_url}/static/app.js"
    assert result.returncode != 0
    out = output_of(result)
    assert css_url in out
    assert js_url in out


@pytest.mark.parametrize("attr_html", ["href='/static/app.css'", 'href="/static/app.css"'])
def test_single_and_double_quoted_references_are_both_discovered(
    attr_html: str,
) -> None:
    page = f"<!DOCTYPE html><html><head><link rel=stylesheet {attr_html}>".encode()
    page += b'<script src="/static/app.js"></script></head><body>x</body></html>'
    routes = {
        "/": (200, "text/html", page),
        "/static/app.js": (200, "application/javascript", JS_BODY),
    }
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
        expected_url = f"{base_url}/static/app.css"
    assert result.returncode != 0, output_of(result)
    assert expected_url in output_of(result)


def test_asset_reference_with_query_string_is_fetched() -> None:
    page = (
        b"<!DOCTYPE html><html><head>"
        b'<link rel="stylesheet" href="/static/app.css?v=deadbeef"/>'
        b'<script src="/static/app.js"></script></head><body>x</body></html>'
    )
    routes = _healthy_routes()
    routes["/"] = (200, "text/html", page)
    with serve(routes) as base_url:
        result = run_harness("--base-url", base_url, "--route", "/")
    assert result.returncode == 0, output_of(result)
    assert "/static/app.css?v=deadbeef" in output_of(result)
