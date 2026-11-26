"""#78 / #87: the builder wire the web is tested with carries the engine's ``cost.offers``.

``tests/fixtures/builder_voucher_wire.json`` is the body of ``/builder/evaluate`` (the route returns
``evaluate_versions`` as it is) for a 10 % voucher capped at 3.000đ on the synthetic reco shop
(``tests/support/shopee_reco``, invented figures). The web tests read it, so a change of the wire
shows up there. THIS test regenerates it and fails if the committed file differs. After a
deliberate change of the answer: ``JULI_WRITE_FIXTURES=1 pytest <this file>`` and commit the file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.encoders import jsonable_encoder

from juli_backend.services.shopee_analytics import materialize
from tests.support.shopee_reco import seed_reco_shop
from tests.unit.test_shopee_builder import evaluate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "builder_voucher_wire.json"
CAPPED = {
    "kind": "voucher",
    "discount_type": "pct",
    "value": 10,
    "min_spend": 0,
    "max_value": 3000,
}


@pytest.fixture
async def reco_shop(session):
    seeded = await seed_reco_shop(session, traffic_days=True)
    await materialize.backfill_shop(session, seeded.shop_id)
    await session.commit()
    return seeded


def _text(body: object) -> str:
    return json.dumps(body, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


async def test_the_builder_voucher_wire_fixture_is_the_real_answer(session, reco_shop):
    body = jsonable_encoder(await evaluate(session, reco_shop, CAPPED))
    cost = body["versions"][0]["result"]["cost"]
    offers = cost["offers"]
    # the fixture is only worth having if it holds a voucher offer with its max discount
    assert [o["label"] for o in offers] == ["voucher"]
    md = offers[0]["max_discount"]
    assert md["cap"] == 3000 and 0 < md["binding_orders"] <= md["qualifying_orders"]
    for o in offers:
        assert o["total"] == pytest.approx(o["expected_uses"] * o["per_use"], rel=1e-9)
    assert sum(o["total"] for o in offers) + cost["fixed"] == pytest.approx(cost["total"], abs=1e-6)
    text = _text(body)
    if os.environ.get("JULI_WRITE_FIXTURES") == "1":
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.exists(), f"run JULI_WRITE_FIXTURES=1 pytest {__file__}"
    assert FIXTURE.read_text(encoding="utf-8") == text, (
        "the builder wire changed: JULI_WRITE_FIXTURES=1 pytest this file and commit the fixture"
    )
