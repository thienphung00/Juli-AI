"""P65 (D74): the sandbox reviewer's "Tạo khuyến mãi" -- a real agent run that creates a
product discount on Juli's TikTok SANDBOX shop through the Promotion API, and nowhere else.

- the tools (``services/agent/tools/promotion_create.py``) with a faked TikTok: candidates
  and the discount range from the shop's rules, the eligibility check, the create (Create
  Activity → Update Activity Product → Get Activity, through ONE SandboxWriteClientFactory
  client), TikTok's refusal reported with its code and message, the refusal of any
  non-sandbox resources;
- the transport allowlists: promotion writes are on the sandbox allowlist only;
- the playbook: the tools are offered by ``create_promotion`` alone;
- the card + approve: the sandbox reviewer gets one real card; approving it starts the
  ``create_promotion`` run; the daily cap 429; a seller cannot see or approve it, a
  reviewer on any other pin is 403;
- the confirmation: the reviewer's discount % / end date are bound to the run; out of
  range is a 422.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok import (
    ProductionWriteResources,
    SandboxWriteResources,
    TikTokAPIError,
)
from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_WRITE_ALLOWED_REQUESTS,
    is_production_read_allowed,
    is_production_write_allowed,
    is_sandbox_write_allowed,
)
from juli_backend.integrations.tiktok.constants import (
    PROMOTION_CREATE_PATH,
    promotion_activity_path,
    promotion_activity_products_path,
)
from juli_backend.integrations.tiktok.exceptions import TransportGuardError
from juli_backend.integrations.tiktok.factories import (
    ClientFactoryConfig,
    SandboxWriteClientFactory,
)
from juli_backend.integrations.tiktok.guards import ProductionWriteGuard, SandboxOnlyWriteGuard
from juli_backend.models.models import (
    ActionCard,
    RunConfirmation,
    WorkflowRun,
)
from juli_backend.models.ops import OpsAuditLog
from juli_backend.services.agent import approval as approval_module
from juli_backend.services.agent import composition, playbooks
from juli_backend.services.agent.runner import compute_params_sha
from juli_backend.services.agent.tools import promotion_create as pc
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.reviewer.config import shop_alias_id
from tests.support.api import build_app, client_for
from tests.support.builders import make_workflow_run
from tests.unit import test_reviewer_sandbox_create_product as p64
from tests.unit.test_reviewer_sandbox_create_product import SOURCE_ID, _headers

# The P64 sandbox world (two shops, credentials, a reviewer) and its approve-queue fake.
reviewer_env = p64.reviewer_env
world = p64.world
enqueued = p64.enqueued

OTHER_ID = "1736405947247986999"
BUSY_ID = "1736405947247986111"
SKU = "1736433041572857475"
NOW = datetime(2026, 10, 23, 3, 0, tzinfo=UTC)  # 10:00 23/10 in Vietnam


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(pc, "_now", lambda: NOW)


@pytest.fixture(autouse=True)
def card_tiktok(monkeypatch):
    """P66 (D16): the card's eligibility check reads this fake TikTok sandbox."""
    from juli_backend.services.reviewer import create_promotion_card as card_module

    state: dict[str, Any] = {"resources": None, "error": None}

    async def resources(session, shop_id):
        if state["error"] is not None:
            raise state["error"]
        return state["resources"] or _sandbox()

    card_module.reset_cache()
    monkeypatch.setattr(card_module, "_promotion_resources", resources)
    yield state
    card_module.reset_cache()


def _detail(product_id: str, title: str, *, stock: int = 40, status: str = "ACTIVATE"):
    return {
        "id": product_id,
        "title": title,
        "status": status,
        "skus": [
            {
                "id": SKU if product_id == SOURCE_ID else product_id + "1",
                "price": {"sale_price": "82000", "currency": "VND"},
                "inventory": [{"warehouse_id": "w", "quantity": stock}],
            }
        ],
    }


class FakeProducts:
    def __init__(self) -> None:
        self.details = {
            SOURCE_ID: _detail(SOURCE_ID, "Bình giữ nhiệt inox 750ml"),
            OTHER_ID: _detail(OTHER_ID, "Bình giữ nhiệt inox 500ml"),
            BUSY_ID: _detail(BUSY_ID, "Ly giữ nhiệt"),
            "empty": _detail("empty", "Hết hàng", stock=0),
        }

    def get_details(self, product_id: str) -> dict[str, Any]:
        return self.details[product_id]

    def search(self, **_: Any) -> dict[str, Any]:
        return {"products": [{"id": k} for k in (SOURCE_ID, OTHER_ID, BUSY_ID, "empty")]}


class FakePromotion:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.create_error: TikTokAPIError | None = None
        self.products_error: TikTokAPIError | None = None
        self.added: list[str] = []

    def search_activities_all(self, *, status: str, **_: Any) -> list[dict[str, Any]]:
        if status == "ONGOING":
            return [{"id": "7000000000000000001", "activity_type": "DIRECT_DISCOUNT"}]
        return [{"id": "7000000000000000002", "activity_type": "SHIPPING_DISCOUNT"}]

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        self.calls.append(("get", activity_id))
        if activity_id == "7000000000000000001":
            return {"activity_id": activity_id, "products": [{"id": BUSY_ID, "discount": "10"}]}
        return {
            "activity_id": activity_id,
            "title": "Giảm giá bình giữ nhiệt · 10:02 23/10",
            "status": "NOT_START",
            "products": [{"id": pid, "discount": "15", "skus": []} for pid in self.added],
        }

    def create_activity(self, *, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("create", body))
        if self.create_error is not None:
            raise self.create_error
        return {"activity_id": "7660009586606409490", "status": "NOT_START"}

    def update_activity_products(self, *, activity_id: str, body: dict[str, Any]) -> dict:
        self.calls.append(("products", body))
        if self.products_error is not None:
            raise self.products_error
        self.added = [p["id"] for p in body["products"]]
        return {"activity_id": activity_id, "status": "NOT_START", "total_count": len(self.added)}

    def deactivate(self, *, activity_id: str) -> dict[str, Any]:
        self.calls.append(("deactivate", activity_id))
        return {"status": "DEACTIVATED"}


def _sandbox(promotion: FakePromotion | None = None) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=cast(Any, None),
        products=cast(Any, FakeProducts()),
        fulfillment=cast(Any, None),
        promotion=cast(Any, promotion or FakePromotion()),
    )


CONTEXT = ProductToolContext(product_id=SOURCE_ID)


def _choice(**kw: Any) -> pc.CreateProductDiscountInput:
    values = {
        "product_ids": [SOURCE_ID],
        "discount_pct": 15,
        "end_date": "2026-10-30",
        "promotion_title": "Giảm giá bình giữ nhiệt",
        "reason_vi": "Sản phẩm bán chạy, còn 40 cái, chưa có khuyến mãi.",
        **kw,
    }
    return pc.CreateProductDiscountInput.model_validate(values)


# -- the tools ----------------------------------------------------------------------------


def test_candidates_list_the_eligible_products_the_range_and_the_dates():
    out = pc.handle_get_promotion_candidates(_sandbox(), CONTEXT, pc.GetPromotionCandidatesInput())
    assert out.ok and out.source_product_id == SOURCE_ID
    by_id = {c.product_id: c for c in out.candidates}
    assert by_id[SOURCE_ID].eligible and by_id[SOURCE_ID].stock == 40
    assert by_id[OTHER_ID].eligible
    assert not by_id[BUSY_ID].eligible
    assert by_id[BUSY_ID].reason_vi == "Sản phẩm đang có khuyến mãi giá khác"
    assert "empty" not in by_id  # out of stock: not even offered
    assert (out.discount_min_pct, out.discount_max_pct) == (5, 30)
    assert out.discount_rule_vi == "Mặc định của Juli: giảm từ 5% đến 30%"
    assert (out.today, out.default_end_date, out.max_end_date) == (
        "2026-10-23",
        "2026-10-30",
        "2026-11-22",
    )
    assert out.existing_price_promotions == 1 and out.existing_promotions_read


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


class WindowedPromotion(FakePromotion):
    """The bound product is in one price promotion with a known window."""

    def __init__(self, begin: datetime, end: datetime) -> None:
        super().__init__()
        self.window = (begin, end)

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        if activity_id == "7000000000000000001":
            return {
                "activity_id": activity_id,
                "begin_time": _epoch(self.window[0]),
                "end_time": _epoch(self.window[1]),
                "products": [{"id": SOURCE_ID}, {"id": BUSY_ID}],
            }
        return super().get_activity(activity_id)


def test_a_running_promotion_names_its_end_date_and_blocks_the_product():
    """P66 (D15): the candidate says when the existing price promotion ends."""
    promotion = WindowedPromotion(NOW - timedelta(days=1), NOW + timedelta(days=5))
    out = pc.handle_get_promotion_candidates(
        _sandbox(promotion), CONTEXT, pc.GetPromotionCandidatesInput()
    )
    source = {c.product_id: c for c in out.candidates}[SOURCE_ID]
    assert source.eligible is False
    assert source.reason_vi == "Sản phẩm đang có khuyến mãi giá khác đến 28/10/2026"
    assert source.existing_promotion_end == "2026-10-28"
    assert pc.first_promotable_product(_sandbox(promotion), [SOURCE_ID, OTHER_ID]) == OTHER_ID


def test_an_upcoming_promotion_after_the_window_does_not_block():
    """P66 (D16): only a promotion overlapping the proposed window makes it ineligible."""
    later = WindowedPromotion(NOW + timedelta(days=12), NOW + timedelta(days=20))
    assert pc.first_promotable_product(_sandbox(later), [SOURCE_ID]) == SOURCE_ID
    check = pc.handle_check_promotion_eligibility(
        _sandbox(later), CONTEXT, pc.CheckPromotionEligibilityInput(
            product_ids=[SOURCE_ID], discount_pct=15, end_date="2026-11-10"
        )
    )  # fmt: skip
    assert check.ok is False and check.error_code == "product_not_eligible"
    assert "đến 12/11/2026" in check.summary_vi


def test_first_promotable_product_refuses_to_guess_when_promotions_are_unread():
    class Unreadable(FakePromotion):
        def search_activities_all(self, *, status: str, **_: Any) -> list[dict[str, Any]]:
            raise TikTokAPIError(36009004, "busy")

    with pytest.raises(pc.PromotionsUnread):
        pc.first_promotable_product(_sandbox(Unreadable()), [SOURCE_ID])


def test_the_shops_rules_bound_the_discount():
    rules = pc.discount_rules_for_run(20, {SKU: 12})
    assert rules["max_pct"] == 20 and rules["max_source"] == "default_max_discount_pct"
    context = ProductToolContext(product_id=SOURCE_ID, discount_rules=rules)
    out = pc.handle_get_promotion_candidates(_sandbox(), context, pc.GetPromotionCandidatesInput())
    assert (
        out.discount_max_pct == 20 and out.discount_rule_vi == "Quy tắc của shop: giảm tối đa 20%"
    )
    assert {c.product_id: c.max_discount_pct for c in out.candidates}[SOURCE_ID] == 12
    refused = pc.handle_check_promotion_eligibility(
        _sandbox(), context, pc.CheckPromotionEligibilityInput(
            product_ids=[SOURCE_ID], discount_pct=15, end_date="2026-10-30"
        )
    )  # fmt: skip
    assert refused.ok is False and refused.error_code == "discount_out_of_range"
    assert refused.summary_vi == "Mức giảm phải từ 5% đến 12%"
    zero = ProductToolContext(product_id=SOURCE_ID, discount_rules=pc.discount_rules_for_run(0))
    out = pc.handle_create_product_discount(_sandbox(), zero, _choice())
    assert out.ok is False and out.error_code == "discount_not_allowed"


@pytest.mark.parametrize(
    ("kw", "code"),
    [
        ({"discount_pct": 40}, "discount_out_of_range"),
        ({"discount_pct": 3}, "discount_out_of_range"),
        ({"end_date": "2026-10-23"}, "end_date_invalid"),
        ({"end_date": "2026-11-23"}, "end_date_invalid"),
        ({"product_ids": [OTHER_ID]}, "source_product_required"),
        ({"product_ids": [SOURCE_ID, "42"]}, "product_not_candidate"),
        ({"product_ids": [SOURCE_ID, BUSY_ID]}, "product_not_eligible"),
    ],
)
def test_check_and_create_refuse_without_any_write(kw, code):
    params = _choice(**kw)
    check = pc.handle_check_promotion_eligibility(
        _sandbox(), CONTEXT, pc.CheckPromotionEligibilityInput.model_validate(params.model_dump())
    )
    assert check.ok is False and check.error_code == code
    promotion = FakePromotion()
    out = pc.handle_create_product_discount(_sandbox(promotion), CONTEXT, params)
    assert out.ok is False and out.error_code == code
    assert out.summary_vi.startswith("Chưa tạo khuyến mãi")
    assert [c for c in promotion.calls if c[0] in ("create", "products")] == []
    assert pc.precheck_create_product_discount(_sandbox(), CONTEXT, params) is not None


def test_check_passes_two_eligible_products():
    out = pc.handle_check_promotion_eligibility(
        _sandbox(),
        CONTEXT,
        pc.CheckPromotionEligibilityInput(
            product_ids=[SOURCE_ID, OTHER_ID], discount_pct=15, end_date="2026-10-30"
        ),
    )
    assert out.ok, out
    assert out.summary_vi == "2 sản phẩm đủ điều kiện · giảm 15% đến 30/10/2026"


def test_create_runs_the_documented_chain_and_reports_the_read_back():
    promotion = FakePromotion()
    out = pc.handle_create_product_discount(
        _sandbox(promotion), CONTEXT, _choice(product_ids=[SOURCE_ID, OTHER_ID])
    )
    assert out.ok, out
    kinds = [kind for kind, _ in promotion.calls]
    assert kinds.count("create") == 1 and kinds.count("products") == 1
    assert kinds[-1] == "get"  # read back last
    create = next(body for kind, body in promotion.calls if kind == "create")
    assert create["activity_type"] == "DIRECT_DISCOUNT" and create["product_level"] == "PRODUCT"
    assert create["title"] == "Giảm giá bình giữ nhiệt · 10:02 23/10"
    assert create["begin_time"] == int((NOW + timedelta(minutes=2)).timestamp())
    end = datetime.fromisoformat("2026-10-30T23:59:59+07:00")
    assert create["end_time"] == int(end.timestamp())
    added = next(body for kind, body in promotion.calls if kind == "products")
    assert added == {
        "activity_id": "7660009586606409490",
        "products": [
            {"id": pid, "discount": "15", "quantity_limit": -1, "quantity_per_user": -1,
             "skus": []}
            for pid in (SOURCE_ID, OTHER_ID)
        ],
    }  # fmt: skip
    assert out.activity_id == "7660009586606409490"
    assert out.status == "NOT_START" and out.status_label_vi == "Chưa bắt đầu"
    assert out.products_confirmed == 2
    assert out.summary_vi == (
        "Đã tạo khuyến mãi trên TikTok · mã 7660009586606409490 · Chưa bắt đầu · "
        "giảm 15% cho 2/2 sản phẩm đến 30/10/2026 · TikTok xác nhận lúc 10:00 23/10/2026"
    )


def test_a_tiktok_refusal_is_reported_with_its_code_and_message_and_nothing_is_claimed():
    promotion = FakePromotion()
    promotion.create_error = TikTokAPIError(17019004, "activity title duplicated", "req-1")
    out = pc.handle_create_product_discount(_sandbox(promotion), CONTEXT, _choice())
    assert out.ok is False and out.error_code == "tiktok_error"
    assert out.summary_vi == (
        "TikTok từ chối tạo khuyến mãi (mã lỗi 17019004): activity title duplicated"
    )
    assert out.activity_id is None and "Đã tạo" not in out.summary_vi
    assert [k for k, _ in promotion.calls if k == "products"] == []


def test_a_refused_product_add_turns_the_empty_activity_off():
    promotion = FakePromotion()
    promotion.products_error = TikTokAPIError(17019010, "product not eligible", "req-2")
    out = pc.handle_create_product_discount(_sandbox(promotion), CONTEXT, _choice())
    assert out.ok is False and out.error_code == "tiktok_error"
    assert "mã lỗi 17019010" in out.summary_vi and "product not eligible" in out.summary_vi
    assert "Juli đã tắt khuyến mãi rỗng mã 7660009586606409490" in out.summary_vi
    assert ("deactivate", "7660009586606409490") in promotion.calls


def test_the_create_refuses_any_non_sandbox_resources_before_a_request():
    promotion = FakePromotion()
    production = ProductionWriteResources(products=cast(Any, FakeProducts()))
    with pytest.raises(pc.PromotionCreateRefused):
        pc.handle_create_product_discount(production, CONTEXT, _choice())
    lookalike = type("R", (), {"products": FakeProducts(), "promotion": promotion})()
    with pytest.raises(pc.PromotionCreateRefused):
        pc.handle_create_product_discount(lookalike, CONTEXT, _choice())
    assert promotion.calls == []


def test_a_banned_term_in_the_title_is_refused_before_the_reviewer_is_asked():
    context = ProductToolContext(product_id=SOURCE_ID, banned_terms=("rẻ nhất",))
    params = _choice(promotion_title="Bình rẻ nhất tuần")
    refusal = pc.precheck_create_product_discount(_sandbox(), context, params)
    assert refusal is not None and refusal.error_code == "promotion_title_rule_violation"
    assert "rẻ nhất" not in refusal.summary_vi and "rẻ nhất" in refusal.model_hint
    out = pc.handle_create_product_discount(_sandbox(), context, params)
    assert out.ok is False and out.error_code == "promotion_title_rule_violation"


# -- one sandbox client, the real guard ----------------------------------------------------


class _Response:
    def __init__(self, data: dict[str, Any], code: int = 0, message: str = "Success") -> None:
        self._body = {"code": code, "data": data, "message": message, "request_id": "r"}
        self.text = json.dumps(self._body)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._body


class _RoutedSession:
    """``requests.Session`` double: answers by (method, path), records every request."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, Any]] = []
        self.added: list[str] = []

    def _answer(self, method: str, url: str, data: Any = None) -> _Response:
        path = "/" + url.split("://", 1)[-1].split("/", 1)[1].split("?", 1)[0]
        body = json.loads(data) if isinstance(data, str) and data else None
        self.requests.append((method, path, body))
        if path == f"/product/202309/products/{SOURCE_ID}":
            return _Response(_detail(SOURCE_ID, "Bình giữ nhiệt inox 750ml"))
        if path == "/product/202309/products/search":
            return _Response({"products": [{"id": SOURCE_ID}]})
        if path == "/promotion/202309/activities/search":
            return _Response({"activities": []})
        if (method, path) == ("POST", PROMOTION_CREATE_PATH):
            return _Response({"activity_id": "7660009586606409490", "status": "NOT_START"})
        if path == promotion_activity_products_path("7660009586606409490"):
            self.added = [p["id"] for p in body["products"]]
            return _Response({"activity_id": "7660009586606409490", "status": "NOT_START"})
        if path == promotion_activity_path("7660009586606409490"):
            return _Response(
                {"activity_id": "7660009586606409490", "status": "NOT_START",
                 "title": "Giảm giá bình giữ nhiệt · 10:02 23/10",
                 "products": [{"id": pid, "discount": "15"} for pid in self.added]}
            )  # fmt: skip
        raise AssertionError(f"unexpected request {method} {path}")

    def get(self, url: str, **kw: Any) -> _Response:
        return self._answer("GET", url)

    def post(self, url: str, **kw: Any) -> _Response:
        return self._answer("POST", url, kw.get("data"))

    def put(self, url: str, **kw: Any) -> _Response:
        return self._answer("PUT", url, kw.get("data"))


def test_the_create_goes_through_exactly_one_sandbox_factory_client(monkeypatch):
    built: list[Any] = []
    original = SandboxWriteClientFactory.create

    def counting_create(self, config):
        client = original(self, config)
        built.append(client)
        return client

    monkeypatch.setattr(SandboxWriteClientFactory, "create", counting_create)
    resources = SandboxWriteClientFactory().create_resources(
        ClientFactoryConfig(
            app_key="k", app_secret="s", access_token="t", merchant_auth_id="sbx-merchant",
            credential_capability="sandbox_write", shop_cipher="ROW_cipher",
        )
    )  # fmt: skip
    assert len(built) == 1
    session = _RoutedSession()
    built[0]._session = session
    out = pc.handle_create_product_discount(resources, CONTEXT, _choice())
    assert out.ok, out
    assert out.summary_vi.startswith(
        "Đã tạo khuyến mãi trên TikTok · mã 7660009586606409490 · Chưa bắt đầu"
    )
    writes = [(m, p) for m, p, _ in session.requests if m == "PUT" or p == PROMOTION_CREATE_PATH]
    assert writes == [
        ("POST", "/promotion/202309/activities"),
        ("PUT", "/promotion/202309/activities/7660009586606409490/products"),
    ]
    assert session.requests[-1][:2] == ("GET", "/promotion/202309/activities/7660009586606409490")
    assert len(built) == 1


# -- transport allowlists -----------------------------------------------------------------


PROMOTION_WRITES = [
    ("POST", PROMOTION_CREATE_PATH),
    ("PUT", promotion_activity_products_path("7660009586606409490")),
    ("PUT", promotion_activity_path("7660009586606409490")),
    ("POST", "/promotion/202309/activities/7660009586606409490/deactivate"),
]


@pytest.mark.parametrize(("method", "path"), PROMOTION_WRITES)
def test_promotion_writes_are_on_the_sandbox_allowlist_only(method, path):
    assert is_sandbox_write_allowed(method, path)
    SandboxOnlyWriteGuard().assert_allowed(method, path)
    assert not is_production_write_allowed(method, path)
    assert not is_production_read_allowed(method, path)
    assert not any(
        allowed == method and pattern.match(path)
        for allowed, pattern in PRODUCTION_WRITE_ALLOWED_REQUESTS
    )
    with pytest.raises(TransportGuardError):
        ProductionWriteGuard().assert_allowed(method, path)


def test_production_resources_carry_no_promotion_and_the_tool_never_goes_live():
    assert not hasattr(ProductionWriteResources(products=cast(Any, None)), "promotion")
    assert "create_product_discount" in composition.NEVER_PRODUCTION_WRITE_TOOLS
    assert "create_product_discount" not in composition.LIVE_ELIGIBLE_WRITE_TOOLS


def test_only_the_create_promotion_playbook_offers_the_promotion_tools():
    tools = {pc.GET_PROMOTION_CANDIDATES_TOOL, pc.CHECK_PROMOTION_ELIGIBILITY_TOOL,
             pc.CREATE_PRODUCT_DISCOUNT_TOOL}  # fmt: skip
    for key, playbook in playbooks.get_registered_playbooks().items():
        offered = {name for step in playbook.steps for name in step.tools}
        if key == playbooks.CREATE_PROMOTION_WORKFLOW_KEY:
            assert offered == tools
        else:
            assert not offered & tools, key
    step = next(
        s
        for s in playbooks.CREATE_PROMOTION_PLAYBOOK.steps
        if pc.CREATE_PRODUCT_DISCOUNT_TOOL in s.tools
    )
    assert step.policy.value == "confirm"


# -- card + approve -----------------------------------------------------------------------


def _promo_card(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if (item["recommendation"].get("card") or {}).get("lever", {}).get("code") == (
            "create_promotion"
        ):
            return item
    return None


async def _promo_rows(session, shop_id) -> list[ActionCard]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_id, ActionCard.workflow_key == "create_promotion"
                )
            )
        ).scalars()
    )


async def test_the_sandbox_reviewer_gets_one_real_promotion_card(session, world):
    ids, reviewer_id = world
    async with client_for(build_app(session)) as client:
        first = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
        second = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
    assert first.status_code == 200, first.text
    item = _promo_card(first.json()["data"])
    assert item is not None
    card = item["recommendation"]["card"]
    assert card["lever"] == {
        "code": "create_promotion",
        "label": "Tạo khuyến mãi",
        "executor": "juli",
    }
    assert card["workflow_label"] == "Khuyến mãi"
    assert card["product_title"] == "Tạo khuyến mãi giảm giá cho «Bình giữ nhiệt inox 750ml»"
    assert card["change_fields"] == [
        {"field": "product_discount", "label": "Khuyến mãi giảm giá trên TikTok"}
    ]
    assert card["reason_short"] == "Thử khuyến mãi trên TikTok"
    assert card["expected_gmv_per_month"] is None  # no ROI / forecast claim
    assert item["is_executable"] is True
    assert _promo_card(second.json()["data"])["id"] == item["id"]
    rows = await _promo_rows(session, ids["sandbox"])
    assert len(rows) == 1 and rows[0].subject_id == str(ids["product"])


async def test_no_card_for_a_product_already_in_a_price_promotion(session, world, card_tiktok):
    """P66 (D16): the live «Nồi lẩu» case -- the only product is held by a running price
    promotion, so no card is emitted, and an active card for it is retired."""
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        first = await client.get("/v1/demo/decisions", headers=headers)
    assert _promo_card(first.json()["data"]) is not None
    from juli_backend.services.reviewer import create_promotion_card as card_module

    card_module.reset_cache()  # the next read re-checks TikTok
    card_tiktok["resources"] = _sandbox(
        WindowedPromotion(NOW - timedelta(days=1), NOW + timedelta(days=5))
    )
    async with client_for(build_app(session)) as client:
        second = await client.get("/v1/demo/decisions", headers=headers)
    assert second.status_code == 200, second.text
    assert _promo_card(second.json()["data"]) is None
    rows = await _promo_rows(session, ids["sandbox"])
    assert [row.status for row in rows] == ["expired"]


async def test_no_card_when_tiktok_cannot_be_read(session, world, card_tiktok):
    ids, reviewer_id = world
    card_tiktok["error"] = RuntimeError("no sandbox credential")
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
    assert listed.status_code == 200, listed.text
    assert _promo_card(listed.json()["data"]) is None
    assert await _promo_rows(session, ids["sandbox"]) == []


async def test_a_seller_never_sees_or_approves_the_promotion_card(session, world, enqueued):
    ids, reviewer_id = world
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
        card_id = _promo_card(listed.json()["data"])["id"]
        seller = _headers(ids["owner"], ids["sandbox"], platform=None, email="o@gmail.com")
        own_list = await client.get("/v1/demo/decisions", headers=seller)
        detail = await client.get(f"/v1/demo/decisions/{card_id}", headers=seller)
        approve = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=seller)
    assert own_list.status_code == 200 and _promo_card(own_list.json()["data"]) is None
    assert detail.status_code == 404
    assert approve.status_code == 404, approve.text
    assert enqueued == []


async def test_a_reviewer_on_another_pin_is_403_and_gets_no_card(
    session, world, monkeypatch, enqueued
):
    ids, reviewer_id = world
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
    card_id = _promo_card(listed.json()["data"])["id"]
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ids["fujiwa"]))
    masked = _headers(reviewer_id, shop_alias_id(ids["fujiwa"]))
    async with client_for(build_app(session)) as client:
        masked_list = await client.get("/v1/demo/decisions", headers=masked)
        approve = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=masked)
    assert masked_list.status_code == 200 and _promo_card(masked_list.json()["data"]) is None
    assert await _promo_rows(session, ids["fujiwa"]) == []
    assert approve.status_code == 403, approve.text
    assert approve.headers["x-juli-reviewer-denied"] == "sandbox_only"
    assert enqueued == []


async def test_reviewer_approve_starts_the_promotion_run_with_the_shop_rules(
    session, world, enqueued
):
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        card_id = _promo_card(listed.json()["data"])["id"]
        approve = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=headers)
    assert approve.status_code == 202, approve.text
    session.expire_all()
    runs = list((await session.execute(select(WorkflowRun))).scalars())
    assert [run.workflow_key for run in runs] == ["create_promotion"]
    run = runs[0]
    assert run.product_id == ids["product"] and run.prompt_version == "create_promotion.v1"
    opening = json.loads(run.state["conversation_window"][0]["content"])
    assert opening["shop_rules"]["discount"]["min_pct"] == 5
    assert opening["shop_rules"]["discount"]["max_pct"] == 30
    assert enqueued == [run.id]


async def test_the_promotion_daily_cap_answers_429(session, world, enqueued):
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        await client.get("/v1/demo/decisions", headers=headers)  # the reviewer's users row
    await p64.seed_capped_runs(
        session,
        shop_id=ids["sandbox"],
        reviewer_id=reviewer_id,
        workflow_key="create_promotion",
        write_tool="create_product_discount",
        statuses=["succeeded"] * approval_module.CREATE_PROMOTION_DAILY_CAP,
    )
    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        card_id = _promo_card(listed.json()["data"])["id"]
        capped = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=headers)
    assert capped.status_code == 429, capped.text
    detail = capped.json()["detail"]
    assert detail["code"] == "create_promotion_daily_cap" and detail["cap"] == 3
    assert detail["retry_after_seconds"] > 0 and detail["retry_at"].endswith("Z")
    assert enqueued == []


async def test_a_failed_discount_write_does_not_use_up_the_cap(session, world, enqueued):
    """P66 (D14): a discount TikTok refused (or a declined run) is not counted."""
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        await client.get("/v1/demo/decisions", headers=headers)  # the reviewer's users row
    await p64.seed_capped_runs(
        session,
        shop_id=ids["sandbox"],
        reviewer_id=reviewer_id,
        workflow_key="create_promotion",
        write_tool="create_product_discount",
        statuses=["succeeded", "succeeded", "failed", None],
    )
    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        card_id = _promo_card(listed.json()["data"])["id"]
        approved = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=headers)
    assert approved.status_code == 202, approved.text


# -- the confirmation: the reviewer's discount % and end date -------------------------------

PROPOSED = _choice().model_dump()


async def _waiting_promotion_run(session, shop_id):
    from types import SimpleNamespace

    run = await make_workflow_run(
        session,
        cast(Any, SimpleNamespace(id=shop_id)),
        status="waiting_approval",
        workflow_key="create_promotion",
        prompt_version="create_promotion.v1",
        state={
            "conversation_window": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "source": "juli",
                            "shop_rules": {"discount": pc.discount_rules_for_run(25)},
                        }
                    ),  # fmt: skip
                }
            ],
            "pending_confirmation": {
                "call_id": "call-1",
                "tool_name": pc.CREATE_PRODUCT_DISCOUNT_TOOL,
                "arguments": dict(PROPOSED),
            },
        },
    )
    session.add(
        RunConfirmation(
            workflow_run_id=run.id,
            tool_call_id="call-1",
            options=[
                {
                    "option_id": "1",
                    "proposed_change": dict(PROPOSED),
                    "rationale": "x",
                    "params_sha": compute_params_sha(dict(PROPOSED)),
                }
            ],
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=4),
        )
    )
    await session.commit()
    return run


@pytest.fixture
def resumed(monkeypatch) -> list[Any]:
    from juli_backend.api.routes import agent_runs

    calls: list[Any] = []
    monkeypatch.setattr(
        agent_runs,
        "_enqueue_resume_agent_workflow",
        lambda run_id, *, approved: calls.append((run_id, approved)) or "task-resume",
    )
    return calls


async def _confirm(session, reviewer_id, shop_id, run, body):
    async with client_for(build_app(session)) as client:
        return await client.post(
            f"/v1/demo/runs/{run.id}/confirmations/call-1",
            json=body,
            headers=_headers(reviewer_id, shop_id),
        )


async def test_the_reviewer_confirms_an_edited_discount_and_end_date(session, world, resumed):
    ids, reviewer_id = world
    run = await _waiting_promotion_run(session, ids["sandbox"])
    resp = await _confirm(
        session, reviewer_id, ids["sandbox"], run,
        {"decision": "approve", "option_id": "1",
         "edited_values": {"discount_pct": 20, "end_date": "2026-11-05"}},
    )  # fmt: skip
    assert resp.status_code == 202, resp.text
    await session.refresh(run)
    pending = run.state["pending_confirmation"]
    expected = {**PROPOSED, "discount_pct": 20, "end_date": "2026-11-05"}
    assert pending["arguments"] == expected
    assert pending["params_sha"] == compute_params_sha(expected)
    assert pending["edited_fields"] == ["discount_pct", "end_date"]
    assert resumed == [(run.id, True)]
    audit = (
        (await session.execute(select(OpsAuditLog).where(
            OpsAuditLog.action == "reviewer_sandbox_create_promotion"
        ))).scalars().one()
    )  # fmt: skip
    after = audit.after if isinstance(audit.after, dict) else json.loads(audit.after)
    assert after["discount_pct"] == 20 and after["end_date"] == "2026-11-05"


@pytest.mark.parametrize(
    ("edited", "field", "fragment"),
    [
        ({"discount_pct": 26}, "discount_pct", "Mức giảm phải từ 5% đến 25%"),
        ({"discount_pct": 2}, "discount_pct", "Mức giảm phải từ 5% đến 25%"),
        ({"end_date": "2026-12-31"}, "end_date", "không quá 30 ngày"),
        ({"end_date": "31/10/2026"}, "end_date", "YYYY-MM-DD"),
        ({"title": "Tiêu đề khác hẳn cho sản phẩm"}, "title", "chỉ sửa được mức giảm"),
    ],
)
async def test_an_out_of_range_edit_is_a_422_and_stays_pending(
    session, world, resumed, edited, field, fragment
):
    ids, reviewer_id = world
    run = await _waiting_promotion_run(session, ids["sandbox"])
    resp = await _confirm(
        session, reviewer_id, ids["sandbox"], run,
        {"decision": "approve", "option_id": "1", "edited_values": edited},
    )  # fmt: skip
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "rule_violation" and detail["field"] == field
    assert fragment in detail["message"]
    session.expire_all()
    confirmation = (await session.execute(select(RunConfirmation))).scalar_one()
    assert confirmation.status == "pending"
    assert resumed == []


# -- the real runner: read, check, pause, the reviewer's edit, create ------------------------


class ScriptedPromotionLLM:
    """Reads the candidates, checks, proposes the create; ends after it returns."""

    def __init__(self) -> None:
        self.seen: list[Any] = []

    async def complete(self, *, messages, system, tools, config, tool_choice=None, **_: Any):
        from juli_backend.services.agent.llm.blocks import FinalResponse, ToolCallBlock
        from tests.unit.test_p64_create_product_walkthrough import _turn

        del system, tools, config, tool_choice
        self.seen = list(messages)
        done = {
            m.get("tool_name") for m in messages if isinstance(m, dict) and m.get("role") == "tool"
        }
        if pc.CREATE_PRODUCT_DISCOUNT_TOOL in done:
            return _turn(
                FinalResponse(content="Đã tạo khuyến mãi. Shop sandbox không có người mua thật.")
            )
        choice = {"product_ids": [SOURCE_ID], "discount_pct": 15, "end_date": "2026-10-30"}
        if pc.CHECK_PROMOTION_ELIGIBILITY_TOOL in done:
            return _turn(ToolCallBlock(call_id="c3", tool_name=pc.CREATE_PRODUCT_DISCOUNT_TOOL,
                                       arguments=_choice().model_dump()))  # fmt: skip
        if pc.GET_PROMOTION_CANDIDATES_TOOL in done:
            return _turn(ToolCallBlock(call_id="c2", tool_name=pc.CHECK_PROMOTION_ELIGIBILITY_TOOL,
                                       arguments=choice))  # fmt: skip
        return _turn(
            ToolCallBlock(call_id="c1", tool_name=pc.GET_PROMOTION_CANDIDATES_TOOL, arguments={})
        )


def _runner(resources, store, sink, llm):
    from juli_backend.services.agent.playbooks import CREATE_PROMOTION_PLAYBOOK
    from juli_backend.services.agent.runner.core import WorkflowRunner
    from juli_backend.services.agent.runner.tool_executor import ProductToolExecutor
    from juli_backend.services.agent.tools import ToolRegistry
    from juli_backend.services.agent.tools.terminal import register_terminal_tools

    registry = ToolRegistry()
    pc.register_promotion_create_tools(registry)
    register_terminal_tools(registry)
    executor = ProductToolExecutor(
        registry=registry,
        read_resources=resources,
        write_resources=resources,
        product_id=SOURCE_ID,
        discount_rules=pc.discount_rules_for_run(25),
    )
    return WorkflowRunner(
        llm_service=llm,
        tool_executor=executor,
        event_sink=sink,
        conversation_store=store,
        registry=registry,
        playbook=CREATE_PROMOTION_PLAYBOOK,
    )


async def test_the_run_pauses_then_creates_exactly_the_reviewers_edit(session, world):
    from juli_backend.services.agent.events import InMemoryEventSink
    from juli_backend.services.agent.runner.state import RunState
    from juli_backend.services.agent.status import WorkflowRunStatus
    from juli_backend.services.agent_runs import confirmations
    from tests.unit.test_p64_create_product_walkthrough import InMemoryStore

    ids, _ = world
    promotion = FakePromotion()
    resources, store, sink, llm = (
        _sandbox(promotion),
        InMemoryStore(),
        InMemoryEventSink(),
        ScriptedPromotionLLM(),
    )
    run_id = uuid.uuid4()
    paused = await _runner(resources, store, sink, llm).run(run_id, product_ref=SOURCE_ID)
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL, paused
    assert [k for k, _ in promotion.calls if k in ("create", "products")] == []  # nothing yet
    state = store.states[run_id].to_dict()
    state["conversation_window"][0] = {
        "role": "user",
        "content": json.dumps(
            {"source": "juli", "shop_rules": {"discount": pc.discount_rules_for_run(25)}}
        ),
    }
    from types import SimpleNamespace

    row = await make_workflow_run(
        session, cast(Any, SimpleNamespace(id=ids["sandbox"])), status="waiting_approval",
        workflow_key="create_promotion", state=state,
    )  # fmt: skip
    await confirmations._apply_seller_edits(
        session, row, {"discount_pct": 20, "end_date": "2026-11-01"}
    )
    store.states[run_id] = RunState.from_dict(cast(dict, row.state))

    done = await _runner(resources, store, sink, llm).resume(run_id, approved=True)
    assert done.status == WorkflowRunStatus.COMPLETED, done
    added = next(body for kind, body in promotion.calls if kind == "products")
    assert {p["discount"] for p in added["products"]} == {"20"}
    create = next(body for kind, body in promotion.calls if kind == "create")
    assert create["end_time"] == int(
        datetime.fromisoformat("2026-11-01T23:59:59+07:00").timestamp()
    )
    completed = [e.payload for e in sink.events if e.event_type == "tool.completed"]
    assert [c.tool_name for c in completed] == [
        "get_promotion_candidates",
        "check_promotion_eligibility",
        "create_product_discount",
    ]
    last = completed[-1]
    assert last.ok and last.summary.startswith(
        "Đã tạo khuyến mãi trên TikTok · mã 7660009586606409490"
    )
    assert last.summary.endswith("· theo bản bạn sửa")


class HangingAfterWriteLLM(ScriptedPromotionLLM):
    """P66 (D21): the closing model turn after the write never returns (run 887bb1be)."""

    async def complete(self, *, messages, **kw: Any):
        done = {
            m.get("tool_name") for m in messages if isinstance(m, dict) and m.get("role") == "tool"
        }
        if pc.CREATE_PRODUCT_DISCOUNT_TOOL in done:
            raise AssertionError("no model turn after the confirmed create")
        return await super().complete(messages=messages, **kw)


async def test_the_run_ends_right_after_the_confirmed_create():
    """P66 (D21): the discount exists on TikTok, so the run is completed at once --
    workflow.completed right after the write's tool.completed, no closing model turn."""
    from juli_backend.services.agent.events import InMemoryEventSink
    from juli_backend.services.agent.status import WorkflowRunStatus
    from tests.unit.test_p64_create_product_walkthrough import InMemoryStore

    resources, store, sink = _sandbox(FakePromotion()), InMemoryStore(), InMemoryEventSink()
    run_id = uuid.uuid4()
    llm = HangingAfterWriteLLM()
    paused = await _runner(resources, store, sink, llm).run(run_id, product_ref=SOURCE_ID)
    assert paused.status == WorkflowRunStatus.WAITING_APPROVAL
    done = await _runner(resources, store, sink, llm).resume(run_id, approved=True)
    assert done.status == WorkflowRunStatus.COMPLETED and done.stop_reason == "final_response"
    assert done.final_response and done.final_response.startswith("Đã tạo khuyến mãi trên TikTok")
    types = [e.event_type for e in sink.events]
    assert types[-2:] == ["tool.completed", "workflow.completed"]


class ConcludingLLM(ScriptedPromotionLLM):
    """Reads the candidates, then concludes without proposing (run 12d703c0)."""

    async def complete(self, *, messages, system, tools, config, tool_choice=None, **_: Any):
        from juli_backend.services.agent.llm.blocks import ToolCallBlock
        from tests.unit.test_p64_create_product_walkthrough import _turn

        done = {
            m.get("tool_name") for m in messages if isinstance(m, dict) and m.get("role") == "tool"
        }
        if pc.GET_PROMOTION_CANDIDATES_TOOL in done:
            return _turn(ToolCallBlock(call_id="c9", tool_name="conclude_without_changes",
                                       arguments={"reason": "busy"}))  # fmt: skip
        return _turn(
            ToolCallBlock(call_id="c1", tool_name=pc.GET_PROMOTION_CANDIDATES_TOOL, arguments={})
        )


async def test_a_run_that_declines_says_why_from_its_facts():
    """P66 (D15): the bound product is held by a price promotion until 28/10 -- the run
    ends with that reason, not "Luồng đã kết thúc"."""
    from juli_backend.services.agent.events import InMemoryEventSink
    from tests.unit.test_p64_create_product_walkthrough import InMemoryStore

    promotion = WindowedPromotion(NOW - timedelta(days=1), NOW + timedelta(days=5))
    sink = InMemoryEventSink()
    result = await _runner(_sandbox(promotion), InMemoryStore(), sink, ConcludingLLM()).run(
        uuid.uuid4(), product_ref=SOURCE_ID
    )
    assert result.stop_reason == "concluded_without_changes"
    last_two = sink.events[-2:]
    assert [e.event_type for e in last_two] == ["workflow.status", "workflow.completed"]
    assert last_two[0].payload.phase_narration == (
        "Sản phẩm «Bình giữ nhiệt inox 750ml» đang có khuyến mãi giá đến 28/10 — TikTok không "
        "cho chồng hai khuyến mãi giá; Juli không tạo khuyến mãi mới."
    )
