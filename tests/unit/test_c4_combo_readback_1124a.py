"""batch-1124-a C4: the Combo Khuyến Mãi read-back.

Connector 0.3.35's combos reader posts ``combo_settings`` (the contract body the Connector's
contract test pins); it lands in ``platform_promotions`` as ``bundle`` with the tiers; a saved
combo's read-back job is queued on ``combo_list`` and the Thực hiện job shows Khớp / Lệch.
Synthetic values only.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from juli_backend.models.platform_data import PlatformPromotion
from juli_backend.models.shopee_fill import ShopeeFillJob
from juli_backend.services import ingest as svc
from juli_backend.services.ingest.schemas import ShopeeComboSettingRow
from juli_backend.services.shopee_recommendations import (
    connector_state,
    fill_queue,
    job_view,
    readback_compare,
    revert_fill,
)
from tests.support.builders import make_tenant
from tests.support.consent import grant_service_consent

CONTRACT = Path(__file__).resolve().parents[2] / "apps/connector/test/fixtures/contract"
READ_AT = datetime(2026, 11, 3, 3, 0)
NAME = "Combo mua 2 giảm 5%"


def _body(**rows_patch) -> svc.IngestBody:
    raw = json.loads((CONTRACT / "combo_settings.body.json").read_text("utf-8"))
    if rows_patch:
        raw["rows"] = [{**raw["rows"][0], **rows_patch}]
    return svc.IngestBody.model_validate(raw)


async def _shop(session):
    _, shop = await make_tenant(session, platform="shopee", tiktok_shop_id=None)
    await grant_service_consent(session, shop.id)
    return shop


async def _ingest(session, shop, body):
    return await svc.ingest(
        session,
        shop_id=shop.id,
        platform="shopee",
        dataset="combo_settings",
        body=body,
        token_id=None,
        now=READ_AT,
    )


def _job(kind, key, status, payload, target=None, created=datetime(2026, 11, 3, 2, 0)):
    return ShopeeFillJob(
        id=uuid.uuid4(), proposal_id=uuid.uuid4(), kind=kind, target=target or {},
        target_key=key, seq=1, version=1, payload=payload, status=status,
        created_at=created, updated_at=created,
    )  # fmt: skip


def _forward(**kw):
    payload = {
        "name": NAME, "starts_at": "18:06 18-11-2026", "ends_at": "16:46 25-11-2026",
        "discount_type": "pct", "tiers": [{"qty": 2, "value": 5}, {"qty": 3, "value": 10}],
        "product_ids": ["1001", "1002"], **kw,
    }  # fmt: skip
    return _job("combo", "combo:1001,1002", "saved", payload)


def _readback(target):
    spec = revert_fill._readback_of_change("bundle_deal", target)
    assert spec is not None
    payload = {
        "mode": "readback", "open_path": spec["open_path"], "target": spec["target"],
        "datasets": spec["datasets"], "forward_kind": spec["forward_kind"],
    }  # fmt: skip
    return _job("readback", spec["key"], "captured", payload, target=spec["target"])


async def test_the_combo_post_lands_as_bundle_promotions_with_their_tiers(session):
    shop = await _shop(session)
    result = await _ingest(session, shop, _body())
    assert result.rows == 2
    rows = {
        r.program_name: r
        for r in (
            await session.scalars(
                select(PlatformPromotion).where(PlatformPromotion.shop_id == shop.id)
            )
        ).all()
    }
    live = rows[NAME]
    assert live.promo_type == "bundle" and live.status == "2"
    assert live.starts_at == datetime(2026, 11, 18, 18, 6, 40)
    assert live.extra == {
        "combo_id": 7001,
        "discount_type": "pct",
        "tiers": [{"qty": 2, "value": 5}, {"qty": 3, "value": 10}],
        "product_count": 2,
        "usage_limit": 5,
    }
    assert rows["Combo cũ"].extra == {"combo_id": 7000, "product_count": 1}  # no detail read


def test_the_row_model_refuses_a_percent_over_100_and_tiers_without_their_kind():
    base = {"combo_id": "1", "program_name": "x", "starts_at": "2026-11-18T18:06:40"}
    with pytest.raises(ValidationError) as over:
        ShopeeComboSettingRow.model_validate(
            {**base, "discount_type": "pct", "tiers": [{"qty": 2, "value": 150}]}
        )
    assert "percent tier" in str(over.value)
    with pytest.raises(ValidationError) as lone:
        ShopeeComboSettingRow.model_validate({**base, "tiers": [{"qty": 2, "value": 5}]})
    assert "come together" in str(lone.value)
    ok = ShopeeComboSettingRow.model_validate(
        {**base, "discount_type": "amount", "tiers": [{"qty": 2, "value": 20000}]}
    )
    assert ok.key() == ("1",)


def test_a_combo_is_queued_on_the_combo_list_and_its_save_waits_for_the_read_back():
    assert fill_queue.READBACK_OF_KIND["combo"] == "combo_list"
    assert fill_queue.readback_of("combo") == "combo_list"
    assert not fill_queue.saved_only(_forward())
    assert connector_state.READER_DATASETS["combos"] == ("combo_settings",)


async def test_a_saved_combo_read_back_by_its_name_is_khop(session):
    shop = await _shop(session)
    await _ingest(session, shop, _body())
    rows = [_forward(), _readback({"combo_name": NAME})]
    got = await job_view.readback_result(session, shop.id, rows)
    assert got == {"result": "match", "diffs": []}
    assert job_view.status_label("readback", "captured", got["result"]) == "Khớp"


async def test_a_tier_shopee_saved_differently_is_lech_on_muc_uu_dai(session):
    shop = await _shop(session)
    await _ingest(
        session,
        shop,
        _body(tiers=[{"qty": 2, "value": 5}, {"qty": 3, "value": 8}]),
    )
    rows = [_forward(), _readback({"combo_id": "7001"})]
    got = await job_view.readback_result(session, shop.id, rows)
    assert got["result"] == "mismatch"
    assert got["diffs"] == [
        {
            "field": "tiers",
            "label_vi": "Mức ưu đãi",
            "card_value": "mua 2 giảm 5; mua 3 giảm 10",
            "seen_value": "mua 2 giảm 5; mua 3 giảm 8",
        }
    ]
    assert job_view.status_label("readback", "captured", got["result"]) == "Lệch"


async def test_by_name_the_newest_combo_of_the_combos_reader_is_the_one_read(session):
    """An older combo of the same name and a Khuyến mãi của Shop snapshot row (no combo_id, no
    tiers) never stand in for the combo just saved."""
    shop = await _shop(session)
    older = _body(combo_id="6990", tiers=[{"qty": 2, "value": 1}])
    newer = _body()
    await _ingest(session, shop, older)
    await _ingest(session, shop, newer)
    session.add(
        PlatformPromotion(
            id=uuid.uuid4(), shop_id=shop.id, platform="shopee", promo_type="bundle",
            program_name=NAME, starts_at=datetime(2026, 11, 18, 18, 6, 40), ordinal=0,
            period_start=datetime(2026, 11, 2).date(), period_end=datetime(2026, 11, 2).date(),
            order_type="none", extra={}, source="extension", source_rank=1, source_version="t",
            captured_at=datetime(2026, 11, 3, 4), updated_at=datetime(2026, 11, 3, 4),
        )
    )  # fmt: skip
    await session.flush()
    row = await readback_compare.observed_row(
        session, shop.id, "combo", {"combo_name": NAME}, datetime(2026, 11, 3, 2, 0)
    )
    assert row is not None and row.extra["combo_id"] == 7001
