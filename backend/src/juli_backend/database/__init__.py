"""Persistence layer facade.

Historically this package eagerly re-exported ``models.models`` and
``repositories.repos`` for convenience (``from juli_backend.database import
Shop, ShopsRepo``). Those modules import back into ``juli_backend.database.*``
(``Base``, ``NotFound``, ``token_crypto``), so eager re-export created an import
cycle: whenever ``repositories.repos`` was the *first* module to touch this
package (e.g. the FastAPI entrypoint imports it via
``core.security.credential_resolver`` before anything imports the facade), this
package's ``__init__`` re-entered ``repositories.repos`` while it was still
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
        ProcessedEvent,
        Product,
        Recommendation,
        Settlement,
        Shop,
        TikTokCredential,
        User,
    )
    from juli_backend.repositories.repos import (
        ActionCardsRepo,
        AlertConfigsRepo,
        AlertHistoryRepo,
        CreatorsRepo,
        GraphRepo,
        InventoryRepo,
        LivestreamsRepo,
        OrdersRepo,
        ProcessedEventsRepo,
        ProductsRepo,
        RecommendationsRepo,
        SettlementsRepo,
        ShopScopedRepo,
        ShopsRepo,
        TikTokCredentialRepo,
        UsersRepo,
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
    "ProcessedEvent": "juli_backend.models.models",
    "Product": "juli_backend.models.models",
    "Recommendation": "juli_backend.models.models",
    "Settlement": "juli_backend.models.models",
    "Shop": "juli_backend.models.models",
    "TikTokCredential": "juli_backend.models.models",
    "User": "juli_backend.models.models",
    # Repositories
    "ActionCardsRepo": "juli_backend.repositories.repos",
    "AlertConfigsRepo": "juli_backend.repositories.repos",
    "AlertHistoryRepo": "juli_backend.repositories.repos",
    "CreatorsRepo": "juli_backend.repositories.repos",
    "GraphRepo": "juli_backend.repositories.repos",
    "InventoryRepo": "juli_backend.repositories.repos",
    "LivestreamsRepo": "juli_backend.repositories.repos",
    "OrdersRepo": "juli_backend.repositories.repos",
    "ProcessedEventsRepo": "juli_backend.repositories.repos",
    "ProductsRepo": "juli_backend.repositories.repos",
    "RecommendationsRepo": "juli_backend.repositories.repos",
    "SettlementsRepo": "juli_backend.repositories.repos",
    "ShopScopedRepo": "juli_backend.repositories.repos",
    "ShopsRepo": "juli_backend.repositories.repos",
    "TikTokCredentialRepo": "juli_backend.repositories.repos",
    "UsersRepo": "juli_backend.repositories.repos",
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
    "ProductsRepo",
    "Recommendation",
    "RecommendationsRepo",
    "Settlement",
    "SettlementsRepo",
    "Shop",
    "ShopScopedRepo",
    "ShopsRepo",
    "TikTokCredential",
    "TikTokCredentialRepo",
    "User",
    "UsersRepo",
    "get_session",
    "init_session_factory",
]
