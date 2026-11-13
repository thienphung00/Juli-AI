"""P97 D85.6: approval queues fill jobs for the token's shop; the Connector's routes serve only
its own shop's open jobs and move them forward; the voucher id it captures feeds read-back.
SQLite; synthetic shops."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, update

from juli_backend.models.ingest import PlatformDailyMetric
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_fill import ShopeeFillJob
from juli_backend.services import ingest as ingest_service
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.ingest import pairing
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import fill_queue
from juli_backend.services.shopee_recommendations.loader import load_env
from juli_backend.services.shopee_recommendations.model import Candidate
from tests.support.api import authenticate, build_app, client_for
from tests.support.shopee_analytics import voucher_rows
from tests.support.shopee_reco import AS_OF, seed_reco_shop
from tests.unit.test_shopee_reco_routes import NOW, _persist, _publish

JOBS = "/v1/ingest/fill-jobs"


@pytest.fixture(autouse=True)
def _flag_on(monkeypatch):
    monkeypatch.setenv("CONNECTOR_FILL_LISTING", "1")


def _cands(budget=120_000):
    return [
        Candidate(
            "min_spend_voucher",
            ("1002",),
            {"value": 3000, "min_spend": 90_000, "quantity": 50, "days": 14},
            wiring_key="aov",
        ),
        Candidate(
            "ads_budget", (), {"daily_budget": budget}, campaign_key="cgroup1", wiring_key="views"
        ),
        Candidate("affiliate_commission", ("1001",), {"commission_pct": 9.0}, wiring_key="views"),
        Candidate(
            "product_discount", ("1001",), {"discount_pct": 15}, wiring_key="ctor", gap_pct=25.0
        ),
    ]


@pytest.fixture
async def shop(session):
    seeded = await seed_reco_shop(session)
    await session.execute(
        update(PlatformDailyMetric)
        .where(PlatformDailyMetric.dataset == "ads_campaign_daily")
        .values(extra={"daily_budget": 30_000, "roi_two_target": 3.0, "campaign_id": "160675212"})
    )
    await session.commit()
    env = await load_env(session, seeded.shop_id, as_of=AS_OF)
    ids = await _persist(session, seeded.shop_id, env, _cands())
    await _publish(session, seeded)
    return seeded, ids


async def _approve(session, seeded, card_id, **kw):
    out = await reco.decide(
        session, seeded.shop_id, card_id, decision="approve", user_id=seeded.user.id, now=NOW, **kw
    )
    await session.commit()
    return out


async def _jobs(session, seeded):
    return list(
        (
            await session.scalars(
                select(ShopeeFillJob)
                .where(ShopeeFillJob.shop_id == seeded.shop_id)
                .order_by(ShopeeFillJob.created_at, ShopeeFillJob.seq)
            )
        ).all()
    )


def test_the_voucher_code_suffix_is_five_chars_a_to_z_and_digits():
    a = fill_queue.voucher_code_suffix("JC-2611-0007", 1)
    b = fill_queue.voucher_code_suffix("JC-2611-0007", 2)
    assert a == fill_queue.voucher_code_suffix("JC-2611-0007", 1) and a != b
    for s in (a, b, fill_queue.voucher_code_suffix("JC-2612-12345", 4)):
        assert 1 <= len(s) <= 5 and s == s.upper() and s.isalnum()


def test_voucher_window_is_minute_precision_gmt7_and_ahead():
    start, end = fill_queue.voucher_window(datetime(2026, 11, 9, 3, 20), 14)
    assert start == "12:00 09-11-2026"  # 10:20 GMT+7 -> next full hour + 1 h
    assert end == "11:59 23-11-2026"


async def test_approving_a_voucher_card_queues_one_job_with_the_form_values(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    p = job.payload
    assert (job.kind, job.status, job.version) == ("voucher", "queued", 1)
    assert p["usecase"] == 1 and p["open_path"] == "/portal/marketing/vouchers/new?usecase=1"
    assert p["discount"] == {"type": "amount", "value": 3000}
    assert (p["min_spend"], p["usage_total"], p["per_buyer"]) == (90_000, 50, 1)
    assert len(p["name"]) <= 100 and len(p["code_suffix"]) <= 5 and p["product_ids"] == []


async def test_a_second_approval_call_does_not_duplicate_the_jobs(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    again = await fill_queue.enqueue_for_approval(
        session, shop_id=seeded.shop_id, proposal_id=ids[0], version=1, now=NOW
    )
    await session.commit()
    assert len(again) == 1 and len(await _jobs(session, seeded)) == 1


async def test_ads_and_affiliate_cards_queue_their_pages_and_discounts_queue_nothing(session, shop):
    seeded, ids = shop
    for card_id in ids[1:]:
        await _approve(session, seeded, card_id)
    jobs = {j.kind: j for j in await _jobs(session, seeded)}
    assert set(jobs) == {"ads_edit", "affiliate_commission"}
    ads = jobs["ads_edit"].payload
    assert (
        ads["open_path"] == "/portal/marketing/pas/product/manual-mpd/160675212"
        or ads["open_path"] == "/portal/marketing/pas/product/manual/160675212"
    )
    assert ads["budget"] == {"mode": "daily", "value": 120_000}
    aff = jobs["affiliate_commission"].payload
    assert aff["product_ids"] == ["1001"] and aff["commission_pct"] == 9.0
    assert aff["open_path"] == "/portal/web-seller-affiliate/open_campaign"


async def test_a_budget_under_shopees_minimum_is_a_failed_job_not_a_fill(session, shop):
    seeded, ids = shop
    proposal = await session.get(ShopProposal, ids[1])
    card = {
        "change_kind": "ads_budget",
        "inputs": {"daily_budget": 22_000},
        "scope": {"campaign_key": "cgroup1"},
        "change": {"target": {}},
    }
    jobs = await fill_queue.build_jobs(session, seeded.shop_id, proposal, card, 1, None, NOW)
    assert jobs[0]["status"] == "failed" and jobs[0]["error"] == "budget_below_minimum"
    assert jobs[0]["payload"] == {}


async def test_nothing_is_queued_with_the_kill_switch_off(session, shop, monkeypatch):
    monkeypatch.delenv("CONNECTOR_FILL_LISTING")
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    assert await _jobs(session, seeded) == []


# ----------------------------------------------------------------------------- routes


async def _token(session, seeded, shop_id="998877"):
    created = await ingest_service.create_pairing_code(
        session, shop=seeded.shop, user_id=seeded.user.id, now=NOW
    )
    issued = await ingest_service.redeem_pairing_code(
        session, code=created.code, platform="shopee", platform_shop_id=shop_id,
        client_label="Juli Connector test", now=NOW,
    )  # fmt: skip
    await session.commit()
    assert pairing.token_hash(issued.token)
    return {"Authorization": f"Bearer {issued.token}"}


@pytest.fixture
async def ext(session, shop):
    seeded, _ = shop
    headers = await _token(session, seeded)
    app = build_app(session)
    async with client_for(app) as client:
        client.headers.update(headers)
        yield client
    app.dependency_overrides.clear()


async def test_the_connector_gets_its_shops_open_jobs_and_moves_them_forward(session, shop, ext):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    got = (await ext.get(JOBS)).json()
    assert got["enabled"] is True and len(got["jobs"]) == 1
    job = got["jobs"][0]
    assert job["kind"] == "voucher" and job["code"].startswith("JC-")
    assert job["open_path"].startswith("/portal/marketing/vouchers/new")
    url = f"{JOBS}/{job['id']}"
    for status in ("opened", "filled", "saved"):
        assert (await ext.post(url, json={"status": status})).status_code == 200
    back = await ext.post(url, json={"status": "opened"})
    assert back.status_code == 409  # never backwards
    done = await ext.post(url, json={"status": "captured", "captured_ref": "1234567890"})
    assert done.status_code == 200 and done.json()["captured_ref"] == "1234567890"
    assert (await ext.get(JOBS)).json()["jobs"] == []  # a captured job is finished
    bad = await ext.post(url, json={"status": "captured", "captured_ref": "x y"})
    assert bad.status_code in (409, 422)


async def test_a_token_never_sees_or_moves_another_shops_jobs(session, shop, ext):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    other = await seed_reco_shop(session)  # a second shop, its own pairing
    await session.commit()
    headers = await _token(session, other, shop_id="55")
    app = build_app(session)
    async with client_for(app) as client:
        client.headers.update(headers)
        assert (await client.get(JOBS)).json()["jobs"] == []
        r = await client.post(f"{JOBS}/{job.id}", json={"status": "opened"})
        assert r.status_code == 404
    app.dependency_overrides.clear()


async def test_the_flag_off_serves_nothing(session, shop, ext, monkeypatch):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    monkeypatch.delenv("CONNECTOR_FILL_LISTING")
    assert (await ext.get(JOBS)).json() == {"enabled": False, "jobs": [], "commands": []}


async def test_the_captured_voucher_id_is_what_mark_executed_verifies(session, shop, ext):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    await ext.post(f"{JOBS}/{job.id}", json={"status": "filled"})
    await ext.post(f"{JOBS}/{job.id}", json={"status": "captured", "captured_ref": "88001"})
    await session.commit()
    # P100: the captured id on a fully saved card executes it by itself, with that id (no typing);
    # the "Đã làm" button after that is refused as already done.
    status = (await session.get(ShopProposal, ids[0])).status
    assert status == "executed"
    with pytest.raises(ProposalError):
        await reco.mark_executed(session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id)
    from juli_backend.models.card_events import CardEvent

    ev = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == ids[0], CardEvent.event_type == "executed")
        )
    ).all()
    assert ev[0].payload["change"]["target"]["voucher_id"] == "88001"


async def test_the_seller_sees_the_checklist_of_a_card(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    app = build_app(session)
    authenticate(app, user=seeded.user, shop=seeded.shop)
    async with client_for(app) as client:
        got = (await client.get(f"/v1/demo/shopee/fill-jobs?card_id={ids[0]}")).json()["data"]
        assert got["enabled"] is True and [j["status"] for j in got["jobs"]] == ["queued"]
        cancelled = await client.post(f"/v1/demo/shopee/fill-jobs/{got['jobs'][0]['id']}/cancel")
        assert cancelled.json()["data"]["status"] == "cancelled"
    app.dependency_overrides.clear()


async def test_the_voucher_list_reader_resolves_the_id_when_the_page_answer_was_missed(
    session, shop, ext
):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    await ext.post(f"{JOBS}/{job.id}", json={"status": "filled"})
    suffix = job.payload["code_suffix"]
    row = voucher_rows(seeded.shop_id)[0]
    row.program_name = "Voucher mới của Juli"
    row.extra = {"voucher_id": "70011", "voucher_code": f"ORYV{suffix}"}
    session.add(row)
    await session.commit()
    got = (await ext.get(JOBS)).json()["jobs"]
    assert got == []  # captured by the list reader: finished
    await session.refresh(job)
    assert (job.status, job.captured_ref) == ("captured", "70011")


# -- Connector 0.3.12 readers: what the new mappers post lands in the period tables ----------------


async def test_product_period_and_group_ads_posts_land_in_the_period_tables(session):
    from datetime import date

    from juli_backend.models.platform_data import PlatformPeriodMetric
    from tests.unit.test_ingest_gateway import _body, _ingest, _shopee_tenant

    _, other = await _shopee_tenant(session)
    period = {"start": "2026-10-01", "end": "2026-10-10", "granularity": "period"}
    item = {"item_id": "1001", "item_name": "Sản phẩm", "sales": 700000, "orders": 8, "units": 9}
    item |= {"buyers": 7, "ctr": 0.05, "conversion_rate": 0.18, "product_visitors": 45}
    variation = {"item_id": "1001", "variation_id": "5001", "sales": 400000, "orders": 4}
    for order_type in ("confirmed", "placed"):
        body = _body([item, variation], period=period, order_type=order_type)
        await _ingest(session, other, "product_period", body)
    ad = {"campaign_name": "Chiến dịch nhóm A", "item_id": "1001", "ordinal": 0}
    ad |= {"ads_impressions": 2000, "ad_clicks": 80, "ctr": 0.04, "ads_expense": 150000}
    ad |= {"sales": 900000, "direct_sales": 600000}
    await _ingest(
        session, other, "ads_campaign_period", _body([ad], period=period, order_type="placed")
    )
    rows = (
        await session.scalars(
            select(PlatformPeriodMetric).where(PlatformPeriodMetric.shop_id == other.id)
        )
    ).all()
    by = {(r.dataset, r.order_type, r.item_id, r.variation_id or "") for r in rows}
    assert ("product_period", "confirmed", "1001", "") in by
    assert ("product_period", "placed", "1001", "5001") in by
    assert any(r.dataset == "ads_campaign_period" and r.stream == "ads" for r in rows)
    assert all(r.period_start == date(2026, 10, 1) for r in rows)


def _combo_card(change_kind="bundle_deal", **inputs):
    return {
        "change_kind": change_kind,
        "inputs": inputs,
        "scope": {"product_ids": ["1001", "1003"]},
    }


async def _combo_jobs(session, seeded, card):
    p = await session.scalar(select(ShopProposal).where(ShopProposal.shop_id == seeded.shop_id))
    assert p is not None
    return await fill_queue.build_jobs(session, seeded.shop_id, p, card, 1, None, NOW)


async def test_a_combo_card_becomes_a_validated_combo_job(session, shop):
    seeded, _ = shop
    card = _combo_card(
        discount_type="amount",
        tiers=[{"qty": 2, "value": 5000}, {"qty": 4, "value": 12000}],
        limit_per_buyer=3,
        start="2026-11-20",
        end="2026-12-05",
    )
    (job,) = await _combo_jobs(session, seeded, card)
    pl = job["payload"]
    assert (job["kind"], job["status"], job["error"]) == ("combo", "queued", None)
    assert pl["open_path"] == "/portal/marketing/bundle/new"
    assert pl["discount_type"] == "amount" and pl["purchase_limit"] == 3
    assert pl["tiers"] == [{"qty": 2, "value": 5000}, {"qty": 4, "value": 12000}]
    assert pl["product_ids"] == ["1001", "1003"]
    assert (pl["starts_at"], pl["ends_at"]) == ("00:00 20-11-2026", "23:59 05-12-2026")
    assert 0 < len(pl["name"]) <= fill_queue.MAX_COMBO_NAME


async def test_a_generated_bundle_card_fills_as_two_percent_tiers_with_a_long_name_cut(
    session, shop
):
    seeded, _ = shop
    (job,) = await _combo_jobs(
        session, seeded, _combo_card(tier2_pct=5, tier3_pct=8, name="N" * 40)
    )
    assert job["payload"]["tiers"] == [{"qty": 2, "value": 5}, {"qty": 3, "value": 8}]
    assert job["payload"]["discount_type"] == "pct" and len(job["payload"]["name"]) == 25
    assert "purchase_limit" not in job["payload"]


@pytest.mark.parametrize(
    "inputs",
    [
        {"tiers": []},
        {"tiers": [{"qty": 3, "value": 5}, {"qty": 2, "value": 8}]},
        {"tiers": [{"qty": 2, "value": 5}, {"qty": 2, "value": 8}]},
        {"tiers": [{"qty": 2, "value": 100}]},
        {"tiers": [{"qty": 2, "value": 0}], "discount_type": "amount"},
        {"tiers": [{"qty": 2, "value": 0}], "discount_type": "special_price"},
        {"tiers": [{"qty": 2, "value": 5}], "discount_type": "free"},
        {"tiers": [{"qty": 2, "value": 5}], "limit_per_buyer": 1_000_000_000},
    ],
)
async def test_a_combo_with_bad_tiers_is_a_failed_job_not_a_fill(session, shop, inputs):
    seeded, _ = shop
    (job,) = await _combo_jobs(session, seeded, _combo_card(**inputs))
    assert (job["status"], job["error"], job["payload"]) == ("failed", "combo_incomplete", {})


async def test_a_legacy_basket_combo_is_failed_with_a_vietnamese_reason(session, shop):
    seeded, _ = shop
    (job,) = await _combo_jobs(session, seeded, _combo_card("combo_multi"))
    assert job["status"] == "failed" and job["kind"] == "combo"
    assert job["error"] == "Combo kiểu cũ — tạo lại theo mức ưu đãi của Shopee"
    assert len(job["error"]) <= 64
