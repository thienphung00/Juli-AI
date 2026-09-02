"""Persistence layer facade.

Historically this package eagerly re-exported ``models.models`` and
``repositories`` for convenience (``from juli_backend.database import
Shop, ShopsRepo``). Those modules import back into ``juli_backend.database.*``
(``Base``, ``NotFound``, ``token_crypto``), so eager re-export created an import
cycle: whenever ``repositories`` was the *first* module to touch this
package (e.g. the FastAPI entrypoint imports it via
``core.security.credential_resolver`` before anything imports the facade), this
package's ``__init__`` re-entered ``repositories`` while it was still
initializing and crashed with a partial-import ``ImportError``.

The leaf, dependency-free symbols (``Base``, session helpers, ``NotFound``) are
still imported eagerly. Model and repository symbols are resolved lazily via
PEP 562 ``__getattr__`` so importing this package never forces ``models`` or
``repositories`` to finish loading before they are ready. The ``TYPE_CHECKING``
block keeps every re-exported name statically visible to mypy and ruff.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from juli_backend.database.database import Base, get_session, init_session_factory
from juli_backend.database.exceptions import NotFound
from juli_backend.database.tenant_context import (
    TenantContextRequiredError,
    clear_tenant_context,
    get_tenant_context,
    set_tenant_context,
    system_scope,
    with_tenant_scope,
)

if TYPE_CHECKING:
    from juli_backend.models.models import (
        ActionCard,
        AlertConfig,
        AlertHistory,
        Campaign,
        Creator,
        GraphEdge,
        InventoryItem,
        Livestream,
        Order,
        Product,
        ProductionWriteAuthorization,
        Recommendation,
        Settlement,
        Shop,
        TikTokCredential,
        User,
    )
    from juli_backend.repositories import (
        ActionCardsRepo,
        AlertConfigsRepo,
        AlertHistoryRepo,
        CreatorsRepo,
        GraphRepo,
        InventoryRepo,
        LivestreamsRepo,
        OrdersRepo,
        ProductionWriteAuthorizationsRepo,
        ProductsRepo,
        RecommendationsRepo,
        SettlementsRepo,
        ShopScopedRepo,
        ShopsRepo,
        TikTokCredentialRepo,
        UsersRepo,
    )
    from juli_backend.services.etl.persistence.ingest import (
        ProcessedEvent,
        ProcessedEventsRepo,
    )

# Lazily re-exported symbol -> defining module. Resolved on first attribute
# access (or `from juli_backend.database import X`) via __getattr__ below.
_LAZY_EXPORTS = {
    # Models
    "ActionCard": "juli_backend.models.models",
    "AlertConfig": "juli_backend.models.models",
    "AlertHistory": "juli_backend.models.models",
    "Campaign": "juli_backend.models.models",
    "Creator": "juli_backend.models.models",
    "GraphEdge": "juli_backend.models.models",
    "InventoryItem": "juli_backend.models.models",
    "Livestream": "juli_backend.models.models",
    "Order": "juli_backend.models.models",
    "ProcessedEvent": "juli_backend.services.etl.persistence.ingest",
    "Product": "juli_backend.models.models",
    "ProductionWriteAuthorization": "juli_backend.models.models",
    "Recommendation": "juli_backend.models.models",
    "Settlement": "juli_backend.models.models",
    "Shop": "juli_backend.models.models",
    "TikTokCredential": "juli_backend.models.models",
    "User": "juli_backend.models.models",
    # Repositories
    "ActionCardsRepo": "juli_backend.repositories",
    "AlertConfigsRepo": "juli_backend.repositories",
    "AlertHistoryRepo": "juli_backend.repositories",
    "CreatorsRepo": "juli_backend.repositories",
    "GraphRepo": "juli_backend.repositories",
    "InventoryRepo": "juli_backend.repositories",
    "LivestreamsRepo": "juli_backend.repositories",
    "OrdersRepo": "juli_backend.repositories",
    "ProcessedEventsRepo": "juli_backend.services.etl.persistence.ingest",
    "ProductionWriteAuthorizationsRepo": "juli_backend.repositories",
    "ProductsRepo": "juli_backend.repositories",
    "RecommendationsRepo": "juli_backend.repositories",
    "SettlementsRepo": "juli_backend.repositories",
    "ShopScopedRepo": "juli_backend.repositories",
    "ShopsRepo": "juli_backend.repositories",
    "TikTokCredentialRepo": "juli_backend.repositories",
    "UsersRepo": "juli_backend.repositories",
}


def __getattr__(name: str):
    module_path = _LAZY_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(importlib.import_module(module_path), name)


def __dir__() -> list[str]:
    return sorted(__all__)


__all__ = [
    "ActionCard",
    "ActionCardsRepo",
    "AlertConfig",
    "AlertConfigsRepo",
    "AlertHistory",
    "AlertHistoryRepo",
    "Base",
    "Campaign",
    "Creator",
    "CreatorsRepo",
    "GraphEdge",
    "GraphRepo",
    "InventoryItem",
    "InventoryRepo",
    "Livestream",
    "LivestreamsRepo",
    "NotFound",
    "Order",
    "OrdersRepo",
    "ProcessedEvent",
    "ProcessedEventsRepo",
    "Product",
    "ProductionWriteAuthorization",
    "ProductionWriteAuthorizationsRepo",
    "ProductsRepo",
    "Recommendation",
    "RecommendationsRepo",
    "Settlement",
    "SettlementsRepo",
    "Shop",
    "ShopScopedRepo",
    "ShopsRepo",
    "TenantContextRequiredError",
    "TikTokCredential",
    "TikTokCredentialRepo",
    "User",
    "UsersRepo",
    "clear_tenant_context",
    "get_session",
    "get_tenant_context",
    "init_session_factory",
    "set_tenant_context",
    "system_scope",
    "with_tenant_scope",
]
