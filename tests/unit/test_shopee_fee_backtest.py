"""P92 B-9: the fee-formula backtest -- formula fees against the Income export's actual fees per
order, mean absolute gap and its share of what the buyer paid. Synthetic shop; asserts the
computation, not a threshold on real data."""

from __future__ import annotations

import pytest

from juli_backend.services.shopee_analytics import fee_backtest as svc
from tests.support.api import client_for
from tests.support.shopee_analytics import CUR_END, seed_shopee_shop
from tests.unit.test_ops_shopee_dashboards import _ops_client
from tests.unit.test_shopee_income_analytics import D, _delivered_refs, _income


def _actual(seeded, refs, totals):
    return [
        _income(
            seeded,
            ref,
            fee_fixed=D(total),
            fee_service=D(0),
            fee_payment=D(0),
            net_shipping_cost=D(0),
        )
        for ref, total in zip(refs, totals, strict=True)
    ]


async def test_no_income_rows_means_nothing_compared_and_no_number(session):
    seeded = await seed_shopee_shop(session)
    out = await svc.run(session, seeded.shop_id, as_of=CUR_END, days=30)
    assert out["orders_compared"] == 0 and out["mean_abs_gap"] is None
    assert out["pct_of_buyer_paid"] is None and out["within_target"] is None
    assert out["orders_skipped"]["no_income"] > 0 and out["worst"] == []


async def test_gap_per_order_is_formula_minus_actual_and_the_means_follow(session):
    seeded = await seed_shopee_shop(session)
    refs = _delivered_refs(seeded, 3)
    session.add_all(_actual(seeded, refs, [9_000, 14_000, 30_000]))
    await session.flush()
    out = await svc.run(session, seeded.shop_id, as_of=CUR_END, days=30)
    assert out["orders_compared"] == 3
    rows = out["worst"]
    assert {r["order_key"] for r in rows} <= {ref[:12] for ref in refs}  # no raw ref leaves
    assert all(len(r["order_key"]) == 12 for r in rows)
    assert sorted(r["actual_fees"] for r in rows) == [9_000, 14_000, 30_000]
    for r in rows:
        assert r["gap"] == pytest.approx(r["formula_fees"] - r["actual_fees"], abs=0.01)
        assert r["formula_fees"] > 0
    gaps = [r["gap"] for r in rows]
    assert out["mean_abs_gap"] == pytest.approx(sum(abs(g) for g in gaps) / 3, abs=0.01)
    assert out["mean_gap"] == pytest.approx(sum(gaps) / 3, abs=0.01)
    paid = sum(r["buyer_paid"] for r in rows)
    expected_pct = sum(abs(g) for g in gaps) / paid * 100
    assert out["pct_of_buyer_paid"] == pytest.approx(expected_pct, abs=0.001)
    assert out["within_target"] is (expected_pct <= 1.0) and out["target_pct"] == 1.0
    assert abs(out["worst"][0]["gap"]) == max(abs(g) for g in gaps)


async def test_the_formula_side_does_not_depend_on_the_actuals(session):
    seeded = await seed_shopee_shop(session)
    refs = _delivered_refs(seeded, 2)
    rows = _actual(seeded, refs, [5_000, 6_000])
    session.add_all(rows)
    await session.flush()
    first = await svc.run(session, seeded.shop_id, as_of=CUR_END, days=30)
    for row, total in zip(rows, (50_000, 1), strict=True):
        row.fee_fixed = D(total)
    await session.flush()
    second = await svc.run(session, seeded.shop_id, as_of=CUR_END, days=30)
    f1 = sorted(r["formula_fees"] for r in first["worst"])
    f2 = sorted(r["formula_fees"] for r in second["worst"])
    assert f1 == f2 and second["mean_abs_gap"] != first["mean_abs_gap"]


async def test_a_perfect_formula_has_zero_gap(session):
    from sqlalchemy import select

    from juli_backend.models.shopee_profit import ShopeeOrderIncome

    seeded = await seed_shopee_shop(session)
    refs = _delivered_refs(seeded, 2)
    session.add_all(_actual(seeded, refs, [1, 1]))
    await session.flush()
    probe = await svc.run(session, seeded.shop_id, as_of=CUR_END, days=30)
    formulas = sorted(r["formula_fees"] for r in probe["worst"])
    stored = (await session.scalars(select(ShopeeOrderIncome))).all()
    # give each order exactly the fees the formula charges it: match by trying both pairings
    for pairing in (formulas, formulas[::-1]):
        for row, fee in zip(stored, pairing, strict=True):
            row.fee_fixed = D(str(fee))
        await session.flush()
        out = await svc.run(session, seeded.shop_id, as_of=CUR_END, days=30)
        if out["mean_abs_gap"] == 0:
            break
    assert out["mean_abs_gap"] == 0 and out["pct_of_buyer_paid"] == 0
    assert out["within_target"] is True


async def test_ops_route_is_viewer_read(session, monkeypatch):
    seeded = await seed_shopee_shop(session)
    session.add_all(_actual(seeded, _delivered_refs(seeded, 2), [8_000, 9_000]))
    await session.commit()
    viewer = await _ops_client(session, monkeypatch, "viewer")
    async with client_for(viewer) as client:
        r = await client.get(
            f"/v1/ops/shops/{seeded.shop_id}/shopee/fee-backtest?days=30&as_of={CUR_END}"
        )
        assert r.status_code == 200, r.text
        assert r.json()["orders_compared"] == 2 and r.json()["pct_of_buyer_paid"] is not None
        assert (
            await client.get(f"/v1/ops/shops/{seeded.shop_id}/shopee/fee-backtest?days=3")
        ).status_code == 422
    viewer.dependency_overrides.clear()
