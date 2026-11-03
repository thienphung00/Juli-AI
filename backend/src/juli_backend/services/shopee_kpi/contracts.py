"""Load a shop's contract KPI appendix from the reference ``kpi.json`` (ADR-117 §4, G7).

Until Juli Ops has a contract form, the appendix lives in
``juli-client-ops/clients/<client>/kpi.json`` and ``scripts/load_kpi_contract.py`` copies
it into ``kpi_contracts`` so the KPI job (:mod:`.job`) can run.

- **Params.** Every key of the file except the reference's local bookkeeping
  (:data:`LOCAL_KEYS`) becomes ``params``; ``measure_start`` gets its own column. The
  terms are validated with :meth:`ContractTerms.from_params` before anything is written.
  A file with ``adjustments`` is refused: an adjustment row needs its own flow / metric /
  confirming email, which the reference shape does not carry.
- **Versions.** Same params and ``measure_start`` as the current version: nothing is
  inserted; status and dates are updated in place (signing does not change the terms).
  Different terms: version n+1 is inserted and n marked ``superseded`` -- never edited --
  and the confirming email is required (G7).

Ops-only tables: everything runs under :func:`ops_role`. Nothing commits here.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.kpi_contracts import (
    CONTRACT_STATUSES,
    CONTRACT_SUPERSEDED,
    KpiContract,
)
from juli_backend.services.ops import ops_role
from juli_backend.services.shopee_kpi.rules import ContractTerms, flows_from_params

#: Reference-file keys that are not contract terms: notes, display strings, the signing
#: date (a column), the reference's own adjustment / achievement logs, and its CSV
#: column map.
LOCAL_KEYS: frozenset[str] = frozenset(
    {
        "_note",
        "client",
        "contract",
        "appendix_signed",
        "measure_start",
        "adjustments",
        "achieved",
        "shop_daily_columns",
    }
)
LOADABLE_STATUSES: tuple[str, ...] = tuple(s for s in CONTRACT_STATUSES if s != CONTRACT_SUPERSEDED)
CONTRACT_REF_MAX = 64

OUTCOME_CREATED = "created"
OUTCOME_NEW_VERSION = "new_version"
OUTCOME_STATUS_UPDATED = "status_updated"
OUTCOME_UNCHANGED = "unchanged"


class ContractFileError(ValueError):
    """The file or the request cannot become a contract version."""


@dataclass(frozen=True)
class ContractFile:
    contract_ref: str
    measure_start: date
    params: dict[str, Any]


@dataclass(frozen=True)
class LoadResult:
    outcome: str
    contract_id: uuid.UUID
    version: int
    superseded_id: uuid.UUID | None = None


def parse_contract_file(doc: Mapping[str, Any], *, contract_ref: str | None = None) -> ContractFile:
    """The reference ``kpi.json`` -> validated contract terms."""
    if doc.get("adjustments"):
        raise ContractFileError("kpi.json has adjustments; the loader does not write them yet")
    raw_start = doc.get("measure_start")
    if not raw_start:
        raise ContractFileError("kpi.json has no measure_start")
    try:
        measure_start = date.fromisoformat(str(raw_start))
    except ValueError as exc:
        raise ContractFileError(f"measure_start is not YYYY-MM-DD: {raw_start!r}") from exc
    ref = (contract_ref or str(doc.get("contract") or "").split(" (")[0]).strip()
    if not ref:
        raise ContractFileError("no contract reference (kpi.json 'contract' or --contract-ref)")
    if len(ref) > CONTRACT_REF_MAX:
        raise ContractFileError(f"contract reference longer than {CONTRACT_REF_MAX} characters")
    # JSON round trip: the params compare equal to what JSONB hands back later.
    params = json.loads(json.dumps({k: v for k, v in doc.items() if k not in LOCAL_KEYS}))
    flows = flows_from_params(params)
    if not flows:
        raise ContractFileError("kpi.json has no flows")
    ContractTerms.from_params(params, measure_start=measure_start, flows=flows)
    return ContractFile(contract_ref=ref, measure_start=measure_start, params=params)


async def load_contract(
    session: AsyncSession,
    shop_id: uuid.UUID,
    contract: ContractFile,
    *,
    status: str,
    sent_on: date | None = None,
    signed_on: date | None = None,
    email_ref: str | None = None,
) -> LoadResult:
    """Insert or update the shop's contract version for ``contract``; see the module doc."""
    if status not in LOADABLE_STATUSES:
        raise ContractFileError(f"status must be one of {', '.join(LOADABLE_STATUSES)}")
    async with ops_role(session):
        same_ref = (KpiContract.shop_id == shop_id) & (
            KpiContract.contract_ref == contract.contract_ref
        )
        current = (
            await session.execute(
                select(KpiContract)
                .where(same_ref, KpiContract.status != CONTRACT_SUPERSEDED)
                .order_by(KpiContract.version.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if current is not None and (
            current.params == contract.params and current.measure_start == contract.measure_start
        ):
            dates = (status, sent_on or current.sent_on, signed_on or current.signed_on)
            if (current.status, current.sent_on, current.signed_on) == dates:
                return LoadResult(OUTCOME_UNCHANGED, current.id, current.version)
            current.status, current.sent_on, current.signed_on = dates
            await session.flush()
            return LoadResult(OUTCOME_STATUS_UPDATED, current.id, current.version)
        if current is not None and not email_ref:
            raise ContractFileError("the terms changed: a new version needs --email-ref (G7)")
        last = (
            await session.execute(select(func.max(KpiContract.version)).where(same_ref))
        ).scalar_one()
        row = KpiContract(
            shop_id=shop_id,
            contract_ref=contract.contract_ref,
            version=(last or 0) + 1,
            status=status,
            sent_on=sent_on,
            signed_on=signed_on,
            measure_start=contract.measure_start,
            params=contract.params,
            email_ref=email_ref,
        )
        if current is not None:
            current.status = CONTRACT_SUPERSEDED
        session.add(row)
        await session.flush()
    if current is None:
        return LoadResult(OUTCOME_CREATED, row.id, row.version)
    return LoadResult(OUTCOME_NEW_VERSION, row.id, row.version, superseded_id=current.id)
