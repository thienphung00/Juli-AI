"""Alerts, recommendations and the persisted Decision rows (ActionCards).

``ActionCardsRepo.upsert`` is keyed by ``workflow_key`` so re-emitting the same
decision is idempotent (ADR-021). The alert and recommendation repos are
append-style: ``create`` rather than ``upsert``, because each row is an event.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select

from juli_backend.models.models import ActionCard, AlertConfig, AlertHistory, Recommendation
from juli_backend.repositories._base import ShopScopedRepo

ACTIVE = "active"


class AlertConfigsRepo(ShopScopedRepo[AlertConfig]):
    _model = AlertConfig

    async def create(self, *, shop_id: uuid.UUID, **values: Any) -> AlertConfig:
        return await self._add(AlertConfig(id=uuid.uuid4(), shop_id=shop_id, **values))

    async def get_by_type(self, shop_id: uuid.UUID, alert_type: str) -> AlertConfig | None:
        return await self._one_or_none(self._scoped(shop_id, AlertConfig.alert_type == alert_type))

    async def list_active(self, shop_id: uuid.UUID) -> list[AlertConfig]:
        return await self._all(self._scoped(shop_id, AlertConfig.is_active.is_(True)))


class AlertHistoryRepo(ShopScopedRepo[AlertHistory]):
    _model = AlertHistory

    async def create(self, *, shop_id: uuid.UUID, **values: Any) -> AlertHistory:
        return await self._add(AlertHistory(id=uuid.uuid4(), shop_id=shop_id, **values))

    async def has_recent_for_type(
        self,
        shop_id: uuid.UUID,
        alert_type: str,
        *,
        since: datetime,
    ) -> bool:
        """Has an alert of ``alert_type`` fired for this shop at or after ``since``?"""
        stmt = (
            select(AlertHistory.id)
            .join(AlertConfig, AlertHistory.alert_config_id == AlertConfig.id)
            .where(
                AlertHistory.shop_id == shop_id,
                AlertConfig.alert_type == alert_type,
                AlertHistory.triggered_at >= since,
            )
        )
        return await self._exists(stmt)


class RecommendationsRepo(ShopScopedRepo[Recommendation]):
    _model = Recommendation

    async def create(self, *, shop_id: uuid.UUID, **values: Any) -> Recommendation:
        return await self._add(Recommendation(id=uuid.uuid4(), shop_id=shop_id, **values))


class ActionCardsRepo(ShopScopedRepo[ActionCard]):
    """Persisted Decision rows; idempotent on ``workflow_key`` (ADR-021)."""

    _model = ActionCard
    _lookup_attrs = ("workflow_key",)

    async def list_active(self, shop_id: uuid.UUID) -> list[ActionCard]:
        """Active cards, highest priority first, newest first within a priority."""
        stmt = self._scoped(shop_id, ActionCard.status == ACTIVE).order_by(
            ActionCard.priority.asc(), ActionCard.created_at.desc()
        )
        return await self._all(stmt)


__all__ = [
    "ACTIVE",
    "ActionCardsRepo",
    "AlertConfigsRepo",
    "AlertHistoryRepo",
    "RecommendationsRepo",
]
