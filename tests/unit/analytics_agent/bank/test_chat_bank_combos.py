"""The generated Chat bank (owner, 26/11): every combination of the code's dimensions
(`dimensions.py`, `combos.py`) is a test id, judged by the oracle and the gap rules.

- default (the deploy gate): the covering array (every pair of every two data dimensions,
  every period x metric x scope triple) plus every create / advise / analysis / explain /
  unsupported / ambiguous / template / 1..5-intent / mismatch combination;
- `-m bank_full` (nightly, before a tag): the full cross product.

A combination passes, or fails with problems a known gap rule explains (xfail naming the
rules), or FAILS (a problem no rule explains: a regression or a new gap). A mismatch case (owner
#115) must be a correct refusal, read from `metrics.capabilities`. After the run, every rule's
footprint and every bucket must equal `combo_record.json` (`combo_eval`), so a fix inside a rule
forces the record (and the rule) to move, and no regression hides inside a rule."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from tests.unit.analytics_agent.bank import combo_eval, combos
from tests.unit.analytics_agent.bank.world import build_sqlite, sqlite_factory

FULL_ENV = "JULI_BANK_FULL"
SEEN: dict[str, combo_eval.Verdict] = {}


def _full(config: pytest.Config) -> bool:
    return os.environ.get(FULL_ENV) == "1" or "bank_full" in (config.getoption("markexpr") or "")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    if "combo_id" in metafunc.fixturenames:
        full = _full(metafunc.config)
        marks = [pytest.mark.bank_full] if full else []
        metafunc.parametrize(
            "combo_id", [pytest.param(i, id=i, marks=marks) for i in combo_eval.ids(full)]
        )


@pytest.fixture(scope="module")
def combo_shop(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Any]:
    path = tmp_path_factory.mktemp("chat_bank_combos") / "shop.sqlite"
    return path, build_sqlite(path)


def _record(full: bool) -> dict[str, Any]:
    rec = json.loads(combo_eval.RECORD_FILE.read_text(encoding="utf-8"))
    return dict(rec["full" if full else "gate"])


async def test_combo(combo_id: str, combo_shop: tuple[Path, Any], request: Any) -> None:
    case = combo_eval.case_of(combo_id)
    path, shop_id = combo_shop
    async with sqlite_factory(path) as factory:
        out, problems = await combo_eval.run_one(factory, shop_id, case)
    v = combo_eval.judge(case, out, problems)
    SEEN[combo_id] = v
    if v.status == "mismatch":  # owner #115: every mismatch is a correct refusal
        assert v.bucket == combos.EXPECTED_BUCKET, (
            f"{combo_id}: outcome {v.bucket!r}. {combos.MISMATCH_RULE}.\n  - "
            + "\n  - ".join(v.problems)
        )
        return
    assert v.status != "fail", f"{combo_id}: unexplained (no gap rule):\n  - " + "\n  - ".join(
        v.unexplained
    )
    if v.status == "gap":
        pending = all(g.pending for g in combos.GAP_RULES if g.name in v.rules)
        pytest.xfail(("pending: " if pending else "gap: ") + ", ".join(v.rules))


@pytest.mark.bank_full  # selected by `-m bank_full` too (a mark never deselects by default)
def test_rule_footprints_match_the_record(request: Any) -> None:
    """Strictness per rule: each rule explains exactly the recorded combinations; a rule that
    explains none must go. Runs after the combinations (definition order)."""
    full = _full(request.config)
    expected = combo_eval.ids(full)
    if len(SEEN) != len(expected):
        pytest.skip(f"partial run ({len(SEEN)} of {len(expected)} combinations): not compared")
    got = combo_eval.summarise(SEEN)
    rec = _record(full)
    assert got["rules"] == rec["rules"], "gap-rule footprints moved: re-record with combo_eval"
    assert got["mismatch"] == rec["mismatch"]
    if full:  # the gate samples the product, so a rule may be empty there
        assert all(r["count"] > 0 for r in got["rules"].values()), "a rule explains nothing"
