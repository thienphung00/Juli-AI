"""Memoised read adapters for the generated bank: the seeded shop is read-only, so a read with the
same arguments returns the same rows. Every `ServiceData` / `ServiceCardEngine` read is cached by
(method, args, profit gate) for the session and handed out as a deep copy (the engine mutates some
rows). The first call of each key runs the production read; nothing else changes."""

from __future__ import annotations

import copy
import json
from typing import Any

from juli_backend.services.analytics_agent.cards_service import ServiceCardEngine
from tests.unit.analytics_agent.bank.sqlite_data import SqliteServiceData

_CACHE: dict[str, Any] = {}

DATA_READS = (
    "shop_daily",
    "source_daily",
    "product_daily",
    "item_names",
    "catalog_search",
    "stock_events",
    "open_cards",
    "overview",
    "metric_view",
    "critical",
    "cost_lines",
    "cost_lines_pair",
    "entity_totals",
    "voucher_figures",
    "campaign_rows",
    "product_profit",
    "product_profit_rows",
    "budget_days",
)


def _gate() -> str:
    from juli_backend.services.shopee_profit import shop_profit

    return str(shop_profit.MIN_KNOWN_GMV_SHARE_PCT)


def _key(name: str, args: tuple[Any, ...], kw: dict[str, Any]) -> str:
    return json.dumps([name, _gate(), args, kw], default=str, sort_keys=True)


async def memo(name: str, fn: Any, *args: Any, **kw: Any) -> Any:
    k = _key(name, args, kw)
    if k not in _CACHE:
        _CACHE[k] = await fn(*args, **kw)
    return copy.deepcopy(_CACHE[k])


def _wrap(name: str) -> Any:
    async def call(self: Any, *args: Any, **kw: Any) -> Any:
        base = getattr(super(type(self), self), name)
        return await memo(f"data.{name}", base, *args, **kw)

    call.__name__ = name
    return call


class CachedData(SqliteServiceData):
    pass


for _n in DATA_READS:
    setattr(CachedData, _n, _wrap(_n))


class CachedCardEngine(ServiceCardEngine):
    async def engine_card(self, kind: str, item: str | None, as_of: Any) -> dict[str, Any]:
        return dict(await memo("card.engine_card", super().engine_card, kind, item, as_of))

    async def build_custom(self, spec: dict[str, Any], as_of: Any) -> dict[str, Any]:
        return dict(await memo("card.build_custom", super().build_custom, spec, as_of))


def cache_size() -> int:
    return len(_CACHE)
