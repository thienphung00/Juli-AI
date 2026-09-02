"""Data access repositories, one module per aggregate.

Import from this package, not from the submodules::

    from juli_backend.repositories import OrdersRepo, TikTokCredentialRepo

Start with ``_base.py`` -- it states the contract every repository follows
(borrowed session, structural tenant scoping, ``get`` raises / ``find`` returns
``None``, naive-UTC timestamps, idempotent upsert). Each other module is that
contract applied to one aggregate:

==========================  =====================================================
``identity``                users and the shops they own
``tiktok_credentials``      OAuth tokens (encrypted at rest) and sync cursors
``commerce``                orders, order lines, returns, products, inventory,
                            settlements -- the silver domain rows
``analytics``               creators, livestreams, performance, the gold KPI
                            envelope and its legacy-shaped adapter
``decisions``               alerts, recommendations, persisted ActionCards
``graph``                   campaign nodes and relationship edges
``bronze``                  append-only raw vendor payloads
``workflow``                webhook intake and the tool-execution audit trail
``backfill``                resumable analytics backfill partitions
``production_write``        single-use production mutation authorizations
==========================  =====================================================

``repos.py`` re-exports everything for callers written before the split.
"""

from __future__ import annotations

from juli_backend.repositories._base import SessionRepo, ShopScopedRepo, utc_now_naive
from juli_backend.repositories.analytics import (
    AnalyticsKpiEnvelopesRepo,
    AnalyticsPerformanceRepo,
    CreatorsRepo,
    GoldKpiEnvelopesRepo,
    LivestreamsRepo,
)
from juli_backend.repositories.backfill import AnalyticsBackfillPartitionsRepo
from juli_backend.repositories.bronze import (
    BronzeCtorPerformanceRawPayloadsRepo,
    BronzeLiveHoursRawPayloadsRepo,
    BronzeOrderRawPayloadsRepo,
    BronzeRawPayloadsRepo,
    BronzeReturnRawPayloadsRepo,
)
from juli_backend.repositories.commerce import (
    InventoryRepo,
    OrderItemsRepo,
    OrdersRepo,
    ProductsRepo,
    ReturnsRepo,
    SettlementsRepo,
)
from juli_backend.repositories.decisions import (
    ActionCardsRepo,
    AlertConfigsRepo,
    AlertHistoryRepo,
    RecommendationsRepo,
)
from juli_backend.repositories.graph import GraphRepo
from juli_backend.repositories.identity import ShopsRepo, UsersRepo
from juli_backend.repositories.production_write import ProductionWriteAuthorizationsRepo
from juli_backend.repositories.tiktok_credentials import TikTokCredentialRepo, TikTokSyncStateRepo
from juli_backend.repositories.workflow import (
    ToolExecutionsRepo,
    WebhookRawEventsRepo,
    WorkflowOutcomeRecordsRepo,
    WorkflowWebhookSignalsRepo,
)

__all__ = [
    "ActionCardsRepo",
    "AlertConfigsRepo",
    "AlertHistoryRepo",
    "AnalyticsBackfillPartitionsRepo",
    "AnalyticsKpiEnvelopesRepo",
    "AnalyticsPerformanceRepo",
    "BronzeCtorPerformanceRawPayloadsRepo",
    "BronzeLiveHoursRawPayloadsRepo",
    "BronzeOrderRawPayloadsRepo",
    "BronzeRawPayloadsRepo",
    "BronzeReturnRawPayloadsRepo",
    "CreatorsRepo",
    "GoldKpiEnvelopesRepo",
    "GraphRepo",
    "InventoryRepo",
    "LivestreamsRepo",
    "OrderItemsRepo",
    "OrdersRepo",
    "ProductionWriteAuthorizationsRepo",
    "ProductsRepo",
    "RecommendationsRepo",
    "ReturnsRepo",
    "SessionRepo",
    "SettlementsRepo",
    "ShopScopedRepo",
    "ShopsRepo",
    "TikTokCredentialRepo",
    "TikTokSyncStateRepo",
    "ToolExecutionsRepo",
    "UsersRepo",
    "WebhookRawEventsRepo",
    "WorkflowOutcomeRecordsRepo",
    "WorkflowWebhookSignalsRepo",
    "utc_now_naive",
]
