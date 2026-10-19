"""Juli Ops console services (fast track P16, DECISIONS D25)."""

from juli_backend.services.ops.access import OpsRoleMissing, ops_role
from juli_backend.services.ops.masking import mask_pii
from juli_backend.services.ops.overrides import cap_guarded, llm_config_for
from juli_backend.services.ops.overview import ShopListing
from juli_backend.services.ops.scopes import shop_scope_status

# Lazy (fast track P53, D62): the worker tasks reached these by deep import
# (`check_import_boundaries.py` reports that). Their callers imported them inside
# the task body, so they stay deferred to first attribute access; the package's
# import-time behaviour is unchanged. Same shape as `services/tiktok/__init__.py`.
_LAZY_EXPORTS = {
    "check_alert": "juli_backend.services.ops.system_cap",
    "purge_expired": "juli_backend.services.ops.audit",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    module = importlib.import_module(module_path)
    return getattr(module, name)


__all__ = [
    "OpsRoleMissing",
    "ShopListing",
    "cap_guarded",
    "check_alert",
    "llm_config_for",
    "mask_pii",
    "ops_role",
    "purge_expired",
    "shop_scope_status",
]
