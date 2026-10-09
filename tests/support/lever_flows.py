"""Shared fakes and seeds for the P10-B lever-flow tests (cover image, promotions,
measurement). No network: TikTok is a pair of in-memory resources that record
every call, so a test can assert that no promotion was ever written (D13).
"""

from __future__ import annotations

import copy
import io
import json
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from juli_backend.models.lever_flows import RunLeverFlow
from juli_backend.models.models import ActionCard, Product, Shop, User
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.agent.runner.state import RunState

PRODUCT_ID = "1736363193934775940"

#: ``wiring_for_run``'s sync session is only used by the photo flow's staged-URI
#: recorder, which these tests never trigger through it.
NO_SYNC_SESSION = cast(Session, None)
CDN_URL = "https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/old-cover~tplv.jpeg"

DETAIL: dict[str, Any] = {
    "id": PRODUCT_ID,
    "title": "Kem dưỡng ẩm ceramide 50ml",
    "description": "<p>mô tả</p>",
    "status": "ACTIVATE",
    "category_chains": [{"id": "601693", "is_leaf": True, "local_name": "Kem dưỡng"}],
    "package_weight": {"unit": "KILOGRAM", "value": "0.2"},
    "main_images": [
        {"uri": "tos-old-1", "width": 600, "height": 600, "urls": [CDN_URL]},
        {"uri": "tos-old-2", "width": 800, "height": 800, "urls": []},
    ],
    "skus": [
        {
            "id": "sku-1",
            "seller_sku": "KD-030",
            "price": {"currency": "VND", "tax_exclusive_price": "279000"},
        }
    ],
}


def png(
    width: int = 1000,
    height: int = 1000,
    *,
    product_box: tuple[int, int, int, int] | None = (100, 60, 900, 940),
    noisy: bool = False,
    fmt: str = "PNG",
) -> bytes:
    """A synthetic product photo: plain white (or noisy) background, dark product box."""
    if noisy:
        import random

        rng = random.Random(7)
        image = Image.new("RGB", (width, height))
        image.putdata(
            [
                (rng.randrange(256), rng.randrange(256), rng.randrange(256))
                for _ in range(width * height)
            ]
        )
    else:
        image = Image.new("RGB", (width, height), (255, 255, 255))
    if product_box is not None:
        ImageDraw.Draw(image).rectangle(product_box, fill=(40, 60, 120))
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def multipart(
    data: bytes, *, filename: str = "cover.png", field: str = "file"
) -> tuple[str, bytes]:
    boundary = "----julitestboundary7MA4YWxk"
    body = (
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return f"multipart/form-data; boundary={boundary}", body


class FakeProducts:
    """A TikTok product: reads, diagnoses, image upload and listing edit."""

    def __init__(self, detail: dict[str, Any] | None = None) -> None:
        self.detail = copy.deepcopy(detail or DETAIL)
        self.edits: list[dict[str, Any]] = []
        self.uploads: list[tuple[str, int]] = []

    def get_details(self, product_id: str) -> dict[str, Any]:
        assert product_id == PRODUCT_ID
        return copy.deepcopy(self.detail)

    def get_diagnoses(self, product_ids: list[str]) -> dict[str, Any]:
        return {
            "products": [
                {
                    "id": PRODUCT_ID,
                    "diagnoses": [
                        {
                            "field": "MAIN_IMAGE",
                            "diagnosis_results": [{"code": "LOW_QUALITY_IMAGE"}],
                        }
                    ],
                }
            ]
        }

    def upload_product_image(
        self, *, image_bytes: bytes, filename: str, use_case: str = "MAIN_IMAGE"
    ):
        self.uploads.append((filename, len(image_bytes)))
        return {"uri": "tos-new-cover", "url": "https://example.invalid/x", "width": 1000}

    def edit(self, *, product_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.edits.append(copy.deepcopy(body))
        for key in ("title", "description", "main_images"):
            self.detail[key] = copy.deepcopy(body[key])
        return {}


class FakePromotion:
    """TikTok promotions: two reads, and every write method recorded (must stay empty)."""

    def __init__(self) -> None:
        self.activities: list[dict[str, Any]] = []
        self.details: dict[str, dict[str, Any]] = {}
        self.writes: list[str] = []
        self.searches: list[str | None] = []

    def add(
        self,
        activity_id: str,
        *,
        activity_type: str = "FIXED_PRICE",
        status: str = "ONGOING",
        begin: datetime = datetime(2026, 10, 9, 1, 0, tzinfo=UTC),
        end: datetime = datetime(2026, 11, 8, 1, 0, tzinfo=UTC),
        product_ids: tuple[str, ...] = (PRODUCT_ID,),
    ) -> None:
        self.activities.append(
            {
                "id": activity_id,
                "activity_type": activity_type,
                "status": status,
                "title": "Giảm giá tháng 10",
                "begin_time": int(begin.timestamp()),
                "end_time": int(end.timestamp()),
            }
        )
        self.details[activity_id] = {
            "id": activity_id,
            "products": [{"id": pid} for pid in product_ids],
        }

    def search_activities(self, *, activity_type=None, page_size=50, **_: Any) -> dict[str, Any]:
        self.searches.append(activity_type)
        return {
            "activities": [
                a for a in self.activities if activity_type in (None, a["activity_type"])
            ]
        }

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        return copy.deepcopy(self.details[activity_id])

    def create_activity(self, **_: Any):
        self.writes.append("create_activity")

    def update_activity(self, **_: Any):
        self.writes.append("update_activity")

    def update_activity_products(self, **_: Any):
        self.writes.append("update_activity_products")

    def deactivate(self, **_: Any):
        self.writes.append("deactivate")


def resources(products: FakeProducts, promotion: FakePromotion | None = None) -> Any:
    return SimpleNamespace(products=products, promotion=promotion or FakePromotion())


async def seed_shop(session: AsyncSession, label: str = "a") -> tuple[Shop, Product]:
    user = User(id=uuid.uuid4(), phone=f"+8493{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(id=uuid.uuid4(), user_id=user.id, shop_name=f"{label} shop", is_active=True)
    product = Product(
        id=uuid.uuid4(),
        shop_id=shop.id,
        tiktok_product_id=PRODUCT_ID,
        name="Kem dưỡng ẩm ceramide 50ml",
        status="ACTIVATE",
        update_time=datetime(2026, 10, 1),
    )
    session.add_all([user, shop, product])
    await session.flush()
    return shop, product


def card_payload(
    *,
    lever: str = "description",
    kpi: str = "ctor",
    current: float = 0.054,
    reference: float = 0.059,
    gmv_per_day: float = 70000,
) -> str:
    return json.dumps(
        {
            "diagnosis": {
                "lever": {"code": lever, "label": lever},
                "main_kpi": {"key": kpi, "label": kpi.upper()},
                "recoverable_gmv_per_day": gmv_per_day,
                "recoverable_gmv_basis": {
                    "stage_rate": kpi,
                    "current_rate": current,
                    "reference_rate": reference,
                },
            }
        }
    )


async def seed_run(
    session: AsyncSession,
    shop: Shop,
    product: Product,
    *,
    lever: str | None = None,
    flow_kind: str | None = None,
    status: str = "queued",
    external_wait_reason: str | None = None,
    payload: str | None = None,
    waiting_since: datetime | None = None,
    subject_ref: str | None = None,
) -> WorkflowRunRow:
    card = ActionCard(
        id=uuid.uuid4(),
        shop_id=shop.id,
        workflow_key="optimize_product_2",
        subject_type="product",
        subject_id=str(product.id),
        priority=1,
        severity="medium",
        title="card",
        recommendation_payload=payload or card_payload(lever=lever or "description"),
        status="approved",
        revision=uuid.uuid4().int % 1_000_000 + 1,
    )
    session.add(card)
    await session.flush()
    run = WorkflowRunRow(
        id=uuid.uuid4(),
        shop_id=shop.id,
        product_id=product.id,
        action_card_id=card.id,
        # SQLite has the active-run index without its Postgres predicate, so a
        # second run on one product needs its own subject_ref there.
        subject_ref=subject_ref or str(product.id),
        state=RunState().to_dict(),
        status=status,
        external_wait_reason=external_wait_reason,
        waiting_external_since=waiting_since,
        prompt_version="optimize_product.v3",
        prompt_sha256="0" * 64,
    )
    session.add(run)
    await session.flush()
    if flow_kind is not None:
        session.add(
            RunLeverFlow(
                shop_id=shop.id,
                workflow_run_id=run.id,
                kind=flow_kind,
                lever=lever or ("cover_image" if flow_kind == "photo" else "product_discount"),
            )
        )
        await session.flush()
    return run


def api_client(engine, shop: Shop):
    """An httpx client on the real app with auth + shop resolved to ``shop``."""
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from juli_backend.api.app import create_app
    from juli_backend.api.dependencies import get_active_shop
    from juli_backend.core.security import get_current_user
    from juli_backend.database import get_session

    factory = async_sessionmaker(engine, expire_on_commit=False)
    application = create_app()

    async def _test_session():
        async with factory() as sess:
            yield sess

    application.dependency_overrides[get_session] = _test_session
    application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=shop.user_id)
    application.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


def shop_today() -> date:
    return date(2026, 10, 9)
