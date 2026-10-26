"""P64 (D73.3 / D73.4): the sandbox reviewer's "Tạo sản phẩm" -- a real agent run that
creates a TikTok listing on Juli's SANDBOX shop, and nowhere else.

- the tools (``services/agent/tools/catalog_create.py``) with a faked TikTok: candidates,
  the requirement check (invalid category / missing required attribute → no create), the
  create itself (exactly one Create Product call on ``SandboxWriteResources``, read back),
  and the refusal of any non-sandbox resources;
- the transport allowlists: product create is on the sandbox allowlist only;
- the playbook: the tools are offered by ``create_product`` alone;
- the card + approve: the sandbox reviewer gets one real card; approving it starts the
  ``create_product`` run; a second approve is 409, the daily cap 429; a seller and a
  non-sandbox shop cannot reach it.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any, cast

import pytest
from sqlalchemy import select

from juli_backend.integrations.tiktok import (
    ProductionWriteResources,
    SandboxWriteResources,
    TikTokAPIError,
    TikTokCapability,
    TransportGuardError,
)
from juli_backend.integrations.tiktok.capabilities import (
    PRODUCTION_WRITE_ALLOWED_REQUESTS,
    is_production_write_allowed,
    is_sandbox_write_allowed,
)
from juli_backend.integrations.tiktok.constants import PRODUCT_CREATE_PATH
from juli_backend.integrations.tiktok.guards import ProductionWriteGuard, SandboxOnlyWriteGuard
from juli_backend.models.models import (
    ActionCard,
    ActionCardApproval,
    ToolExecution,
    WorkflowRun,
)
from juli_backend.models.ops import OpsAuditLog
from juli_backend.repositories import TikTokCredentialRepo
from juli_backend.services.agent import approval as approval_module
from juli_backend.services.agent import playbooks
from juli_backend.services.agent.tools import catalog_create as cc
from juli_backend.services.agent.tools.product import ProductToolContext
from juli_backend.services.reviewer.config import shop_alias_id
from tests.support import reviewer as rv
from tests.support.api import build_app, client_for
from tests.support.builders import utc_now_naive

SOURCE_ID = "1736405947247986307"
WAREHOUSE = "7657265511696664340"


class FakeProducts:
    """``ProductsResource`` double for the sandbox shop (water bottle, VN)."""

    def __init__(self, *, attributes: list[dict[str, Any]] | None = None) -> None:
        self.created: list[dict[str, Any]] = []
        self.prerequisites_failed: list[str] = []
        self.create_error: int | None = None
        self.attributes = attributes or [
            {"id": "100149", "name": "Xuất xứ", "is_requried": True, "type": "PRODUCT_PROPERTY"},
            {"id": "101164", "name": "Kiểu", "is_requried": False, "type": "PRODUCT_PROPERTY"},
        ]

    def get_details(self, product_id: str) -> dict[str, Any]:
        if product_id == SOURCE_ID:
            return {
                "id": SOURCE_ID,
                "title": "Bình giữ nhiệt inox 750ml",
                "description": "<p>Bình inox giữ nhiệt.</p>",
                "category_chains": [{"id": "605254", "is_leaf": True, "local_name": "Bình nước"}],
                "main_images": [{"uri": "tos-src-1"}, {"uri": "tos-src-2"}],
                "product_attributes": [
                    {"id": "100149", "values": [{"id": "1000854", "name": "Việt Nam"}]},
                    {"id": "999", "values": [{"name": "không thuộc danh mục"}]},
                ],
                "package_weight": {"value": "500", "unit": "GRAM"},
                "skus": [
                    {
                        "id": "1736433041572857475",
                        "price": {"sale_price": "82000", "currency": "VND"},
                        "inventory": [{"warehouse_id": WAREHOUSE, "quantity": 40}],
                    }
                ],
            }
        return {"id": product_id, "title": "Combo 2 bình giữ nhiệt", "status": "PENDING",
                "audit": {"status": "AUDITING"}}  # fmt: skip

    def get_categories(self) -> dict[str, Any]:
        return {
            "categories": [
                {"id": "601450", "is_leaf": False, "local_name": "Nhà cửa"},
                {"id": "700001", "is_leaf": True, "local_name": "Bình nước inox giữ nhiệt"},
                {"id": "605254", "is_leaf": True, "local_name": "Bình nước"},
                {"id": "700002", "is_leaf": True, "local_name": "Áo thun"},
                {"id": "700003", "is_leaf": True, "local_name": "Khoá", "permission_statuses":
                 ["INVITE_ONLY"]},
            ]
        }  # fmt: skip

    def check_listing_prerequisites(self, *, category_id: str) -> dict[str, Any]:
        return {
            "check_results": [
                {"check_item": item, "is_failed": True} for item in self.prerequisites_failed
            ]
            + [{"check_item": "SHOP_STATUS", "is_failed": False}]
        }

    def get_category_attributes(self, *, category_id: str) -> dict[str, Any]:
        return {"attributes": self.attributes}

    def create(self, *, body: dict[str, Any]) -> dict[str, Any]:
        if self.create_error is not None:
            raise TikTokAPIError(self.create_error, "rejected")
        self.created.append(body)
        return {"product_id": "1737000000000000001", "skus": [{"id": "s"}]}


def _sandbox(products: FakeProducts) -> SandboxWriteResources:
    return SandboxWriteResources(
        inventory=cast(Any, None),
        products=cast(Any, products),
        fulfillment=cast(Any, None),
        promotion=cast(Any, None),
    )


CONTEXT = ProductToolContext(product_id=SOURCE_ID)


DRAFT_P1 = (
    "Combo 2 bình giữ nhiệt inox 304 dung tích 750ml, thân hai lớp giữ nóng khoảng 12 giờ "
    "và giữ lạnh khoảng 24 giờ."
)
DRAFT_P2 = "Nắp xoay chống tràn, kèm dây đeo. Trong hộp có 2 bình và 2 dây đeo."


def _create(category_id: str = "605254") -> cc.CreateProductInput:
    return cc.CreateProductInput(
        category_id=category_id,
        title="Combo 2 bình giữ nhiệt inox 750ml",
        description=f"{DRAFT_P1}\n\n{DRAFT_P2}",
        reason_vi="Cùng danh mục bình nước với sản phẩm gốc.",
    )


# -- tools ------------------------------------------------------------------------------


def test_candidates_put_the_source_category_first_and_offer_leaves_only():
    out = cc.handle_get_category_candidates(
        _sandbox(FakeProducts()), CONTEXT, cc.GetCategoryCandidatesInput()
    )
    ids = [c.category_id for c in out.candidates]
    assert ids[0] == "605254"  # the source listing's own leaf category
    assert ids[1] == "700001"  # best word overlap with the source title
    assert "601450" not in ids and "700003" not in ids  # not a leaf / not available
    assert out.price == "82000" and out.new_listing_stock == 10
    assert out.ok and out.summary_vi


def test_check_refuses_a_category_that_is_not_a_candidate():
    out = cc.handle_check_listing_requirements(
        _sandbox(FakeProducts()), CONTEXT, cc.CheckListingRequirementsInput(category_id="42")
    )
    assert out.ok is False and out.error_code == "category_suggestion_invalid"


def test_check_reports_a_missing_required_attribute_and_never_guesses():
    products = FakeProducts(
        attributes=[
            {"id": "101489", "name": "Tên nhà sản xuất", "is_requried": True},
            {"id": "100149", "name": "Xuất xứ", "is_required": True},
        ]
    )
    out = cc.handle_check_listing_requirements(
        _sandbox(products), CONTEXT, cc.CheckListingRequirementsInput(category_id="605254")
    )
    assert out.ok is False and out.error_code == "required_attribute_missing"
    assert out.missing == ["Tên nhà sản xuất"]


def test_create_builds_one_create_call_from_the_source_and_reads_it_back():
    products = FakeProducts()
    out = cc.handle_create_product(_sandbox(products), CONTEXT, _create())
    assert out.ok, out
    assert len(products.created) == 1
    body = products.created[0]
    assert body["category_id"] == "605254"
    assert body["title"] == "Combo 2 bình giữ nhiệt inox 750ml"
    assert body["description"] == f"<p>{DRAFT_P1}</p><p>{DRAFT_P2}</p>"
    assert body["main_images"] == [{"uri": "tos-src-1"}, {"uri": "tos-src-2"}]
    sku = body["skus"][0]
    assert sku["price"] == {"amount": "82000", "currency": "VND"}
    assert sku["inventory"] == [{"warehouse_id": WAREHOUSE, "quantity": 10}]
    # Only attributes the category knows, copied verbatim -- never invented.
    assert body["product_attributes"] == [
        {"id": "100149", "values": [{"id": "1000854", "name": "Việt Nam"}]}
    ]
    assert body["package_weight"] == {"value": "500", "unit": "GRAM"}
    assert "brand_id" not in body
    # TikTok's read-back, shown honestly.
    assert out.tiktok_product_id == "1737000000000000001"
    assert out.status == "PENDING" and out.status_label_vi == "Đang chờ TikTok duyệt"
    assert out.audit_status == "AUDITING"
    assert out.confirmed_at and out.confirmed_at.endswith("Z")
    assert out.summary_vi.startswith("Đã tạo sản phẩm trên TikTok · mã 1737000000000000001")
    assert "TikTok xác nhận lúc" in out.summary_vi


def test_create_html_escapes_the_drafted_description():
    assert cc.description_html("a <b>x</b>\nb") == "<p>a &lt;b&gt;x&lt;/b&gt;</p><p>b</p>"


@pytest.mark.parametrize(
    ("category", "products_kw", "code"),
    [
        ("42", {}, "category_suggestion_invalid"),
        (
            "605254",
            {"attributes": [{"id": "5", "name": "Thương hiệu", "is_requried": True}]},
            "required_attribute_missing",
        ),
    ],
)
def test_create_refuses_without_calling_tiktok_create(category, products_kw, code):
    products = FakeProducts(**products_kw)
    out = cc.handle_create_product(_sandbox(products), CONTEXT, _create(category))
    assert out.ok is False and out.error_code == code
    assert products.created == []
    assert out.summary_vi.startswith("Chưa tạo sản phẩm")


def test_create_reports_prerequisites_and_tiktok_errors_honestly():
    products = FakeProducts()
    products.prerequisites_failed = ["SHOP_TAX"]
    refused = cc.handle_create_product(_sandbox(products), CONTEXT, _create())
    assert refused.error_code == "listing_prerequisites_failed" and products.created == []
    products = FakeProducts()
    products.create_error = 12019009
    failed = cc.handle_create_product(_sandbox(products), CONTEXT, _create())
    assert failed.ok is False and failed.error_code == "tiktok_error"
    assert "12019009" in failed.summary_vi
    # TikTok's own reason is kept, so the refused field is visible to the reviewer and in the log.
    assert "rejected" in failed.summary_vi


def test_create_refuses_production_write_resources_before_any_request():
    products = FakeProducts()
    production = ProductionWriteResources(products=cast(Any, products))
    with pytest.raises(cc.CreateProductRefused):
        cc.handle_create_product(production, CONTEXT, _create())
    with pytest.raises(cc.CreateProductRefused):
        cc.handle_create_product(type("R", (), {"products": products})(), CONTEXT, _create())
    assert products.created == []


# -- transport allowlists ---------------------------------------------------------------


def test_product_create_is_on_the_sandbox_allowlist_only():
    assert PRODUCT_CREATE_PATH == "/product/202309/products"
    assert is_sandbox_write_allowed("POST", PRODUCT_CREATE_PATH)
    assert not is_production_write_allowed("POST", PRODUCT_CREATE_PATH)
    assert not any(
        method == "POST" and pattern.match(PRODUCT_CREATE_PATH)
        for method, pattern in PRODUCTION_WRITE_ALLOWED_REQUESTS
    )
    SandboxOnlyWriteGuard().assert_allowed("POST", PRODUCT_CREATE_PATH)
    with pytest.raises(TransportGuardError):
        ProductionWriteGuard().assert_allowed("POST", PRODUCT_CREATE_PATH)


def test_only_the_create_product_playbook_offers_the_create_tools():
    tools = {cc.GET_CATEGORY_CANDIDATES_TOOL, cc.CHECK_LISTING_REQUIREMENTS_TOOL,
             cc.CREATE_PRODUCT_TOOL}  # fmt: skip
    for key, playbook in playbooks.get_registered_playbooks().items():
        offered = {name for step in playbook.steps for name in step.tools}
        if key == playbooks.CREATE_PRODUCT_WORKFLOW_KEY:
            assert offered == tools
        else:
            assert not offered & tools, key
    create_step = next(
        step
        for step in playbooks.CREATE_PRODUCT_PLAYBOOK.steps
        if cc.CREATE_PRODUCT_TOOL in step.tools
    )
    assert create_step.policy.value == "confirm"


# -- card + approve ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reviewer_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", rv.JWT_SECRET)
    monkeypatch.setenv("REVIEWER_ACCOUNT_CACHE_SECONDS", "0")
    rv.reset_caches()
    yield
    rv.reset_caches()


@pytest.fixture
async def world(session, monkeypatch):
    sandbox = await rv.seed_reference_shop(
        session,
        name="Juli Sandbox VN",
        tiktok_shop_id="7600000000000000001",
        title="Bình giữ nhiệt inox 750ml",
        product_id=SOURCE_ID,
        seller_sku="SBX-01",
    )
    fujiwa = await rv.seed_reference_shop(session)
    await TikTokCredentialRepo(session).create(
        sandbox.shop.id,
        "sbx-token",
        "sbx-refresh",
        utc_now_naive() + timedelta(days=30),
        merchant_authorization_id="sandbox-merchant-7001",
        capability=TikTokCapability.SANDBOX_WRITE.value,
        shop_cipher="cipher-sbx",
        scopes="seller.product.write",
    )
    await TikTokCredentialRepo(session).create(
        fujiwa.shop.id,
        "fuji-token",
        "fuji-refresh",
        utc_now_naive() + timedelta(days=30),
        merchant_authorization_id="prod-merchant-9001",
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher="cipher-fuji",
        scopes="seller.product.basic",
    )
    await session.commit()
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(sandbox.shop.id))
    reviewer_id = await rv.make_reviewer(session)
    ids = {
        "sandbox": sandbox.shop.id,
        "owner": sandbox.owner.id,
        "product": sandbox.product.id,
        "fujiwa": fujiwa.shop.id,
    }
    return ids, reviewer_id


@pytest.fixture
def enqueued(monkeypatch) -> list[uuid.UUID]:
    queued: list[uuid.UUID] = []
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_run_agent_workflow",
        lambda run_id: queued.append(run_id) or "celery-1",
    )
    monkeypatch.setattr(
        "juli_backend.api.routes.demo_execution._enqueue_approval_baseline",
        lambda shop_id, run_id: None,
    )
    return queued


def _headers(user_id, shop_id=None, **kw) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {rv.token(user_id, **kw)}"}
    if shop_id is not None:
        headers["X-Shop-Id"] = str(shop_id)
    return headers


def _create_card(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in items:
        if (item["recommendation"].get("card") or {}).get("lever", {}).get("code") == (
            "create_product"
        ):
            return item
    return None


async def _create_cards(session, shop_id) -> list[ActionCard]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(ActionCard).where(
                    ActionCard.shop_id == shop_id, ActionCard.workflow_key == "create_product"
                )
            )
        ).scalars()
    )


async def test_the_sandbox_reviewer_gets_one_real_create_product_card(session, world):
    ids, reviewer_id = world
    async with client_for(build_app(session)) as client:
        first = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
        second = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
    assert first.status_code == 200, first.text
    item = _create_card(first.json()["data"])
    assert item is not None
    card = item["recommendation"]["card"]
    assert card["lever"] == {"code": "create_product", "label": "Tạo sản phẩm", "executor": "juli"}
    assert card["status"] == "pending"
    assert card["change_fields"] == [{"field": "new_listing", "label": "Sản phẩm mới"}]
    assert card["reason_short"] == "Mở rộng danh mục"
    # P64 walkthrough: it reads as a creation, not "Tối ưu sản phẩm".
    assert card["workflow_label"] == "Tạo sản phẩm"
    assert card["product_title"] == "Tạo sản phẩm mới từ Bình giữ nhiệt inox 750ml"
    assert item["is_executable"] is True
    assert item["recommendation"]["diagnosis"]["tiktok_product_id"] == SOURCE_ID
    assert _create_card(second.json()["data"])["id"] == item["id"]
    rows = await _create_cards(session, ids["sandbox"])
    assert len(rows) == 1 and rows[0].subject_id == str(ids["product"])


async def test_a_seller_never_sees_or_approves_the_create_card(session, world, enqueued):
    ids, reviewer_id = world
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, ids["sandbox"])
        )
        card_id = _create_card(listed.json()["data"])["id"]
        seller = _headers(ids["owner"], ids["sandbox"], platform=None, email="o@gmail.com")
        own_list = await client.get("/v1/demo/decisions", headers=seller)
        detail = await client.get(f"/v1/demo/decisions/{card_id}", headers=seller)
        approve = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=seller)
    assert own_list.status_code == 200
    assert _create_card(own_list.json()["data"]) is None
    assert detail.status_code == 404
    assert approve.status_code == 404, approve.text
    assert enqueued == []


async def test_reviewer_approve_starts_the_create_run_once(session, world, enqueued):
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        card_id = _create_card(listed.json()["data"])["id"]
        approve = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=headers)
        again = await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=headers)
    assert approve.status_code == 202, approve.text
    assert again.status_code == 409
    session.expire_all()
    runs = list((await session.execute(select(WorkflowRun))).scalars())
    assert [run.workflow_key for run in runs] == ["create_product"]
    assert runs[0].product_id == ids["product"] and runs[0].prompt_version == "create_product.v2"
    assert enqueued == [runs[0].id]
    actions = [row.action for row in (await session.execute(select(OpsAuditLog))).scalars()]
    assert "reviewer_sandbox_approve" in actions


async def seed_capped_runs(
    session,
    *,
    shop_id,
    reviewer_id,
    workflow_key: str,
    write_tool: str,
    statuses: list[str],
    hours_ago: float = 1,
) -> None:
    """P66 (D14): one approved run per entry of ``statuses``, each with its TikTok write
    in ``tool_executions`` at that status (``None`` = the run never reached the write)."""
    for status in statuses:
        old = ActionCard(
            id=uuid.uuid4(), shop_id=shop_id, workflow_key=workflow_key,
            subject_type="product", subject_id=uuid.uuid4().hex, revision=1, priority=0,
            severity="medium", title="cũ", description="",
            recommendation_payload=json.dumps({}), status="approved",
        )  # fmt: skip
        session.add(old)
        await session.flush()
        written_at = utc_now_naive() - timedelta(hours=hours_ago)
        session.add(
            ActionCardApproval(
                action_card_id=old.id,
                approved_by_user_id=reviewer_id,
                approved_at=written_at,
                card_snapshot={},
            )
        )
        run = WorkflowRun(
            shop_id=shop_id, action_card_id=old.id, workflow_key=workflow_key,
            subject_type="product", subject_ref=old.subject_id, state={},
            status="completed" if status == "succeeded" else "failed",
            prompt_version="v", prompt_sha256="a" * 64,
        )  # fmt: skip
        session.add(run)
        await session.flush()
        if status is not None:
            session.add(
                ToolExecution(
                    shop_id=shop_id,
                    approval_id=str(old.id),
                    tool_name=write_tool,
                    status=status,
                    workflow_run_id=run.id,
                    tool_call_id="call-1",
                    operation=write_tool,
                    created_at=written_at,
                )  # fmt: skip
            )
    await session.commit()


async def _approve_create_card(session, ids, reviewer_id):
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        listed = await client.get("/v1/demo/decisions", headers=headers)
        card_id = _create_card(listed.json()["data"])["id"]
        return await client.post(f"/v1/demo/decisions/{card_id}/approve", headers=headers)


async def test_the_daily_cap_answers_429_with_when_it_frees_up(session, world, enqueued):
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        await client.get("/v1/demo/decisions", headers=headers)  # the reviewer's users row
    await seed_capped_runs(
        session,
        shop_id=ids["sandbox"],
        reviewer_id=reviewer_id,
        workflow_key="create_product",
        write_tool="create_product",
        statuses=["succeeded"] * approval_module.CREATE_PRODUCT_DAILY_CAP,
    )
    capped = await _approve_create_card(session, ids, reviewer_id)
    assert capped.status_code == 429, capped.text
    detail = capped.json()["detail"]
    assert detail["code"] == "create_product_daily_cap" and detail["cap"] == 3
    # P66 (D13): the oldest counted write leaves the 24-hour window in ~23 hours.
    assert 22 * 3600 < detail["retry_after_seconds"] <= 23 * 3600 + 5
    assert detail["retry_at"].endswith("Z")
    assert capped.headers["Retry-After"] == str(detail["retry_after_seconds"])
    assert enqueued == []


async def test_the_cap_counts_only_writes_tiktok_confirmed(session, world, enqueued):
    """P66 (D14): declined, crashed or TikTok-refused test runs never use up the cap."""
    ids, reviewer_id = world
    headers = _headers(reviewer_id, ids["sandbox"])
    async with client_for(build_app(session)) as client:
        await client.get("/v1/demo/decisions", headers=headers)  # the reviewer's users row
    await seed_capped_runs(
        session,
        shop_id=ids["sandbox"],
        reviewer_id=reviewer_id,
        workflow_key="create_product",
        write_tool="create_product",
        statuses=["succeeded", "succeeded", "failed", "failed", None, None],
    )
    # Two confirmed writes a day ago no longer count either.
    await seed_capped_runs(
        session,
        shop_id=ids["sandbox"],
        reviewer_id=reviewer_id,
        workflow_key="create_product",
        write_tool="create_product",
        statuses=["succeeded", "succeeded"],
        hours_ago=25,
    )
    approved = await _approve_create_card(session, ids, reviewer_id)
    assert approved.status_code == 202, approved.text
    assert len(enqueued) == 1


async def test_a_create_card_on_a_non_sandbox_shop_is_not_executable(session, world):
    ids, reviewer_id = world
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=ids["fujiwa"],
        workflow_key="create_product",
        subject_type="product",
        subject_id=uuid.uuid4().hex,
        revision=1,
        priority=0,
        severity="medium",
        title="x",
        description="",
        recommendation_payload=json.dumps({}),
        status="active",
    )
    session.add(card)
    await session.commit()
    with pytest.raises(approval_module.WorkflowNotExecutable):
        await approval_module.approve_action_card(
            session,
            shop_id=ids["fujiwa"],
            action_card_id=card.id,
            approved_by_user_id=reviewer_id,
            allow_create_product=True,
        )
    await session.rollback()


async def test_a_masked_reviewer_gets_no_create_card(session, world, monkeypatch):
    ids, reviewer_id = world
    monkeypatch.setenv("REVIEWER_SHOP_ID", str(ids["fujiwa"]))
    async with client_for(build_app(session)) as client:
        listed = await client.get(
            "/v1/demo/decisions", headers=_headers(reviewer_id, shop_alias_id(ids["fujiwa"]))
        )
    assert listed.status_code == 200
    assert await _create_cards(session, ids["fujiwa"]) == []
