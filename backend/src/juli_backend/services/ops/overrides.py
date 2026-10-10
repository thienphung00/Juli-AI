"""Per-shop overrides set in Juli Ops, as the seller / worker paths read them (D25.4, D25.8).

``ops_shop_settings`` holds one row per shop; a NULL column means "Mặc định".
The seller-facing code runs as ``juli_app`` under the shop's scope and has no
grant on that table, so it reads its OWN shop's row through the SECURITY
DEFINER function ``ops_current_shop_overrides()`` (migration 083), which only
ever returns the row of ``app_current_shop_id()``. On SQLite (unit tests) the
table is read directly.

With no row -- or when the read fails -- every accessor returns the default,
so a shop nobody configured behaves exactly as before P16.

Who reads what:

- card limits → ``services/action_cards/emission_budget.py`` (daily / weekly /
  open; the seller's own "Số thẻ mở cùng lúc" can still only lower the open cap);
- enabled streams / actions, content cards on/off → the same budget suppresses
  a draft whose stream or action is off (reason ``ops_disabled``), and
  ``content_cards.emission`` writes no content card for an off stream;
- OpenAI model → content drafting (``content_cards.planner``) and agent runs
  (``workers/tasks/agent_workflow``);
- monthly OpenAI cap (a ``shop_rules`` row shared with P15, default $5, see
  ``services/shop_rules/openai_cap.py``) → content drafting and agent runs
  (Optimize Product) stop for the shop when the month's ``workflow_runs.cost_usd``
  reaches it (``openai_cap_status``); rule cards are not affected. The overview
  shows a badge and the gate logs ``ops_openai_cap_reached`` (the team alert).
- promotion API on/off → :func:`promotion_api_enabled`. Juli makes no promotion
  write today (D13: the seller applies promotions in Seller Center), so it is
  stored, shown and audited, and gates nothing yet (DEBT).
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import DecisionEmissionConfig
from juli_backend.models.ops import STAGE_TRIAL, OpsShopSettings
from juli_backend.services.agent.llm.config import LLMConfig
from juli_backend.services.ops.access import is_sqlite

logger = logging.getLogger(__name__)

#: The four seller streams (``services/shop_diagnosis/channels.Channel`` values).
STREAM_PRODUCT_CARD = "product_card"
STREAM_SHOP_TAB = "shop_tab"
STREAM_VIDEO = "seller_video"
STREAM_LIVE = "seller_live"
STREAMS: tuple[str, ...] = (STREAM_PRODUCT_CARD, STREAM_SHOP_TAB, STREAM_VIDEO, STREAM_LIVE)
STREAM_LABELS: dict[str, str] = {
    STREAM_PRODUCT_CARD: "Thẻ SP",
    STREAM_SHOP_TAB: "Tab",
    STREAM_VIDEO: "Video",
    STREAM_LIVE: "LIVE",
}

#: The actions ("Hành động") a card can carry: the seven product levers
#: (``optimize_product.decision_cards.LEVER_CODES``) and the two content ones.
PRODUCT_ACTIONS: tuple[str, ...] = (
    "cover_image",
    "title",
    "description",
    "product_discount",
    "buy_more_save_more",
    "flash_sale",
    "shipping_discount",
)
CONTENT_ACTIONS: tuple[str, ...] = ("video_script", "live_script")
ACTIONS: tuple[str, ...] = PRODUCT_ACTIONS + CONTENT_ACTIONS

#: content workflow key → (stream, action)
CONTENT_KINDS: dict[str, tuple[str, str]] = {
    "content_video": (STREAM_VIDEO, "video_script"),
    "content_live": (STREAM_LIVE, "live_script"),
}

#: The default drafting model (``services/agent/llm/config.DEFAULT_MODEL``).
DEFAULT_OPENAI_MODEL = "gpt-5.4-nano"


def allowed_openai_models() -> tuple[str, ...]:
    """Models an override may name: only PRICED ones, or the monthly cap could not
    count their cost (``estimate_cost_usd`` is 0 for an unpriced model)."""
    from juli_backend.services.agent.llm.config import PRICE_TABLE_USD_PER_MILLION_TOKENS

    return tuple(sorted(PRICE_TABLE_USD_PER_MILLION_TOKENS))


#: The shop's clock (UTC+7) for "this month".
SHOP_UTC_OFFSET = timedelta(hours=7)


@dataclass(frozen=True)
class ShopOverrides:
    """One shop's overrides; ``None`` = the default."""

    stage: str = STAGE_TRIAL
    card_daily_limit: int | None = None
    card_weekly_limit: int | None = None
    card_open_limit: int | None = None
    enabled_streams: frozenset[str] | None = None
    enabled_actions: frozenset[str] | None = None
    content_cards_enabled: bool | None = None
    promotion_api_enabled: bool | None = None
    openai_model: str | None = None


DEFAULT_OVERRIDES = ShopOverrides()


def _as_set(value: Any) -> frozenset[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None
    if not isinstance(value, list):
        return None
    return frozenset(str(item) for item in value)


def from_row(row: OpsShopSettings | None) -> ShopOverrides:
    if row is None:
        return DEFAULT_OVERRIDES
    return ShopOverrides(
        stage=row.stage or STAGE_TRIAL,
        card_daily_limit=row.card_daily_limit,
        card_weekly_limit=row.card_weekly_limit,
        card_open_limit=row.card_open_limit,
        enabled_streams=_as_set(row.enabled_streams),
        enabled_actions=_as_set(row.enabled_actions),
        content_cards_enabled=row.content_cards_enabled,
        promotion_api_enabled=row.promotion_api_enabled,
        openai_model=row.openai_model,
    )


async def shop_overrides(session: AsyncSession, shop_id: uuid.UUID) -> ShopOverrides:
    """The shop's overrides as its own scope may see them; defaults on any doubt."""
    if is_sqlite(session):
        row = await session.get(OpsShopSettings, shop_id)
        return from_row(row)
    try:
        async with session.begin_nested():
            result = (
                (await session.execute(text("SELECT * FROM public.ops_current_shop_overrides()")))
                .mappings()
                .first()
            )
    except SQLAlchemyError:  # defaults are the safe answer; logged
        logger.warning("ops_overrides_read_failed", extra={"shop_id": str(shop_id)}, exc_info=True)
        return DEFAULT_OVERRIDES
    if result is None or result["out_shop_id"] != shop_id:
        return DEFAULT_OVERRIDES
    return ShopOverrides(
        stage=result["out_stage"] or STAGE_TRIAL,
        card_daily_limit=result["out_card_daily_limit"],
        card_weekly_limit=result["out_card_weekly_limit"],
        card_open_limit=result["out_card_open_limit"],
        enabled_streams=_as_set(result["out_enabled_streams"]),
        enabled_actions=_as_set(result["out_enabled_actions"]),
        content_cards_enabled=result["out_content_cards_enabled"],
        promotion_api_enabled=result["out_promotion_api_enabled"],
        openai_model=result["out_openai_model"],
    )


# -- what each consumer asks ---------------------------------------------------


def emission_limits(
    config: DecisionEmissionConfig, overrides: ShopOverrides
) -> DecisionEmissionConfig:
    """D24.17 limits with the shop's overrides applied (may raise or lower)."""
    if overrides.card_daily_limit is not None:
        config = replace(config, daily_new_cap=overrides.card_daily_limit)
    if overrides.card_weekly_limit is not None:
        config = replace(config, weekly_new_cap=overrides.card_weekly_limit)
    if overrides.card_open_limit is not None:
        config = replace(config, max_open=overrides.card_open_limit)
    return config


def stream_enabled(overrides: ShopOverrides, stream: str) -> bool:
    return overrides.enabled_streams is None or stream in overrides.enabled_streams


def action_enabled(overrides: ShopOverrides, action: str | None) -> bool:
    if action is None or overrides.enabled_actions is None:
        return True
    return action in overrides.enabled_actions


def content_kind_enabled(overrides: ShopOverrides, workflow_key: str) -> bool:
    """A content card kind (``content_video`` / ``content_live``) may be proposed."""
    if overrides.content_cards_enabled is False:
        return False
    stream, action = CONTENT_KINDS.get(workflow_key, (None, None))
    if stream is None:
        return True
    return stream_enabled(overrides, stream) and action_enabled(overrides, action)


def product_card_enabled(overrides: ShopOverrides, lever: str | None) -> bool:
    """An Optimize Product card may be proposed: its action is on and a product stream is."""
    product_stream_on = stream_enabled(overrides, STREAM_PRODUCT_CARD) or stream_enabled(
        overrides, STREAM_SHOP_TAB
    )
    return product_stream_on and action_enabled(overrides, lever)


def promotion_api_enabled(overrides: ShopOverrides) -> bool:
    """Default OFF: Juli may create promotions itself only when Ops turns it on."""
    return overrides.promotion_api_enabled is True


def openai_model(overrides: ShopOverrides) -> str:
    return overrides.openai_model or DEFAULT_OPENAI_MODEL


async def llm_config_for(session: AsyncSession, shop_id: uuid.UUID) -> LLMConfig:
    """The agent runner's ``LLMConfig`` with the shop's model override (P16)."""
    current = await shop_overrides(session, shop_id)
    config = LLMConfig()
    return replace(config, model=current.openai_model) if current.openai_model else config


# -- the monthly OpenAI cap (D25.8) ----------------------------------------------


@dataclass(frozen=True)
class CapStatus:
    cap_usd: Decimal
    is_default: bool
    spent_usd: Decimal
    reached: bool


def month_start_utc(now: datetime | None = None) -> datetime:
    """The first instant of the shop's (UTC+7) current month, as naive UTC."""
    current = (now or datetime.now(UTC)).astimezone(UTC) + SHOP_UTC_OFFSET
    local_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (local_start - SHOP_UTC_OFFSET).replace(tzinfo=None)


async def openai_cost_this_month(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> Decimal:
    """Sum of the month's ``workflow_runs.cost_usd`` (content drafts + agent runs)."""
    from juli_backend.models.models import WorkflowRun

    start = month_start_utc(now)
    total = (
        await session.execute(
            select(func.coalesce(func.sum(WorkflowRun.cost_usd), 0)).where(
                WorkflowRun.shop_id == shop_id, WorkflowRun.created_at >= start
            )
        )
    ).scalar_one()
    return Decimal(str(total or 0))


async def openai_cap_status(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    overrides: ShopOverrides | None = None,
    now: datetime | None = None,
) -> CapStatus:
    """Spent this month vs the shop's cap (``shop_rules`` row shared with P15, $5 default)."""
    from juli_backend.services.shop_rules.openai_cap import openai_monthly_cap_usd

    del overrides  # the cap is not an ops_shop_settings column (shared with P15)
    cap = await openai_monthly_cap_usd(session, shop_id)
    spent = await openai_cost_this_month(session, shop_id, now=now)
    return CapStatus(
        cap_usd=cap.usd, is_default=cap.is_default, spent_usd=spent, reached=spent >= cap.usd
    )


class CapGuardedLLMService:
    """D25.8 for agent runs (Optimize Product): refuse the model call over the cap.

    Wraps the run's ``LLMService``; when the shop's month has reached its cap
    every ``complete`` raises ``LLMProviderError`` before any request, so the
    runner ends the run its usual way (``failed`` / ``llm_error``) without
    spending. Logged ``ops_openai_cap_reached`` (the team alert).
    """

    def __init__(self, inner: Any, cap: CapStatus, shop_id: uuid.UUID) -> None:
        self._inner = inner
        self._cap = cap
        self._shop_id = shop_id

    async def complete(self, **kwargs: Any) -> Any:
        if self._cap.reached:
            from juli_backend.services.agent.llm.openai_adapter import LLMProviderError

            logger.warning(
                "ops_openai_cap_reached",
                extra={
                    "shop_id": str(self._shop_id),
                    "spent_usd": float(self._cap.spent_usd),
                    "cap_usd": float(self._cap.cap_usd),
                    "path": "agent_run",
                },
            )
            raise LLMProviderError("monthly OpenAI cap reached for this shop")
        return await self._inner.complete(**kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


async def cap_guarded(session: AsyncSession, shop_id: uuid.UUID, inner: Any) -> Any:
    return CapGuardedLLMService(inner, await openai_cap_status(session, shop_id), shop_id)
