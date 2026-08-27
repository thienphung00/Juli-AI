"""The product detail must survive the pause, because the write happens after it.

#1389 gave `update_product_listing` the full B-4 edit body, which needs the
product's own `category_id`, `skus` and `package_weight`. Those come from the
detail read by `get_product_information` on the FIRST leg.

But a `CONFIRM`-policy write happens on the **resume** leg, in a fresh process,
and on that leg the model goes straight to the write — it does not re-read the
product. So anything held only in executor or guard memory is gone by the time
the body is built.

That is the same boundary #1382 was lost across: the compare-before-write basis
was captured on leg 1, discarded at the pause, and the resume leg started empty.
Every concurrency test lived inside a single leg, so none of them could see it.

These tests span the boundary. The seam-level test in
`test_agent_workflow_task_wiring.py` proves `_construct_runner` passes
`state.product_detail` to the executor; these prove the value is actually there
to pass, and that it is the product the run read rather than something a test
handed in.
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
from juli_backend.services.agent.runner.state import RunState

# Shaped like docs/integrations/tiktok_api/samples/products-detail-response.json,
# trimmed to the fields the B-4 edit body draws on.
DETAIL: dict[str, Any] = {
    "id": "1736363193934775939",
    "title": "Nồi lẩu điện mini 1.5L có nắp kính",
    "description": "<p>mô tả</p>",
    "category_chains": [
        {"id": "849672", "is_leaf": False, "local_name": "Nhà bếp", "parent_id": "0"},
        {"id": "601693", "is_leaf": True, "local_name": "Nồi điện", "parent_id": "849672"},
    ],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "skus": [
        {
            "id": "1734952449674217079",
            "price": {"currency": "VND", "tax_exclusive_price": "599000"},
            "inventory": [{"quantity": 0, "warehouse_id": "7272949914115966726"}],
        }
    ],
}


class TestDetailCrossesThePauseBoundary:
    def test_a_guard_capture_reaches_state_and_serializes(self):
        """Leg 1: what the guard captured must land in RunState and survive the
        JSONB round trip, or the resume leg has nothing to rehydrate from."""
        guard = ConcurrencyGuard()
        guard.set_product_detail(DETAIL)

        state = RunState()
        assert state.product_detail is None, "precondition: a fresh run has no detail"

        captured = guard.get_product_detail()
        assert captured is not None
        state.product_detail = dict(captured)

        assert state.to_dict()["product_detail"] == DETAIL

    def test_the_resume_leg_rehydrates_the_same_product(self):
        """Leg 2, in a fresh process: `_construct_runner` reads
        `run.state["product_detail"]`. It must come back intact — every field the
        B-4 body needs, for the product the run actually read."""
        state = RunState()
        state.product_detail = dict(DETAIL)
        blob = state.to_dict()

        # Exactly what workers/tasks/agent_workflow.py does on resume.
        rehydrated = blob.get("product_detail")

        assert rehydrated is not None
        assert rehydrated["id"] == DETAIL["id"], "must be the product the run read"
        for field in ("category_chains", "skus", "package_weight"):
            assert rehydrated[field] == DETAIL[field], f"{field} is required by the B-4 body"

    def test_an_unpersisted_detail_leaves_the_resume_leg_empty(self):
        """Non-vacuity — the pre-fix path, kept executable so the two assertions
        above cannot quietly become tautologies. Capturing into the guard alone,
        without mirroring into state, strands the detail exactly as #1382's basis
        was stranded."""
        guard = ConcurrencyGuard()
        guard.set_product_detail(DETAIL)

        state = RunState()  # nothing mirrored
        assert guard.get_product_detail() is not None, "the guard did capture it"
        assert state.to_dict().get("product_detail") is None, (
            "and it was lost across the boundary — the write would then fail closed"
        )

    def test_round_trip_through_from_dict_preserves_the_detail(self):
        """`RunState.from_dict` is the other half of the persistence path; a
        detail that serializes but does not deserialize is still lost."""
        state = RunState()
        state.product_detail = dict(DETAIL)

        restored = RunState.from_dict(state.to_dict())

        assert restored.product_detail == DETAIL


class TestTheProducerActuallyRuns:
    """The producer side — dispatching the read must POPULATE the guard.

    Everything above tests that a populated guard reaches the write. That is
    the consumer half, and it passes just as happily when nothing ever fills
    the guard in the first place: an earlier revision of #1389 defined
    `set_product_detail` and never called it in production, so the whole
    persistence chain was inert and `update_product_listing` failed closed on
    every run.

    That is the fourth time this lane shipped a consumer without its producer
    — #1379 (tool declared in the playbook, never registered in the production
    registry), #1382 (basis captured, never persisted), the `product_detail`
    field declared on the context and never assigned, and this. Each time the
    unit tests supplied the missing input themselves and passed.

    So this asserts the production dispatch path fills the guard, using the
    real `ProductToolExecutor` rather than a hand-populated one.
    """

    def test_dispatching_get_product_information_populates_the_guard(self):
        from juli_backend.services.agent.runner.concurrency import ConcurrencyGuard
        from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
        from juli_backend.services.agent.tools.product import register_product_read_tools
        from juli_backend.services.agent.tools.registry import ToolRegistry

        class _Products:
            def get_details(self, product_id):
                return dict(DETAIL, id=product_id)

        class _Resources:
            products = _Products()

        registry = ToolRegistry()
        register_product_read_tools(registry)
        guard = ConcurrencyGuard()
        executor = ProductToolExecutor(
            registry=registry,
            read_resources=_Resources(),
            product_id=DETAIL["id"],
            concurrency_guard=guard,
        )

        assert guard.get_product_detail() is None, "precondition: nothing captured yet"

        spec = registry.get("get_product_information")
        executor.execute(
            tool_name="get_product_information",
            params=spec.input_model(),
            tool_call_id="c1",
        )

        captured = guard.get_product_detail()
        assert captured is not None, (
            "dispatching the read must populate the guard — without this the "
            "whole pause/resume chain is inert and every write fails closed"
        )
        assert captured["id"] == DETAIL["id"]
        for field in ("category_chains", "skus", "package_weight"):
            assert field in captured, f"{field} is required by the B-4 edit body"
