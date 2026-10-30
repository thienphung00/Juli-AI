"""P64: V2 categories on the create chain, and a failed write never reads as applied.

Live run 74aefd1a (2026-10-23, reviewer on the TikTok VN sandbox shop): TikTok refused
``POST /product/202309/products`` with 12052217 "Parameter `category_version` is invalid
because all-region shops must use V2 categories". ``create_product`` returned ``ok=false``
yet the runner recorded the write ``succeeded``, emitted ``tool.completed ok=true`` ("Xong"),
let the model narrate and ended ``final_response`` -- so the run showed "Đã ghi lên TikTok",
"Đã ghi lên shop sandbox TikTok của Juli" and "Kết thúc · đặt lịch đo".

1. Every create-chain call (Get Categories, Check Listing Prerequisites, Get Attributes,
   Get Brands) and the Create Product body carry ``category_version=v2``.
2. A WRITE whose handler returns ``ok=false`` (or raises) ends the run ``failed`` with the
   step ``ok=false`` and TikTok's reason, ``rows_affected`` 0 and no model narration after.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from juli_backend.integrations.tiktok import PRODUCT_CATEGORY_VERSION, TikTokAPIError
from juli_backend.integrations.tiktok.resources.products import ProductsResource
from juli_backend.services.agent.events import InMemoryEventSink
from juli_backend.services.agent.runner.seller_facing_copy import WRITE_FAILED_SUMMARY
from juli_backend.services.agent.status import StopReason, WorkflowRunStatus
from juli_backend.services.agent.tools import catalog_create as cc
from tests.unit.test_p64_create_product_walkthrough import (
    InMemoryStore,
    ScriptedLLM,
    _completed,
    _runner,
)
from tests.unit.test_reviewer_sandbox_create_product import (
    CONTEXT,
    SOURCE_ID,
    FakeProducts,
    _create,
    _sandbox,
)

LIVE_REFUSAL = (
    "Invalid Parameter. Parameter `category_version` is invalid because all-region shops "
    "must use V2 categories. Use V2 categories and retry."
)


# -- 1. V2 categories ---------------------------------------------------------------------


class RecordingClient:
    """``TikTokClient`` double: records every signed call, answers like the sandbox shop."""

    def __init__(self) -> None:
        self.gets: list[tuple[str, dict[str, str]]] = []
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def get(self, path: str, params: dict[str, str] | None = None, **_: Any) -> dict[str, Any]:
        self.gets.append((path, dict(params or {})))
        if path.endswith("/categories"):
            return {"categories": [{"id": "605254", "is_leaf": True, "local_name": "Bình nước"}]}
        if path.endswith("/attributes"):
            return {"attributes": [{"id": "100149", "name": "Xuất xứ", "is_requried": True}]}
        if path.endswith("/prerequisites"):
            return {"check_results": [{"check_item": "SHOP_STATUS", "is_failed": False}]}
        return {}

    def post(self, path: str, body: dict[str, Any] | None = None, **_: Any) -> dict[str, Any]:
        self.posts.append((path, dict(body or {})))
        return {"product_id": "1737000000000000001"}


class ChainProducts(ProductsResource):
    """The real resource methods over :class:`RecordingClient`; only the reads of the
    source listing and the new product come from the sandbox double."""

    def __init__(self, client: RecordingClient) -> None:
        super().__init__(cast(Any, client))
        self._details = FakeProducts()

    def get_details(self, product_id: str) -> dict:
        return self._details.get_details(product_id)


def test_the_category_version_is_v2():
    assert PRODUCT_CATEGORY_VERSION == "v2"


def test_every_category_call_of_the_resource_sends_v2():
    client = RecordingClient()
    products = ProductsResource(cast(Any, client))
    products.get_categories()
    products.check_listing_prerequisites(category_id="605254")
    products.get_category_attributes(category_id="605254")
    products.get_brands(category_id="605254")
    assert len(client.gets) == 4
    for path, params in client.gets:
        assert params.get("category_version") == "v2", path


def test_the_whole_create_chain_and_the_create_body_use_v2():
    client = RecordingClient()
    out = cc.handle_create_product(_sandbox(ChainProducts(client)), CONTEXT, _create())
    assert out.ok, out
    paths = [path for path, _ in client.gets]
    assert any(p.endswith("/categories") for p in paths)
    assert any(p.endswith("/prerequisites") for p in paths)
    assert any(p.endswith("/attributes") for p in paths)
    for path, params in client.gets:
        assert params.get("category_version") == "v2", path
    ((_, body),) = client.posts
    assert body["category_version"] == "v2"
    assert body["category_id"] == "605254"  # an id from the V2 list


def test_the_create_body_carries_v2():
    plan = cc.plan_listing(_sandbox(FakeProducts()), SOURCE_ID, "605254")
    body = cc.create_body(plan, title="Bình giữ nhiệt inox 750ml", description="Mô tả bình.")
    assert body["category_version"] == "v2"


# -- 2. a failed write ends the run failed --------------------------------------------------


class RefusingProducts(FakeProducts):
    """The live refusal: TikTok answers the create with 12052217."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    def create(self, *, body: dict[str, Any]) -> dict[str, Any]:
        raise self.error


async def _pause_then_approve(products: FakeProducts):
    store, sink = InMemoryStore(), InMemoryEventSink()
    llm = ScriptedLLM(["Combo 2 bình giữ nhiệt inox 750ml nắp xoay chống tràn"])
    run_id = uuid.uuid4()
    paused = await _runner(products, store, sink, llm).run(run_id, product_ref=SOURCE_ID)
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL, paused
    return run_id, store, sink, llm


async def test_the_live_refusal_ends_the_run_failed_never_completed():
    products = RefusingProducts(TikTokAPIError(12052217, LIVE_REFUSAL))
    run_id, store, sink, llm = await _pause_then_approve(products)
    llm.titles.clear()

    done = await _runner(products, store, sink, llm).resume(run_id, approved=True)

    assert done.status == WorkflowRunStatus.FAILED, done
    assert done.stop_reason == StopReason.TOOL_ERROR_UNRECOVERABLE
    write = _completed(sink)[-1]
    assert write.tool_name == cc.CREATE_PRODUCT_TOOL
    assert write.ok is False
    assert write.summary.startswith(WRITE_FAILED_SUMMARY)
    assert "12052217" in write.summary and "V2 categories" in write.summary
    types = [event.event_type for event in sink.events]
    assert "workflow.failed" in types and "workflow.completed" not in types
    assert types[-1] == "workflow.failed"  # no narration after the refusal
    assert store.states[run_id].rows_affected == 0
    assert products.created == []


async def test_a_write_that_raises_closes_its_step_failed_before_the_run_ends():
    products = RefusingProducts(RuntimeError("pool exhausted"))
    run_id, store, sink, llm = await _pause_then_approve(products)

    with pytest.raises(RuntimeError):
        await _runner(products, store, sink, llm).resume(run_id, approved=True)

    write = _completed(sink)[-1]
    assert write.tool_name == cc.CREATE_PRODUCT_TOOL
    assert write.ok is False and write.summary == WRITE_FAILED_SUMMARY


async def test_a_successful_create_still_completes():
    products = FakeProducts()
    run_id, store, sink, llm = await _pause_then_approve(products)
    done = await _runner(products, store, sink, llm).resume(run_id, approved=True)
    assert done.status == WorkflowRunStatus.COMPLETED, done
    assert _completed(sink)[-1].ok is True
    assert store.states[run_id].rows_affected == 1
