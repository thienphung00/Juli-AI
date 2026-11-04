"""What the Demo (seller) and Ops routes of the Shopee recommendation cards share: request
bodies and the mapping from the services' refusals to HTTP errors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from juli_backend.services.shop_proposals import ProposalError


class WhatIfBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict)
    #: P91: the version the inputs move (1-based; omitted = version 1); only it is recomputed
    version: int | None = Field(default=None, ge=1, le=4)


class ApproveBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] | None = None
    #: P91: which version of the card is approved (recorded on the decision and the events)
    chosen_version: int = Field(default=1, ge=1, le=4)
    note: str | None = Field(default=None, max_length=2000)


class RequestChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str = Field(min_length=1, max_length=2000)


class DismissBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: ADR-107 decision 5; omitted = ``unspecified``
    reason_code: str | None = Field(default=None, max_length=32)
    note: str | None = Field(default=None, max_length=2000)


class ExecutedBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    executed_at: datetime | None = None
    #: the voucher's id in Seller Centre after creating it (needed to read the voucher back)
    voucher_id: str | None = Field(default=None, max_length=64)
    evidence_ref: str | None = Field(default=None, max_length=500)


def refused(exc: ProposalError) -> HTTPException:
    return HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.detail or exc.code}
    )
