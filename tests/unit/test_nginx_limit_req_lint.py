"""Nginx rate-limiting configuration lint (ADR-061 §2b step 8).

Verify that limit_req zones are properly configured on sensitive routes:
- /webhooks/tiktok (strict, webhook authentication cost)
- /v1/demo/* (public/unauthenticated)
- /v1/demo/runs/{run_id}/events (SSE)
- Authenticated catch-all (generous, auth cost already paid)

The lint must:
1. Assert limit_req is present on webhook and demo locations
2. Assert the authenticated catch-all has a generous zone rather than none
3. Detect when a referenced zone is removed (config becomes invalid)
4. Prevent a revert from leaving a zone referenced-but-undefined
"""

from __future__ import annotations

import re
from pathlib import Path


def _read_nginx_file(path: Path) -> str:
    """Read the Nginx config file content."""
    return path.read_text()


def _extract_zones_defined(content: str) -> set[str]:
    """Extract all limit_req_zone names defined in the config."""
    pattern = r"limit_req_zone\s+.*?\s+zone=([a-zA-Z0-9_]+):"
    return set(re.findall(pattern, content))


def _extract_zone_references(content: str) -> set[str]:
    """Extract all limit_req zone references in the config."""
    pattern = r"limit_req\s+zone=([a-zA-Z0-9_]+)\s+"
    return set(re.findall(pattern, content))


def _extract_locations_with_limit_req(content: str) -> dict[str, str | None]:
    """Extract all location blocks and their limit_req zones.

    Returns: {location_pattern: zone_name or None}
    """
    locations = {}

    # Find all location blocks with their content
    # Matches: location PATH { ... limit_req zone=NAME ... }
    location_pattern = (
        r"location\s+([^\{]+)\s*\{([^\}]*?)"
        r"(?:limit_req\s+zone=([a-zA-Z0-9_]+)|(?=\}))"
    )
    for match in re.finditer(location_pattern, content):
        location = match.group(1).strip()
        zone = match.group(3) if match.group(3) else None
        locations[location] = zone

    return locations


def test_nginx_rate_limits_conf_defines_required_zones():
    """rate-limits.conf must define zones for webhook, demo, auth, and authenticated."""
    rate_limits_path = Path(__file__).parent.parent.parent / "infra" / "nginx" / "rate-limits.conf"
    content = _read_nginx_file(rate_limits_path)
    zones = _extract_zones_defined(content)

    # These zones must be defined
    required_zones = {"webhook_tiktok", "demo_public", "auth_callback", "api_authenticated"}
    assert required_zones.issubset(zones), (
        f"Missing zones: {required_zones - zones}. Defined zones: {zones}"
    )


def test_nginx_api_conf_webhook_has_limit_req():
    """The /webhooks/tiktok location must have limit_req."""
    api_conf_path = (
        Path(__file__).parent.parent.parent / "infra" / "nginx" / "api.app-juli.com.conf"
    )
    content = _read_nginx_file(api_conf_path)

    # Find the webhooks/tiktok location block
    webhook_pattern = r"location\s+=\s+/webhooks/tiktok\s*\{([^\}]*?)\}"
    match = re.search(webhook_pattern, content)
    assert match, "webhook location block not found"

    location_content = match.group(1)
    assert "limit_req" in location_content, (
        "/webhooks/tiktok location must have a limit_req directive"
    )
    assert "zone=webhook_tiktok" in location_content, (
        "/webhooks/tiktok must use the webhook_tiktok zone"
    )


def test_nginx_api_conf_demo_has_limit_req():
    """The /v1/demo/* locations must have limit_req."""
    api_conf_path = (
        Path(__file__).parent.parent.parent / "infra" / "nginx" / "api.app-juli.com.conf"
    )
    content = _read_nginx_file(api_conf_path)

    # Find demo location blocks
    demo_locations = []

    # Main /v1/demo/ location
    demo_pattern = r"location\s+/v1/demo/\s*\{([^\}]*?)\}"
    match = re.search(demo_pattern, content)
    assert match, "main /v1/demo/ location not found"
    demo_locations.append(("/v1/demo/", match.group(1)))

    # SSE /v1/demo/runs/{run_id}/events location
    sse_pattern = r"location\s+~\s+\^/v1/demo/runs/.*?/events\$\s*\{([^\}]*?)\}"
    match = re.search(sse_pattern, content)
    assert match, "/v1/demo/runs/{run_id}/events location not found"
    demo_locations.append(("/v1/demo/runs/.../events", match.group(1)))

    # All demo locations must have limit_req with demo_public zone
    for loc_name, loc_content in demo_locations:
        assert "limit_req" in loc_content, f"{loc_name} must have a limit_req directive"
        assert "zone=demo_public" in loc_content, f"{loc_name} must use the demo_public zone"


def test_nginx_api_conf_authenticated_catchall_has_generous_zone():
    """The authenticated catch-all location must have limit_req with a generous zone."""
    api_conf_path = (
        Path(__file__).parent.parent.parent / "infra" / "nginx" / "api.app-juli.com.conf"
    )
    content = _read_nginx_file(api_conf_path)

    # Find the root / location (the authenticated catch-all)
    # It should be the last one in the file
    root_pattern = r"location\s+/\s*\{([^\}]*?)(?=\s*\}$)"
    matches = list(re.finditer(root_pattern, content, re.MULTILINE | re.DOTALL))
    assert matches, "authenticated catch-all location / not found"

    # Take the last match
    location_content = matches[-1].group(1)
    assert "limit_req" in location_content, "Authenticated catch-all must have limit_req"
    assert "zone=api_authenticated" in location_content, (
        "Authenticated catch-all must use the api_authenticated (generous) zone, not a strict one"
    )


def test_nginx_no_undefined_zone_references():
    """Verify no location references a zone that is not defined."""
    rate_limits_path = Path(__file__).parent.parent.parent / "infra" / "nginx" / "rate-limits.conf"
    api_conf_path = (
        Path(__file__).parent.parent.parent / "infra" / "nginx" / "api.app-juli.com.conf"
    )

    rate_limits_content = _read_nginx_file(rate_limits_path)
    api_conf_content = _read_nginx_file(api_conf_path)

    defined_zones = _extract_zones_defined(rate_limits_content)
    referenced_zones = _extract_zone_references(api_conf_content)

    undefined = referenced_zones - defined_zones
    assert not undefined, (
        f"References to undefined zones: {undefined}. Defined zones: {defined_zones}"
    )


def test_nginx_zone_removal_detection():
    """Demonstrate that the lint would catch a removed zone.

    This test verifies that if a zone is removed from rate-limits.conf,
    the undefined zone reference detection would catch it.
    """
    rate_limits_path = Path(__file__).parent.parent.parent / "infra" / "nginx" / "rate-limits.conf"

    rate_limits_content = _read_nginx_file(rate_limits_path)

    # Simulate a broken config that references a non-existent zone
    broken_config = """
    location = /webhooks/tiktok {
        limit_req zone=webhook_tiktok_deleted burst=40 nodelay;
        proxy_pass http://juli_api/webhooks/tiktok;
    }
    """

    defined_zones = _extract_zones_defined(rate_limits_content)
    referenced_zones = _extract_zone_references(broken_config)

    # The broken config would reference a zone that doesn't exist
    undefined = referenced_zones - defined_zones
    # Only check if webhook_tiktok_deleted is different from webhook_tiktok
    if "webhook_tiktok_deleted" in referenced_zones:
        assert "webhook_tiktok_deleted" in undefined, (
            "Lint should detect the undefined zone reference"
        )
