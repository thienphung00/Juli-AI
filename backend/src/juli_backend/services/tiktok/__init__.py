from juli_backend.services.tiktok.dispatcher import TikTokWebhookDispatcher
from juli_backend.services.tiktok.signature import TikTokWebhookSignatureVerifier
from juli_backend.services.tiktok.webhook import (
    ACCOUNT_LIFECYCLE_CHANNEL,
    EVENT_CATEGORY_ROUTES,
    TikTokWebhookService,
    resolve_ingest_channel,
    should_handoff_to_etl,
)
from juli_backend.services.tiktok.webhook_catalog import (
    PHASE2_CATALOG,
    PHASE2_CATALOG_IDS,
    resolve_catalog_entry,
)

# Lazy: `poll_resources` imports `juli_backend.core.security` (package root),
# and `core.security.tiktok_oauth` imports `services.tiktok.token_expiry`
# (a grandfathered forbidden edge -- see
# docs/architecture/import-boundary-baseline.json). An eager top-level import
# here would make that a real circular import at package-init time instead of
# a merely-forbidden one; deferring it until first attribute access keeps
# this package's own `__init__` free of the cycle, mirroring
# `services/etl/__init__.py`'s `_LAZY_EXPORTS` shape.
#
# `make_binding_verifier` (#1995) is lazy for the same reason:
# `credential_binding` imports `juli_backend.core.security` at its own top
# level, so an eager re-export would pull the same cycle in here. It is listed
# at all because `services/action_cards/refresh.py` is a genuine cross-module
# consumer and was reaching it by deep import, which this package's own rule
# ("import from the package root only") forbids and
# `check_module_boundaries.py` reports.
_LAZY_EXPORTS = {
    "build_fujiwa_poll_vendor_resources": "juli_backend.services.tiktok.poll_resources",
    "make_binding_verifier": "juli_backend.services.tiktok.credential_binding",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "ACCOUNT_LIFECYCLE_CHANNEL",
    "EVENT_CATEGORY_ROUTES",
    "PHASE2_CATALOG",
    "PHASE2_CATALOG_IDS",
    "TikTokWebhookDispatcher",
    "TikTokWebhookService",
    "TikTokWebhookSignatureVerifier",
    "build_fujiwa_poll_vendor_resources",
    "make_binding_verifier",
    "resolve_catalog_entry",
    "resolve_ingest_channel",
    "should_handoff_to_etl",
]
