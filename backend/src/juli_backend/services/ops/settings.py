"""Per-shop settings in Juli Ops: read, change, back to default (D25.4); every change audited."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.config import decision_emission_config
from juli_backend.database.tenant_context import with_shop_scope
from juli_backend.models.ops import STAGE_LABELS, STAGES, OpsShopSettings
from juli_backend.models.run_changes import ShopRule
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops import overrides as ov
from juli_backend.services.ops.access import ops_role
from juli_backend.services.optimize_product.tunables import (
    TUNABLE_KEYS,
    DiagTunables,
    TunableError,
    validate_tunable,
)
from juli_backend.services.shop_rules.diag_tunables import (
    DIAG_TUNABLES,
    overrides_from_row,
    set_tunable_overrides,
)
from juli_backend.services.shop_rules.openai_cap import (
    OPENAI_MONTHLY_CAP_USD,
    CapValidationError,
    OpenAICap,
    cap_from_row,
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
    # D29.11 (P23): the diagnosis / KPI tunables, Admin-only.
    *TUNABLE_KEYS,
)
#: Stored on ``ops_shop_settings``; the cap lives in ``shop_rules`` (shared with P15).
CAP_FIELD = "openai_monthly_cap_usd"
#: D29.11: stored in one team ``shop_rules`` row (``shop_rules.diag_tunables``), no
#: migration; only an Admin may change them (``ADMIN_ONLY_FIELDS``).
TUNABLE_FIELDS: tuple[str, ...] = TUNABLE_KEYS
ADMIN_ONLY_FIELDS: frozenset[str] = frozenset(TUNABLE_KEYS)
ROW_FIELDS: tuple[str, ...] = tuple(
    f for f in OVERRIDE_FIELDS if f != CAP_FIELD and f not in TUNABLE_FIELDS
)
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
        **DiagTunables().to_json(),
    }


def _value(row: OpsShopSettings | None, name: str) -> Any:
    if row is None:
        return None
    value = getattr(row, name)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _view(
    shop_id: uuid.UUID,
    row: OpsShopSettings | None,
    cap: OpenAICap,
    tunables: dict[str, Any] | None = None,
) -> ShopSettingsView:
    overrides = {name: _value(row, name) for name in ROW_FIELDS}
    overrides[CAP_FIELD] = None if cap.is_default else float(cap.usd)
    for name in TUNABLE_FIELDS:
        overrides[name] = (tunables or {}).get(name)
    return ShopSettingsView(
        shop_id=shop_id,
        stage=row.stage if row is not None else "trial",
        overrides=overrides,
        defaults=defaults(),
        updated_at=row.updated_at if row is not None else None,
    )


def snapshot(
    row: OpsShopSettings | None, cap: OpenAICap, tunables: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Every settable key's stored value (``None`` = Mặc định); the audit diffs two."""
    data = {name: _value(row, name) for name in ROW_FIELDS}
    data["stage"] = row.stage if row is not None else "trial"
    data[CAP_FIELD] = None if cap.is_default else float(cap.usd)
    for name in TUNABLE_FIELDS:
        data[name] = (tunables or {}).get(name)
    return data


async def _cap(
    session: AsyncSession, shop_id: uuid.UUID, *, restore_role: str | None = None
) -> OpenAICap:
    async with with_shop_scope(session, shop_id, restore_role=restore_role):
        return await openai_monthly_cap_usd(session, shop_id)


# -- the cap + tunables cache (P29) -------------------------------------------------
#
# The settings and simulation pages read the shop's two team ``shop_rules`` rows
# (the OpenAI cap, the D29 tunables) under the shop's scope: the scope's GUC
# statement plus the read, ~0.8 s from the VPS, for values only Ops changes.
# Cached per process for CAP_CACHE_TTL_SECONDS, keyed by shop id -- one shop's
# entry is only ever served for that shop, and only to an Ops route that has
# already passed the staff gate (every staff member may see every shop).
#
# Invalidation: the only writer of either row is :func:`update_settings` (PUT
# settings, "Về mặc định", PUT openai-cap), which forgets the shop's entry
# before it writes; the routes forget it again after their COMMIT, so a read
# racing the write cannot re-cache the old value for longer than that window.
# The enforcement paths (the cap gate, the diagnosis) never read this cache.
# The API runs one process; were it more, another process's entry would lag a
# change by at most the TTL.

CAP_CACHE_TTL_SECONDS = 30.0

_cap_cache: dict[uuid.UUID, tuple[float, OpenAICap, dict[str, Any]]] = {}
_cap_cache_lock = threading.Lock()


def cached_cap_and_tunables(shop_id: uuid.UUID) -> tuple[OpenAICap, dict[str, Any]] | None:
    """This shop's cap and tunables if read in the last 30 s (a copy), else None."""
    with _cap_cache_lock:
        hit = _cap_cache.get(shop_id)
        if hit is None:
            return None
        stored_at, cap, tunables = hit
        if time.monotonic() - stored_at > CAP_CACHE_TTL_SECONDS:
            del _cap_cache[shop_id]
            return None
        return cap, dict(tunables)


def _remember_cap_and_tunables(
    shop_id: uuid.UUID, cap: OpenAICap, tunables: dict[str, Any]
) -> None:
    with _cap_cache_lock:
        _cap_cache[shop_id] = (time.monotonic(), cap, dict(tunables))


def forget_cap_and_tunables(shop_id: uuid.UUID | None = None) -> None:
    """Drop one shop's cached cap/tunables (every shop when ``None``: tests)."""
    with _cap_cache_lock:
        if shop_id is None:
            _cap_cache.clear()
        else:
            _cap_cache.pop(shop_id, None)


async def cap_and_tunables(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    restore_role: str | None = None,
    transaction_ends_after: bool = False,
) -> tuple[OpenAICap, dict[str, Any], bool]:
    """The cached pair, else :func:`_cap_and_tunables` (and cache it).

    The third value says whether ``restore_role`` was used: on a cache hit no
    statement ran, so a caller that handed over an ``ops_role`` restore still
    owns it (or, when its transaction ends next, may simply drop it).
    """
    hit = cached_cap_and_tunables(shop_id)
    if hit is not None:
        return hit[0], hit[1], False
    cap, tunables = await _cap_and_tunables(
        session,
        shop_id,
        restore_role=restore_role,
        transaction_ends_after=transaction_ends_after,
    )
    _remember_cap_and_tunables(shop_id, cap, tunables)
    return cap, tunables, True


async def _cap_and_tunables(
    session: AsyncSession,
    shop_id: uuid.UUID,
    *,
    restore_role: str | None = None,
    transaction_ends_after: bool = False,
) -> tuple[OpenAICap, dict[str, Any]]:
    """Both team ``shop_rules`` rows in ONE statement, under one shop scope."""
    async with with_shop_scope(
        session,
        shop_id,
        restore_role=restore_role,
        transaction_ends_after=transaction_ends_after,
    ):
        return await _read_cap_and_tunables(session, shop_id)


async def _read_cap_and_tunables(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[OpenAICap, dict[str, Any]]:
    """The one-statement read itself; the caller holds the shop's scope."""
    rows = (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key.in_((OPENAI_MONTHLY_CAP_USD, DIAG_TUNABLES)),
                ShopRule.scope_ref == "",
            )
        )
    ).scalars()
    by_key = {row.rule_key: row for row in rows}
    return cap_from_row(by_key.get(OPENAI_MONTHLY_CAP_USD)), overrides_from_row(
        by_key.get(DIAG_TUNABLES)
    )


async def cap_and_tunables_in_scope(
    session: AsyncSession, shop_id: uuid.UUID
) -> tuple[OpenAICap, dict[str, Any]]:
    """The cached pair, else the read (and cache it); the caller holds the shop's scope."""
    hit = cached_cap_and_tunables(shop_id)
    if hit is not None:
        return hit
    cap, tunables = await _read_cap_and_tunables(session, shop_id)
    _remember_cap_and_tunables(shop_id, cap, tunables)
    return cap, tunables


async def get_settings(session: AsyncSession, shop_id: uuid.UUID) -> ShopSettingsView:
    return await view_of(session, shop_id, await settings_row(session, shop_id))


async def settings_row(session: AsyncSession, shop_id: uuid.UUID) -> OpsShopSettings | None:
    """The shop's ``ops_shop_settings`` row (an ops read; free inside an open ops block)."""
    async with ops_role(session):
        return await session.get(OpsShopSettings, shop_id)


async def view_of(
    session: AsyncSession,
    shop_id: uuid.UUID,
    row: OpsShopSettings | None,
    *,
    restore_role: str | None = None,
) -> ShopSettingsView:
    """The settings view from an already-read row plus the cap (read under the shop's scope).

    Split from :func:`get_settings` (P22) so a route can read the row inside the
    ops block it already holds and pay for one role switch, not two;
    ``restore_role`` is that block's handed-over restore (``OpsRoleBlock``).
    """
    cap, tunables = await _cap_and_tunables(session, shop_id, restore_role=restore_role)
    return view_from(shop_id, row, cap, tunables)


def view_from(
    shop_id: uuid.UUID,
    row: OpsShopSettings | None,
    cap: OpenAICap,
    tunables: dict[str, Any] | None = None,
) -> ShopSettingsView:
    """The settings view from a row and a cap (and D29 tunables) the caller already read."""
    return _view(shop_id, row, cap, tunables)


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
    if name in TUNABLE_FIELDS:
        if value is None:
            return None
        try:
            return validate_tunable(name, value)
        except TunableError as exc:
            raise SettingsError(str(exc)) from None
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
    # P29: before the write; the route forgets it again after its COMMIT.
    forget_cap_and_tunables(shop_id)
    cap_before, tunables_before = await _cap_and_tunables(session, shop_id)
    cap_after, tunables_after = cap_before, tunables_before
    tunable_changes = {k: v for k, v in clean.items() if k in TUNABLE_FIELDS}
    if tunable_changes:
        merged = {**tunables_before, **{k: v for k, v in tunable_changes.items()}}
        low = merged.get("kpi_min_band_mult", DiagTunables().kpi_min_band_mult)
        high = merged.get("kpi_max_band_mult", DiagTunables().kpi_max_band_mult)
        if high is not None and low is not None and high < low:
            raise SettingsError("kpi_max_band_mult must be ≥ kpi_min_band_mult")
        async with with_shop_scope(session, shop_id):
            tunables_after = await set_tunable_overrides(session, shop_id, tunable_changes)
    if CAP_FIELD in clean:
        async with with_shop_scope(session, shop_id):
            if clean[CAP_FIELD] is None:
                await clear_openai_monthly_cap(session, shop_id)
            else:
                await set_openai_monthly_cap(
                    session, shop_id, clean[CAP_FIELD], set_by_user_id=None
                )
            cap_after = await openai_monthly_cap_usd(session, shop_id)
    row_changes = {k: v for k, v in clean.items() if k != CAP_FIELD and k not in TUNABLE_FIELDS}
    async with ops_role(session):
        row = await session.get(OpsShopSettings, shop_id)
        before = snapshot(row, cap_before, tunables_before)
        if row is None and (row_changes or isinstance(stage, str)):
            row = OpsShopSettings(shop_id=shop_id, stage="trial")
            session.add(row)
        if row is not None:
            for name, value in row_changes.items():
                setattr(row, name, value)
            if isinstance(stage, str):
                row.stage = stage
            row.updated_at = moment
        after = snapshot(row, cap_after, tunables_after)
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    if changed:
        # D27.5/27.6: one save = one row listing every changed key; a save of a
        # single key names it, so repeated edits of it within 10 minutes merge.
        await audit.record(
            session,
            actor,
            action,
            shop_id=shop_id,
            before={k: before.get(k) for k in changed},
            after={k: after.get(k) for k in changed},
            field=changed[0] if len(changed) == 1 else None,
        )
    return _view(shop_id, row, cap_after, tunables_after)


async def reset_overrides(
    session: AsyncSession,
    actor: audit.Actor,
    shop_id: uuid.UUID,
    *,
    include_admin_fields: bool = True,
) -> ShopSettingsView:
    """ "Về mặc định": every override back to NULL (stage kept). Audited.

    The OpenAI cap goes back to its default ($5/month) too. The D29 tunables
    (Admin-only) are reset only when ``include_admin_fields``.
    """
    return await update_settings(
        session,
        actor,
        shop_id,
        {
            name: None
            for name in OVERRIDE_FIELDS
            if include_admin_fields or name not in ADMIN_ONLY_FIELDS
        },
        action="settings_reset",
    )
