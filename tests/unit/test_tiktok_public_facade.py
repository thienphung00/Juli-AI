"""TikTok package-root public facade contract (MMU-5 / GitHub #557 packet 1)."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = ROOT / "backend/src"

# Documented public surface — must match integrations/tiktok/MODULE.md + __all__.
EXPECTED_PUBLIC_EXPORTS = frozenset(
    {
        # Authentication
        "TikTokAuth",
        "TikTokBusinessAdvertiserAuth",
        "TikTokBusinessAccountHolderAuth",
        "DEFAULT_OPEN_API_BASE_URL",
        # HTTP client
        "TikTokClient",
        # #1200: safe identifier rendering, needed by services/tiktok/
        # credential_binding.py, which may only reach the package root (depth-2 cap).
        "redact_shop_identifier",
        # Request signing
        "sign_request",
        # Rate limiting
        "RateLimiter",
        # API path constants
        "ANALYTICS_BESTSELLING_PRODUCTS_PATH",
        "ANALYTICS_BESTSELLING_VIDEOS_PATH",
        "ANALYTICS_LIVE_OVERVIEW_PERFORMANCE_PATH",
        "ANALYTICS_LIVE_PERFORMANCE_LIST_PATH",
        "ANALYTICS_SHOP_PERFORMANCE_PATH",
        "ANALYTICS_SHOP_PRODUCTS_PERFORMANCE_PATH",
        "ANALYTICS_SHOP_SKUS_PERFORMANCE_PATH",
        "CANCELLATION_SEARCH_PATH",
        "FINANCE_STATEMENTS_PATH",
        "INVENTORY_SEARCH_PATH",
        "MARKETPLACE_CREATORS_SEARCH_PATH",
        "ORDER_SEARCH_PATH",
        "PRODUCT_SEARCH_PATH",
        "RETURN_SEARCH_PATH",
        "analytics_shop_performance_per_hour_path",
        "analytics_shop_product_performance_path",
        "analytics_shop_sku_performance_path",
        "promotion_activity_path",
        # Client factories
        "ClientFactoryConfig",
        "ProductionReadClientFactory",
        "ProductionReadResources",
        "SandboxWriteClientFactory",
        "SandboxWriteResources",
        # Merchant capability isolation
        "PRODUCTION_AUTH_ID",
        "SANDBOX_AUTH_ID",
        "TikTokCapability",
        "is_cross_merchant_lookup",
        "resolve_merchant_context",
        # Vendor → ingest mapping
        "analytics_snapshot_key",
        "expand_analytics_live_session",
        "expand_analytics_product_detail",
        "expand_analytics_product_list_item",
        "expand_analytics_shop_performance",
        "expand_analytics_shop_performance_per_hour",
        "expand_analytics_sku_detail",
        "expand_analytics_sku_list_item",
        "expand_inventory_search",
        "expand_order_line_items",
        "normalize_cancellation",
        "normalize_creator",
        "normalize_inventory",
        "normalize_livestream",
        "normalize_order",
        "normalize_product",
        "normalize_return",
        "normalize_statement",
        # Resources
        "strip_nones",
        "AnalyticsResource",
        "AuthorizationResource",
        "CreatorsResource",
        "FulfillmentResource",
        "InventoryResource",
        "LivestreamsResource",
        "OrdersResource",
        "ProductsResource",
        "PromotionResource",
        "ReturnsResource",
        "SettlementsResource",
        # Exceptions
        "TikTokAPIError",
        "AuthenticationError",
        "PermissionDeniedError",
        "ResourceNotFoundError",
        "RateLimitError",
        "TikTokSystemError",
        "TransportGuardError",
        "error_from_response",
        # Selective — OAuth verify_connection caller slice
        "TikTokSchemaError",
    }
)


def test_module_md_public_surface_matches_facade() -> None:
    import juli_backend.integrations.tiktok as tiktok

    assert hasattr(tiktok, "__all__")
    assert frozenset(tiktok.__all__) == EXPECTED_PUBLIC_EXPORTS


@pytest.mark.parametrize("export_name", sorted(EXPECTED_PUBLIC_EXPORTS))
def test_tiktok_public_export_is_importable_from_package_root(export_name: str) -> None:
    import juli_backend.integrations.tiktok as tiktok

    symbol = getattr(tiktok, export_name)
    assert symbol is not None


def test_tiktok_package_import_has_no_http_redis_db_or_celery_side_effects() -> None:
    """Importing the facade must not open network, Redis, DB, or Celery connections."""
    probe = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        from unittest import mock

        sys.path.insert(0, {str(BACKEND_SRC)!r})
        side_effects: list[str] = []

        def _trap_http(*_args, **_kwargs):
            side_effects.append("http")
            raise AssertionError("HTTP invoked during TikTok package import")

        class _TrapRedis:
            def __init__(self, *_args, **_kwargs):
                side_effects.append("redis")
                raise AssertionError("Redis client constructed during import")

        class _TrapEngine:
            def __init__(self, *_args, **_kwargs):
                side_effects.append("db")
                raise AssertionError("SQLAlchemy engine constructed during import")

        class _TrapCelery:
            def __init__(self, *_args, **_kwargs):
                side_effects.append("celery")
                raise AssertionError("Celery app constructed during import")

        with mock.patch("requests.get", _trap_http), \\
             mock.patch("requests.post", _trap_http), \\
             mock.patch("requests.put", _trap_http), \\
             mock.patch("requests.request", _trap_http), \\
             mock.patch("requests.Session", _TrapRedis), \\
             mock.patch("redis.Redis", _TrapRedis), \\
             mock.patch("redis.from_url", _TrapRedis), \\
             mock.patch("sqlalchemy.create_engine", _TrapEngine), \\
             mock.patch("celery.Celery", _TrapCelery):
            import juli_backend.integrations.tiktok as tiktok
            for name in tiktok.__all__:
                getattr(tiktok, name)

        assert side_effects == [], f"unexpected import-time side effects: {{side_effects}}"
        print("OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
