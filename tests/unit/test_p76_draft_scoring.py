"""P76-5: TikTok scores the confirmed listing draft once, right before the write.

``score_listing_draft`` asks ``diagnose_optimize`` for the draft's codes; any TikTok
error, unreadable payload or slow answer is ``not_read`` -- never a guess, never a
blocker. The listing write handler calls it once before ``products.edit`` and the score
rides the handler's output, which is what the ledger stores as the write's outcome.
"""

from __future__ import annotations

from typing import Any

import pytest
import requests

from juli_backend.integrations.tiktok import ClientFactoryConfig, SandboxWriteClientFactory
from juli_backend.services.agent.tools import draft_scoring
from juli_backend.services.agent.tools.draft_scoring import (
    DraftScore,
    parse_draft_codes,
    score_confirmed_listing,
    score_listing_draft,
    stored_draft_score,
)
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.agent.tools.product_write import (
    UpdateProductListingInput,
    handle_update_product_listing,
)
from tests.support.tiktok_draft_scoring import (
    CLEAN_DATA,
    EMPTY_DATA,
    NOT_A_CODE_DATA,
    SCORED_DATA,
    DraftScoringProducts,
    sandbox_resources,
)

PRODUCT_ID = "1700000000000000001"
DETAIL: dict[str, Any] = {
    "id": PRODUCT_ID,
    "title": "Bình giữ nhiệt mẫu",
    "description": "<p>Mô tả mẫu</p>",
    "category_chains": [{"id": "600001", "is_leaf": True}],
    "main_images": [{"uri": "tos-sample/cover-1"}, {"uri": "tos-sample/cover-2"}],
}
SCORED_AT = "2026-10-29T03:00:00Z"


def _score(products: DraftScoringProducts, **kwargs: Any) -> DraftScore:
    return score_listing_draft(
        sandbox_resources(products),
        PRODUCT_ID,
        "600001",
        "Bình giữ nhiệt inox 500ml giữ nóng 12 giờ",
        "<p>Mô tả mới</p>",
        [{"uri": "tos-sample/cover-1"}],
        clock=lambda: SCORED_AT,
        **kwargs,
    )


def test_a_scored_draft_keeps_tiktoks_codes_once_and_when():
    products = DraftScoringProducts(SCORED_DATA)

    score = _score(products)

    assert score == DraftScore(
        status="scored",
        codes_after=["SEO_DIAGNOSTIC_ITEM", "MAIN_IMG_NUMBER_LESS_THAN_FIVE"],
        scored_at=SCORED_AT,
    )
    assert products.diagnose_calls == [
        {
            "product_id": PRODUCT_ID,
            "category_id": "600001",
            "optimization_fields": ["NONE"],
            "title": "Bình giữ nhiệt inox 500ml giữ nóng 12 giờ",
            "description": "<p>Mô tả mới</p>",
            "main_images": [{"uri": "tos-sample/cover-1"}],
        }
    ]


def test_a_clean_draft_is_scored_with_no_codes():
    score = _score(DraftScoringProducts(CLEAN_DATA))

    assert score.status == "scored"
    assert score.codes_after == []


@pytest.mark.parametrize(
    "result",
    [RuntimeError("sandbox down"), EMPTY_DATA, ["not", "a", "payload"], {"diagnoses": "x"}],
)
def test_an_error_or_unreadable_answer_is_not_read_never_clean(result: object):
    score = _score(DraftScoringProducts(result))

    assert score == DraftScore(status="not_read")


def test_a_slow_tiktok_is_not_read_within_the_budget():
    products = DraftScoringProducts(CLEAN_DATA, block=True)
    try:
        score = _score(products, timeout_seconds=0.05)
    finally:
        products.release()

    assert score.status == "not_read"


def test_free_text_in_a_code_slot_is_not_echoed():
    assert parse_draft_codes(NOT_A_CODE_DATA) == []


def test_the_budget_is_a_few_seconds():
    assert 0 < draft_scoring.SCORING_TIMEOUT_SECONDS <= 3


def test_only_the_writable_sandbox_bundle_is_scored():
    products = DraftScoringProducts(SCORED_DATA)

    assert score_confirmed_listing(products, PRODUCT_ID, {"category_id": "600001"}) is None
    assert products.diagnose_calls == []


def test_a_body_without_a_category_is_not_read_without_a_call():
    products = DraftScoringProducts(SCORED_DATA)

    score = score_confirmed_listing(sandbox_resources(products), PRODUCT_ID, {})

    assert score == DraftScore(status="not_read")
    assert products.diagnose_calls == []


def _write(products: DraftScoringProducts) -> dict[str, Any]:
    output = handle_update_product_listing(
        sandbox_resources(products),
        ProductToolContext(product_id=PRODUCT_ID, product_detail=DETAIL),
        UpdateProductListingInput(title="Bình giữ nhiệt inox 500ml giữ nóng 12 giờ"),
    )
    # What the executor hands the ledger as the write's outcome.
    return output.model_dump(mode="json")


def test_the_write_scores_the_confirmed_body_once_before_editing():
    products = DraftScoringProducts(SCORED_DATA)

    outcome = _write(products)

    assert products.events == ["diagnose_optimize", "edit"]
    sent = products.edit_calls[0][1]
    asked = products.diagnose_calls[0]
    assert (asked["title"], asked["description"], asked["category_id"]) == (
        sent["title"],
        sent["description"],
        sent["category_id"],
    )
    assert asked["main_images"] == sent["main_images"]
    assert outcome["draft_score"]["status"] == "scored"
    assert outcome["draft_score"]["codes_after"] == [
        "SEO_DIAGNOSTIC_ITEM",
        "MAIN_IMG_NUMBER_LESS_THAN_FIVE",
    ]
    assert stored_draft_score(outcome) == DraftScore.model_validate(outcome["draft_score"])


def test_the_write_still_happens_when_tiktoks_check_fails():
    products = DraftScoringProducts(RuntimeError("sandbox down"))

    outcome = _write(products)

    assert len(products.edit_calls) == 1
    assert outcome["draft_score"] == {"status": "not_read", "codes_after": [], "scored_at": None}
    assert outcome["title"] == "Bình giữ nhiệt inox 500ml giữ nóng 12 giờ"


def test_an_unscored_write_keeps_its_old_outcome_shape():
    products = DraftScoringProducts(SCORED_DATA)
    output = handle_update_product_listing(
        # Not a sandbox bundle: nothing is scored, the edit still goes out.
        _AnyBundle(products),
        ProductToolContext(product_id=PRODUCT_ID, product_detail=DETAIL),
        UpdateProductListingInput(title="Bình giữ nhiệt inox 500ml giữ nóng 12 giờ"),
    )

    assert output.model_dump(mode="json") == {
        "title": "Bình giữ nhiệt inox 500ml giữ nóng 12 giờ",
        "description": None,
        "image_attached": False,
    }
    assert products.diagnose_calls == []
    assert len(products.edit_calls) == 1


class _AnyBundle:
    """A write bundle that is not the sandbox's (e.g. a seller's own-shop products)."""

    def __init__(self, products: DraftScoringProducts) -> None:
        self.products = products


def test_a_stored_outcome_without_a_score_reads_as_none():
    assert stored_draft_score({"title": "x"}) is None
    assert stored_draft_score({"draft_score": {"status": "bogus"}}) is None
    assert stored_draft_score({"draft_score": "scored"}) is None


def test_the_scoring_copy_is_closed_once_the_call_ends():
    products = DraftScoringProducts(SCORED_DATA)

    _score(products)

    assert len(products.copies) == 1
    assert products.closed == 1


def test_a_bundle_that_cannot_give_its_own_session_is_not_read_without_a_call():
    class SharedOnly:
        def __init__(self) -> None:
            self.calls = 0

        def diagnose_optimize(self, **kwargs: Any) -> dict[str, Any]:
            self.calls += 1
            return CLEAN_DATA

    class Bundle:
        products = SharedOnly()

    score = score_listing_draft(Bundle(), PRODUCT_ID, "600001", "t", None, None)

    assert score == DraftScore(status="not_read")
    assert Bundle.products.calls == 0


class _Response:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {"code": 0, "message": "Success", "data": self._data}


def test_the_scoring_call_and_the_write_never_share_a_session(monkeypatch):
    """Real guarded sandbox client from the factory; only the HTTP send is stubbed."""
    sessions: dict[str, list[requests.Session]] = {"post": [], "put": []}
    closed: list[requests.Session] = []

    def post(self: requests.Session, url: str, **kwargs: Any) -> _Response:
        sessions["post"].append(self)
        return _Response(CLEAN_DATA)

    def put(self: requests.Session, url: str, **kwargs: Any) -> _Response:
        sessions["put"].append(self)
        return _Response({})

    original_close = requests.Session.close

    def close(self: requests.Session) -> None:
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(requests.Session, "post", post)
    monkeypatch.setattr(requests.Session, "put", put)
    monkeypatch.setattr(requests.Session, "close", close)
    resources = SandboxWriteClientFactory().create_resources(
        ClientFactoryConfig(
            app_key="app-key-sample",
            app_secret="app-secret-sample",
            access_token="token-sample",
            merchant_auth_id="merchant-sample",
            credential_capability="sandbox_write",
        )
    )

    output = handle_update_product_listing(
        resources,
        ProductToolContext(product_id=PRODUCT_ID, product_detail=DETAIL),
        UpdateProductListingInput(title="Bình giữ nhiệt inox 500ml giữ nóng 12 giờ"),
    )

    assert output.draft_score is not None and output.draft_score.status == "scored"
    assert len(sessions["post"]) == 1 and len(sessions["put"]) == 1
    scoring_session, write_session = sessions["post"][0], sessions["put"][0]
    assert scoring_session is not write_session
    assert closed == [scoring_session]
