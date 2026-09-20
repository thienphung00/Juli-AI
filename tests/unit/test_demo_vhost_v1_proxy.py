"""demo.app-juli.com must proxy /v1 to the API upstream (issue #1970).

`apps/demo` calls the backend with RELATIVE paths and deliberately has no
client-side API base env var (#397): `src/lib/shops-client.ts` requests
`/v1/shops`, `src/lib/tiktok-connect-client.ts` requests
`/v1/auth/tiktok/start`. Before this, `infra/nginx/demo.app-juli.com.conf` had
exactly one location — `/` → `juli_demo` — so every one of those calls was
served by Next.js and 404'd. A signed-in seller could not list their shops and
had no route at all to connect one.

The owner chose a same-origin proxy over cross-origin CORS on 2026-09-15.

There is no other automated check on this file's location map:
`check_nginx_rate_limits.py` reads only `api.app-juli.com.conf`, and
`check_nginx_config_parses.sh` proves the config PARSES, not that it routes
anywhere in particular. Deleting the `/v1/` block would leave both green and
break the demo silently — which is what this test exists to stop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_VHOST = REPO_ROOT / "infra" / "nginx" / "demo.app-juli.com.conf"
API_VHOST = REPO_ROOT / "infra" / "nginx" / "api.app-juli.com.conf"
RATE_LIMITS = REPO_ROOT / "infra" / "nginx" / "rate-limits.conf"

API_UPSTREAM = "juli_api"


def _location_blocks(conf_text: str) -> dict[str, str]:
    """Map each `location <path>` to its body, by brace counting.

    A regex cannot bound an nginx block — they nest and comments contain
    braces — so this walks from each header to its matching close, the same way
    `agent-runtime/scripts/ci/check_nginx_rate_limits.py` does.
    """
    blocks: dict[str, str] = {}
    for match in re.finditer(r"location\s+(?P<mod>=|~\*|~|\^~)?\s*(?P<path>\S+)\s*\{", conf_text):
        depth = 1
        start = pos = match.end()
        while pos < len(conf_text) and depth > 0:
            if conf_text[pos] == "{":
                depth += 1
            elif conf_text[pos] == "}":
                depth -= 1
            pos += 1
        blocks[match.group("path")] = conf_text[start : pos - 1]
    return blocks


@pytest.fixture(scope="module")
def demo_locations() -> dict[str, str]:
    return _location_blocks(DEMO_VHOST.read_text(encoding="utf-8"))


def test_demo_vhost_proxies_v1_to_the_api_upstream(demo_locations) -> None:
    """The gap the issue measured: /v1 on the demo host reached no API at all."""
    block = demo_locations.get("/v1/")
    assert block is not None, (
        "infra/nginx/demo.app-juli.com.conf has no `location /v1/` — every relative "
        "/v1 call from apps/demo is served by Next.js and 404s"
    )
    assert re.search(rf"proxy_pass\s+http://{API_UPSTREAM}", block), (
        f"`location /v1/` must proxy to the `{API_UPSTREAM}` upstream"
    )


def test_the_connect_start_route_is_reachable_through_the_auth_location(demo_locations) -> None:
    """`/v1/auth/tiktok/start` is what the connect button calls (#1970)."""
    block = demo_locations.get("/v1/auth/")
    assert block is not None, "no `location /v1/auth/` on the demo vhost"
    assert re.search(rf"proxy_pass\s+http://{API_UPSTREAM}", block)


def test_every_proxied_v1_location_carries_an_edge_rate_limit(demo_locations) -> None:
    """ADR-061 §2b, restated for the second hostname.

    These locations reach the SAME single-uvicorn-worker API as
    api.app-juli.com. An unthrottled door here is not a smaller version of an
    unthrottled door there — it is the same door under another name.
    """
    unthrottled = [
        path
        for path, body in demo_locations.items()
        if path.startswith("/v1") and not re.search(r"^\s*limit_req\s+zone=", body, re.MULTILINE)
    ]
    assert unthrottled == [], f"proxied /v1 locations with no limit_req: {unthrottled}"


def test_the_demo_v1_zones_are_the_ones_the_api_vhost_uses(demo_locations) -> None:
    """Same zones, not a second set: a client shares one bucket across hostnames."""
    demo_zones = {
        match.group(1)
        for path, body in demo_locations.items()
        if path.startswith("/v1")
        for match in re.finditer(r"limit_req\s+zone=(\S+?)[\s;]", body)
    }
    api_zones = set(
        re.findall(r"limit_req\s+zone=(\S+?)[\s;]", API_VHOST.read_text(encoding="utf-8"))
    )
    defined = set(
        re.findall(
            r"^\s*limit_req_zone\s+\S+\s+zone=(\S+?):",
            RATE_LIMITS.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    )

    assert demo_zones, "no rate-limit zones referenced by the demo vhost's /v1 locations"
    assert demo_zones <= api_zones, (
        f"demo vhost invented zones the API vhost does not use: {demo_zones - api_zones}"
    )
    assert demo_zones <= defined, f"zone(s) referenced but never defined: {demo_zones - defined}"


def test_the_next_app_still_serves_everything_else(demo_locations) -> None:
    """The /v1 blocks must not have stolen the demo app's own traffic.

    nginx picks the LONGEST matching prefix, so `/` keeps everything outside
    /v1 — but only while `/` still proxies to the demo upstream.
    """
    root = demo_locations.get("/")
    assert root is not None
    assert re.search(r"proxy_pass\s+http://juli_demo", root)


def test_the_demo_vhost_does_not_redefine_the_api_upstream() -> None:
    """Including the deployment-owned upstream twice is a hard nginx error.

    `upstream juli_api` is defined by /etc/nginx/juli/api-upstream.conf, which
    api.app-juli.com.conf already includes; upstreams are http-context and
    shared across vhosts. A second include would be `duplicate upstream` and
    nginx would refuse to load ANY site — and a separately-named copy would go
    stale at the next blue/green API cutover (the lane alternates 8000/8020),
    silently pointing the demo at a dead port.
    """
    # Directives only — the file NAMES api-upstream.conf in a comment
    # explaining exactly this, and a bare substring search would flag the
    # explanation as the thing it warns against.
    directives = [
        line
        for line in DEMO_VHOST.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    ]
    body = "\n".join(directives)
    assert not re.search(r"^\s*include\s+\S*api-upstream\.conf\s*;", body, re.MULTILINE)
    assert not re.search(r"^\s*upstream\s+juli_api\s*\{", body, re.MULTILINE)
