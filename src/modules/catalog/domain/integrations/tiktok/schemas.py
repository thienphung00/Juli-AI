"""Pydantic models for TikTok Shop Partner API response ``data`` payloads."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

T = TypeVar("T", bound=BaseModel)


class TikTokSchemaError(ValueError):
    """Raised when a Partner API ``data`` payload fails schema validation."""


class TikTokModel(BaseModel):
    """Base model — preserves unknown API fields for forward compatibility."""

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class PaginatedData(TikTokModel):
    next_page_token: str | None = None
    page_token: str | None = None


class TikTokOrder(TikTokModel):
    id: str | None = None
    user_id: str | None = None
    status: str | None = None
    order_status: str | None = None
    update_time: int | None = None
    cancel_reason: str | None = None
    cancellation_initiator: str | None = None
    payment: dict[str, Any] | None = None
    line_items: list[dict[str, Any]] = Field(default_factory=list)


class OrdersSearchData(PaginatedData):
    orders: list[TikTokOrder] = Field(default_factory=list)


class TikTokProduct(TikTokModel):
    id: str | None = None
    title: str | None = None
    status: str | None = None
    audit: dict[str, Any] | None = None
    create_time: int | None = None
    update_time: int | None = None


class ProductsSearchData(PaginatedData):
    products: list[TikTokProduct] = Field(default_factory=list)


class TikTokReturnOrder(TikTokModel):
    return_id: str | None = None
    order_id: str | None = None
    user_id: str | None = None
    return_status: str | None = None
    return_reason: str | None = None
    return_reason_text: str | None = None
    return_type: str | None = None
    refund_amount: dict[str, Any] | None = None
    return_line_items: list[dict[str, Any]] = Field(default_factory=list)
    update_time: int | None = None
    create_time: int | None = None


class ReturnsSearchData(PaginatedData):
    return_orders: list[TikTokReturnOrder] = Field(default_factory=list)


class AuthorizedShop(TikTokModel):
    id: str | None = None
    cipher: str | None = None
    name: str | None = None
    region: str | None = None


class AuthorizedShopsData(TikTokModel):
    shops: list[AuthorizedShop] = Field(default_factory=list)


class MarketplaceCreator(TikTokModel):
    creator_user_id: str | None = None
    nickname: str | None = None
    follower_count: int | None = None
    gmv: dict[str, Any] | None = None
    update_time: int | None = None


class MarketplaceCreatorsSearchData(PaginatedData):
    marketplace_creators: list[MarketplaceCreator] = Field(default_factory=list)


class CreatorContentDetail(TikTokModel):
    """Post-stream creator content (live/video) from Affiliate Seller API."""

    content_id: str | None = None
    room_id: str | None = None
    livestream_id: str | None = None
    creator_user_id: str | None = None
    creator_id: str | None = None
    title: str | None = None
    total_viewers: int | None = None
    viewer_count: int | None = None
    total_views: int | None = None
    orders_placed: int | None = None
    order_count: int | None = None
    total_sale_gmv: str | float | None = None
    revenue: str | float | None = None
    duration_seconds: int | None = None
    start_time: int | None = None
    end_time: int | None = None
    update_time: int | None = None
    create_time: int | None = None


class CreatorContentSearchData(PaginatedData):
    creator_content_details: list[CreatorContentDetail] = Field(default_factory=list)


class FinanceStatement(TikTokModel):
    statement_id: str | None = None
    id: str | None = None
    statement_time: int | None = None
    settlement_amount: str | float | None = None
    revenue_amount: str | float | None = None
    net_sales: str | float | None = None
    total_amount: str | float | None = None
    currency: str | None = None
    payment_status: str | None = None
    status: str | None = None


class FinanceStatementsData(PaginatedData):
    statements: list[FinanceStatement] = Field(default_factory=list)


def coerce_model(model: type[T], value: T | dict[str, Any] | BaseModel) -> T:
    """Return a validated model from either a model instance or raw dict."""
    if isinstance(value, model):
        return value
    if isinstance(value, BaseModel):
        return model.model_validate(value.model_dump())
    return validate_data(model, value)


def validate_data(model: type[T], data: dict[str, Any]) -> T:
    """Validate a ``data`` dict against a Pydantic model."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise TikTokSchemaError(str(exc)) from exc


def validate_items(model: type[T], items: list[dict[str, Any]]) -> list[T]:
    """Validate each item in a list response."""
    validated: list[T] = []
    for item in items:
        try:
            validated.append(model.model_validate(item))
        except ValidationError as exc:
            raise TikTokSchemaError(str(exc)) from exc
    return validated
