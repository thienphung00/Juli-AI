"""The structured-output schemas of the content drafts (contract §3, D24.16, D24.19).

The JSON schema is the content-engine script frame (HOOK / SETUP / VALUE / CTA as
timed scenes, ``cut.json``-style hook options) for a video, and the ASBC host
frame plus the basket order for a LIVE. OpenAI's strict structured output needs
every property required and ``additionalProperties: false``; ranges the schema
cannot express are checked by ``guardrails``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from juli_backend.services.content_cards.constants import VIDEO, ContentKind

_STR: dict[str, Any] = {"type": "string"}
_NUM: dict[str, Any] = {"type": "number"}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(properties),
        "properties": properties,
    }


VIDEO_SCRIPT_SCHEMA: dict[str, Any] = _object(
    {
        "hook_options": {"type": "array", "items": _STR},
        "scenes": {
            "type": "array",
            "items": _object(
                {
                    "t_from": _NUM,
                    "t_to": _NUM,
                    "visual": _STR,
                    "voiceover": _STR,
                    "on_screen": _STR,
                }
            ),
        },
        "cta": _STR,
        "hashtags": {"type": "array", "items": _STR},
        "music_hint": _STR,
        "product_on_screen_by_s": _NUM,
    }
)

LIVE_PLAN_SCHEMA: dict[str, Any] = _object(
    {
        "opening": _STR,
        "show": _STR,
        "close": _STR,
        "offer": _object(
            {
                "type": {"type": "string", "enum": ["flash_sale", "voucher", "gift", "none"]},
                "discount_pct": {"type": ["number", "null"]},
                "text": _STR,
            }
        ),
        "basket_order": {
            "type": "array",
            "items": _object({"position": {"type": "integer"}, "sku": _STR, "pin_at": _STR}),
        },
    }
)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Scene(_Strict):
    t_from: float
    t_to: float
    visual: str
    voiceover: str
    on_screen: str


class VideoScript(_Strict):
    hook_options: list[str]
    scenes: list[Scene]
    cta: str
    hashtags: list[str]
    music_hint: str
    product_on_screen_by_s: float


class LiveOffer(_Strict):
    type: Literal["flash_sale", "voucher", "gift", "none"]
    discount_pct: float | None = None
    text: str


class BasketItem(_Strict):
    position: int
    sku: str
    pin_at: str


class LivePlan(_Strict):
    opening: str
    show: str
    close: str
    offer: LiveOffer
    basket_order: list[BasketItem] = Field(default_factory=list)


def schema_for(kind: ContentKind) -> tuple[str, dict[str, Any]]:
    """(schema name, JSON schema) for the kind's structured output."""
    if kind == VIDEO:
        return "video_script", VIDEO_SCRIPT_SCHEMA
    return "live_plan", LIVE_PLAN_SCHEMA


class SchemaViolation(ValueError):
    """The model's text is not a document of the requested schema."""


def parse_draft(kind: ContentKind, text: str) -> VideoScript | LivePlan:
    """Parse the model's JSON text into the kind's model, or raise ``SchemaViolation``."""
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SchemaViolation(f"not JSON: {exc}") from exc
    try:
        if kind == VIDEO:
            return VideoScript.model_validate(data)
        return LivePlan.model_validate(data)
    except ValidationError as exc:
        raise SchemaViolation(str(exc).splitlines()[0]) from exc


__all__ = [
    "LIVE_PLAN_SCHEMA",
    "VIDEO_SCRIPT_SCHEMA",
    "BasketItem",
    "LiveOffer",
    "LivePlan",
    "Scene",
    "SchemaViolation",
    "VideoScript",
    "parse_draft",
    "schema_for",
]
