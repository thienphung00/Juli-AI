"""Synthetic fixture: hardcoded Redis prefix outside registry / juli: convention."""

from __future__ import annotations

from typing import Any


def _rogue_cache_key(shop_id: str) -> str:
    return f"rogue:cache:{shop_id}"


def write_rogue_cache(redis_client: Any, shop_id: str) -> None:
    redis_client.set(_rogue_cache_key(shop_id), "1")
