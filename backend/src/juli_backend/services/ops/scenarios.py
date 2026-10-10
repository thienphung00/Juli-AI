"""Saved "Mô phỏng" scenarios per shop, one of which may be the shop's target (D25.10)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ops import OpsSimScenario
from juli_backend.repositories._base import utc_now_naive
from juli_backend.services.ops import audit
from juli_backend.services.ops.access import ops_role
from juli_backend.services.ops.simulation import SimulationError, validate_deltas

NAME_MAX = 120


class ScenarioNotFound(LookupError):
    pass


def to_json(row: OpsSimScenario) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "shop_id": str(row.shop_id),
        "name": row.name,
        "deltas": row.deltas,
        "is_target": row.is_target,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _name(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise SimulationError("name is required")
    name = raw.strip()
    if len(name) > NAME_MAX:
        raise SimulationError(f"name is longer than {NAME_MAX} characters")
    return name


async def list_scenarios(session: AsyncSession, shop_id: uuid.UUID) -> list[OpsSimScenario]:
    async with ops_role(session):
        return list(
            (
                await session.execute(
                    select(OpsSimScenario)
                    .where(OpsSimScenario.shop_id == shop_id)
                    .order_by(OpsSimScenario.is_target.desc(), OpsSimScenario.created_at.desc())
                )
            )
            .scalars()
            .all()
        )


async def _get(session: AsyncSession, shop_id: uuid.UUID, scenario_id: uuid.UUID) -> OpsSimScenario:
    row = await session.get(OpsSimScenario, scenario_id)
    if row is None or row.shop_id != shop_id:
        raise ScenarioNotFound(str(scenario_id))
    return row


async def _clear_target(session: AsyncSession, shop_id: uuid.UUID) -> None:
    await session.execute(
        update(OpsSimScenario)
        .where(OpsSimScenario.shop_id == shop_id, OpsSimScenario.is_target.is_(True))
        .values(is_target=False, updated_at=utc_now_naive())
    )
    await session.flush()


async def create_scenario(
    session: AsyncSession,
    actor: audit.Actor,
    shop_id: uuid.UUID,
    *,
    name: Any,
    deltas: Any,
    is_target: bool = False,
) -> OpsSimScenario:
    clean_name = _name(name)
    clean = validate_deltas(deltas)
    async with ops_role(session):
        if is_target:
            await _clear_target(session, shop_id)
        row = OpsSimScenario(
            id=uuid.uuid4(),
            shop_id=shop_id,
            name=clean_name,
            deltas=clean,
            is_target=is_target,
            created_by=actor.staff_id,
        )
        session.add(row)
    await audit.record(session, actor, "scenario_create", shop_id=shop_id, after=to_json(row))
    return row


async def update_scenario(
    session: AsyncSession,
    actor: audit.Actor,
    shop_id: uuid.UUID,
    scenario_id: uuid.UUID,
    *,
    name: Any = None,
    deltas: Any = None,
    is_target: bool | None = None,
) -> OpsSimScenario:
    async with ops_role(session):
        row = await _get(session, shop_id, scenario_id)
        before = to_json(row)
        if name is not None:
            row.name = _name(name)
        if deltas is not None:
            row.deltas = validate_deltas(deltas)
        if is_target is True and not row.is_target:
            await _clear_target(session, shop_id)
            row.is_target = True
        elif is_target is False:
            row.is_target = False
        row.updated_at = utc_now_naive()
    action = "scenario_set_target" if is_target else "scenario_update"
    await audit.record(session, actor, action, shop_id=shop_id, before=before, after=to_json(row))
    return row


async def delete_scenario(
    session: AsyncSession, actor: audit.Actor, shop_id: uuid.UUID, scenario_id: uuid.UUID
) -> None:
    async with ops_role(session):
        row = await _get(session, shop_id, scenario_id)
        before = to_json(row)
        await session.delete(row)
    await audit.record(session, actor, "scenario_delete", shop_id=shop_id, before=before)
