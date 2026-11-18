"""batch-1118f F1.3: a "Tự tạo" card made through the real builder route is never re-issued by the
stale recompute (sent or approved), and keeps its revision and status. Synthetic shop."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.services.shopee_recommendations import stale, store
from tests.unit import test_shopee_reco_manual as _m

NOW = _m.NOW
DEMO = _m.DEMO
shop = _m.shop  # the shared fixtures, re-exported
seller = _m.seller


@pytest.mark.timeout(180)
async def test_a_stale_run_leaves_a_manual_card_untouched_sent_and_approved(session, shop, seller):
    seeded, _ = shop
    r = await seller.post(
        f"{DEMO}/manual", json=_m._body([_m._discount(), _m._combo()], chosen=1, primary=True)
    )
    assert r.status_code == 201, r.text
    cid = uuid.UUID(r.json()["id"])
    assert (await store.card_meta(session, seeded.shop_id, cid))["origin"] == "manual"
    for step in ("sent", "approved"):
        if step == "approved":
            ok = await seller.post(f"{DEMO}/{cid}/approve", json={})
            assert ok.status_code == 200, ok.text
        await store.set_meta(session, seeded.shop_id, cid, {"stale": True, "stale_reason": "t"})
        await session.commit()
        counts = await stale.rerun_stale(session, seeded.shop_id, now=NOW)
        await session.commit()
        assert counts["kept_manual"] == 1 and counts["revised"] == counts["replaced"] == 0
        p = await session.get(ShopProposal, cid)
        assert p.status == step and p.revision == 1
        successors = (
            await session.scalars(select(ShopProposal).where(ShopProposal.supersedes_id == cid))
        ).all()
        assert successors == []
