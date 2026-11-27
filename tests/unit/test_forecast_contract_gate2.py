"""Forecast contract, gate 2 (ratchet): no NEW module reads the old money layer, and no NEW
"30 days" current-figure function.

- ``predicted.money_per_month`` is the old money layer: since the OptionResult (``result_store``)
  it drives nothing the seller sees or any total. The modules that still touch it are listed
  below (they move off it in tag 3); a module not on the list that starts reading or writing it
  fails here.
- F1 (owner 2026-11-25): there is ONE "hiện tại" -- ``forecast_base.current_30d`` (the plain sums
  of the last 30 days). The functions named for a 30-day figure today are listed; a new one fails
  (call ``forecast_base.current_30d`` / ``shopee_recommendations.current`` instead).

Both lists only shrink: an entry that no longer matches fails too, so the list is trimmed in the
same change that moves a module off.
"""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "backend" / "src" / "juli_backend"
OLD_MONEY_KEY = "money_per_month"

#: modules that read (or build) ``predicted.money_per_month`` today -- tag 3 moves them off
MONEY_PER_MONTH_ALLOWED = frozenset(
    {
        "services/shopee_builder/outcome.py",  # reads
        "services/shopee_recommendations/cards.py",  # builds the block
        "services/shopee_recommendations/kol_cards.py",  # builds the block
        "services/shopee_recommendations/manual.py",  # reads
        "services/shopee_recommendations/mega.py",  # builds the block
        "services/shopee_recommendations/plan_aggregate.py",  # reads
        "services/shopee_recommendations/targets.py",  # reads + merges
        "services/shopee_recommendations/trigger_adapter.py",  # reads
        "services/shopee_recommendations/voucher_notes.py",  # reads
    }
)

#: a function named for a 30-day figure: ``*_30d``, ``*_30_days``, ``thirty*``
THIRTY_DAY_NAME = re.compile(r"(?:^|_)(?:30_?d(?:ays?)?|thirty)(?:_|$)")
#: (module, qualname) of the 30-day functions today. ``forecast_base.current_30d`` is THE one
#: hiện tại; the others wrap it, convert a result to 30 days, or are model features (rates).
THIRTY_DAY_ALLOWED = frozenset(
    {
        ("services/shopee_analytics/forecast_base.py", "current_30d"),  # F1: the one
        ("services/shopee_recommendations/current.py", "current_30d"),  # wraps it on the env
        ("services/shopee_recommendations/current.py", "gmv_30d"),
        ("services/shopee_recommendations/current.py", "orders_30d"),
        ("services/shopee_recommendations/env.py", "RecoEnv.shop_gmv_30d"),
        ("services/shopee_recommendations/env.py", "RecoEnv.shop_orders_30d"),
        ("services/shopee_recommendations/plan_aggregate.py", "CardResult.before_30d"),
        ("services/shopee_builder/engine/wire.py", "per_30d_profit"),  # a result per 30 days
        ("ai/features/anomaly.py", "_compute_shop_return_rate_30d"),  # model feature (a rate)
        ("ai/features/anomaly.py", "_compute_seller_fault_cancel_rate_30d"),
        ("ai/features/seller_stage.py", "_compute_return_rate_30d"),
    }
)


@functools.cache
def _modules() -> list[tuple[str, ast.Module]]:
    out = []
    for p in sorted(SRC.rglob("*.py")):
        out.append((p.relative_to(SRC).as_posix(), ast.parse(p.read_text(encoding="utf-8"))))
    return out


def _docstrings(tree: ast.Module) -> set[int]:
    """ids of the docstring constants (a docstring that names the layer reads nothing)."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _touches_old_money(tree: ast.Module) -> bool:
    docs = _docstrings(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == OLD_MONEY_KEY and id(node) not in docs:
            return True
        if isinstance(node, ast.Attribute) and node.attr == OLD_MONEY_KEY:
            return True
        if isinstance(node, ast.Name) and node.id == OLD_MONEY_KEY:
            return True
    return False


def _thirty_day_defs(tree: ast.Module) -> list[str]:
    found: list[str] = []

    def visit(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                qual = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef) and THIRTY_DAY_NAME.search(child.name):
                    found.append(qual)
                visit(child, f"{qual}.")
            else:
                visit(child, prefix)

    visit(tree, "")
    return found


def test_no_new_module_reads_the_old_money_layer() -> None:
    touching = {mod for mod, tree in _modules() if _touches_old_money(tree)}
    new = sorted(touching - MONEY_PER_MONTH_ALLOWED)
    assert new == [], (
        f"{new} read predicted.{OLD_MONEY_KEY} (the old money layer): use the card's "
        "OptionResult (shopee_recommendations.result_store) instead"
    )
    gone = sorted(MONEY_PER_MONTH_ALLOWED - touching)
    assert gone == [], f"{gone} no longer touch {OLD_MONEY_KEY}: drop them from the list"


def test_no_new_thirty_day_current_figure_function() -> None:
    defs = {(mod, q) for mod, tree in _modules() for q in _thirty_day_defs(tree)}
    new = sorted(defs - THIRTY_DAY_ALLOWED)
    assert new == [], (
        f"{new} define a new 30-day figure: F1 has one hiện tại, "
        "forecast_base.current_30d (shopee_recommendations.current on an env)"
    )
    gone = sorted(THIRTY_DAY_ALLOWED - defs)
    assert gone == [], f"{gone} are gone: drop them from the list"


def test_the_gate_catches_a_new_reader_and_a_new_thirty_day_function() -> None:
    """The detectors themselves: a key read, an attribute, a docstring that only names it; a
    module-level and a nested 30-day def."""
    reader = ast.parse('def f(card):\n    return card["predicted"]["money_per_month"]["total"]\n')
    attr = ast.parse("def f(p):\n    return p.money_per_month\n")
    doc_only = ast.parse('"""the old ``money_per_month`` layer is gone"""\nX = 1\n')
    assert _touches_old_money(reader) and _touches_old_money(attr)
    assert not _touches_old_money(doc_only)
    src = (
        "def hien_tai_30d(env):\n    pass\n"
        "class A:\n    def last_30_days(self):\n        pass\n"
        "    def per30(self):\n        pass\n"
        "def thirty_day_gmv():\n    pass\n"
    )
    assert _thirty_day_defs(ast.parse(src)) == ["hien_tai_30d", "A.last_30_days", "thirty_day_gmv"]
