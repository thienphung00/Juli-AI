"""Per-shop settings in Juli Ops: read, change, back to default (D25.4); every change audited."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import decision_emission_config
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ops import STAGE_LABELS, STAGES, OpsShopSettings
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops import overrides as ov
from juli_backend.services.ops.access import ops_role
from juli_backend.services.shop_rules.openai_cap import (
    CapValidationError,
    OpenAICap,
    clear_openai_monthly_cap,
    default_cap_usd,
    openai_monthly_cap_usd,
    set_openai_monthly_cap,
    validate_cap,
)

#: The override columns ("Cài đặt riêng"); NULL = Mặc định.
OVERRIDE_FIELDS: tuple[str, ...] = (
    "card_daily_limit",
    "card_weekly_limit",
    "card_open_limit",
    "enabled_streams",
    "enabled_actions",
    "content_cards_enabled",
    "promotion_api_enabled",
    "openai_model",
    "openai_monthly_cap_usd",
)
#: Stored on ``ops_shop_settings``; the cap lives in ``shop_rules`` (shared with P15).
CAP_FIELD = "openai_monthly_cap_usd"
ROW_FIELDS: tuple[str, ...] = tuple(f for f in OVERRIDE_FIELDS if f != CAP_FIELD)
#: Other settable fields (not "overrides": they have no default to return to).
OTHER_FIELDS: tuple[str, ...] = ("stage",)
LIMIT_RANGE = (1, 100)


class SettingsError(ValueError):
    """An invalid settings value (422)."""


@dataclass(frozen=True)
class ShopSettingsView:
    shop_id: uuid.UUID
    stage: str
    overrides: dict[str, Any]
    defaults: dict[str, Any]
    updated_at: datetime | None

    def to_json(self) -> dict[str, Any]:
        return {
            "shop_id": str(self.shop_id),
            "stage": self.stage,
            "stage_label": STAGE_LABELS.get(self.stage, self.stage),
            "overrides": self.overrides,
            "defaults": self.defaults,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "options": {
                "stages": [{"id": s, "label": STAGE_LABELS[s]} for s in STAGES],
                "streams": [{"id": s, "label": ov.STREAM_LABELS[s]} for s in ov.STREAMS],
                "actions": list(ov.ACTIONS),
                "models": list(ov.allowed_openai_models()),
            },
        }


def defaults() -> dict[str, Any]:
    """What a shop with no override gets (D24.17 limits, every stream and action on…)."""
    config = decision_emission_config()
    return {
        "card_daily_limit": config.daily_new_cap,
        "card_weekly_limit": config.weekly_new_cap,
        "card_open_limit": config.max_open,
        "enabled_streams": list(ov.STREAMS),
        "enabled_actions": list(ov.ACTIONS),
        "content_cards_enabled": True,
        "promotion_api_enabled": False,
        "openai_model": ov.DEFAULT_OPENAI_MODEL,
        "openai_monthly_cap_usd": float(default_cap_usd()),
    }


def _value(row: OpsShopSettings | None, name: str) -> Any:
    if row is None:
        return None
    value = getattr(row, name)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _view(shop_id: uuid.UUID, row: OpsShopSettings | None, cap: OpenAICap) -> ShopSettingsView:
    overrides = {name: _value(row, name) for name in ROW_FIELDS}
    overrides[CAP_FIELD] = None if cap.is_default else float(cap.usd)
    return ShopSettingsView(
        shop_id=shop_id,
        stage=row.stage if row is not None else "trial",
        overrides=overrides,
        defaults=defaults(),
        updated_at=row.updated_at if row is not None else None,
    )


def snapshot(row: OpsShopSettings | None, cap: OpenAICap) -> dict[str, Any]:
    """The audit's before/after picture."""
    data = {} if row is None else {name: _value(row, name) for name in (*ROW_FIELDS, "stage")}
    if row is not None or not cap.is_default:
        data[CAP_FIELD] = None if cap.is_default else float(cap.usd)
    return data


async def _cap(session: AsyncSession, shop_id: uuid.UUID) -> OpenAICap:
    async with with_shop_scope(session, shop_id):
        return await openai_monthly_cap_usd(session, shop_id)


async def get_settings(session: AsyncSession, shop_id: uuid.UUID) -> ShopSettingsView:
    async with ops_role(session):
        row = await session.get(OpsShopSettings, shop_id)
    return _view(shop_id, row, await _cap(session, shop_id))


def _limit(name: str, value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(f"{name} must be a whole number")
    low, high = LIMIT_RANGE
    if not low <= value <= high:
        raise SettingsError(f"{name} must be between {low} and {high}")
    return value


def _subset(name: str, value: Any, allowed: tuple[str, ...]) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SettingsError(f"{name} must be a list of ids")
    unknown = sorted(set(value) - set(allowed))
    if unknown:
        raise SettingsError(f"{name}: unknown {', '.join(unknown)}")
    return [v for v in allowed if v in value]


def _flag(name: str, value: Any) -> bool | None:
    if value is None or isinstance(value, bool):
        return value
    raise SettingsError(f"{name} must be true, false or null")


def _validated(name: str, value: Any) -> Any:
    if name in ("card_daily_limit", "card_weekly_limit", "card_open_limit"):
        return _limit(name, value)
    if name == "enabled_streams":
        return _subset(name, value, ov.STREAMS)
    if name == "enabled_actions":
        return _subset(name, value, ov.ACTIONS)
    if name in ("content_cards_enabled", "promotion_api_enabled"):
        return _flag(name, value)
    if name == "openai_model":
        if value is None:
            return None
        if value not in ov.allowed_openai_models():
            raise SettingsError(
                f"openai_model must be one of {', '.join(ov.allowed_openai_models())}"
            )
        return value
    if name == CAP_FIELD:
        if value is None:
            return None
        try:
            return validate_cap(value)
        except CapValidationError as exc:
            raise SettingsError(str(exc)) from None
    raise SettingsError(f"unknown setting {name!r}")


async def update_settings(
    session: AsyncSession,
    actor: audit.Actor,
    shop_id: uuid.UUID,
    changes: dict[str, Any],
    *,
    now: datetime | None = None,
    action: str = "settings_update",
) -> ShopSettingsView:
    """Apply ``changes`` (a field set to ``None`` goes back to default). Audited."""
    unknown = sorted(set(changes) - set(OVERRIDE_FIELDS) - set(OTHER_FIELDS))
    if unknown:
        raise SettingsError(f"unknown setting(s): {', '.join(unknown)}")
    clean = {
        name: _validated(name, value) for name, value in changes.items() if name in OVERRIDE_FIELDS
    }
    stage = changes.get("stage")
    if "stage" in changes and stage not in STAGES:
        raise SettingsError(f"stage must be one of {', '.join(STAGES)}")
    moment = now or utc_now_naive()
    cap_before = await _cap(session, shop_id)
    cap_after = cap_before
    if CAP_FIELD in clean:
        async with with_shop_scope(session, shop_id):
            if clean[CAP_FIELD] is None:
                await clear_openai_monthly_cap(session, shop_id)
            else:
                await set_openai_monthly_cap(
                    session, shop_id, clean[CAP_FIELD], set_by_user_id=None
                )
            cap_after = await openai_monthly_cap_usd(session, shop_id)
    row_changes = {k: v for k, v in clean.items() if k != CAP_FIELD}
    async with ops_role(session):
        row = await session.get(OpsShopSettings, shop_id)
        before = snapshot(row, cap_before)
        if row is None and (row_changes or isinstance(stage, str)):
            row = OpsShopSettings(shop_id=shop_id, stage="trial")
            session.add(row)
        if row is not None:
            for name, value in row_changes.items():
                setattr(row, name, value)
            if isinstance(stage, str):
                row.stage = stage
            row.updated_at = moment
        after = snapshot(row, cap_after)
    await audit.record(session, actor, action, shop_id=shop_id, before=before, after=after)
    return _view(shop_id, row, cap_after)


async def reset_overrides(
    session: AsyncSession, actor: audit.Actor, shop_id: uuid.UUID
) -> ShopSettingsView:
    """ "Về mặc định": every override back to NULL (stage kept). Audited.

    The OpenAI cap goes back to its default ($5/month) too.
    """
    return await update_settings(
        session,
        actor,
        shop_id,
        {name: None for name in OVERRIDE_FIELDS},
        action="settings_reset",
    )
