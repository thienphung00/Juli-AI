#!/usr/bin/env python3
"""Lint: inbound edge rate limits stay wired on the routes ADR-061 §2b requires.

Issue #898 / ADR-061 §2b: nginx `limit_req` zones are the ONLY inbound throttle —
`infra/systemd/juli-api.service` runs uvicorn `--workers 1`, so a flood must be
rejected at the edge before it reaches the sole worker. This is a static text lint
(no nginx binary required) so it runs on every PR; `check_nginx_config_parses.sh`
is the separate, Docker-based check that the resulting config actually parses on
the nginx version the review VPS runs.

Binding requirement (issue #898 exit gate): a `limit_req` directive must be present
on the webhook receiver and the public Demo read locations, so deleting either one
fails the build. This also checks the OAuth callback and authenticated catch-all
locations (all four are ADR-061 §2b requirements) and asserts `/health` carries NO
`limit_req` (ADR-061 doNotInfer: uptime polling must never be throttled).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
NGINX_DIR = REPO_ROOT / "infra" / "nginx"
API_VHOST_PATH = NGINX_DIR / "api.app-juli.com.conf"
RATE_LIMITS_PATH = NGINX_DIR / "rate-limits.conf"

LOCATION_HEADER_RE = re.compile(
    r"location\s+(?P<modifier>=|~\*|~|\^~)?\s*(?P<path>\S+)\s*\{",
)
LIMIT_REQ_RE = re.compile(r"^\s*limit_req\s+zone=", re.MULTILINE)
LIMIT_REQ_ZONE_DEF_RE = re.compile(r"^\s*limit_req_zone\s+\S+\s+zone=(\S+?):", re.MULTILINE)


@dataclass(frozen=True)
class LocationBlock:
    path: str
    modifier: str | None
    body: str


def extract_ssl_server_block(conf_text: str) -> str:
    """Return the body of the `listen 443 ssl` server block.

    The vhost also has a port-80 redirect server with its own `location /` (no rate
    limit needed — it only 301s to HTTPS). Scoping to the TLS server block avoids
    matching that redirect location instead of the real proxying catch-all.
    """
    marker = "listen 443"
    idx = conf_text.find(marker)
    if idx == -1:
        raise AssertionError("no `listen 443 ssl` server block found")
    # Walk back to the enclosing `server {`.
    open_idx = conf_text.rfind("server {", 0, idx)
    if open_idx == -1:
        raise AssertionError("could not locate the `server {` enclosing `listen 443`")
    brace_start = conf_text.find("{", open_idx)
    depth = 1
    pos = brace_start + 1
    while pos < len(conf_text) and depth > 0:
        if conf_text[pos] == "{":
            depth += 1
        elif conf_text[pos] == "}":
            depth -= 1
        pos += 1
    return conf_text[brace_start + 1 : pos - 1]


def extract_location_blocks(conf_text: str) -> list[LocationBlock]:
    """Split an nginx conf into its `location` blocks via brace counting.

    A regex alone cannot bound a `location { ... }` block (nginx blocks nest and
    contain unrelated braces in comments), so this walks braces from each
    `location` header to its matching close.
    """
    blocks: list[LocationBlock] = []
    for match in LOCATION_HEADER_RE.finditer(conf_text):
        depth = 1
        start = match.end()
        pos = start
        while pos < len(conf_text) and depth > 0:
            if conf_text[pos] == "{":
                depth += 1
            elif conf_text[pos] == "}":
                depth -= 1
            pos += 1
        body = conf_text[start : pos - 1]
        blocks.append(
            LocationBlock(path=match.group("path"), modifier=match.group("modifier"), body=body)
        )
    return blocks


def find_location(blocks: list[LocationBlock], path: str) -> LocationBlock | None:
    for block in blocks:
        if block.path == path:
            return block
    return None


def find_location_prefix(blocks: list[LocationBlock], prefix: str) -> LocationBlock | None:
    for block in blocks:
        if block.modifier is None and block.path == prefix:
            return block
    return None


def has_limit_req(block: LocationBlock) -> bool:
    return bool(LIMIT_REQ_RE.search(block.body))


def referenced_zones(conf_text: str) -> set[str]:
    return set(re.findall(r"limit_req\s+zone=(\S+?)[\s;]", conf_text))


def defined_zones(rate_limits_text: str) -> set[str]:
    return set(LIMIT_REQ_ZONE_DEF_RE.findall(rate_limits_text))


def run_check() -> tuple[bool, str, list[str]]:
    errors: list[str] = []

    if not API_VHOST_PATH.is_file():
        return False, f"missing {API_VHOST_PATH.relative_to(REPO_ROOT)}", [
            f"missing {API_VHOST_PATH.relative_to(REPO_ROOT)}"
        ]
    if not RATE_LIMITS_PATH.is_file():
        return False, f"missing {RATE_LIMITS_PATH.relative_to(REPO_ROOT)}", [
            f"missing {RATE_LIMITS_PATH.relative_to(REPO_ROOT)}"
        ]

    vhost_text = API_VHOST_PATH.read_text(encoding="utf-8")
    zones_text = RATE_LIMITS_PATH.read_text(encoding="utf-8")
    ssl_server_text = extract_ssl_server_block(vhost_text)
    blocks = extract_location_blocks(ssl_server_text)

    # Binding (issue #898 exit gate): webhook receiver and public Demo read path.
    webhook = find_location(blocks, "/webhooks/tiktok")
    if webhook is None:
        errors.append("no `location = /webhooks/tiktok` block found in api.app-juli.com.conf")
    elif not has_limit_req(webhook):
        errors.append("`location = /webhooks/tiktok` has no `limit_req zone=...` directive")

    demo = find_location_prefix(blocks, "/v1/demo/")
    if demo is None:
        errors.append("no `location /v1/demo/` block found in api.app-juli.com.conf")
    elif not has_limit_req(demo):
        errors.append("`location /v1/demo/` has no `limit_req zone=...` directive")

    # ADR-061 §2b also requires the OAuth callback surface and authenticated
    # catch-all to carry a limit_req zone (strict / generous respectively).
    auth = find_location_prefix(blocks, "/v1/auth/")
    if auth is None:
        errors.append("no `location /v1/auth/` block found in api.app-juli.com.conf")
    elif not has_limit_req(auth):
        errors.append("`location /v1/auth/` has no `limit_req zone=...` directive")

    catchall = find_location_prefix(blocks, "/")
    if catchall is None:
        errors.append("no authenticated catch-all `location /` block found in api.app-juli.com.conf")
    elif not has_limit_req(catchall):
        errors.append("catch-all `location /` has no `limit_req zone=...` directive")

    # ADR-061 doNotInfer: /health must never be throttled.
    health = find_location(blocks, "/health")
    if health is None:
        errors.append("no `location = /health` block found in api.app-juli.com.conf")
    elif has_limit_req(health):
        errors.append(
            "`location = /health` carries a `limit_req` directive — uptime polling must "
            "never be throttled (ADR-061 doNotInfer)"
        )

    # Every zone the vhost references must actually be defined somewhere, and
    # limit_req_status must be set to 429 (not nginx's 503 default) so rejections
    # return the semantically correct status code.
    used = referenced_zones(vhost_text)
    defined = defined_zones(zones_text)
    undefined = sorted(used - defined)
    if undefined:
        errors.append(f"zone(s) referenced but never defined in rate-limits.conf: {undefined}")
    if not re.search(r"^\s*limit_req_status\s+429\s*;", zones_text, re.MULTILINE):
        errors.append("rate-limits.conf must set `limit_req_status 429;`")

    if errors:
        return False, f"{len(errors)} problem(s); first: {errors[0]}", errors
    return True, "webhook, demo, auth, and catch-all locations are rate-limited; /health is exempt", []


def main() -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import print_check_result  # noqa: E402

    passed, detail, errors = run_check()
    for err in errors:
        print(f"nginx_rate_limits: FAIL — {err}", file=sys.stderr)
    return print_check_result("nginx_rate_limits", passed, detail)


if __name__ == "__main__":
    raise SystemExit(main())
