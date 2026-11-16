"""F8: the middle scenario is ranked by profit when known, by GMV when not."""

from __future__ import annotations

from juli_backend.services.shopee_builder.engine.engine import run
from tests.unit.test_funnel_engine import simple_base, voucher_option


def test_f8_the_middle_scenario_ranks_by_profit_then_by_gmv():
    for profit in (True, False):
        base = simple_base(profit=profit)
        r = run(base, voucher_option(), n=1000)
        key = (lambda s: s.profit) if profit else (lambda s: s.gmv)
        before = key(r.before)
        d_low, d_mid, d_high = (key(s) - before for s in (r.low, r.likely, r.high))
        assert d_low <= d_mid <= d_high
