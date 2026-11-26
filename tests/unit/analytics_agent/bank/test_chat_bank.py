"""The Chat regression bank (owner decision #109): every seller question that has passed must
keep passing. One test id per case of `cases.json`, run end to end on the seeded synthetic shop
(SQLite) with the parser / router fakes the case gives; figures checked against the tab's own
service. A known gap is `xfail(strict=True)` naming it, so the fix flips it and the bank forces
the marker off; a case waiting for tag 2 is `pending` (also strict). Nothing is skipped.

How to add a case: `README.md` beside this file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.unit.analytics_agent.bank import runner
from tests.unit.analytics_agent.bank.sqlite_data import SqliteServiceData
from tests.unit.analytics_agent.bank.world import build_sqlite, sqlite_factory

CASES = runner.load_cases()


def _param(case: dict[str, Any]) -> Any:
    status = case.get("status", "pass")
    marks = []
    if status == "xfail":
        marks.append(pytest.mark.xfail(strict=True, reason=f"gap: {case['reason']}"))
    elif status == "pending":
        marks.append(pytest.mark.xfail(strict=True, reason=f"pending: {case['reason']}"))
    return pytest.param(case, id=case["id"], marks=marks)


@pytest.fixture(scope="session")
def bank_shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    path = tmp_path_factory.mktemp("chat_bank") / "shop.sqlite"
    return path, build_sqlite(path)


@pytest.mark.parametrize("case", [_param(c) for c in CASES])
async def test_bank_case(
    case: dict[str, Any], bank_shop: tuple[Path, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    runner.ungate_if_asked(case, monkeypatch)
    path, shop_id = bank_shop
    async with sqlite_factory(path) as factory:
        data = SqliteServiceData(factory, shop_id)
        out = await runner.ask(factory, data, shop_id, case)
        problems = await runner.check(out, case, factory, shop_id)
    assert not problems, f"{case['id']} ({case['question']!r}):\n  - " + "\n  - ".join(problems)
