"""Metric rankings in the daily job and on the read route (fast track P8-A, AC-8.1).

The daily job builds the ADR-109 d.5 rankings from the same fetched snapshot
as the ADR-108 report (no extra TikTok call) and stores one row per stream ×
metric; ``GET /v1/demo/analysis/rankings`` serves the caller's own shop only.
SQLite here; the Postgres RLS proof is
``tests/integration/test_shop_metric_rankings_two_tenant.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.models import Shop, User
from juli_backend.models.shop_diagnosis import (
    RANKING_METRICS,
    RANKING_STREAMS,
    ShopDiagnosisReport,
    ShopMetricRanking,
)
from juli_backend.repositories import ShopMetricRankingsRepo, TikTokCredentialRepo
from juli_backend.services.shop_diagnosis.channels import Counts
from juli_backend.services.shop_diagnosis.rankings import (
    STREAM_METRICS,
    Metric,
    VideoWindowMetrics,
    reconciles,
)
from juli_backend.services.shop_diagnosis_daily import build_and_store_shop_diagnosis
from tests.support.shop_diagnosis import END, FakeTikTokReadResources

NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)
#: Thẻ sản phẩm 6 + Tab Cửa hàng 4 + LIVE 3 (no video input).
WITHOUT_VIDEOS = 13


@pytest.fixture(autouse=True)
def _no_lazy_refresh(monkeypatch):
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)


async def _make_shop(session, *, label: str) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8492{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name=f"{label} shop",
        tiktok_shop_id=f"tt-{label}-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    session.add_all([user, shop])
    await session.flush()
    await TikTokCredentialRepo(session).create(
        shop_id=shop.id,
        access_token=f"access-{label}",
        refresh_token=f"refresh-{label}",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=f"merchant-{label}",
        capability=TikTokCapability.SELLER_CONNECT.value,
        shop_cipher=f"cipher-{label}",
    )
    await session.commit()
    return shop


async def _build(engine, shop_id, tmp_path: Path, **kwargs):
    resources = FakeTikTokReadResources()
    result = await build_and_store_shop_diagnosis(
        session_factory=async_sessionmaker(engine, expire_on_commit=False),
        shop_id=shop_id,
        app_key="app-key",
        app_secret="app-secret",
        create_resources=lambda _config: resources,
        now=NOW,
        tmp_root=tmp_path,
        sleep_s=0,
        backoff_sleep=lambda _s: None,
        **kwargs,
    )
    return result, resources


async def _stored(session, model, shop_id) -> list:
    stmt = select(model).where(model.shop_id == shop_id)
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# The daily job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_job_stores_every_stream_metric_ranking_from_the_same_fetch(
    engine, session, tmp_path
):
    shop = await _make_shop(session, label="rk")
    result, resources = await _build(engine, shop.id, tmp_path)

    assert result.built and len(result.metric_rankings) == WITHOUT_VIDEOS
    rows = await _stored(session, ShopMetricRanking, shop.id)
    assert {(r.stream, r.metric) for r in rows} == {
        (s.value, m.value)
        for s, ms in STREAM_METRICS.items()
        if s.value != "seller_video"
        for m in ms
    }
    for row in rows:
        assert row.end_date == END
        assert reconciles(row.ranking), (row.stream, row.metric)
    # One fetch: the A-34 list once per day of the 60, LIVE and videos listed once.
    assert sum(1 for c in resources.calls if c[0] == "a34") == 60
    assert sum(1 for c in resources.calls if c[0] == "live") == 1
    assert not list(tmp_path.iterdir())  # the snapshot folder is gone


@pytest.mark.asyncio
async def test_video_rankings_are_built_when_window_metrics_are_supplied(engine, session, tmp_path):
    shop = await _make_shop(session, label="rk-video")
    seen: list = []

    def video_metrics(folder: Path, snapshot):
        seen.append((folder.exists(), snapshot.end))
        return [
            VideoWindowMetrics("v1", "Mở hộp", END, Counts(5_000, 200, None, 10, 1_000_000)),
        ]

    result, _ = await _build(engine, shop.id, tmp_path, video_metrics=video_metrics)

    assert seen == [(True, END)]  # read inside the temporary snapshot, before deletion
    assert len(result.metric_rankings) == WITHOUT_VIDEOS + 2
    rows = await _stored(session, ShopMetricRanking, shop.id)
    video = {r.metric: r.ranking for r in rows if r.stream == "seller_video"}
    assert set(video) == {"impressions", "ctr"}
    assert video["ctr"]["row_kind"] == "video"


@pytest.mark.asyncio
async def test_a_ranking_failure_never_blocks_the_report(engine, session, tmp_path):
    shop = await _make_shop(session, label="rk-fail")

    def broken(_folder, _snapshot):
        raise RuntimeError("video input broke")

    result, _ = await _build(engine, shop.id, tmp_path, video_metrics=broken)

    assert result.built and result.metric_rankings == []
    assert len(await _stored(session, ShopDiagnosisReport, shop.id)) == 2
    assert await _stored(session, ShopMetricRanking, shop.id) == []


@pytest.mark.asyncio
async def test_a_forced_rebuild_replaces_the_rankings_of_the_same_day(engine, session, tmp_path):
    shop = await _make_shop(session, label="rk-again")
    await _build(engine, shop.id, tmp_path)
    await _build(engine, shop.id, tmp_path, force=True)
    rows = await _stored(session, ShopMetricRanking, shop.id)
    assert len(rows) == WITHOUT_VIDEOS


# ---------------------------------------------------------------------------
# GET /v1/demo/analysis/rankings
# ---------------------------------------------------------------------------


async def _store(session, shop_id, *, end: date, stream="product_card", metric="ctr", tag="x"):
    await ShopMetricRankingsRepo(session).save(
        shop_id,
        end_date=end,
        stream=stream,
        metric=metric,
        ranking={"tag": tag, "down": [], "up": [], "closing": {}},
        built_at=datetime(2026, 10, 7, 1, 0),
    )
    await session.commit()


@pytest_asyncio.fixture
async def two_shops(session):
    return await _make_shop(session, label="api-a"), await _make_shop(session, label="api-b")


def _client(engine, shop: Shop, *, authenticated: bool = True) -> AsyncClient:
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
    if authenticated:
        application.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=shop.user_id
        )
        application.dependency_overrides[get_active_shop] = lambda: shop
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://test")


URL = "/v1/demo/analysis/rankings"


@pytest.mark.asyncio
async def test_the_route_returns_the_latest_ranking_of_the_stream_and_metric(
    engine, session, two_shops
):
    shop_a, _ = two_shops
    await _store(session, shop_a.id, end=END - timedelta(days=1), tag="old")
    await _store(session, shop_a.id, end=END, tag="new")
    await _store(session, shop_a.id, end=END, metric="aov", tag="aov")

    async with _client(engine, shop_a) as client:
        resp = await client.get(URL, params={"stream": "product_card", "metric": "ctr"})
        resp_aov = await client.get(URL, params={"stream": "product_card", "metric": "aov"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"as_of", "built_at", "stream", "metric", "ranking"}
    assert body["as_of"] == END.isoformat()
    assert (body["stream"], body["metric"]) == ("product_card", "ctr")
    assert body["ranking"]["tag"] == "new"
    assert resp_aov.json()["ranking"]["tag"] == "aov"


@pytest.mark.asyncio
async def test_the_route_404s_when_nothing_is_stored(engine, two_shops):
    shop_a, _ = two_shops
    async with _client(engine, shop_a) as client:
        resp = await client.get(URL, params={"stream": "seller_live", "metric": "ctor"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_the_route_refuses_a_metric_the_stream_does_not_rank(engine, two_shops):
    shop_a, _ = two_shops
    async with _client(engine, shop_a) as client:
        not_clickable = await client.get(URL, params={"stream": "seller_video", "metric": "ctor"})
        no_cart = await client.get(URL, params={"stream": "shop_tab", "metric": "add_to_cart_rate"})
        affiliate = await client.get(URL, params={"stream": "affiliate", "metric": "ctr"})
        unknown = await client.get(URL, params={"stream": "product_card", "metric": "gmv"})
        missing = await client.get(URL, params={"stream": "product_card"})
    for resp in (not_clickable, no_cart, affiliate, unknown, missing):
        assert resp.status_code == 422


@pytest.mark.asyncio
async def test_shop_a_never_reads_shop_bs_ranking(engine, session, two_shops):
    shop_a, shop_b = two_shops
    await _store(session, shop_b.id, end=END, tag="shop-b-secret")
    params = {"stream": "product_card", "metric": "ctr", "shop_id": str(shop_b.id)}
    async with _client(engine, shop_a) as client:
        resp = await client.get(URL, params=params)
    assert resp.status_code == 404
    assert "shop-b-secret" not in resp.text


@pytest.mark.asyncio
async def test_the_route_401s_without_a_jwt(engine, two_shops):
    shop_a, _ = two_shops
    async with _client(engine, shop_a, authenticated=False) as client:
        resp = await client.get(
            URL,
            params={"stream": "product_card", "metric": "ctr"},
            headers={"X-Shop-Id": str(shop_a.id)},
        )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_the_migration_matches_the_model_and_chains_onto_076():
    root = Path(__file__).resolve().parents[2]
    text = (
        root / "backend/src/juli_backend/database/migrations/versions/077_metric_rankings.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "077_metric_rankings"' in text
    assert len("077_metric_rankings") <= 32
    assert 'down_revision: str | None = "076_shop_diagnosis_reports"' in text
    for column in ShopMetricRanking.__table__.columns:
        assert f'"{column.name}"' in text, column.name
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "app_current_shop_id()" in text
    for value in (*RANKING_STREAMS, *RANKING_METRICS):
        assert f'"{value}"' in text, value


def test_the_models_allowed_values_are_the_rankings_streams_and_metrics():
    assert set(RANKING_STREAMS) == {s.value for s in STREAM_METRICS}
    assert set(RANKING_METRICS) == {m.value for m in Metric}
