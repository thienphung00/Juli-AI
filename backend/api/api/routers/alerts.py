import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.integrations.catalog.domain.alerts import RuleConfigInput, configure_rules
from backend.api.api.dependencies import get_active_shop
from backend.database import AlertConfigsRepo, AlertHistoryRepo, Shop, get_session
from backend.database.models import AlertConfig, AlertHistory

router = APIRouter(prefix="/alerts", tags=["alerts"])


class AlertHistoryItem(BaseModel):
    id: uuid.UUID
    alert_type: str
    channel: str
    triggered_at: datetime
    status: str
    payload: dict | None = None

    model_config = {"from_attributes": True}


class PaginatedAlertHistory(BaseModel):
    items: list[AlertHistoryItem]
    next_cursor: str | None = None


class RuleConfigBody(BaseModel):
    alert_type: str
    channel: str = "fcm"
    is_active: bool = True
    threshold: dict | None = None
    cooldown_seconds: int = 3600


class AlertConfigRequest(BaseModel):
    rules: list[RuleConfigBody] = Field(min_length=1)


class AlertConfigRuleResponse(BaseModel):
    id: uuid.UUID
    alert_type: str
    channel: str
    is_active: bool
    threshold: dict | None = None


class AlertConfigResponse(BaseModel):
    rules: list[AlertConfigRuleResponse]


@router.get("/history", response_model=PaginatedAlertHistory)
async def list_alert_history(
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=50, ge=1, le=200),
    after: uuid.UUID | None = Query(default=None),
) -> PaginatedAlertHistory:
    """Return paginated alert history for the active shop."""
    repo = AlertHistoryRepo(session)
    rows = await repo.list(shop.id, limit=limit + 1, after=after)

    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = str(page[-1].id) if has_more and page else None

    config_repo = AlertConfigsRepo(session)
    config_cache: dict[uuid.UUID, AlertConfig] = {}

    items: list[AlertHistoryItem] = []
    for row in page:
        config = config_cache.get(row.alert_config_id)
        if config is None:
            config = await config_repo.get(shop.id, row.alert_config_id)
            config_cache[row.alert_config_id] = config
        items.append(_history_to_response(row, config))

    return PaginatedAlertHistory(items=items, next_cursor=next_cursor)


@router.put("/config", response_model=AlertConfigResponse)
async def upsert_alert_config(
    body: AlertConfigRequest,
    shop: Shop = Depends(get_active_shop),
    session: AsyncSession = Depends(get_session),
) -> AlertConfigResponse:
    """Create or update per-shop alert rules and thresholds."""
    inputs = [
        RuleConfigInput(
            alert_type=rule.alert_type,
            channel=rule.channel,
            is_active=rule.is_active,
            threshold=rule.threshold,
            cooldown_seconds=rule.cooldown_seconds,
        )
        for rule in body.rules
    ]
    saved = await configure_rules(session, shop.id, inputs)
    return AlertConfigResponse(rules=[_config_to_response(c) for c in saved])


def _history_to_response(
    row: AlertHistory, config: AlertConfig
) -> AlertHistoryItem:
    payload: dict | None = None
    if row.payload:
        try:
            payload = json.loads(row.payload)
        except json.JSONDecodeError:
            payload = {"raw": row.payload}
    return AlertHistoryItem(
        id=row.id,
        alert_type=config.alert_type,
        channel=config.channel,
        triggered_at=row.triggered_at,
        status=row.status,
        payload=payload,
    )


def _config_to_response(config: AlertConfig) -> AlertConfigRuleResponse:
    threshold: dict | None = None
    if config.threshold_json:
        try:
            threshold = json.loads(config.threshold_json)
        except json.JSONDecodeError:
            threshold = None
    return AlertConfigRuleResponse(
        id=config.id,
        alert_type=config.alert_type,
        channel=config.channel,
        is_active=config.is_active,
        threshold=threshold,
    )
