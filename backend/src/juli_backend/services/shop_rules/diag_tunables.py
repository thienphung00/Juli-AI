"""Per-shop D29 tunables (D29.11): one team-set ``shop_rules`` row, no migration.

ONE storage for every reader, like the OpenAI cap (``openai_cap``): a
``shop_rules`` row with ``rule_key = "diag_tunables"`` (shop-wide, ``scope_ref =
''``), value a JSON object holding only the keys an Ops Admin overrode
(``diag_windows``, ``diag_min_events``, ``kpi_min_band_mult``,
``kpi_max_band_mult``, ``guard_band_mult``, ``volatile_cv``). No row = every
default (``optimize_product.tunables.DiagTunables``).

It is a TEAM setting: deliberately NOT in ``rules.RULE_KEYS``, so the seller's
``/v1/demo/rules`` refuses it; Juli Ops "Cài đặt shop" writes it (audited)
through ``services.ops.settings``. The nightly card pipeline and the
measurement read it through :func:`diag_tunables`, under the shop's own scope.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.run_changes import ShopRule
from juli_backend.services.optimize_product.tunables import (
    TUNABLE_KEYS,
    DiagTunables,
    validate_tunable,
)

DIAG_TUNABLES = "diag_tunables"


async def _row(session: AsyncSession, shop_id: uuid.UUID) -> ShopRule | None:
    return (
        await session.execute(
            select(ShopRule).where(
                ShopRule.shop_id == shop_id,
                ShopRule.rule_key == DIAG_TUNABLES,
                ShopRule.scope_ref == "",
            )
        )
    ).scalar_one_or_none()


async def tunable_overrides(session: AsyncSession, shop_id: uuid.UUID) -> dict[str, Any]:
    """The stored overrides (only the valid ones); ``{}`` when none. Caller holds the scope."""
    row = await _row(session, shop_id)
    if row is None or not isinstance(row.value, dict):
        return {}
    out: dict[str, Any] = {}
    for key in TUNABLE_KEYS:
        if row.value.get(key) is None:
            continue
        try:
            out[key] = validate_tunable(key, row.value[key])
        except ValueError:
            continue
    return out


async def diag_tunables(session: AsyncSession, shop_id: uuid.UUID) -> DiagTunables:
    """The shop's D29 tunables: defaults with its overrides applied."""
    return DiagTunables.from_overrides(await tunable_overrides(session, shop_id))


async def set_tunable_overrides(
    session: AsyncSession,
    shop_id: uuid.UUID,
    changes: dict[str, Any],
) -> dict[str, Any]:
    """Apply validated ``changes`` (``None`` = back to default); returns the stored overrides.

    The caller validates (``validate_tunable``) and audits. The row is removed
    when no override is left.
    """
    row = await _row(session, shop_id)
    stored = row.value if row is not None else None
    current: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
    for key, value in changes.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value
    if not current:
        if row is not None:
            await session.delete(row)
            await session.flush()
        return {}
    now = datetime.now(UTC).replace(tzinfo=None)
    if row is None:
        session.add(
            ShopRule(
                shop_id=shop_id,
                rule_key=DIAG_TUNABLES,
                scope_ref="",
                value=current,
                set_by="team",
                set_by_user_id=None,
                set_at=now,
            )
        )
    else:
        row.value = current
        row.set_by = "team"
        row.set_at = now
    await session.flush()
    return current


__all__ = ["DIAG_TUNABLES", "diag_tunables", "set_tunable_overrides", "tunable_overrides"]
