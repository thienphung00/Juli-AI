"""Pydantic models for TikTok Shop OAuth and webhook infrastructure."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TikTokOAuthCallbackParams(BaseModel):
    """Query parameters TikTok sends to the OAuth redirect URL."""

    code: str = Field(min_length=1)
    state: str = Field(min_length=1)


class TikTokWebhookPayload(BaseModel):
    """Parsed TikTok webhook event body."""

    type: str = Field(min_length=1)
    shop_id: str = Field(min_length=1)
    timestamp: int | None = None
    data: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TikTokWebhookPayload:
        return cls(
            type=str(raw["type"]),
            shop_id=str(raw["shop_id"]),
            timestamp=raw.get("timestamp"),
            data=raw.get("data"),
        )


class TikTokOAuthCallbackResult(BaseModel):
    """Infrastructure-only OAuth callback response (no persisted tokens)."""

    status: str
    message: str
