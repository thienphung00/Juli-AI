"""Request bodies and helpers shared by the Ops and Demo routes of the manual offers and the
comparison (p91 D-3): limits live here -- 2-4 variants, at most 3 combo products, qty 1-20,
money bounds, percent 0-90."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from juli_backend.services.shopee_recommendations import combo, manual

MAX_MONEY = 2_000_000_000  # đ
MAX_INPUT_KEYS = 24


class ComboItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str = Field(min_length=1, max_length=64)
    sku: str | None = Field(default=None, max_length=64)
    qty: int = Field(default=1, ge=1, le=combo.MAX_QTY)


class VoucherBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: int | None = Field(default=None, ge=1, le=MAX_MONEY)
    pct: float | None = Field(default=None, gt=0, le=90)
    min_spend: int = Field(default=0, ge=0, le=MAX_MONEY)
    max_value: int | None = Field(default=None, ge=1, le=MAX_MONEY)

    @model_validator(mode="after")
    def _one_of(self) -> VoucherBody:
        if (self.value is None) == (self.pct is None):
            raise ValueError("exactly one of value / pct")
        return self


class ExtraBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    addon_item: str | None = Field(default=None, max_length=64)
    gift_item: str | None = Field(default=None, max_length=64)
    combo_items: list[ComboItemBody] | None = Field(default=None, max_length=combo.MAX_LINES)
    discount_type: Literal["pct", "amount", "fixed_price"] | None = None
    discount_value: float | None = Field(default=None, ge=0, le=MAX_MONEY)
    voucher: VoucherBody | None = None

    @model_validator(mode="after")
    def _pct_bound(self) -> ExtraBody:
        if self.discount_type == "pct" and (self.discount_value or 0) > 90:
            raise ValueError("a percent discount is at most 90")
        return self


class VariantBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str | None = Field(default=None, max_length=60)
    change_kind: str = Field(min_length=1, max_length=32)
    items: list[str] = Field(default_factory=list, max_length=3)
    extra: ExtraBody = Field(default_factory=ExtraBody)
    inputs: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _limits(self) -> VariantBody:
        if len(self.inputs) > MAX_INPUT_KEYS:
            raise ValueError("too many inputs")
        for key, value in self.inputs.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, int | float):
                if abs(value) > MAX_MONEY:
                    raise ValueError(f"input {key} is out of bounds")
                if "pct" in key and not 0 <= value <= 90:
                    raise ValueError(f"input {key} must be between 0 and 90")
            elif isinstance(value, str):
                if len(value) > 500:
                    raise ValueError(f"input {key} is too long")
            elif value is not None and not isinstance(value, list | dict):
                raise ValueError(f"input {key} has an unsupported type")
        if self.change_kind == combo.KIND:
            n = len(self.extra.combo_items or [])
            if not combo.MIN_LINES <= n <= combo.MAX_LINES:
                raise ValueError("a combo needs 2 or 3 products")
            if self.extra.discount_type is None or self.extra.discount_value is None:
                raise ValueError("a combo needs discount_type and discount_value")
        return self

    def as_dict(self) -> dict[str, Any]:
        out = self.model_dump(exclude_none=True)
        extra = out.get("extra") or {}
        v = extra.get("discount_value")
        if isinstance(v, float) and v == int(v):
            extra["discount_value"] = int(v)
        return out


class CompareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variants: list[VariantBody] = Field(
        min_length=manual.MIN_VARIANTS, max_length=manual.MAX_VARIANTS
    )
    as_of: date | None = None


class ManualBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variants: list[VariantBody] = Field(min_length=1, max_length=manual.MAX_VARIANTS)
    #: index of the variant that becomes the card; the others are kept as its versions
    chosen: int = Field(default=0, ge=0, lt=manual.MAX_VARIANTS)
    #: ask to take the product's #1 slot in the queue
    primary: bool = False
    #: must be true to save a variant that breaks a floor price or the spend cap
    acknowledge_breaches: bool = False
    as_of: date | None = None

    @model_validator(mode="after")
    def _chosen_in_range(self) -> ManualBody:
        if self.chosen >= len(self.variants):
            raise ValueError("chosen must index one of the variants")
        return self


def breach_refusal(exc: manual.BreachNotAcknowledged) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": exc.code, "message": exc.detail, "breaches": exc.breaches},
    )
