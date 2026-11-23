"""batch-1118g t2 (F3.1 revert-fill, F3.2 read-back, contract D): the undo of an executed card
is queued for the Connector (never pressed), served only for an executed card, confirmed by a
read-back before "Đã hoàn tác"; a read-back job follows "Đã làm" and each saved revert job.
SQLite, synthetic shops. The serving rule on Postgres is proven by the gate."""

from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from juli_backend.models.card_events import CardEvent
from juli_backend.models.platform_data import PlatformItem
from juli_backend.models.shop_proposals import ShopProposal
from juli_backend.models.shopee_connector import ShopeeConnectorTokenState
from juli_backend.models.shopee_fill import (
    STATUS_CAPTURED,
    STATUS_FAILED,
    STATUS_QUEUED,
    STATUS_SAVED,
    ShopeeFillJob,
)
from juli_backend.services import ingest as ingest_service
from juli_backend.services import shopee_recommendations as reco
from juli_backend.services.ingest.rate_limit import InMemoryRateGate, set_ingest_rate_gate
from juli_backend.services.shop_proposals import ProposalError
from juli_backend.services.shopee_recommendations import (
    connector_state,
    fill_queue,
    revert_fill,
    store,
)
from tests.support.consent import grant_service_consent
from tests.support.shopee_analytics import voucher_rows
from tests.unit import test_p97_fill_queue as _p97
from tests.unit import test_shopee_builder as _builder
from tests.unit.test_shopee_file_datasets import _ingest, _rows, _shop
from tests.unit.test_shopee_reader_datasets import _post

NOW = _p97.NOW
_approve = _p97._approve
_jobs = _p97._jobs
shop = _p97.shop
_flag_on = _p97._flag_on
builder_shop = _builder.shop
BUILDER_AS_OF = _builder.AS_OF
JOBS = _p97.JOBS


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
        "code_suffix": "AB12C",
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
    c = revert_fill._readback_of_change("combo", {"name": "x"})  # S-E118: a combo is read back
    assert c["key"] == "readback:combo:x" and c["target"] == {"combo_name": "x"}
    assert c["datasets"] == ["combo_list"] and c["open_path"].endswith("/bundle/list")
    assert revert_fill._readback_of_change("combo", {}) is None


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
    assert state["ready"] is False  # a read-back job alone proves nothing: no voucher data at all
    other = voucher_rows(seeded.shop_id)[0]
    other.program_name = "Voucher khác"
    other.extra = {"voucher_id": "999"}  # another voucher, from a list captured after the save
    other.captured_at = later + timedelta(minutes=2)
    session.add(other)
    await session.commit()
    state = await revert_fill.revert_state(session, seeded.shop_id, ids[0])
    assert state["ready"] is True  # that list lacks voucher 555
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
    builder_shop,
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


# ------------------------------------------------------------- read-back ingest, E32, reconcile


ext = _p97.ext


async def test_a_voucher_readback_ingest_verifies_the_card_at_once(session, shop, generous_gate):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _executed(session, seeded, ids[0], voucher_id="555")
    ev = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == ids[0], CardEvent.event_type == "executed")
        )
    ).one()
    expected = ev.payload["change"]["expected"]
    stamp = (_p97.NOW + timedelta(hours=2)).isoformat() + "+00:00"
    body = _post(
        [
            {
                "voucher_id": "555",
                "program_name": "Voucher thử",
                "starts_at": "2026-10-01T00:00:00",
                "ends_at": "2026-12-31T23:59:59",
                **expected,
            }
        ],
        _p97.NOW.date().isoformat(),
        "period",
        captured_at=stamp,
    )
    assert await _verification_events(session, ids[0]) == []
    await grant_service_consent(session, seeded.shop_id)
    await ingest_service.ingest(
        session,
        shop_id=seeded.shop_id,
        platform="shopee",
        dataset="voucher_settings",
        body=ingest_service.IngestBody.model_validate(body),
        token_id=None,
        now=_p97.NOW + timedelta(hours=3),
    )
    assert await _verification_events(session, ids[0]) == ["verified"]  # not at 01:17Z


async def _verification_events(session, card_id):
    rows = await session.scalars(
        select(CardEvent.event_type).where(
            CardEvent.card_id == card_id,
            CardEvent.event_type.in_(("verified", "mismatch", "not_seen")),
        )
    )
    return list(rows)


async def test_reconcile_queues_a_readback_for_every_pending_executed_card(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _executed(session, seeded, ids[0], voucher_id="555")
    (rb,) = [j for j in await _jobs(session, seeded) if j.kind == "readback"]
    rb.status = STATUS_CAPTURED  # an earlier read-back is finished, the card is still pending
    await session.commit()
    out = await connector_state.request_reconcile(session, seeded.shop_id, now=NOW)
    await session.commit()
    assert out["requested"] is True and out["readbacks"] == 1
    (rb,) = [j for j in await _jobs(session, seeded) if j.kind == "readback"]
    await session.refresh(rb)
    assert rb.status == STATUS_QUEUED


async def test_the_poll_stores_the_connector_version_per_computer(session, shop, ext):
    seeded, _ = shop
    r = await ext.get(JOBS, params={"sc_open": "true"}, headers={"X-Connector-Version": "0.3.31"})
    assert r.status_code == 200
    rows = await session.scalars(
        select(ShopeeConnectorTokenState).where(ShopeeConnectorTokenState.shop_id == seeded.shop_id)
    )
    assert [r.connector_version for r in rows] == ["0.3.31"]


# ----------------------------------------------------------------------------- F2.2 / E40


async def test_a_manual_product_voucher_queues_usecase_two_with_the_cards_products(session, shop):
    seeded, ids = shop
    p = await session.get(ShopProposal, ids[0])
    card = await store.card_payload(session, seeded.shop_id, ids[0])
    card["scope"] = {"level": "shop", "product_ids": ["1002", "1003"]}  # the kind's default level
    card["candidate_extra"] = {"voucher_scope": "product"}
    (job,) = await fill_queue.build_jobs(session, seeded.shop_id, p, card, 1, None, NOW)
    assert job["payload"]["usecase"] == 2 and job["payload"]["product_ids"] == ["1002", "1003"]
    assert job["payload"]["open_path"].endswith("usecase=2")
    card["candidate_extra"] = {"voucher_scope": "shop"}  # a shop voucher stays shop-wide
    (job,) = await fill_queue.build_jobs(session, seeded.shop_id, p, card, 1, None, NOW)
    assert job["payload"]["usecase"] == 1 and job["payload"]["product_ids"] == []


# ------------------------------------------------------------------------------ F2.3 / E46


async def test_executed_expects_the_saved_forms_values_and_keeps_the_cards(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    (job,) = await _jobs(session, seeded)
    job.payload = {
        **job.payload,
        "fill_check": [
            {"key": "min_spend", "ok": False, "seen": "100.000"},
            {"key": "usage_total", "ok": True, "seen": "50"},
        ],
    }
    job.captured_ref = "555"
    await session.commit()
    await reco.mark_executed(session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id)
    await session.commit()  # no typed voucher id: the captured one is used
    ev = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == ids[0], CardEvent.event_type == "executed")
        )
    ).one()
    change = ev.payload["change"]
    assert change["target"]["voucher_id"] == "555"
    assert change["expected"]["min_spend"] == 100_000 and change["expected"]["usage_limit"] == 50
    assert change["card_expected"] == {"min_spend": 90_000}


# ----------------------------------------------------------------------- verifier follow-ups


async def test_an_ended_or_listed_voucher_is_judged_on_a_list_read_after_the_save(session, shop):
    seeded, _ = shop
    since = _p97.NOW + timedelta(minutes=5)
    assert await revert_fill._voucher_ended(session, seeded.shop_id, "555", since) is False
    live = voucher_rows(seeded.shop_id)[0]
    live.program_name = "Voucher sống"
    live.extra = {"voucher_id": "555"}
    live.status = "ongoing"
    live.captured_at = since + timedelta(minutes=1)
    old = voucher_rows(seeded.shop_id)[1]
    old.program_name = "Voucher cũ"
    old.extra = {"voucher_id": "999"}
    old.captured_at = since - timedelta(minutes=30)  # before the save: does not count
    session.add_all([live, old])
    await session.commit()
    assert await revert_fill._voucher_ended(session, seeded.shop_id, "555", since) is False
    live.status = "ended"
    await session.commit()
    assert await revert_fill._voucher_ended(session, seeded.shop_id, "555", since) is True


async def test_an_affiliate_commission_read_before_the_save_does_not_confirm(session, shop):
    from sqlalchemy import update

    seeded, _ = shop
    job = _fake("affiliate_commission", {"product_ids": ["1001"], "commission_pct": 5.0})
    since = _p97.NOW
    for at, ok in (((since - timedelta(hours=1)), False), ((since + timedelta(hours=1)), True)):
        await session.execute(
            update(PlatformItem)
            .where(PlatformItem.shop_id == seeded.shop_id, PlatformItem.item_id == "1001")
            .values(
                extra={
                    "affiliate_commission_pct": 5.0,
                    "affiliate_commission_pct_at": at.isoformat(),
                }
            )
        )
        await session.commit()
        got = await revert_fill._affiliate_matches(session, seeded.shop_id, job, since)
        assert got is ok


async def test_a_queued_or_failed_readback_is_no_step_and_never_fails_the_card(session, shop):
    from juli_backend.services.shopee_recommendations import execution_state

    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await _executed(session, seeded, ids[0], voucher_id="555")
    (rb,) = [j for j in await _jobs(session, seeded) if j.kind == "readback"]

    def card_of(out):
        return next(c for c in out["cards"] if c["card_id"] == str(ids[0]))

    before = card_of(await execution_state.execution_states(session, seeded.shop_id, now=NOW))
    rb.status, rb.error = STATUS_FAILED, "readback_unsupported"
    await session.commit()
    after = card_of(await execution_state.execution_states(session, seeded.shop_id, now=NOW))
    assert after["state"] == before["state"] != "failed"
    assert after["jobs"] == before["jobs"] and after["jobs"]["failed"] == 0
    assert after["fields"] == before["fields"]


async def test_a_verification_bug_never_fails_the_ingest(session, shop, generous_gate, monkeypatch):
    from juli_backend.services.card_events import verification

    seeded, ids = shop
    await grant_service_consent(session, seeded.shop_id)

    async def boom(*args, **kwargs):
        raise TypeError("evaluator bug")

    monkeypatch.setattr(verification, "verify_objects", boom)
    stamp = (_p97.NOW + timedelta(hours=2)).isoformat() + "+00:00"
    body = _post(
        [{"item_id": "1001", "item_name": "Găng tay"}],
        _p97.NOW.date().isoformat(),
        "period",
        captured_at=stamp,
    )
    await ingest_service.ingest(
        session,
        shop_id=seeded.shop_id,
        platform="shopee",
        dataset="item_catalog",
        body=ingest_service.IngestBody.model_validate(body),
        token_id=None,
        now=_p97.NOW + timedelta(hours=3),
    )
    items = await _rows(session, PlatformItem, SimpleNamespace(id=seeded.shop_id))
    assert {i.name for i in items if i.item_id == "1001"} == {"Găng tay"}
    # the post was stored although the verification raised


async def test_the_voucher_payload_carries_the_smart_flag_default_off(session, shop):
    seeded, ids = shop
    p = await session.get(ShopProposal, ids[0])
    card = await store.card_payload(session, seeded.shop_id, ids[0])
    (job,) = await fill_queue.build_jobs(session, seeded.shop_id, p, card, 1, None, NOW)
    assert job["payload"]["smart"] is False
    card["smart"] = True
    (job,) = await fill_queue.build_jobs(session, seeded.shop_id, p, card, 1, None, NOW)
    assert job["payload"]["smart"] is True


# ------------------------------------------------------------ batch-1123-a2 Track S (K1 / K3 / K4)


async def test_a_typed_code_is_kept_as_a_code_and_still_queues_a_readback(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await reco.mark_executed(
        session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id, voucher_id="oryvab12c"
    )
    await session.commit()
    ev = (
        await session.scalars(
            select(CardEvent).where(CardEvent.card_id == ids[0], CardEvent.event_type == "executed")
        )
    ).one()
    target = ev.payload["change"]["target"]
    assert "voucher_id" not in target
    assert target["voucher_code"] == "ORYVAB12C" and target["code_suffix"] == "AB12C"
    back = [j for j in await _jobs(session, seeded) if j.kind == "readback"]
    assert len(back) == 1 and back[0].target["voucher_code"] == "ORYVAB12C"
    assert back[0].payload["forward_kind"] == "voucher"


async def test_marking_done_with_no_id_and_no_code_reads_back_by_the_card_name(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    await reco.mark_executed(session, seeded.shop_id, ids[0], now=NOW, user_id=seeded.user.id)
    await session.commit()  # S-E118: no 422 any more
    (back,) = [j for j in await _jobs(session, seeded) if j.kind == "readback"]
    assert back.target.get("name")


async def test_the_card_detail_carries_the_current_job_and_the_done_button(session, shop):
    seeded, ids = shop
    await _approve(session, seeded, ids[0])
    detail = await reco.card_detail(session, seeded.shop_id, ids[0], audience="seller")
    assert detail["can_mark_done"] is True
    job = detail["job"]
    assert job["role"] == "forward" and job["kind"] == "voucher"
    assert job["status_label"] == "Chờ điền" and job["open_path"]
    assert job["readback"] == {"result": None, "diffs": []}
    listing = await reco.list_cards(session, seeded.shop_id, audience="seller")
    mine = next(c for c in listing["cards"] if c["id"] == str(ids[0]))
    assert mine["job"]["job_id"] == job["job_id"] and mine["can_mark_done"] is True
