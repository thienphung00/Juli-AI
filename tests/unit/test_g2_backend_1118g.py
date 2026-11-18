"""batch-1118g t2 (F3.1 revert-fill, F3.2 read-back, contract D): the undo of an executed card
is queued for the Connector (never pressed), served only for an executed card, confirmed by a
read-back before "Đã hoàn tác"; a read-back job follows "Đã làm" and each saved revert job.
SQLite, synthetic shops. The serving rule on Postgres is proven by the gate."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select

from juli_backend.models.shopee_fill import (
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import fill_queue, revert_fill
from tests.unit import test_p97_fill_queue as _p97

NOW = _p97.NOW
_approve = _p97._approve
_jobs = _p97._jobs
shop = _p97.shop
_flag_on = _p97._flag_on


async def _executed(session, seeded, card_id, voucher_id=None):
    await reco.mark_executed(
        session, seeded.shop_id, card_id, now=NOW, user_id=seeded.user.id, voucher_id=voucher_id
    )
    await session.commit()


def _fake(kind, payload=None, target=None, ref=None, key="k"):
    return ShopeeFillJob(
        id=uuid.uuid4(), kind=kind, payload=payload or {}, target=target or {},
        captured_ref=ref, target_key=key, seq=1, version=1, status=STATUS_SAVED,
    )  # fmt: skip


# ---------------------------------------------------------------------- job builders (pure)


def test_a_text_revert_job_puts_the_captured_before_value_back():
    fwd = _fake(
        "title", {"before_values": {"title": "Old name"}}, {"item_id": "1001"}, key="title:1001"
    )
    spec = revert_fill._revert_spec(fwd, {"title": "ignored"})
    assert spec["kind"] == "title" and spec["target_key"] == "revert:title:1001"
    assert spec["error"] is None
    p = spec["payload"]
    assert p["mode"] == "revert" and p["open_path"] == "/portal/product/1001"
    assert p["fields"][0]["key"] == "title" and p["fields"][0]["value"] == "Old name"


def test_a_text_revert_falls_back_to_the_cards_change_before_then_fails():
    fwd = _fake("description_first_line", {}, {"item_id": "1001"})
    spec = revert_fill._revert_spec(fwd, {"first_line": "Dòng đầu cũ"})
    assert spec["payload"]["fields"][0]["value"] == "Dòng đầu cũ" and spec["error"] is None
    unknown = revert_fill._revert_spec(fwd, {})
    assert unknown["error"] == "revert_value_unknown"


def test_voucher_and_combo_revert_jobs_only_name_the_object_to_end():
    v = revert_fill._revert_spec(
        _fake("voucher", {"code_suffix": "AB12C", "name": "Voucher X"}, ref="777"), {}
    )
    assert v["kind"] == "voucher_end" and v["target_key"] == "revert:voucher:777"
    assert v["payload"] == {
        "mode": "revert",
        "open_path": "/portal/marketing/vouchers/list",
        "voucher_id": "777",
        "code": "ORYVAB12C",
        "name": "Voucher X",
    }
    c = revert_fill._revert_spec(_fake("combo", {"name": "Combo A"}), {})
    assert c["kind"] == "combo_end" and c["payload"]["open_path"].endswith("/bundle/list")
    assert c["payload"]["name"] == "Combo A" and c["target_key"] == "revert:combo:Combo A"


def test_an_affiliate_revert_carries_the_before_commission():
    fwd = _fake("affiliate_commission", {"product_ids": ["1001"], "commission_pct": 9})
    spec = revert_fill._revert_spec(fwd, {"commission_pct": 5})
    assert spec["kind"] == "affiliate_commission" and spec["payload"]["mode"] == "revert"
    assert spec["payload"]["commission_pct"] == 5.0
    assert revert_fill._revert_spec(fwd, {})["error"] == "revert_value_unknown"


def test_readback_specs_name_the_page_and_dataset():
    t = revert_fill._readback_of_change("title", {"item_id": "9"})
    assert t["key"] == "readback:9" and t["datasets"] == ["item_catalog"]
    assert t["target"] == {"item_id": "9"}
    v = revert_fill._readback_of_change("voucher", {"voucher_id": "5"})
    assert v["key"] == "readback:voucher:5" and v["datasets"] == ["voucher_list"]
    assert revert_fill._readback_of_change("combo", {"name": "x"}) is None


# ------------------------------------------------------------------------------ DB flow


async def test_revert_fill_is_refused_unless_the_card_is_executed(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    with pytest.raises(ProposalError) as err:
        await revert_fill.revert_fill(session, seeded.shop_id, ids[0], now=NOW)
    assert err.value.code == "card_not_executed" and err.value.status == 409


async def test_executing_queues_a_readback_and_an_executed_card_serves_only_revert_and_readback(
    session, shop
):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _executed(session, seeded, ids[0], voucher_id="555")
    rows = await _jobs(session, seeded)
    (rb,) = [j for j in rows if j.kind == "readback"]
    assert rb.target_key == "readback:voucher:555" and rb.status == STATUS_QUEUED
    assert rb.payload["mode"] == "readback" and rb.payload["target"] == {"voucher_id": "555"}
    served = await fill_queue.jobs_for_shop(session, seeded.shop_id)
    assert [j["kind"] for j in served] == ["readback"]  # the forward voucher job is not served

    out = await revert_fill.revert_fill(session, seeded.shop_id, ids[0], now=NOW)
    await session.commit()
    assert out["ready"] is False and [j["kind"] for j in out["jobs"]] == ["voucher_end"]
    assert out["jobs"][0]["payload"]["mode"] == "revert"
    served = await fill_queue.jobs_for_shop(session, seeded.shop_id)
    assert {j["kind"] for j in served} == {"readback", "voucher_end"}
    again = await revert_fill.revert_fill(session, seeded.shop_id, ids[0], now=NOW)
    assert len(again["jobs"]) == 1  # idempotent


async def test_reverted_is_refused_until_the_readback_confirms_unless_manual(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _executed(session, seeded, ids[0], voucher_id="555")
    await revert_fill.revert_fill(session, seeded.shop_id, ids[0], now=NOW)
    await session.commit()
    with pytest.raises(ProposalError) as err:
        await reco.mark_reverted(session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id)
    assert err.value.code == "revert_not_confirmed" and err.value.status == 409

    detail = await reco.card_detail(session, seeded.shop_id, ids[0], audience="seller")
    assert detail["revert"]["ready"] is False and len(detail["revert"]["jobs"]) == 1

    out = await reco.mark_reverted(
        session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id, manual=True
    )
    assert out["reverted"] is True


async def test_a_saved_revert_queues_a_readback_and_ready_needs_the_object_ended(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _executed(session, seeded, ids[0], voucher_id="555")
    await revert_fill.revert_fill(session, seeded.shop_id, ids[0], now=NOW)
    await session.commit()
    later = NOW + timedelta(minutes=5)
    rev = next(j for j in await _jobs(session, seeded) if j.kind == "voucher_end")
    await fill_queue.report(session, seeded.shop_id, rev.id, status="filled", now=later)
    await fill_queue.report(session, seeded.shop_id, rev.id, status="saved", now=later)
    await session.commit()
    rb = next(j for j in await _jobs(session, seeded) if j.kind == "readback")
    assert rb.status == STATUS_QUEUED  # queued again after the revert

    state = await revert_fill.revert_state(session, seeded.shop_id, ids[0])
    assert state["ready"] is False  # saved, but no read-back after it yet
    await fill_queue.report(
        session, seeded.shop_id, rb.id, status=STATUS_CAPTURED, now=later + timedelta(minutes=1)
    )
    await session.commit()
    state = await revert_fill.revert_state(session, seeded.shop_id, ids[0])
    assert state["ready"] is True  # the voucher is gone from the list read-back
    out = await reco.mark_reverted(session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id)
    assert out["reverted"] is True


async def test_a_readback_job_never_auto_executes_or_fails_the_card(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (fwd,) = await _jobs(session, seeded)
    for status in ("filled", "saved"):
        await fill_queue.report(session, seeded.shop_id, fwd.id, status=status, now=NOW)
    await fill_queue.report(
        session, seeded.shop_id, fwd.id, status="captured", captured_ref="42", now=NOW
    )
    await session.commit()
    kinds = sorted(j.kind for j in await _jobs(session, seeded))
    assert kinds == ["readback", "voucher"]  # auto-executed, one read-back
    rows = await session.scalars(select(ShopeeFillJob).where(ShopeeFillJob.kind == "readback"))
    assert all(j.status != STATUS_FAILED for j in rows)


# ------------------------------------------------------------------- contract D (E20 / E50)

from juli_backend.models.platform_data import PlatformItem  # noqa: E402
from juli_backend.services.ingest.rate_limit import (  # noqa: E402
    InMemoryRateGate,
    set_ingest_rate_gate,
)
from tests.unit.test_shopee_builder import AS_OF as BUILDER_AS_OF  # noqa: E402
from tests.unit.test_shopee_builder import shop as builder_shop  # noqa: E402,F401
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop  # noqa: E402
from tests.unit.test_shopee_reader_datasets import _post  # noqa: E402


@pytest.fixture
def generous_gate():
    set_ingest_rate_gate(InMemoryRateGate())
    yield
    set_ingest_rate_gate(None)


async def test_a_partial_catalog_row_merges_without_blanking_the_name(session, generous_gate):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post(
            [{"item_id": "1001", "item_name": "Găng tay", "description_first_line": "Dòng đầu"}],
            "2026-10-29",
            "period",
        ),
    )
    await _ingest(
        session,
        shop,
        "item_catalog",
        _post([{"item_id": "1001", "commission_pct": 7.5}], "2026-10-30", "period"),
    )
    (item,) = await _rows(session, PlatformItem, shop)
    assert item.name == "Găng tay"
    assert item.extra["description_first_line"] == "Dòng đầu"  # kept
    assert item.extra["affiliate_commission_pct"] == 7.5
    assert item.extra["affiliate_commission_pct_at"] and item.extra["description_first_line_at"]


async def test_the_picker_and_a_new_description_card_carry_the_current_values(
    session,
    builder_shop,  # noqa: F811
):
    from sqlalchemy import update

    from juli_backend.services.shopee_builder import service as builder

    await session.execute(
        update(PlatformItem)
        .where(PlatformItem.shop_id == builder_shop.shop_id, PlatformItem.item_id == "1001")
        .values(
            extra={"description_first_line": "Dòng đầu hiện tại", "affiliate_commission_pct": 6.0}
        )
    )
    await session.commit()
    out = await builder.products(session, builder_shop.shop_id, as_of=BUILDER_AS_OF)
    by = {p["item_id"]: p for p in out["products"]}
    assert by["1001"]["current_first_line"] == "Dòng đầu hiện tại"
    assert by["1001"]["current_commission_pct"] == 6.0
    assert by["1002"]["current_first_line"] is None and by["1002"]["current_commission_pct"] is None

    from juli_backend.services.shopee_builder import specs as sp
    from juli_backend.services.shopee_builder.translate import to_variant
    from juli_backend.services.shopee_recommendations import loader

    spec = sp.DescriptionSpec(kind="description_first_line", item_id="1001", first_line="Mới")
    env = await loader.load_env(session, builder_shop.shop_id, as_of=BUILDER_AS_OF, now=_p97.NOW)
    ctx = await builder.build_context(
        session, builder_shop.shop_id, [spec], as_of=BUILDER_AS_OF, now=_p97.NOW, env=env
    )
    got = to_variant(spec, ctx).variant["extra"]
    assert got["current_first_line"] == "Dòng đầu hiện tại"
