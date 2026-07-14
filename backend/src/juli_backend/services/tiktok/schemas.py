"""Pydantic models for TikTok Shop OAuth and webhook infrastructure."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TikTokOAuthCallbackParams(BaseModel):
    """Query parameters TikTok sends to the OAuth redirect URL.

    Partner Center may redirect with ``code`` only (no ``state``) when the seller
    authorizes from the TikTok console rather than via a Juli-initiated auth URL.
    """

    code: str = Field(min_length=1)
    state: str | None = None
    app_key: str | None = None
    locale: str | None = None
    shop_region: str | None = None


class TikTokWebhookPayload(BaseModel):
    """Parsed TikTok webhook event body."""

    type: str = Field(min_length=1)
    shop_id: str = Field(min_length=1)
    timestamp: int | None = None
    data: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TikTokWebhookPayload:
        return cls(
            type=_canonical_event_type(raw["type"]),
            shop_id=_resolve_shop_id(raw),
            timestamp=raw.get("timestamp"),
            data=raw.get("data") if isinstance(raw.get("data"), dict) else None,
        )


def _resolve_shop_id(raw: dict[str, Any]) -> str:
    """Return the TikTok shop key for handoff.

    Most Partner Center events send top-level ``shop_id``. Inventory #68
    (`INVENTORY_CHANGED`) sends ``seller_open_id`` plus ``data.seller_id``
    (numeric shop id) with no top-level ``shop_id``.
    """
    shop_id = raw.get("shop_id")
    if shop_id is not None and str(shop_id).strip():
        return str(shop_id)

    data = raw.get("data")
    if isinstance(data, dict):
        seller_id = data.get("seller_id")
        if seller_id is not None and str(seller_id).strip():
            return str(seller_id)
        nested_shop = data.get("shop_id")
        if nested_shop is not None and str(nested_shop).strip():
            return str(nested_shop)

    raise KeyError("shop_id")


def _canonical_event_type(type_value: Any) -> str:
    """Normalize Partner Center ``type`` (numeric catalog id or name) to a string."""
    raw = str(type_value).strip()
    if not raw:
        raise ValueError("type")
    from juli_backend.services.tiktok.webhook_catalog import resolve_catalog_entry

    entry = resolve_catalog_entry(raw)
    if entry is not None:
        return entry.event_types[0]
    return raw


class TikTokOAuthCallbackResult(BaseModel):
    """Infrastructure-only OAuth callback response (no persisted tokens)."""

    status: str
    message: str
    open_id_present: bool | None = None
    access_token_expires_in: int | None = None
