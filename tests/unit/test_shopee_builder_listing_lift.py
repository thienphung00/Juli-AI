"""P100 UI fix: the listing levers follow the content. A title / first line is scored by the
share of the product's keyword volume it holds; cover image and price display wait for the banner
checks.
#93 (owner, F5): a title and a cover image show no uplift until measured; keyword coverage still
scores a first line."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal as D

import pytest
from pydantic import TypeAdapter

from juli_backend.services.shopee_analytics import materialize
from juli_backend.services.shopee_builder import keyword_coverage as kwc
from juli_backend.services.shopee_builder import service as builder
from juli_backend.services.shopee_builder import specs as sp
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_builder_drafts import _market

NOW = datetime(2026, 10, 8, 3, 0)
SPEC = TypeAdapter(sp.VersionSpec)
W = {"găng tay": 5000.0, "dùng một lần": 1200.0, "nitrile": 900.0}


def test_coverage_folds_case_and_diacritics_and_matches_whole_words():
    assert kwc.coverage("GANG TAY Nitrile", W) == D(5900) / D(7100)
    assert kwc.coverage("găngtay nitrilex", W) == 0
    assert kwc.coverage("abc xyz", W) == 0
    assert kwc.coverage("x", {}) == 0


def test_gain_share_is_the_share_of_the_missing_weight_captured():
    assert kwc.gain_share("Găng tay", "abc xyz", W) == 0
    assert kwc.gain_share("Găng tay", "Găng tay dùng một lần nitrile", W) == 1
    half = kwc.gain_share("Găng tay", "Găng tay nitrile", W)
    assert D("0.4") < half < D("0.5")
    assert kwc.gain_share("Găng tay dùng một lần nitrile", "Găng tay dùng một lần nitrile", W) == 0
    assert kwc.gain_share(None, "Găng tay", W) == D(5000) / D(7100)


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await _market(session, seeded.shop_id)
    await session.commit()
    return seeded


@pytest.fixture
async def bare_shop(session):
    seeded = await seed_reco_shop(session)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    return seeded


async def one(session, shop, **version):
    out = await builder.evaluate_versions(
        session, shop.shop_id, [SPEC.validate_python(version)], as_of=AS_OF, now=NOW
    )
    return out["versions"][0]


def _profit(v):
    """The likely Δ profit. F5 (owner 2026-11-16) nulls a within-noise value on screen; the
    internal likely column (``detail``) still carries it."""
    if not v["result"]["estimable"]:
        return None
    shown = v["result"]["delta"]["profit"]
    if shown is not None:
        return shown["value"]
    assert "profit" in v["result"]["within_noise"]
    d = v["result"]["detail"]
    return round(d["likely"]["profit"] - d["before"]["profit"])


async def test_no_title_scores_an_uplift_until_measured(session, shop):
    keyword_title = await one(
        session,
        shop,
        kind="title",
        item_id="1001",
        title="Găng tay tự hủy sinh học STAHAUS, găng tay dùng một lần, găng tay nitrile y tế",
    )
    junk = await one(session, shop, kind="title", item_id="1001", title="abc xyz")
    assert keyword_title["ok"] and junk["ok"]
    # #93 (owner, F5): a title shows no uplift until measured, whatever keywords it holds
    for v in (keyword_title, junk):
        assert v["result"]["estimable"] is False
        assert _profit(v) is None


async def test_a_title_holding_the_same_keywords_as_today_shows_no_delta(session, shop):
    same = await one(
        session, shop, kind="title", item_id="1001", title="Găng tay tự hủy sinh học STAHAUS"
    )
    # #93 (owner, F5): no title uplift until measured, so no Δ at all (was an estimable 0)
    assert same["ok"] and same["result"]["estimable"] is False
    assert _profit(same) is None


async def test_a_description_first_line_follows_the_keywords(session, shop):
    dot = await one(
        session, shop, kind="description_first_line", item_id="1001", first_line="Xin chào."
    )
    rich = await one(
        session,
        shop,
        kind="description_first_line",
        item_id="1001",
        first_line="Găng tay nitrile, găng tay y tế, găng tay dùng một lần hộp 100 chiếc.",
    )
    assert _profit(dot) == 0 and _profit(rich) > 0


async def test_no_keyword_data_uses_the_kind_prior_for_a_first_line(session, bare_shop):
    # decision #27 / #29: no keyword weights = the typical result of the kind, never a stop
    v = await one(
        session,
        bare_shop,
        kind="description_first_line",
        item_id="1001",
        first_line="Găng tay nitrile.",
    )
    assert v["ok"] is True
    assert v["result"]["estimable"] is True
    assert v["result"]["basis"] != "not_estimable"
    assert v["result"].get("reason_code") is None
    assert _profit(v) is not None and _profit(v) > 0
    # #93 (owner, F5): a title gets no uplift until measured, so no kind prior either
    title = await one(
        session, bare_shop, kind="title", item_id="1001", title="Găng tay nitrile hộp 100"
    )
    assert title["ok"] is True and title["result"]["estimable"] is False


async def test_cover_image_waits_and_price_display_uses_the_kind_prior(session, shop):
    cover = await one(
        session,
        shop,
        kind="cover_image",
        item_id="1001",
        overlay={"layout": "banner_bottom", "badge_text": "x"},
    )
    display = await one(
        session, shop, kind="price_display", item_id="1001", text="Chỉ 3.000đ/chiếc"
    )
    for v in (cover, display):
        assert v["ok"] is True
        assert v["result"]["cost"]["total"] == 0
    # #93 (owner, F5): a cover image shows no uplift until measured; price display keeps its prior
    assert cover["result"]["estimable"] is False
    assert display["result"]["estimable"] is True
    assert display["result"]["basis"] != "not_estimable"
