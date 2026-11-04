"""Request bodies shared by the Ops and Demo routes of the draft plan, the aggregate, the
measurement window and the change sets (P91 D-6, D-7, D-8)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from juli_backend.services.shopee_recommendations import config, plans

MAX_INPUT_KEYS = 24
MAX_MONEY = 2_000_000_000


class AddCardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    card_id: uuid.UUID
    #: the version that goes into the plan (1-based)
    chosen_version: int = Field(default=1, ge=1, le=config.MAX_VERSIONS)
    #: a floor / spend-cap breach never blocks: it must be acknowledged (else 422 with the list)
    acknowledge_breaches: bool = False


class SwitchVersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, le=config.MAX_VERSIONS)


class PlanWhatIfBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict, max_length=MAX_INPUT_KEYS)


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledge_breaches: bool = False
    #: the one planned execution date of every card (default today)
    planned_date: date | None = None
    note: str | None = Field(default=None, max_length=2000)


class WindowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: measurement window in days (3..90); null = automatic (the recommended preset per product)
    days: int | None = Field(default=None, ge=1, le=1000)
    #: only this product (an override of the plan default); omitted = the whole plan
    product_id: str | None = Field(default=None, min_length=1, max_length=64)


class SetWindowBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(ge=1, le=1000)


ChangeSetStatus = Annotated[str | None, Query(pattern="^(measuring|done|cut)$")]


def breach_refusal(exc: plans.PlanBreachNotAcknowledged) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": exc.code, "message": exc.detail, "breaches": exc.breaches},
    )
