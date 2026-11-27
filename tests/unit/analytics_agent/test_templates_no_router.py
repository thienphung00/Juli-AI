"""#112(1a): the five template buttons answer on the test shop with the router down.

A template names its chain, metric and window, so nothing is routed; its card stage picks in code
(kind order, the product that explains most, the best estimable version). Jev raises
`JevUnavailable` on any call: a template must never reach it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from juli_backend.services.analytics_agent.types import TEMPLATES
from tests.unit.analytics_agent.bank import runner
from tests.unit.analytics_agent.bank.sqlite_data import SqliteServiceData
from tests.unit.analytics_agent.bank.world import build_sqlite, sqlite_factory


@pytest.fixture(scope="module")
def shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    path = tmp_path_factory.mktemp("templates_no_router") / "shop.sqlite"
    return path, build_sqlite(path)


@pytest.mark.parametrize("key", [t.key for t in TEMPLATES])
async def test_template_answers_with_the_router_down(key: str, shop: tuple[Path, Any]) -> None:
    path, shop_id = shop
    case = {"id": key, "question": f"[{key}]", "template": key, "jev_down": True, "expect": {}}
    async with sqlite_factory(path) as factory:
        out = await runner.ask(factory, SqliteServiceData(factory, shop_id), shop_id, case)
        problems = await runner.check(out, case, factory, shop_id)
    assert out.error is None and not problems, (out.error, problems)
    assert out.jev_calls == 0  # never asked: no router_unavailable possible
    assert not out.of("unsupported") and not out.of("error") and not out.of("needs_choice")
    assert out.of("done") and out.final_text().strip()
    assert out.stop_reasons and "error" not in out.stop_reasons
