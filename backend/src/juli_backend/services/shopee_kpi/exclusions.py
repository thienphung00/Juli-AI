"""The days a shop's contract leaves out of every comparison (Phụ lục 01, Mục 2.5).

Other readers of the daily metrics (proposal results, ADR-118) must drop the same sale
days as the KPI job. The rule stays in ``rules.excluded_days``; this only builds its
input from the shop's current contract, or from ``PARAM_DEFAULTS`` when the shop has none.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.kpi_contracts import KpiExclusion
from juli_backend.services.ops import ops_role
from juli_backend.services.shopee_kpi import job
from juli_backend.services.shopee_kpi.rules import ContractTerms, FlowSpec, excluded_days

# ``from_params`` insists on pass / target and a flow; exclusions use neither.
_STAND_IN_FLOWS = (FlowSpec(flow="the_san_pham", metrics=("ctr",)),)


async def contract_excluded_days(
    session: AsyncSession, shop_id: uuid.UUID, first: date, last: date
) -> frozenset[date]:
    """``sale_days`` ± ``pad_days`` plus the contract's extra days, within [first, last]."""
    params: dict[str, Any] = {"pass": 0, "target": 0}
    extra: list[date] = []
    try:
        contract = await job.current_contract(session, shop_id)
    except job.NoKpiContract:
        pass
    else:
        params["exclusions"] = (contract.params or {}).get("exclusions")
        async with ops_role(session):
            extra = list(
                (
                    await session.execute(
                        select(KpiExclusion.day).where(KpiExclusion.contract_id == contract.id)
                    )
                ).scalars()
            )
    terms = ContractTerms.from_params(
        params, measure_start=first, flows=_STAND_IN_FLOWS, extra_excluded=extra
    )
    return excluded_days(terms, first, last)
