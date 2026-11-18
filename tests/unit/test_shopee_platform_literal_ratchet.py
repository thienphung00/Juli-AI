"""Ratchet (W4): the ``platform == "shopee"`` / ``!= "shopee"`` literals in ``backend/src``.

Each one is a place TikTok parity has to look at. The count may go down, never up, and no new
file may gain one: a new guard goes through ``api/capability_gate.py`` (the platform set is
data there, ``requires_data_on``) or ``services/capabilities`` ``can()``. When a count falls,
lower the pin here in the same change.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "backend" / "src" / "juli_backend"
LITERAL = re.compile(r"""(?:==|!=)\s*["']shopee["']|["']shopee["']\s*(?:==|!=)""")

PINNED: dict[str, int] = {
    "api/reviewer.py": 1,
    "api/routes/ingest_connector_ticks.py": 3,
    "api/routes/ingest_fill.py": 3,  # the three principal checks (W3b), not the seller guards
    "api/routes/ingest_market.py": 1,
    "api/routes/ingest_order_ref.py": 1,
    "api/routes/shopee_analytics_common.py": 1,
    "repositories/shopee_analytics.py": 2,
    "services/exports/collect.py": 3,
    "services/ops/contract_shops.py": 2,
    "services/reviewer/sandbox.py": 1,
    "services/sample_shop/seed.py": 1,
    "services/shopee_analytics/materialize.py": 2,
    "services/shopee_analytics/stored.py": 1,
    "services/shopee_builder/ads_campaigns.py": 1,
    "services/shopee_recommendations/codes.py": 2,
    "services/shopee_recommendations/daily_generation.py": 2,
    "services/shopee_recommendations/sim_priors.py": 1,
    "services/shopee_recommendations/store.py": 1,
    "services/stock_alert/job.py": 1,
}
PINNED_TOTAL = 30


def _counts() -> Counter[str]:
    found: Counter[str] = Counter()
    for path in SRC.rglob("*.py"):
        n = len(LITERAL.findall(path.read_text(encoding="utf-8")))
        if n:
            found[path.relative_to(SRC).as_posix()] = n
    return found


def test_no_new_shopee_platform_literal() -> None:
    found = _counts()
    grew = {f: (found[f], PINNED.get(f, 0)) for f in found if found[f] > PINNED.get(f, 0)}
    assert grew == {}, f"new shopee platform literal(s) (found, pinned): {grew}"


def test_total_does_not_exceed_the_pin() -> None:
    assert sum(_counts().values()) <= PINNED_TOTAL


def test_pin_sums_to_the_total() -> None:
    assert sum(PINNED.values()) == PINNED_TOTAL


def test_the_gate_holds_the_platform_set_as_data() -> None:
    gate = (SRC / "api" / "capability_gate.py").read_text(encoding="utf-8")
    assert LITERAL.search(gate) is None
