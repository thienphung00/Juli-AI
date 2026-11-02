"""P83: TikTok's draft check runs while the write goes out, within a 12 s total budget.

Live sandbox run d7b5d16c: the 3 s wait *before* the write timed out, so Đo lường had no
"Sau sửa" line. Scoring now starts first, the edit is performed meanwhile, and the score
is collected afterwards from what is left of the budget measured from the start of scoring.
"""

from __future__ import annotations

import threading
from typing import Any

import pytest

from juli_backend.services.agent.tools import draft_scoring
from juli_backend.services.agent.tools.draft_scoring import start_listing_draft_score
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    handle_update_product_listing,
)
from tests.support.tiktok_draft_scoring import SCORED_DATA, DraftScoringProducts, sandbox_resources

PRODUCT_ID = "1700000000000000001"
DETAIL: dict[str, Any] = {
    "id": PRODUCT_ID,
    "title": "Bình giữ nhiệt mẫu",
    "description": "<p>Mô tả mẫu</p>",
    "category_chains": [{"id": "600001", "is_leaf": True}],
    "main_images": [{"uri": "tos-sample/cover-1"}],
}


def _write(products: DraftScoringProducts) -> dict[str, Any]:
    output = handle_update_product_listing(
        sandbox_resources(products),
        ProductToolContext(product_id=PRODUCT_ID, product_detail=DETAIL),
        UpdateProductListingInput(title="Bình giữ nhiệt inox 500ml giữ nóng 12 giờ"),
    )
    return output.model_dump(mode="json")


def test_the_budget_is_twelve_seconds_by_default():
    assert draft_scoring.DRAFT_SCORE_BUDGET_SECONDS == 12.0


def test_the_write_goes_out_while_a_slow_score_is_still_running_and_is_then_scored():
    products = DraftScoringProducts(SCORED_DATA, block=True)
    seen_at_edit: list[list[str]] = []

    def during_edit() -> None:
        seen_at_edit.append(list(products.events))
        # The slow TikTok answers a moment after the edit went out (stands in for ~5 s).
        threading.Timer(0.05, products.release).start()

    products.on_edit = during_edit

    outcome = _write(products)

    # The edit ran before the score finished: "diagnose_done" was not yet recorded.
    assert "diagnose_done" not in seen_at_edit[0]
    assert products.events.index("edit") < products.events.index("diagnose_done")
    assert outcome["draft_score"]["status"] == "scored"
    assert outcome["draft_score"]["codes_after"] == [
        "SEO_DIAGNOSTIC_ITEM",
        "MAIN_IMG_NUMBER_LESS_THAN_FIVE",
    ]
    assert products.closed == 1


def test_the_score_still_scores_the_exact_body_written():
    products = DraftScoringProducts(SCORED_DATA)

    _write(products)

    sent = products.edit_calls[0][1]
    asked = products.diagnose_calls[0]
    assert (asked["title"], asked["description"], asked["category_id"]) == (
        sent["title"],
        sent["description"],
        sent["category_id"],
    )
    assert asked["main_images"] == sent["main_images"]


def test_a_score_slower_than_the_budget_is_not_read_and_the_write_is_unaffected(monkeypatch):
    monkeypatch.setattr(draft_scoring, "DRAFT_SCORE_BUDGET_SECONDS", 0.05)
    products = DraftScoringProducts(SCORED_DATA, block=True)
    try:
        outcome = _write(products)
    finally:
        products.release()

    assert len(products.edit_calls) == 1
    assert outcome["draft_score"] == {"status": "not_read", "codes_after": [], "scored_at": None}
    assert outcome["title"] == "Bình giữ nhiệt inox 500ml giữ nóng 12 giờ"


def test_the_deadline_counts_from_the_start_of_scoring_not_from_the_wait():
    now = [100.0]
    products = DraftScoringProducts(SCORED_DATA, block=True)
    try:
        pending = start_listing_draft_score(
            sandbox_resources(products),
            PRODUCT_ID,
            "600001",
            "t",
            None,
            None,
            monotonic=lambda: now[0],
        )
        now[0] = 112.5  # the write took 12.5 s: nothing is left to wait
        score = pending.wait()
    finally:
        products.release()

    assert score.status == "not_read"


def test_time_spent_writing_comes_out_of_the_budget_not_added_to_it():
    now = [0.0]
    products = DraftScoringProducts(SCORED_DATA)
    pending = start_listing_draft_score(
        sandbox_resources(products),
        PRODUCT_ID,
        "600001",
        "t",
        None,
        None,
        monotonic=lambda: now[0],
    )
    now[0] = 5.0  # the write took 5 s; 7 s of the 12 s remain

    assert pending.wait().status == "scored"


def test_a_failing_write_keeps_its_error_and_leaves_no_crashing_scorer():
    products = DraftScoringProducts(SCORED_DATA, block=True)
    products.edit_error = RuntimeError("edit refused")
    products.on_edit = products.release

    with pytest.raises(RuntimeError, match="edit refused"):
        _write(products)

    # The scoring thread finishes on its own, closes its client and its answer is dropped.
    for _ in range(200):
        if products.closed:
            break
        threading.Event().wait(0.01)
    assert products.closed == 1


def test_a_failing_score_never_changes_the_write():
    products = DraftScoringProducts(RuntimeError("sandbox down"))

    outcome = _write(products)

    assert len(products.edit_calls) == 1
    assert outcome["draft_score"]["status"] == "not_read"
