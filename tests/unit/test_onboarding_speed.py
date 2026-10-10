"""Onboarding speed (fast track P17): quick scan, upgrade to full cards, status, history.

ACCEPTANCE AC-17.1 – AC-17.4 (AC-17.5 / AC-17.6 -- 429 and cost pacing -- live in
``test_shop_diagnosis_video_windows.py`` and ``test_order_costs.py``). Contract
``fasttrack/contracts/p17-onboarding-speed.md``.

Every TikTok read goes to an in-memory fake; nothing reaches TikTok, Redis or a
broker. The full-diagnosis side reuses the P7-B catalog seeded by
``test_optimize_product_decision_cards`` (60 days of product analytics).
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.ingestion import (
    BOOTSTRAP_FAST_DONE,
    QUICK_SCAN_DONE,
    QUICK_SCAN_FAILED,
    QUICK_SCAN_RUNNING,
    QUICK_SCAN_SKIPPED,
    ShopIngestionState,
)
from juli_backend.models.models import ActionCard, Product, User
from juli_backend.repositories import ProductsRepo, ShopIngestionStateRepo, TikTokCredentialRepo
from juli_backend.services.action_cards.optimize_product_cards import (
    OPTIMIZE_PRODUCT_WORKFLOW_KEY,
    WITHDRAWN_STATUS,
)
from juli_backend.services.onboarding import quick_scan as qs
from juli_backend.services.onboarding.status import (
    build_onboarding_status,
    history_days_available,
)
from juli_backend.services.optimize_product.funnel import FunnelWindow, ShopMedians
from juli_backend.services.optimize_product.listing_signals import EvidenceSource
from tests.unit.test_optimize_product_decision_cards import (
    AOV,
    CATALOG,
    COMPUTED_AT,
    _client,
    _score,
    _seed_shop,
)

#: The quick scan runs a few minutes after connect, the same shop day as the
#: full diagnosis in these tests (2026-10-07 UTC+7).
SCAN_AT = COMPUTED_AT - timedelta(minutes=30)


@pytest.fixture(autouse=True)
def _quick_scan_env(monkeypatch):
    monkeypatch.delenv(qs.MAX_CARDS_ENV, raising=False)
    monkeypatch.delenv(qs.ENABLED_ENV, raising=False)
    # The P7-B catalog's top sellers are its healthy products; ask about them all.
    monkeypatch.setenv(qs.TOP_PRODUCTS_ENV, "30")


@pytest_asyncio.fixture
async def session_factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


# -- fakes ----------------------------------------------------------------------------


def _a34_row(product_id: str, impressions: int, clicks: int, orders: int) -> dict[str, Any]:
    return {
        "id": product_id,
        "total_performance": {
            "gmv": {"amount": str(orders * AOV), "currency": "VND"},
            "sku_orders": orders,
            "items_sold": orders,
            "product_impressions": impressions,
            "product_clicks": clicks,
        },
    }


def _catalog_rows(label: str, *, overrides: dict[str, tuple[Decimal, Decimal]] | None = None):
    """The P7-B catalog as 14-day A-34 rows (same daily volumes as the seeded analytics)."""
    rows = []
    for index, (suffix, ctr, ctor, _short) in enumerate(CATALOG):
        ctr, ctor = (overrides or {}).get(suffix, (ctr, ctor))
        impressions = Decimal(2000 + 100 * index)
        clicks = (impressions * ctr).quantize(Decimal("1"))
        orders = (clicks * ctor).quantize(Decimal("1"))
        rows.append(
            _a34_row(f"{label}-{suffix}", int(impressions * 14), int(clicks * 14), int(orders * 14))
        )
    return rows


def _diagnosis_entry(product_id: str, field: str, *codes: str) -> dict[str, Any]:
    return {
        "id": product_id,
        "diagnoses": [
            {
                "field": field,
                "diagnosis_results": [
                    {"code": code, "how_to_solve": f"Sửa {code.lower()}"} for code in codes
                ],
            }
        ],
    }


class FakeQuickResources:
    """A-34 pages, the diagnoses endpoint and Get Product; records every call."""

    def __init__(
        self,
        rows: list[dict],
        diagnoses: list[dict],
        *,
        details: dict[str, dict] | None = None,
        page_size: int = 100,
        fail_list: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, Any]] = []
        outer = self

        class Analytics:
            def list_product_performance(self, **kwargs):
                outer.calls.append(("a34", kwargs))
                if fail_list is not None:
                    raise fail_list
                token = int(kwargs.get("page_token") or 0)
                page = rows[token : token + page_size]
                more = token + page_size < len(rows)
                return {"products": page, "next_page_token": str(token + page_size) if more else ""}

        class Products:
            def get_diagnoses(self, product_ids):
                outer.calls.append(("diagnoses", list(product_ids)))
                return {"products": [d for d in diagnoses if d["id"] in product_ids]}

            def get_details(self, product_id):
                outer.calls.append(("details", product_id))
                return (details or {})[product_id]

        self.analytics = Analytics()
        self.products = Products()

    def of(self, kind: str) -> list[Any]:
        return [args for k, args in self.calls if k == kind]


async def _credential(session, shop) -> None:
    shop.tiktok_shop_id = shop.tiktok_shop_id or f"tt-{uuid.uuid4().hex[:8]}"
    await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token="access",
        refresh_token="refresh",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=f"merchant-{uuid.uuid4().hex[:6]}",
        capability=TikTokCapability.SELLER_CONNECT.value,
        shop_cipher="cipher",
    )
    await ShopIngestionStateRepo(session).stamp_once(
        shop.id, "connect_committed_at", SCAN_AT.replace(tzinfo=None) - timedelta(minutes=2)
    )
    await session.commit()


async def _scan(session_factory, shop, resources, **kwargs):
    return await qs.run_quick_scan(
        session_factory=session_factory,
        shop_id=shop.id,
        app_key="app",
        app_secret="secret",
        create_resources=lambda _cfg: resources,
        now=kwargs.pop("now", SCAN_AT),
        **kwargs,
    )


async def _cards(session, shop_id, *, status: str | None = "active") -> list[ActionCard]:
    stmt = select(ActionCard).where(
        ActionCard.shop_id == shop_id, ActionCard.workflow_key == OPTIMIZE_PRODUCT_WORKFLOW_KEY
    )
    if status is not None:
        stmt = stmt.where(ActionCard.status == status)
    stmt = stmt.execution_options(populate_existing=True)
    return list((await session.execute(stmt)).scalars())


def _diag(card: ActionCard) -> dict:
    return json.loads(card.recommendation_payload)["diagnosis"]


async def _product_id(session, shop_id, tiktok_id: str) -> str:
    row = (
        await session.execute(
            select(Product).where(
                Product.shop_id == shop_id, Product.tiktok_product_id == tiktok_id
            )
        )
    ).scalar_one()
    return str(row.id)


#: Three quick candidates on the P7-B catalog: a weak-CTR product with an image
#: code, a weak-CTOR product with a description code, and a product that is
#: weak only in the last 14 days (healthy over the 60 days the full run reads).
def _three_candidates(label: str):
    rows = _catalog_rows(label, overrides={"healthy05": (Decimal("0.02"), Decimal("0.05"))})
    diagnoses = [
        _diagnosis_entry(f"{label}-weakctr00", "MAIN_IMAGE", "MAIN_IMG_NUMBER_LESS_THAN_FIVE"),
        _diagnosis_entry(f"{label}-weakctor01", "DESCRIPTION", "DESC_LESS_THAN_FIVE_HUNDRED_CHARS"),
        _diagnosis_entry(f"{label}-healthy05", "TITLE", "TITLE_LESS_THAN_40_CHARACTERS"),
    ]
    return rows, diagnoses


# -- AC-17.1: quick-scan selection (pure) ---------------------------------------------------


def test_the_scan_window_is_the_last_fourteen_full_local_days():
    start, end_lt = qs.scan_window(datetime(2026, 10, 7, 20, 0, tzinfo=UTC))  # 03:00 on the 8th
    assert (start, end_lt) == (date(2026, 9, 24), date(2026, 10, 8))
    assert (end_lt - start).days == qs.WINDOW_DAYS == 14


def test_only_cover_title_description_backed_by_a_tiktok_code_become_quick_cards():
    rows, diagnoses = _three_candidates("Q")
    # A fourth weak product whose only TikTok code is unrelated: no lever, no card.
    diagnoses.append(_diagnosis_entry("Q-weakctr01", "OTHER", "SOMETHING_ELSE"))
    funnels = qs.funnels_from_a34(rows)
    asked = qs.top_by_gmv(funnels, 30)
    evidence = qs.evidence_from_diagnoses({"products": diagnoses})

    selection = qs.select_quick_proposals(funnels, evidence, asked)

    levers = {p.product_id: p.lever.value for p in selection.proposals}
    assert levers == {
        "Q-weakctr00": "ảnh bìa",
        "Q-weakctor01": "mô tả",
        "Q-healthy05": "tiêu đề",
    }
    for proposal in selection.proposals:
        assert proposal.recoverable_gmv_per_day and proposal.recoverable_gmv_per_day > 0
        assert proposal.recoverable_basis["window_days"] == 14  # D22 on the 14 days
        assert all(e.source is EvidenceSource.TIKTOK for e in proposal.evidence)
        assert proposal.lever_confirmed
    values = [p.recoverable_gmv_per_day for p in selection.proposals]
    assert values == sorted(values, reverse=True)


def test_a_product_not_asked_or_without_a_code_gets_no_quick_card():
    rows, diagnoses = _three_candidates("N")
    funnels = qs.funnels_from_a34(rows)
    evidence = qs.evidence_from_diagnoses({"products": diagnoses})
    # Only the healthy top sellers were asked: none is weak.
    top_two = qs.top_by_gmv(funnels, 2)
    assert all("healthy" in pid for pid in top_two)
    assert qs.select_quick_proposals(funnels, evidence, top_two).proposals == []
    # Asked, weak, but TikTok flagged nothing.
    assert qs.select_quick_proposals(funnels, {}, ["N-weakctr00"]).proposals == []


def test_the_d22_estimate_on_fourteen_days_prices_extra_clicks_through_ctor():
    rows, diagnoses = _three_candidates("D")
    funnels = qs.funnels_from_a34(rows)
    by_id = {f.product_id: f for f in funnels}
    selection = qs.select_quick_proposals(
        funnels, qs.evidence_from_diagnoses({"products": diagnoses}), list(by_id)
    )
    cover = next(p for p in selection.proposals if p.product_id == "D-weakctr00")
    window: FunnelWindow = by_id["D-weakctr00"].current
    medians: ShopMedians = selection.medians
    expected = (
        (medians.ctr - window.ctr) * window.per_day(window.impressions) * window.ctor * window.aov
    )
    assert cover.recoverable_gmv_per_day == pytest.approx(expected)
    assert cover.recoverable_basis["stage_rate"] == "ctr"


def test_max_cards_is_one_to_three(monkeypatch):
    assert qs.max_cards() == 3
    monkeypatch.setenv(qs.MAX_CARDS_ENV, "9")
    assert qs.max_cards() == 3
    monkeypatch.setenv(qs.MAX_CARDS_ENV, "0")
    assert qs.max_cards() == 1


# -- AC-17.1 / 17.2: the scan writes and surfaces quick cards; the full diagnosis upgrades ------


@pytest.mark.asyncio
async def test_quick_cards_take_the_day_one_juli_slots_and_the_full_run_upgrades_them(
    session, session_factory
):
    shop = await _seed_shop(session, "U")
    await _credential(session, shop)
    rows, diagnoses = _three_candidates("U")
    resources = FakeQuickResources(rows, diagnoses)

    result = await _scan(session_factory, shop, resources)

    assert result.status == QUICK_SCAN_DONE and result.cards == 3 and result.surfaced == 3
    # Budget: 1 A-34 page (25 products) + 1 diagnoses call; no Get Product (catalog known).
    assert [k for k, _ in resources.calls] == ["a34", "diagnoses"]
    a34 = resources.of("a34")[0]
    assert (a34["start_date_ge"], a34["end_date_lt"]) == ("2026-09-23", "2026-10-07")
    assert result.seconds_since_connect is not None and result.seconds_since_connect >= 0

    quick = await _cards(session, shop.id)
    assert len(quick) == 3
    by_product = {_diag(c)["tiktok_product_id"]: c for c in quick}
    for card in quick:
        diagnosis = _diag(card)
        assert card.surfaced_at is not None
        assert diagnosis["quick_scan"]["label"] == "Đề xuất nhanh · dựa trên 14 ngày"
        assert diagnosis["quick_scan"]["confidence"] == "Tham khảo"
        assert diagnosis["recoverable_gmv_basis"]["window_days"] == 14
        payload = json.loads(card.recommendation_payload)
        assert payload["expected_impact"]["confidence"] == "reference"
    state = await ShopIngestionStateRepo(session).find(shop.id)
    await session.refresh(state)
    assert state.quick_scan_status == QUICK_SCAN_DONE and state.quick_scan_cards == 3
    assert state.quick_scan_started_at is not None and state.quick_scan_done_at is not None

    surfaced_at = {pid: c.surfaced_at for pid, c in by_product.items()}
    ids = {pid: c.id for pid, c in by_product.items()}

    # The full diagnosis (end of the fast phase) on the seeded 60 days.
    await ShopIngestionStateRepo(session).stamp_once(shop.id, "fast_done_at")
    await session.commit()
    await _score(session, shop)

    cover = await session.get(ActionCard, ids["U-weakctr00"], populate_existing=True)
    desc = await session.get(ActionCard, ids["U-weakctor01"], populate_existing=True)
    title = await session.get(ActionCard, ids["U-healthy05"], populate_existing=True)
    # Same product + same lever: the same row, re-scored, still surfaced.
    for card, lever in ((cover, "cover_image"), (desc, "description")):
        diagnosis = _diag(card)
        assert (
            card.status == "active"
            and card.surfaced_at == surfaced_at[diagnosis["tiktok_product_id"]]
        )
        assert "quick_scan" not in diagnosis
        assert diagnosis["lever"]["code"] == lever
        assert diagnosis["lever"]["confirmed"] is True
        assert any(e["source"] == "tiktok" for e in diagnosis["lever"]["evidence"])
        assert diagnosis["recoverable_gmv_basis"]["window_days"] == 30
    # Healthy over 60 days: the full run does not confirm it -> withdrawn at once.
    assert title.status == WITHDRAWN_STATUS and title.surfaced_at is None
    # The 3 Juli slots of the day were taken by the quick cards: nothing new today.
    surfaced = [c for c in await _cards(session, shop.id) if c.surfaced_at is not None]
    assert {c.id for c in surfaced} == {cover.id, desc.id}


@pytest.mark.asyncio
async def test_full_cards_fill_the_slots_the_quick_cards_left(
    session, session_factory, monkeypatch
):
    monkeypatch.setenv(qs.MAX_CARDS_ENV, "1")
    shop = await _seed_shop(session, "F")
    await _credential(session, shop)
    rows, diagnoses = _three_candidates("F")
    result = await _scan(session_factory, shop, FakeQuickResources(rows, diagnoses))
    assert result.cards == 1 and result.surfaced == 1
    (quick,) = await _cards(session, shop.id)

    await ShopIngestionStateRepo(session).stamp_once(shop.id, "fast_done_at")
    await session.commit()
    await _score(session, shop)

    surfaced = [c for c in await _cards(session, shop.id) if c.surfaced_at is not None]
    assert quick.id in {c.id for c in surfaced}
    # D24.21: 3 Juli slots on day 1 -- 1 quick + 2 full (no Seller Center / content candidate).
    assert len(surfaced) == 3
    assert sum(1 for c in surfaced if "quick_scan" in _diag(c)) == 0


@pytest.mark.asyncio
async def test_a_quick_card_whose_product_gets_another_lever_is_superseded(
    session, session_factory
):
    shop = await _seed_shop(session, "L")
    await _credential(session, shop)
    rows = _catalog_rows("L")
    # The short-titled weak-CTR product: TikTok flags its description only. The
    # quick scan proposes the description; the full run (CTR branch, local
    # title code) proposes the title.
    diagnoses = [_diagnosis_entry("L-weakctr00", "TITLE", "TITLE_LESS_THAN_40_CHARACTERS")]
    await _scan(session_factory, shop, FakeQuickResources(rows, diagnoses))
    (quick,) = await _cards(session, shop.id)
    assert _diag(quick)["lever"]["code"] == "title"

    # Make the quick card's lever differ from what the full run will propose.
    payload = json.loads(quick.recommendation_payload)
    payload["diagnosis"]["lever"]["code"] = "cover_image"
    quick.recommendation_payload = json.dumps(payload)
    await ShopIngestionStateRepo(session).stamp_once(shop.id, "fast_done_at")
    await session.commit()

    await _score(session, shop)
    old = await session.get(ActionCard, quick.id, populate_existing=True)
    assert old.status == WITHDRAWN_STATUS
    successor = (
        await session.execute(
            select(ActionCard)
            .where(ActionCard.supersedes_card_id == quick.id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert _diag(successor)["lever"]["code"] == "title"
    assert successor.revision == quick.revision + 1


@pytest.mark.asyncio
async def test_a_product_missing_from_the_catalog_gets_a_placeholder_row(session, session_factory):
    user = User(phone=f"+1666{uuid.uuid4().int % 10_000_000:07d}")
    session.add(user)
    await session.flush()
    from juli_backend.models.models import Shop

    shop = Shop(user_id=user.id, shop_name="new shop", tiktok_shop_id="tt-new-p17")
    session.add(shop)
    await session.commit()
    await _credential(session, shop)
    rows = [_a34_row(f"P-ok{i}", 30_000, 1500, 75) for i in range(5)]
    rows.append(_a34_row("P-weak", 30_000, 600, 30))
    details = {
        "P-weak": {
            "id": "P-weak",
            "title": "Áo thun cotton nam",
            "status": "ACTIVATE",
            "create_time": 1_700_000_000,
        }
    }
    diagnoses = [_diagnosis_entry("P-weak", "MAIN_IMAGE", "MAIN_IMG_NUMBER_LESS_THAN_FIVE")]
    resources = FakeQuickResources(rows, diagnoses, details=details)

    result = await _scan(session_factory, shop, resources)

    assert result.cards == 1 and resources.of("details") == ["P-weak"]
    product = (
        await session.execute(
            select(Product)
            .where(Product.tiktok_product_id == "P-weak")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert product.title == "Áo thun cotton nam" and product.status == "ACTIVATE"
    assert product.update_time == qs.PLACEHOLDER_UPDATE_TIME
    (card,) = await _cards(session, shop.id)
    assert card.subject_id == str(product.id)
    assert _diag(card)["product_title"] == "Áo thun cotton nam"

    # The first real product sync overwrites the placeholder.
    await ProductsRepo(session).upsert(
        shop_id=shop.id,
        tiktok_product_id="P-weak",
        title="Áo thun cotton nam",
        name="Áo thun cotton nam",
        status="ACTIVATE",
        category="Thời trang",
        update_time=datetime(2026, 10, 7, 1, 0),
    )
    await session.commit()
    product = await session.get(Product, product.id, populate_existing=True)
    assert product.category == "Thời trang"


@pytest.mark.asyncio
async def test_the_scan_runs_once_and_skips_when_full_cards_exist(session, session_factory):
    shop = await _seed_shop(session, "S")
    await _credential(session, shop)
    rows, diagnoses = _three_candidates("S")
    resources = FakeQuickResources(rows, diagnoses)
    await _scan(session_factory, shop, resources)
    again = await _scan(session_factory, shop, resources)
    assert again.skipped_reason == "already_ran" and len(resources.of("a34")) == 1

    shop2 = await _seed_shop(session, "S2")
    await _credential(session, shop2)
    await ShopIngestionStateRepo(session).stamp_once(shop2.id, "first_card_at")
    await session.commit()
    fresh = FakeQuickResources(*_three_candidates("S2"))
    skipped = await _scan(session_factory, shop2, fresh)
    assert skipped.status == QUICK_SCAN_SKIPPED and skipped.skipped_reason == "full_cards_exist"
    assert fresh.calls == []  # no TikTok call


@pytest.mark.asyncio
async def test_a_failing_read_records_failed_and_never_raises(session, session_factory):
    shop = await _seed_shop(session, "X")
    await _credential(session, shop)
    resources = FakeQuickResources([], [], fail_list=RuntimeError("boom"))
    result = await _scan(session_factory, shop, resources)
    assert result.status == QUICK_SCAN_FAILED
    state = await ShopIngestionStateRepo(session).find(shop.id)
    await session.refresh(state)
    assert state.quick_scan_status == QUICK_SCAN_FAILED
    assert await _cards(session, shop.id) == []


@pytest.mark.asyncio
async def test_the_decisions_endpoint_labels_a_quick_card(app, session, session_factory):
    shop = await _seed_shop(session, "E")
    await _credential(session, shop)
    await _scan(session_factory, shop, FakeQuickResources(*_three_candidates("E")))
    user = await session.get(User, shop.user_id)
    async with _client(app, user, shop) as client:
        resp = await client.get("/v1/demo/decisions")
    assert resp.status_code == 200, resp.text
    items = [i for i in resp.json()["data"] if i["recommendation"].get("card")]
    assert len(items) == 3
    for item in items:
        card = item["recommendation"]["card"]
        assert card["quick_scan"]["label"] == "Đề xuất nhanh · dựa trên 14 ngày"
        assert card["quick_scan"]["confidence"] == "Tham khảo"
        assert "14 ngày" in (card["gmv_method"] or "")
        assert item["recommendation"]["diagnosis"]["quick_scan"]["window_days"] == 14


@pytest_asyncio.fixture
async def app(session):
    from juli_backend.api.app import create_app
    from juli_backend.database import get_session

    application = create_app()

    async def _test_session():
        yield session

    application.dependency_overrides[get_session] = _test_session
    yield application
    application.dependency_overrides.clear()


# -- AC-17.3: onboarding status ----------------------------------------------------------------

NOW = datetime(2026, 10, 10, 9, 0)


def _state(**values: Any) -> ShopIngestionState:
    base = {
        "shop_id": uuid.uuid4(),
        "status": "fast_running",
        "history_chunks_done": 0,
        "history_empty_chunks": 0,
    }
    return ShopIngestionState(**{**base, **values})


def _status(state, *, report=False):
    return build_onboarding_status(
        state, shop_id=uuid.uuid4(), report_exists=report, now=NOW.replace(tzinfo=UTC)
    )


def test_status_while_the_quick_scan_and_the_fast_phase_run():
    state = _state(
        quick_scan_status=QUICK_SCAN_RUNNING,
        quick_scan_started_at=NOW - timedelta(minutes=1),
        fast_started_at=NOW - timedelta(minutes=1),
    )
    body = _status(state)
    assert body["active"] and body["current_step"] == 1
    assert body["label"] == "Juli đang đọc dữ liệu shop · bước 1/3"
    assert body["poll_interval_seconds"] == 15
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["quick_scan"]["status"] == "running"
    assert steps["backfill_diagnosis"]["status"] == "running"
    assert steps["backfill_diagnosis"]["eta_seconds"] == 900 - 60
    assert steps["history"]["status"] == "pending"
    assert body["history_days_available"] == 0 and body["history_target_days"] == 180


def test_status_after_the_quick_scan_with_thirty_days_in():
    state = _state(
        quick_scan_status=QUICK_SCAN_DONE,
        quick_scan_cards=2,
        fast_started_at=NOW - timedelta(minutes=12),
        fast_done_at=NOW - timedelta(minutes=2),
        history_earliest_date=date(2026, 9, 10),
        analytics_through_date=date(2026, 10, 9),
    )
    body = _status(state)
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["quick_scan"] == {
        **steps["quick_scan"],
        "status": "done",
        "detail": "2 đề xuất nhanh",
    }
    assert body["current_step"] == 2 and body["label"].endswith("bước 2/3")
    assert body["history_days_available"] == 30
    assert steps["backfill_diagnosis"]["percent"] == 35  # 70 % × 30/60, no report yet
    assert steps["backfill_diagnosis"]["detail"] == "30/60 ngày"


def test_status_with_only_history_left_slows_the_poll():
    state = _state(
        status=BOOTSTRAP_FAST_DONE,
        quick_scan_status=QUICK_SCAN_DONE,
        fast_started_at=NOW - timedelta(hours=1),
        fast_done_at=NOW - timedelta(minutes=50),
        history_earliest_date=date(2026, 8, 11),
        analytics_through_date=date(2026, 10, 9),
    )
    body = _status(state, report=True)
    assert body["history_days_available"] == 60
    assert not body["active"] and body["current_step"] == 3
    assert body["label"] == "Đang tải lịch sử · còn 120 ngày"
    assert body["poll_interval_seconds"] == 300
    assert body["history_days_remaining"] == 120 and not body["window_90d_available"]
    steps = {s["key"]: s for s in body["steps"]}
    assert steps["backfill_diagnosis"]["status"] == "done"
    assert steps["history"]["status"] == "running" and steps["history"]["percent"] == 33


def test_status_done_and_the_ninety_day_window_unlocks_at_180_days():
    state = _state(
        status="history_done",
        quick_scan_status=QUICK_SCAN_DONE,
        fast_started_at=NOW - timedelta(days=5),
        fast_done_at=NOW - timedelta(days=5),
        history_earliest_date=date(2026, 4, 13),
        analytics_through_date=date(2026, 10, 9),
    )
    body = _status(state, report=True)
    assert body["history_days_available"] == 180 and body["window_90d_available"]
    assert body["history_complete"] and body["current_step"] is None
    assert body["label"] is None and body["poll_interval_seconds"] is None


def test_a_walk_that_ended_early_sets_the_target_to_what_tiktok_had():
    state = _state(
        status="history_done",
        quick_scan_status=QUICK_SCAN_DONE,
        fast_started_at=NOW - timedelta(days=2),
        fast_done_at=NOW - timedelta(days=2),
        history_done_at=NOW - timedelta(days=1),
        history_earliest_date=date(2026, 7, 2),
        analytics_through_date=date(2026, 10, 9),
    )
    body = _status(state, report=True)
    assert body["history_days_available"] == 100
    assert body["history_complete"] and body["history_target_days"] == 100
    assert body["history_days_remaining"] == 0 and not body["window_90d_available"]


def test_a_stale_quick_scan_and_a_pre_p17_shop_do_not_hold_the_strip():
    stale = _state(
        quick_scan_status=QUICK_SCAN_RUNNING,
        quick_scan_started_at=NOW - timedelta(hours=1),
    )
    assert {s["key"]: s for s in _status(stale)["steps"]}["quick_scan"]["status"] == "failed"
    legacy = _state(
        status=BOOTSTRAP_FAST_DONE,
        fast_started_at=NOW - timedelta(days=30),
        fast_done_at=NOW - timedelta(days=30),
        history_earliest_date=date(2025, 10, 10),
        analytics_through_date=date(2026, 10, 9),
    )
    body = _status(legacy, report=True)
    assert {s["key"]: s for s in body["steps"]}["quick_scan"]["status"] == "skipped"
    assert not body["active"]
    assert _status(None)["active"] and _status(None)["current_step"] == 1


def test_history_days_available_is_contiguous_days_stored():
    assert history_days_available(None) == 0
    assert history_days_available(_state(history_earliest_date=date(2026, 9, 1))) == 0
    state = _state(
        fast_done_at=NOW,
        history_earliest_date=date(2026, 9, 1),
        latest_available_date=date(2026, 9, 30),
    )
    assert history_days_available(state) == 30


@pytest.mark.asyncio
async def test_the_onboarding_endpoint_reads_the_shops_state(app, session):
    shop = await _seed_shop(session, "O")
    await ShopIngestionStateRepo(session).update(
        shop.id,
        quick_scan_status=QUICK_SCAN_DONE,
        quick_scan_cards=1,
        fast_started_at=datetime(2026, 10, 7, 8, 0),
        history_earliest_date=date(2026, 9, 8),
    )
    await session.commit()
    user = await session.get(User, shop.user_id)
    async with _client(app, user, shop) as client:
        resp = await client.get("/v1/shops/me/onboarding")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["shop_id"] == str(shop.id) and body["total_steps"] == 3
    assert [s["key"] for s in body["steps"]] == ["quick_scan", "backfill_diagnosis", "history"]
    assert body["active"] and body["current_step"] == 2
    assert set(body) >= {
        "history_days_available",
        "history_target_days",
        "history_days_remaining",
        "history_complete",
        "window_90d_available",
        "poll_interval_seconds",
    }


@pytest.mark.asyncio
async def test_the_onboarding_endpoint_needs_a_signed_in_shop(app):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/v1/shops/me/onboarding")
    assert resp.status_code in (401, 403, 422)


# -- AC-17.1: the bootstrap task enqueues the quick scan beside the fast phase -----------------


class _NullSession:
    async def commit(self):
        return None


@pytest.mark.asyncio
async def test_bootstrap_enqueues_the_quick_scan_once_before_the_fast_phase():
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_bootstrap_task

    lock = InMemoryShopIngestLock()
    shop_id = str(uuid.uuid4())
    order: list[str] = []

    @asynccontextmanager
    async def factory():
        yield _NullSession()

    async def collaborators(_session):
        return {}

    async def fast_fn(**_kwargs):
        order.append("fast")
        return SimpleNamespace(skipped=False, reason=None)

    enqueuers = Enqueuers(
        bootstrap=lambda *a, **k: "b",
        history=lambda *a, **k: "h",
        poll=lambda shop_id: "p",
        diagnosis=lambda shop_id: "d",
        quick_scan=lambda sid: order.append(f"quick:{sid}") or "q",
    )
    for _ in range(2):
        await run_bootstrap_task(
            shop_id,
            session_factory=factory,
            lock=lock,
            collaborators=collaborators,
            enqueuers=enqueuers,
            fast_fn=fast_fn,
        )
    assert order == [f"quick:{shop_id}", "fast", "fast"]  # de-duplicated by its marker


def test_the_quick_scan_routes_to_the_priority_queue_and_history_extends_nightly():
    from celery.schedules import crontab

    from juli_backend.workers.celery_app import celery_app

    assert celery_app.conf.task_routes["juli_backend.shop_quick_scan"] == {
        "queue": "ingest_priority"
    }
    entry = celery_app.conf.beat_schedule["shop-history-extend"]
    assert entry["task"] == "juli_backend.shop_history_extend"
    assert entry["schedule"] == crontab(hour=19, minute=43)


@pytest.mark.asyncio
async def test_the_quick_scan_task_takes_its_own_lock_not_the_cycle_lock():
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_quick_scan import run_quick_scan_task

    lock = InMemoryShopIngestLock()
    shop_id = str(uuid.uuid4())
    lock.try_acquire(shop_id, "cycle", ttl_seconds=60)  # the fast phase holds it
    seen: list[bool] = []

    async def fake_scan(**kwargs):
        seen.append(lock.is_held(shop_id, "quick_scan"))
        return "ran"

    import juli_backend.services.onboarding as module

    original = module.run_quick_scan
    module.run_quick_scan = fake_scan
    try:
        result = await run_quick_scan_task(
            shop_id, session_factory=None, app_key="a", app_secret="s", lock=lock
        )
        token = lock.try_acquire(shop_id, "quick_scan", ttl_seconds=60)
        skipped = await run_quick_scan_task(
            shop_id, session_factory=None, app_key="a", app_secret="s", lock=lock
        )
    finally:
        module.run_quick_scan = original
    assert result == "ran" and seen == [True] and token is not None and skipped is None


# -- AC-17.4: history to 180 days, nightly, resumable, capped ----------------------------------


async def _hist(session, shop, analytics, **kwargs):
    from juli_backend.workers.services.polling.ingestion import run_history_chunks
    from tests.support.shop_ingestion_fakes import FakeRateLimiter, make_resources
    from tests.unit.test_shop_ingestion import CONFIG, Handoffs, _no_sleep
    from tests.unit.test_shop_ingestion import NOW as INGEST_NOW

    return await run_history_chunks(
        session=session,
        config=CONFIG,
        shop_id=shop.id,
        rate_limiter=FakeRateLimiter(),
        handoff_fn=Handoffs(session),
        create_resources=lambda _cfg: make_resources(analytics),
        sleep=_no_sleep,
        now=kwargs.pop("now", INGEST_NOW),
        **kwargs,
    )


def _detail_calls(analytics) -> int:
    return len(analytics.calls.get("get_product_performance", []))


def test_the_look_back_defaults_to_180_days(monkeypatch):
    from juli_backend.services.onboarding import history
    from juli_backend.workers.services.polling.ingestion import history_max_lookback_days

    monkeypatch.delenv(history.MAX_LOOKBACK_DAYS_ENV, raising=False)
    assert history_max_lookback_days() == 180 == history.history_target_days()
    assert (history.connect_days(), history.nightly_chunks(), history.nightly_chunk_days()) == (
        60,
        2,
        15,
    )
    monkeypatch.setenv(history.MAX_LOOKBACK_DAYS_ENV, "120")
    assert history.history_target_days() == 120


@pytest.mark.asyncio
async def test_after_connect_the_chain_stops_at_sixty_days_then_extends_nightly(session):
    from tests.support.shop_ingestion_fakes import FakeAnalyticsResource
    from tests.unit.test_shop_ingestion import LATEST, _count_score, _fast, _make_shop

    shop = await _make_shop(session, label="p17h")
    analytics = FakeAnalyticsResource(prefix="p17h", earliest_data=LATEST - timedelta(days=400))
    await _fast(session, shop, analytics, score_fn=_count_score)
    state = await ShopIngestionStateRepo(session).find(shop.id)
    assert history_days_available(state) == 30

    first = await _hist(session, shop, analytics, chunk_days=30, stop_at_days=60, max_chunks=12)
    assert first.reason == "connect_window_done" and not first.done
    assert len(first.chunks) == 1
    state = await ShopIngestionStateRepo(session).find(shop.id)
    assert history_days_available(state) == 60

    calls = _detail_calls(analytics)
    again = await _hist(session, shop, analytics, chunk_days=30, stop_at_days=60)
    assert again.reason == "connect_window_done" and _detail_calls(analytics) == calls

    # Night 1: two 15-day chunks; the same night again is a no-op.
    night = date(2026, 7, 17)
    n1 = await _hist(session, shop, analytics, chunk_days=15, max_chunks=2, once_on=night)
    assert len(n1.chunks) == 2 and n1.reason == "chunk_budget"
    assert history_days_available(await ShopIngestionStateRepo(session).find(shop.id)) == 90
    calls = _detail_calls(analytics)
    same = await _hist(session, shop, analytics, chunk_days=15, max_chunks=2, once_on=night)
    assert same.reason == "already_extended" and _detail_calls(analytics) == calls

    # Nights 2-4 reach the 180-day look-back and end the walk there.
    for offset in (1, 2, 3):
        result = await _hist(
            session,
            shop,
            analytics,
            chunk_days=15,
            max_chunks=2,
            once_on=night + timedelta(days=offset),
        )
    assert result.done and result.reason == "max_lookback"
    state = await ShopIngestionStateRepo(session).find(shop.id)
    await session.refresh(state)
    assert state.history_done_at is not None
    assert history_days_available(state) >= 179  # floor = today − 180


@pytest.mark.asyncio
async def test_the_history_task_parks_at_sixty_days_and_nightly_never_re_enqueues():
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_history_task

    lock = InMemoryShopIngestLock()
    shop_id = str(uuid.uuid4())
    enqueued: list[dict] = []
    seen: list[dict] = []

    @asynccontextmanager
    async def factory():
        yield _NullSession()

    async def collaborators(_session):
        return {}

    def history_fn_for(reason: str):
        async def history_fn(**kwargs):
            seen.append(kwargs)
            return SimpleNamespace(done=False, reason=reason)

        return history_fn

    enqueuers = Enqueuers(history=lambda sid, **k: enqueued.append(k) or "h")
    await run_history_task(
        shop_id,
        session_factory=factory,
        lock=lock,
        collaborators=collaborators,
        enqueuers=enqueuers,
        history_fn=history_fn_for("connect_window_done"),
    )
    assert seen[-1]["stop_at_days"] == 60 and enqueued == []

    await run_history_task(
        shop_id,
        session_factory=factory,
        lock=lock,
        collaborators=collaborators,
        enqueuers=enqueuers,
        history_fn=history_fn_for("chunk_budget"),
        nightly=True,
        now=datetime(2026, 10, 9, 19, 43, tzinfo=UTC),
    )
    assert seen[-1]["once_on"] == date(2026, 10, 10)  # 02:43 UTC+7
    assert (seen[-1]["chunk_days"], seen[-1]["max_chunks"]) == (15, 2)
    assert "stop_at_days" not in seen[-1]
    assert enqueued == []

    # Before the 60 days: the chain continues.
    await run_history_task(
        shop_id,
        session_factory=factory,
        lock=lock,
        collaborators=collaborators,
        enqueuers=enqueuers,
        history_fn=history_fn_for("chunk_budget"),
    )
    assert len(enqueued) == 1


@pytest.mark.asyncio
async def test_the_poll_keeps_only_the_post_connect_chain_alive():
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_poll_shop_task

    histories: list[str] = []

    @asynccontextmanager
    async def factory():
        yield _NullSession()

    async def collaborators(_session):
        return {}

    def cycle_with(pending: bool):
        async def cycle_fn(**_kwargs):
            return SimpleNamespace(
                needs_bootstrap=False,
                history_done=False,
                history_connect_pending=pending,
                analytics_ran=False,
            )

        return cycle_fn

    for pending in (False, True):
        await run_poll_shop_task(
            str(uuid.uuid4()),
            session_factory=factory,
            lock=InMemoryShopIngestLock(),
            collaborators=collaborators,
            enqueuers=Enqueuers(history=lambda sid, **k: histories.append(sid) or "h"),
            cycle_fn=cycle_with(pending),
        )
    assert len(histories) == 1


@pytest.mark.asyncio
async def test_the_nightly_fanout_enqueues_one_run_per_shop_past_its_fast_phase():
    from juli_backend.workers.services.polling.ingestion import PollableShop
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import Enqueuers, run_history_extend_fanout

    done, fresh, busy = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    lock = InMemoryShopIngestLock()
    lock.try_acquire(str(busy), "history", ttl_seconds=60)
    calls: list[tuple[str, dict]] = []

    async def enumerate_fn(_session):
        return [
            PollableShop(shop_id=done, fast_done=True),
            PollableShop(shop_id=fresh, fast_done=False),
            PollableShop(shop_id=busy, fast_done=True),
        ]

    enqueuers = Enqueuers(history=lambda sid, **k: calls.append((sid, k)) or "h")
    count = await run_history_extend_fanout(
        _NullSession(), lock=lock, enqueuers=enqueuers, enumerate_fn=enumerate_fn
    )
    assert count == 1 and calls[0][0] == str(done) and calls[0][1]["nightly"] is True
    # Queued already (marker): the next tick that night does not stack another.
    again = await run_history_extend_fanout(
        _NullSession(), lock=lock, enqueuers=enqueuers, enumerate_fn=enumerate_fn
    )
    assert again == 0
