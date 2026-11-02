"""Juli Ops: the Shopee KPI job of a shop (ADR-117 step 3, G6). Internal only.

Mounted beside ``api/routes/ops.py`` under ``/v1/ops`` with the same auth dependencies
(Cloudflare Access → Supabase → active staff row → role) and PII-masking route class.
Contract terms and forecasts are Ops-only (D42 G4); nothing here is reachable from the
seller app.

- ``POST /v1/ops/shops/{id}/shopee-kpi/run`` (Vận hành) -- run the job now: the Phụ lục 01
  table, the milestone forecasts and the CTR / CTOR band, stored in ``kpi_forecasts``.
  Optional ``as_of`` (default: the last day every contract flow has) and ``measure_start``
  (a proposal run on another start date: forecasts only, never targets). Audited
  ``shopee_kpi_run``.
- ``GET  /v1/ops/shops/{id}/shopee-kpi`` (Xem+) -- the KPI table as of now (arithmetic
  over stored rows, nothing written) and the newest run's forecasts.

The service is ``services/shopee_kpi``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.api.routes.ops import MaskedRoute, OpsContext, _shop, operator, viewer
from juli_backend.database import get_session
from juli_backend.services import shopee_kpi
from juli_backend.services.ops import audit

router = APIRouter(prefix="/ops", tags=["ops"], route_class=MaskedRoute)

ACTION_SHOPEE_KPI_RUN = "shopee_kpi_run"


class KpiRunWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date | None = None
    measure_start: date | None = None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _refused(exc: Exception) -> HTTPException:
    if isinstance(exc, shopee_kpi.NoKpiContract):
        return HTTPException(status_code=404, detail={"code": "no_kpi_contract"})
    if isinstance(exc, shopee_kpi.NoMetrics):
        return HTTPException(status_code=409, detail={"code": "no_metrics"})
    if isinstance(exc, shopee_kpi.MeasureStartMissing):
        return HTTPException(status_code=409, detail={"code": "measure_start_missing"})
    return HTTPException(
        status_code=422, detail={"code": "invalid_contract_params", "message": str(exc)}
    )


_REFUSALS = (
    shopee_kpi.NoKpiContract,
    shopee_kpi.NoMetrics,
    shopee_kpi.MeasureStartMissing,
    shopee_kpi.ContractTermsError,
)


@router.post("/shops/{shop_id}/shopee-kpi/run")
async def ops_run_shopee_kpi(
    shop_id: uuid.UUID,
    body: KpiRunWrite | None = None,
    ctx: OpsContext = Depends(operator),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    req = body or KpiRunWrite()
    try:
        result = await shopee_kpi.run_shop_kpi(
            session, shop_id, now=_now(), as_of=req.as_of, measure_start=req.measure_start
        )
    except _REFUSALS as exc:
        await session.rollback()
        raise _refused(exc) from None
    await audit.record(
        session,
        ctx.staff.actor,
        ACTION_SHOPEE_KPI_RUN,
        shop_id=shop_id,
        after={
            "contract_id": str(result.contract_id),
            "as_of": result.as_of.isoformat(),
            "measure_start": result.report.measure_start.isoformat(),
            "forecasts": len(result.forecasts) + len(result.bands),
            "targets_written": result.targets_written,
        },
    )
    await session.commit()
    return {
        "contract_id": str(result.contract_id),
        "run_at": result.run_at.isoformat() + "Z",
        "inputs_sha256": result.inputs_sha256,
        "targets_written": result.targets_written,
        "kpi": result.report.to_json(),
        "forecast_rows": len(result.forecasts) + len(result.bands),
    }


@router.get("/shops/{shop_id}/shopee-kpi")
async def ops_get_shopee_kpi(
    shop_id: uuid.UUID,
    ctx: OpsContext = Depends(viewer),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    await _shop(session, shop_id)
    try:
        contract, report = await shopee_kpi.current_report(session, shop_id)
    except _REFUSALS as exc:
        await session.rollback()
        raise _refused(exc) from None
    rows = await shopee_kpi.latest_forecasts(session, shop_id)
    payload = {
        "contract": {
            "id": str(contract.id),
            "contract_ref": contract.contract_ref,
            "version": contract.version,
            "status": contract.status,
        },
        "kpi": report.to_json(),
        "forecasts": {
            "run_at": rows[0].run_at.isoformat() + "Z" if rows else None,
            "inputs_sha256": rows[0].inputs_sha256 if rows else None,
            "rows": [shopee_kpi.forecast_json(r) for r in rows],
        },
    }
    await session.commit()
    return payload
