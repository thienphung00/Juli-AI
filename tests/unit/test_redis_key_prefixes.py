"""Redis application key prefix policy tests (MMU-12 / GitHub #560)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHECK_SCRIPT = ROOT / "agent-runtime/scripts/ci/check_redis_key_prefixes.py"
SYNTHETIC_FIXTURE = ROOT / "tests/fixtures/redis_key_prefixes/synthetic"
REGISTRY_PATH = ROOT / "docs/architecture/ownership-registry.yml"

sys.path.insert(0, str(ROOT / "agent-runtime/scripts/ci"))
from check_ownership_registry import load_ownership_registry  # noqa: E402
from check_redis_key_prefixes import (  # noqa: E402
    collect_unknown_prefixes,
    load_redis_key_policy,
    validate_scan,
)


def _run_checker(*extra: str) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(CHECK_SCRIPT), *extra]
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)


def test_registry_documents_juli_module_convention_and_legacy_allowlist() -> None:
    policy = load_redis_key_policy(REGISTRY_PATH)
    assert policy["futureConvention"] == "juli:<module>:"
    allowlist = set(policy["legacyAllowlist"])
    assert "ratelimit:*" in allowlist
    assert "analytics:kpi_envelope:*" in allowlist
    assert "material_analytics:mutex:*" in allowlist
    assert "material_analytics:coalesce68:*" in allowlist


def test_registry_lists_material_and_kpi_redis_patterns_with_owners() -> None:
    registry = load_ownership_registry(REGISTRY_PATH)
    patterns = {entry["pattern"]: entry["owner"] for entry in registry["redisNamespaces"]}
    assert patterns["ratelimit:*"] == "Integrations"
    assert patterns["analytics:kpi_envelope:*"] == "Intelligence"
    assert patterns["material_analytics:mutex:*"] == "Data Pipeline"
    assert patterns["material_analytics:coalesce68:*"] == "Data Pipeline"
    celery = next(e for e in registry["redisNamespaces"] if e["pattern"] == "celery-*")
    assert celery["owner"] == "Workers & Async"
    assert "broker" in celery["notes"].lower()


def test_rate_limiter_key_pattern_compatible_integrations_ownership() -> None:
    """Rate limiter keeps ratelimit:{app_id}:{shop_id}:{endpoint}; owner Integrations."""
    from juli_backend.integrations.tiktok.rate_limiter import RateLimiter

    key = RateLimiter._key("app_1", "shop_99", "/orders/search")
    assert key == "ratelimit:app_1:shop_99:/orders/search"

    registry = load_ownership_registry(REGISTRY_PATH)
    patterns = {entry["pattern"]: entry["owner"] for entry in registry["redisNamespaces"]}
    assert patterns["ratelimit:*"] == "Integrations"


def test_synthetic_unknown_prefix_fails_check() -> None:
    unknown = collect_unknown_prefixes(SYNTHETIC_FIXTURE, REGISTRY_PATH)
    assert any("rogue:cache:" in item.prefix for item in unknown)

    passed, errors = validate_scan(SYNTHETIC_FIXTURE, REGISTRY_PATH)
    assert not passed
    assert any("rogue:cache:" in err for err in errors)


def test_synthetic_unknown_prefix_fails_cli_strict() -> None:
    result = _run_checker(
        "--scan-root",
        str(SYNTHETIC_FIXTURE),
        "--registry",
        str(REGISTRY_PATH),
        "--strict",
    )
    assert result.returncode != 0, result.stdout + result.stderr
    combined = result.stdout + result.stderr
    assert "redis_key_prefixes: FAIL" in combined
    assert "rogue:cache:" in combined


def test_production_backend_scan_passes_registered_prefixes() -> None:
    backend_root = ROOT / "backend/src/juli_backend"
    passed, errors = validate_scan(backend_root, REGISTRY_PATH)
    assert passed, errors
