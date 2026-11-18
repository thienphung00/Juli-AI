"""batch-1118f t1 (F1.1 - F1.4, F1.8, E22): a second execution after a revert reuses the day's
change set; withdrawn / reverted cards' jobs are never served; manual cards survive the stale
recompute; reverted cards leave Thực hiện; a sheet's "before" survives a cancelled job.
SQLite, synthetic shops. The unique-index behaviour on Postgres is proven by the gate."""

from __future__ import annotations

from sqlalchemy import select

from juli_backend.models.shop_proposals import STATUS_APPROVED, STATUS_EXECUTED, ShopProposal
from juli_backend.models.shopee_fill import STATUS_CANCELLED, STATUS_QUEUED
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shopee_recommendations import (
    change_sets,
    config,
    execution_state,
    fill,
    fill_queue,
    listing,
    sheet,
    stale,
    store,
)
from tests.unit import test_p97_fill_queue as _p97

NOW = _p97.NOW
_approve = _p97._approve
_jobs = _p97._jobs
shop = _p97.shop  # the shared fixture, re-exported
_flag_on = _p97._flag_on  # the autouse switch


async def _executed(session, seeded, card_id):
    await reco.mark_executed(session, seeded.shop_id, card_id, now=NOW, user_id=seeded.user.id)
    await session.commit()


# ------------------------------------------------------------------------------ F1.1


async def test_executing_after_a_revert_reopens_the_days_cut_set(session, shop):
    seeded, ids = shop
    a, b = ids[2], ids[3]  # two cards on the same product, same day
    await _approve(session, seeded, a)
    await _approve(session, seeded, b)
    await _executed(session, seeded, a)
    await reco.mark_reverted(session, seeded.shop_id, a, now=NOW, user_id=seeded.user.id)
    await session.commit()
    (only,) = await change_sets.sets_for(session, seeded.shop_id)
    assert only.status == change_sets.SET_CUT

    await _executed(session, seeded, b)  # used to hit uq_shop_reco_change_sets_product_day

    (cs,) = await change_sets.sets_for(session, seeded.shop_id)
    assert cs.id == only.id and cs.status == change_sets.SET_MEASURING
    assert cs.card_ids == [str(b)] and cs.cut_at is None and cs.cut_days is None
    assert str(a) in (cs.result or {}).get("reset_card_ids", [])  # A stays out of the measurement
    assert "state" not in (cs.result or {})
    meta = await store.card_meta(session, seeded.shop_id, b)
    assert meta["change_set"] == str(cs.id) and not meta.get("measure_cut_at")


# ------------------------------------------------------------------------------ F1.2


async def test_withdraw_and_revert_cancel_the_open_jobs_and_nothing_is_served(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])  # voucher: one queued job
    await _approve(session, seeded, ids[2])  # affiliate: one queued job
    assert {j.status for j in await _jobs(session, seeded)} == {STATUS_QUEUED}

    await reco.withdraw(session, seeded.shop_id, ids[0], now=NOW)
    await _executed(session, seeded, ids[2])
    await reco.mark_reverted(session, seeded.shop_id, ids[2], now=NOW, user_id=seeded.user.id)
    await session.commit()

    assert {j.status for j in await _jobs(session, seeded)} == {STATUS_CANCELLED}
    assert await fill_queue.jobs_for_shop(session, seeded.shop_id) == []


async def test_a_queued_job_of_a_non_approved_card_is_never_served(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    assert len(await fill_queue.jobs_for_shop(session, seeded.shop_id)) == 1
    p = await session.get(ShopProposal, ids[0])
    p.status = "withdrawn"  # the job is still queued: the card status alone keeps it off the poll
    await session.flush()
    assert job.status == STATUS_QUEUED
    assert await fill_queue.jobs_for_shop(session, seeded.shop_id) == []
    assert fill_queue.SERVABLE_CARD_STATUSES == (STATUS_APPROVED, "planned")


# ------------------------------------------------------------------------------ F1.3


async def _flag_stale(session, shop_id, card_id):
    await store.set_meta(session, shop_id, card_id, {"stale": True, "stale_reason": "t"})
    await session.commit()


async def test_a_stale_run_leaves_a_manual_card_untouched(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await store.set_meta(session, seeded.shop_id, ids[0], {"origin": "manual"})
    await _flag_stale(session, seeded.shop_id, ids[0])
    counts = await stale.rerun_stale(session, seeded.shop_id, now=NOW)
    p = await session.get(ShopProposal, ids[0])
    assert counts["kept_manual"] == 1 and counts["revised"] == counts["replaced"] == 0
    assert p.status == STATUS_APPROVED and p.revision == 1
    others = (
        await session.scalars(select(ShopProposal).where(ShopProposal.supersedes_id == p.id))
    ).all()
    assert others == []


async def test_an_approved_generated_card_is_not_re_issued_either(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _flag_stale(session, seeded.shop_id, ids[0])
    counts = await stale.rerun_stale(session, seeded.shop_id, now=NOW)
    assert counts["kept_approved"] == 1 and counts["revised"] == 0
    assert (await session.get(ShopProposal, ids[0])).status == STATUS_APPROVED


# ------------------------------------------------------------------------------ F1.4


async def test_a_reverted_card_leaves_thuc_hien_and_measurement(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[2])
    await _approve(session, seeded, ids[3])
    await _executed(session, seeded, ids[2])
    await _executed(session, seeded, ids[3])
    await reco.mark_reverted(session, seeded.shop_id, ids[2], now=NOW, user_id=seeded.user.id)
    await session.commit()
    listed = {
        c["card_id"]
        for c in (await execution_state.execution_states(session, seeded.shop_id, now=NOW))["cards"]
    }
    assert str(ids[2]) not in listed and str(ids[3]) in listed
    measured = {
        c["card_id"]
        for c in (await execution_state.measurement_states(session, seeded.shop_id, now=NOW))[
            "cards"
        ]
    }
    assert str(ids[2]) not in measured
    assert str(ids[2]) in await store.reset_card_ids(session, seeded.shop_id)  # not learned from
    assert (await session.get(ShopProposal, ids[2])).status == STATUS_EXECUTED  # status unchanged
    detail = await reco.card_detail(session, seeded.shop_id, ids[2], audience="seller")
    assert detail["reverted"]["by"] == f"user:{seeded.user.id}" and detail["reverted"]["at"]


# ------------------------------------------------------------------------------ F1.8


def test_the_first_job_holding_a_before_value_fills_the_step():
    base = sheet.build_sheet(
        "description_first_line", {"item_id": "1001"}, {"first_line": None},
        {"first_line": "Dòng mới"}, {}, names={"1001": "Sản phẩm mẫu"}, items=[],
    )  # fmt: skip
    jobs = [
        {"payload": {}},
        {"payload": {"before_values": {"first_line": "Dòng cũ đầu"}}},
        {"payload": {"before_values": {"first_line": "Dòng sau khi sửa"}}},
    ]
    got = sheet.with_job_before(base, jobs)
    assert got["steps"][0]["before"] == "Dòng cũ đầu"
    assert got["steps"][0]["before_source"] == "connector"
    # a value the card already holds is never replaced
    kept = sheet.with_job_before(
        sheet.build_sheet(
            "description_first_line",
            {"item_id": "1001"},
            {"first_line": "Của thẻ"},
            {"first_line": "Dòng mới"},
            {},
            names={"1001": "Sản phẩm mẫu"},
            items=[],
        ),  # fmt: skip
        jobs,
    )
    assert kept["steps"][0]["before"] == "Của thẻ"


async def test_a_cancelled_job_still_gives_the_sheet_its_before(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    job.payload = {**job.payload, "before_values": {"min_spend": "x"}}
    job.status = STATUS_CANCELLED
    await session.flush()
    from juli_backend.services.shopee_recommendations import service

    rows = await service._job_rows(session, seeded.shop_id, ids[0])
    assert rows and rows[0]["payload"]["before_values"] == {"min_spend": "x"}


# ------------------------------------------------------------------------------ E22


def test_the_description_first_line_limit_is_one_constant_of_300():
    assert config.MAX_DESCRIPTION_FIRST_LINE_CHARS == 300
    assert fill_queue._TEXT_FIELDS["description_first_line"]["max_chars"] == 300
    assert fill.FIELDS["description_first_line"]["max_chars"] == 300
    assert listing.MAX_DESCRIPTION_LINE_CHARS == 300
