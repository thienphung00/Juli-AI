"""P71: Đo lường on the sandbox shop measures TikTok's own listing-quality diagnosis.

A sandbox listing-edit run read TikTok's product diagnosis in its first step ("Đọc chẩn
đoán TikTok": Tiêu đề quá ngắn, Mô tả chưa xuống dòng, ...). The reviewer's runs list
carries that reading (Ngày 0, from the run's stored conversation) and TikTok's diagnosis
of the same product now (re-read on demand, cached). Never a CTR / view / CTOR figure,
never a guessed count; sellers' lists are unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import select

from juli_backend.models.models import Product, WorkflowRun
from juli_backend.services.agent_runs import listing_quality
from tests.support.api import build_app, client_for
from tests.unit import test_reviewer_sandbox_create_product as p64
from tests.unit.test_p67_reviewer_confirmed_writes import _run_with_write
from tests.unit.test_reviewer_sandbox_create_product import _headers

reviewer_env = p64.reviewer_env
world = p64.world

DAY0_CODES = [
    {"code": "TITLE_LESS_THAN_40_CHARACTERS", "label_vi": "Tiêu đề quá ngắn"},
    {"code": "DESC_NO_NEW_LINE", "label_vi": "Mô tả chưa xuống dòng"},
    {"code": "DESC_LESS_THAN_FIVE_HUNDRED_CHARS", "label_vi": "Mô tả quá ngắn"},
    {"code": "MAIN_IMG_NUMBER_LESS_THAN_FIVE", "label_vi": "Ít hơn 5 ảnh chính"},
]


def _state(content: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_window": [
            {"role": "user", "content": "..."},
            {
                "role": "tool",
                "tool_call_id": "c-diag",
                "tool_name": "get_product_diagnoses",
                "content": content,
            },
            {"role": "assistant", "content": "..."},
        ]
    }


class FakeProducts:
    def __init__(self, codes: list[str]) -> None:
        self.codes = codes
        self.calls: list[list[str]] = []
        self.error: Exception | None = None

    def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
        self.calls.append(product_ids)
        if self.error is not None:
            raise self.error
        return {
            "products": [
                {
                    "id": product_ids[0],
                    "diagnoses": [
                        {
                            "field": "DESCRIPTION",
                            "diagnosis_results": [{"code": c} for c in self.codes],
                        }
                    ],
                }
            ]
        }


class FakeResources:
    def __init__(self, products: FakeProducts) -> None:
        self.products = products


@pytest.fixture
def tiktok(monkeypatch) -> FakeProducts:
    products = FakeProducts(["MAIN_IMG_NUMBER_LESS_THAN_FIVE"])

    async def resources(session, shop_id):
        return FakeResources(products)

    listing_quality.reset_cache()
    monkeypatch.setattr(listing_quality, "_resources", resources)
    yield products
    listing_quality.reset_cache()


async def _listing_edit(session, ids, reviewer_id, *, state: dict[str, Any], n: int = 1):
    run_id = await _run_with_write(
        session, ids, reviewer_id, workflow="optimize_product_2", tool="update_product_listing",
        outcome={"title": "Tiêu đề mới", "description": "Mô tả mới"}, n=n,
    )  # fmt: skip
    run = await session.get(WorkflowRun, run_id)
    run.state = state
    await session.commit()
    return run_id


async def _quality(session, ids, user_id, **headers) -> dict[str, Any]:
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/runs", headers=_headers(user_id, ids["sandbox"], **headers)
        )
    assert listed.status_code == 200, listed.text
    return {item["id"]: item.get("listing_quality") for item in listed.json()["data"]}


def test_day0_is_the_runs_own_diagnosis_step():
    reading = listing_quality.day0_reading(_state({"codes": DAY0_CODES, "count": 4}))
    assert reading is not None
    assert reading.count == 4
    assert reading.issues == (
        "Tiêu đề quá ngắn",
        "Mô tả chưa xuống dòng",
        "Mô tả quá ngắn",
        "Ít hơn 5 ảnh chính",
    )


def test_an_unread_diagnosis_step_is_no_day0_never_zero():
    assert (
        listing_quality.day0_reading(_state({"codes": [], "count": 0, "unavailable": True})) is None
    )
    assert listing_quality.day0_reading({}) is None
    assert listing_quality.day0_reading(None) is None


async def test_a_sandbox_listing_edit_shows_tiktoks_diagnosis_before_and_now(
    session, world, tiktok
):
    ids, reviewer_id = world
    run_id = await _listing_edit(
        session, ids, reviewer_id, state=_state({"codes": DAY0_CODES, "count": 4})
    )

    quality = (await _quality(session, ids, reviewer_id))[str(run_id)]

    assert quality["before"] == {
        "count": 4,
        "issues": [code["label_vi"] for code in DAY0_CODES],
        "read_at": None,
    }
    assert quality["after"]["count"] == 1
    assert quality["after"]["issues"] == ["Ít hơn 5 ảnh chính"]
    assert quality["after"]["read_at"]
    product = await session.scalar(select(Product).where(Product.id == ids["product"]))
    assert tiktok.calls == [[product.tiktok_product_id]]


async def test_the_reread_is_cached_across_polls(session, world, tiktok):
    ids, reviewer_id = world
    await _listing_edit(session, ids, reviewer_id, state=_state({"codes": [], "count": 0}))

    await _quality(session, ids, reviewer_id)
    await _quality(session, ids, reviewer_id)

    assert len(tiktok.calls) == 1


async def test_tiktok_unread_now_is_unknown_not_zero(session, world, tiktok):
    ids, reviewer_id = world
    tiktok.error = RuntimeError("sandbox down")
    run_id = await _listing_edit(
        session, ids, reviewer_id, state=_state({"codes": DAY0_CODES, "count": 4})
    )

    quality = (await _quality(session, ids, reviewer_id))[str(run_id)]

    assert quality["before"]["count"] == 4
    assert quality["after"] is None


async def test_sellers_and_other_runs_carry_no_listing_quality(session, world, tiktok):
    ids, reviewer_id = world
    edit = await _listing_edit(session, ids, reviewer_id, state=_state({"codes": [], "count": 0}))
    promo = await _run_with_write(
        session, ids, reviewer_id, workflow="create_promotion", tool="create_product_discount",
        outcome={"ok": True, "activity_id": "7699734374178817800", "discount_pct": 12}, n=2,
    )  # fmt: skip
    await session.commit()

    reviewer = await _quality(session, ids, reviewer_id)
    seller = await _quality(session, ids, ids["owner"], platform=None, email="o@gmail.com")

    assert reviewer[str(edit)] is not None
    assert reviewer[str(promo)] is None
    assert all(value is None for value in seller.values())
