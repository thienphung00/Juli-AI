"""Owner D14 / D15 / D17 (2026-10-27): who takes part in a pooled figure, when a cell is used,
and the record of who contributed.

- D11 / D17: only ``pooled_training`` shops contribute, and only they receive the pooled
  figure (neither borrow nor lend) -- the Ops card-group EB prior and the D30.3 fleet
  calibration factor alike. ``pooled_training`` is granted only to Juli's own shops.
- D14 (``services/consent/pooling.py``, the one place the thresholds live): a cell is used
  only with ≥ 5 contributing shops and no shop over 50 % of its weight (Ops: measured
  group comparisons; fleet: day-14 results); else the next wider cell (Ops: lever type ->
  metric × channel; fleet: lever -> every lever); else no pooled figure.
- Production today: only Juli's own shop(s) consent -> NO pooled cell is active anywhere,
  and nothing is recorded (D14 as defence in depth).
- D15: the persisted fleet figure writes a ``pooled_contributor_sets`` row (shop ids,
  SHA-256 of the sorted list, shop count per cell); the query-time Ops prior logs the same
  fields. Never a shop name.

SQLite unit substrate; the Postgres proof is ``tests/integration/test_ops_pooled_consent_db.py``.
Synthetic fixtures only.
"""

from __future__ import annotations

import hashlib
import importlib.util
import logging
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from juli_backend.database.tenant_scoped_tables import TABLE_CLASSIFICATION_MAP
from juli_backend.models.consent import POOLED_FIGURES, PooledContributorSet
from juli_backend.models.lever_flows import LeverCalibration
from juli_backend.services.action_cards.card_groups import apply_pooled_eb
from juli_backend.services.action_cards.group_stats import PRIOR_DEFAULT, PRIOR_POOLED
from juli_backend.services.action_cards.optimize_product_cards import calibration_stats
from juli_backend.services.consent import grant_consent, pooling
from juli_backend.services.consent.pooling import (
    MAX_SHOP_SHARE,
    MIN_CONTRIBUTING_SHOPS,
    CellCheck,
    check_cell,
    contributing_set,
    contributors_sha256,
    first_active,
)
from juli_backend.services.lever_flows.measurement import (
    FleetDraw,
    fleet_calibration_stats,
    pool_fleet_calibration,
)
from juli_backend.services.optimize_product.prediction import (
    FLEET_ALL_LEVERS,
    CalibrationStats,
    fleet_stats_for,
    predict,
)
from tests.support.builders import make_tenant
from tests.unit.test_p45_eb_lift import _comparison, _eb_draws, _view, draws_from_rows

REPO = Path(__file__).resolve().parents[2]
MIGRATION = REPO / "backend/src/juli_backend/database/migrations/versions/107_ops_pooled_consent.py"
SERVICES = REPO / "backend/src/juli_backend/services"
NOW = datetime(2026, 10, 27, 3, 0)


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# =========================================================================== D14, pure


def test_the_thresholds_are_the_owners_and_live_in_one_place():
    assert (MIN_CONTRIBUTING_SHOPS, MAX_SHOP_SHARE) == (5, 0.5)
    # Both estimators judge their cells through the same function, and neither restates
    # the numbers.
    for path in ("action_cards/card_groups.py", "lever_flows/measurement.py"):
        source = (SERVICES / path).read_text("utf-8")
        assert "check_cell(" in source
        assert "MIN_CONTRIBUTING_SHOPS" not in source and "0.5 *" not in source


def test_five_shops_is_the_floor():
    four = check_cell("c", {f"s{i}": 1 for i in range(4)})
    five = check_cell("c", {f"s{i}": 1 for i in range(5)})
    assert (four.shops, four.active) == (4, False)
    assert (five.shops, five.active) == (5, True)
    # A shop with no weight in the cell does not count as a contributor.
    padded = check_cell("c", {**{f"s{i}": 1 for i in range(4)}, "empty": 0})
    assert (padded.shops, padded.active) == (4, False)


def test_no_shop_may_hold_more_than_half_of_a_cell():
    exactly_half = check_cell("c", {"big": 4, "a": 1, "b": 1, "c": 1, "d": 1})
    over_half = check_cell("c", {"big": 5, "a": 1, "b": 1, "c": 1, "d": 1})
    assert exactly_half.max_share == pytest.approx(0.5) and exactly_half.active
    assert over_half.max_share == pytest.approx(5 / 9) and not over_half.active


def test_first_active_walks_narrow_to_wide_and_may_find_none():
    short = {f"s{i}": 1 for i in range(3)}
    wide = {f"s{i}": 1 for i in range(6)}
    chosen = first_active([("narrow", short), ("wide", wide)])
    assert chosen is not None and chosen.key == "wide" and chosen.shops == 6
    assert first_active([("narrow", short), ("wide", short)]) is None


def test_the_ops_prior_falls_back_from_the_lever_type_to_metric_channel_then_default():
    # Three shops measured the cover image, three others the title, all on CTR · total.
    cover = _eb_draws("cover_image", [(f"c{i}", f"cg{i}", 3.0) for i in range(3)])
    title = _eb_draws("title", [(f"t{i}", f"tg{i}", 1.0) for i in range(3)])
    view = _view("me", "cover_image", 40.0)
    [out] = apply_pooled_eb([view], cover + title, pooled=True, min_groups=3)
    prior = out["verdict"]["primary"]["eb"]["prior"]
    # The lever type has 3 shops (short); every lever on CTR · total has 6.
    assert (prior["source"], prior["cell"], prior["n_groups"]) == (
        PRIOR_POOLED,
        "metric_channel",
        6,
    )
    # Only the cover-image shops: both cells short -> the default prior, no cell named.
    [alone] = apply_pooled_eb([_view("me", "cover_image", 40.0)], cover, pooled=True, min_groups=3)
    default = alone["verdict"]["primary"]["eb"]["prior"]
    assert default["source"] == PRIOR_DEFAULT and "cell" not in default


def test_one_dominant_shop_keeps_the_ops_cell_closed():
    # Five shops, but one holds 5 of the 9 measured comparisons (> 50 %).
    rows = [("big", f"b{i}", "cover_image", "ctr", "total", _comparison(3.0)) for i in range(5)]
    rows += [(f"s{i}", f"g{i}", "cover_image", "ctr", "total", _comparison(2.0)) for i in range(4)]
    used: dict[str, CellCheck] = {}
    [out] = apply_pooled_eb(
        [_view("me", "cover_image", 40.0)],
        draws_from_rows(rows),
        pooled=True,
        min_groups=3,
        used_cells=used,
    )
    assert out["verdict"]["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT
    assert used == {}


def _fleet(shop: str, lever: str, coefficient: str, readings: int) -> FleetDraw:
    return FleetDraw(shop, lever, Decimal(coefficient), readings)


def test_the_fleet_level_is_results_weighted_and_needs_five_balanced_shops():
    draws = [_fleet(f"s{i}", "cover_image", "0.4", 2) for i in range(4)]
    draws.append(_fleet("s4", "cover_image", "0.9", 2))
    fleet, used = pool_fleet_calibration(draws)
    assert fleet["cover_image"] == (Decimal("0.5"), 10)
    assert {c.key for c in used} == {"lever:cover_image", "all_levers"}
    # One shop with 10 of 18 results (> 50 %): no lever cell, and the wide cell is the same
    # five shops with the same imbalance -> nothing.
    heavy = [*draws[:4], _fleet("s4", "cover_image", "0.9", 10)]
    assert pool_fleet_calibration(heavy) == ({}, [])


def test_the_fleet_level_falls_back_to_every_lever_then_to_nothing():
    draws = [_fleet(f"a{i}", "cover_image", "0.5", 2) for i in range(3)]
    draws += [_fleet(f"b{i}", "description", "1.0", 2) for i in range(3)]
    fleet, used = pool_fleet_calibration(draws)
    # Neither lever has 5 shops; all six together do.
    assert set(fleet) == {FLEET_ALL_LEVERS}
    assert fleet[FLEET_ALL_LEVERS] == (Decimal("0.75"), 12)
    assert [c.key for c in used] == ["all_levers"]
    stats = {k: CalibrationStats(float(c), n) for k, (c, n) in fleet.items()}
    assert fleet_stats_for(stats, "title") == stats[FLEET_ALL_LEVERS]
    assert predict("title", 80, fleet=fleet_stats_for(stats, "title")).source == "fleet"
    # Four shops in all: no cell, no fleet level, the prior.
    assert pool_fleet_calibration(draws[:4]) == ({}, [])
    assert fleet_stats_for({}, "title") is None


# =========================================================================== D15, pure


def test_the_contributing_set_hash_is_the_sorted_ids_and_order_free():
    ids = ["c", "a", "b"]
    expected = hashlib.sha256(b"a\nb\nc").hexdigest()
    assert contributors_sha256(ids) == expected == contributors_sha256(reversed(ids))
    one = CellCheck("lever:x", 2, 0.5, ("a", "b"))
    two = CellCheck("all_levers", 3, 0.4, ("a", "b", "c"))
    cs = contributing_set(pooling.FIGURE_FLEET_CALIBRATION, [one, two])
    assert cs.shop_ids == ("a", "b", "c") and cs.sha256 == expected
    assert cs.cells == {"all_levers": 3, "lever:x": 2}
    assert set(cs.to_json()) == {"figure", "shop_ids", "sha256", "cells"}


def test_the_audit_vocabulary_matches_the_migration_and_the_table_is_ops_only():
    assert tuple(_module(MIGRATION, "mig107_cells").FIGURES) == POOLED_FIGURES == pooling.FIGURES
    assert TABLE_CLASSIFICATION_MAP[("public", "pooled_contributor_sets")] == "ops_only"
    columns = set(PooledContributorSet.__table__.columns.keys())
    assert not any("name" in c for c in columns) and "shop_id" not in columns


# =========================================================================== with the DB


async def _pool(session, shop_id: uuid.UUID) -> None:
    await grant_consent(
        session,
        shop_id,
        scope="pooled_training",
        method="contract_paper",
        terms_version="synthetic-terms-01",
        evidence_ref="synthetic/contract.pdf",
        granted_by="Synthetic Director",
        granted_at=NOW,
    )


def _calibration(shop_id: uuid.UUID, coefficient: str, readings: int, lever="cover_image"):
    return LeverCalibration(
        shop_id=shop_id,
        lever=lever,
        coefficient=Decimal(coefficient),
        readings=readings,
        updated_at=NOW,
    )


async def _audit_rows(session) -> list[PooledContributorSet]:
    return list((await session.execute(select(PooledContributorSet))).scalars())


@pytest.mark.asyncio
async def test_production_today_one_consenting_shop_means_no_pooled_cell_anywhere(session):
    """Only the development shop consents (lots of data); every other shop does not."""
    _, dev = await make_tenant(session, shop_name="Synthetic Dev Shop")
    await _pool(session, dev.id)
    session.add(_calibration(dev.id, "0.8", 40))
    session.add(_calibration(dev.id, "0.6", 25, lever="description"))
    others = [(await make_tenant(session))[1] for _ in range(6)]
    for shop in others:
        session.add(_calibration(shop.id, "1.2", 3))
    await session.flush()

    for shop in (dev, *others):
        shop_stats, fleet = await calibration_stats(session, shop.id)
        assert fleet == {}
    assert await fleet_calibration_stats(session) == {}
    # The Ops prior: the dev shop's draws alone open no cell either.
    draws = _eb_draws("cover_image", [(str(dev.id), f"g{i}", 3.0) for i in range(8)])
    [out] = apply_pooled_eb([_view("me", "cover_image", 40.0)], draws, pooled=True, min_groups=3)
    assert out["verdict"]["primary"]["eb"]["prior"]["source"] == PRIOR_DEFAULT
    # Nothing pooled, nothing recorded.
    assert await _audit_rows(session) == []


@pytest.mark.asyncio
async def test_a_non_consenting_shop_neither_borrows_nor_lends_the_fleet_level(session):
    """D11 / D17: five consenting shops pool among themselves; the outsider gets nothing."""
    pooled = [(await make_tenant(session))[1] for _ in range(5)]
    for shop in pooled:
        await _pool(session, shop.id)
        session.add(_calibration(shop.id, "0.5", 4))
    _, outsider = await make_tenant(session)
    session.add(_calibration(outsider.id, "1.9", 50))  # would dominate if it were pooled
    await session.flush()

    shop_stats, fleet = await calibration_stats(session, outsider.id)
    assert fleet == {}  # does not borrow
    assert shop_stats["cover_image"] == CalibrationStats(1.9, 50)  # its own level is its own
    assert await _audit_rows(session) == []  # nothing pooled for it, nothing recorded

    # A consenting shop receives the pool -- without the outsider's results (does not lend).
    _, fleet = await calibration_stats(session, pooled[0].id)
    assert fleet["cover_image"] == CalibrationStats(0.5, 20)
    [row] = await _audit_rows(session)
    assert row.figure == "fleet_calibration" and row.applied_shop_id == pooled[0].id
    assert row.contributor_shop_ids == sorted(str(s.id) for s in pooled)
    assert str(outsider.id) not in row.contributor_shop_ids
    assert row.contributors_sha256 == contributors_sha256(str(s.id) for s in pooled)
    assert row.cells == {"all_levers": 5, "lever:cover_image": 5}


@pytest.mark.asyncio
async def test_the_audit_holds_ids_only_and_a_query_without_a_run_records_nothing(session):
    names = [f"Synthetic Shop {i}" for i in range(5)]
    pooled = [(await make_tenant(session, shop_name=n))[1] for n in names]
    for shop in pooled:
        await _pool(session, shop.id)
        session.add(_calibration(shop.id, "0.5", 4))
    await session.flush()

    # No applied shop (no persisted run): the figure, no row.
    assert "cover_image" in await fleet_calibration_stats(session)
    assert await _audit_rows(session) == []
    await calibration_stats(session, pooled[0].id)
    [row] = await _audit_rows(session)
    dumped = repr(
        (row.contributor_shop_ids, row.cells, row.contributors_sha256, row.applied_shop_id)
    )
    assert not any(name in dumped for name in names)


@pytest.mark.asyncio
async def test_the_ops_page_logs_its_contributing_set(session, monkeypatch, caplog):
    """D15 for the query-time Ops prior: a structured log line, ids only."""
    from tests.support.api import client_for
    from tests.unit.test_p45_eb_lift import _ops_client, _seed_groups

    shops = [(await make_tenant(session, shop_name=f"Synthetic Ops {i}"))[1] for i in range(6)]
    await _seed_groups(session, shops)
    app = await _ops_client(session, monkeypatch)
    with caplog.at_level(logging.INFO, logger="juli_backend.services.consent.pooling"):
        async with client_for(app) as client:
            response = await client.get(f"/v1/ops/shops/{shops[0].id}/groups")
    assert response.status_code == 200
    [record] = [r for r in caplog.records if r.getMessage().startswith("pooled_contributor_set")]
    assert record.figure == "ops_group_prior" and record.persisted is False
    assert record.applied_shop_id == str(shops[0].id)
    assert record.shop_ids == sorted(str(s.id) for s in shops[1:])
    assert record.cells == {"lever_type:cover_image|ctr|total": 5}
    assert record.sha256 == contributors_sha256(record.shop_ids)
    assert "Synthetic Ops" not in record.getMessage() + repr(record.__dict__)
    # Nothing is stored for a page view.
    assert await _audit_rows(session) == []
