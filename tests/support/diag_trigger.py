"""Pin a shop's stored ``diag_trigger`` for tests written against an older card trigger.

F11 (2026-11-16) made ``shared`` (the shared detector, ``services.forecast.triggers``) the
default card trigger. Tests whose fixtures and expectations were built for the D39.1
metric-first trigger keep testing it as the rollback value: every shop without its own
``diag_trigger`` override reads ``metric_first``; an explicit override still wins.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from juli_backend.services.optimize_product.tunables import DIAG_TRIGGER, TRIGGER_METRIC_FIRST


def pin_diag_trigger(monkeypatch: pytest.MonkeyPatch, value: str = TRIGGER_METRIC_FIRST) -> None:
    # The package re-exports the ``diag_tunables`` function under the module's name.
    module = importlib.import_module("juli_backend.services.shop_rules.diag_tunables")
    real = module.tunable_overrides

    async def pinned(session: Any, shop_id: Any) -> dict[str, Any]:
        overrides = dict(await real(session, shop_id))
        overrides.setdefault(DIAG_TRIGGER, value)
        return overrides

    monkeypatch.setattr(module, "tunable_overrides", pinned)


__all__ = ["pin_diag_trigger"]
