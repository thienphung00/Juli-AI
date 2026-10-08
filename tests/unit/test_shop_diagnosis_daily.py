"""Shop diagnosis as a product (fast track P7-A, AC-7.1 / AC-7.2).

The daily job builds the ADR-108 report from a fake production-read TikTok
resource (``tests/support/shop_diagnosis.py``) and stores it; the read route
serves it to the caller's own shop only. SQLite here; the Postgres RLS proof
is ``tests/integration/test_shop_diagnosis_two_tenant.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from juli_backend.integrations.tiktok.merchant import TikTokCapability
from juli_backend.models.ingestion import ShopIngestionState
from juli_backend.models.models import Shop, User
from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
from juli_backend.repositories import ShopDiagnosisReportsRepo, TikTokCredentialRepo
from juli_backend.services.shop_diagnosis_daily import (
    build_and_store_shop_diagnosis,
    json_safe,
    report_end_date,
)
from juli_backend.services.shop_diagnosis_daily.fetch import DAYS
from tests.support.shop_diagnosis import BUYER_MARKERS, END, FakeTikTokReadResources

#: 2026-10-07 10:00 UTC is 17:00 in UTC+7, so "yesterday" there is END (10-06).
NOW = datetime(2026, 10, 7, 10, 0, tzinfo=UTC)

#: The report.json contract the Phân tích UI renders (do not change).
REPORT_KEYS = {
    "shop_name",
    "end",
    "windows",
    "ranking",
    "missing_days",
    "sale_days",
    "total",
    "channels",
    "affiliate_rows",
    "groups",
    "timelines",
    "shop_bands",
    "shop_flash",
    "vouchers",
    "selection",
    "profiles",
    "rest_total",
    "rest_self_search",
    "rest_conclusion",
    "watch",
    "titles",
    "orders_present",
}


@pytest.fixture(autouse=True)
def _no_lazy_refresh(monkeypatch):
    """`_lazy_refresh` is a no-op without TikTok app env -- keep it that way."""
    monkeypatch.delenv("TIKTOK_APP_KEY", raising=False)
    monkeypatch.delenv("TIKTOK_APP_SECRET", raising=False)


async def _make_shop(
    session,
    *,
    label: str,
    capability: TikTokCapability = TikTokCapability.SELLER_CONNECT,
    with_credential: bool = True,
) -> Shop:
    user = User(id=uuid.uuid4(), phone=f"+8491{uuid.uuid4().int % 10_000_000:07d}")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name=f"{label} shop",
        tiktok_shop_id=f"tt-{label}-{uuid.uuid4().hex[:6]}",
        is_active=True,
    )
    session.add_all([user, shop])
    await session.flush()
    if with_credential:
        await TikTokCredentialRepo(session).create(
            shop_id=shop.id,
            access_token=f"access-{label}",
            refresh_token=f"refresh-{label}",
            token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
            merchant_authorization_id=f"merchant-{label}",
            capability=capability.value,
            shop_cipher=f"cipher-{label}",
        )
    await session.commit()
    return shop


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def _build(factory, shop_id, resources, tmp_path: Path, **kwargs):
    seen_configs: list = []

    def create_resources(config):
        seen_configs.append(config)
        return resources

    result = await build_and_store_shop_diagnosis(
        session_factory=factory,
        shop_id=shop_id,
        app_key="app-key",
        app_secret="app-secret",
        create_resources=create_resources,
        now=NOW,
        tmp_root=tmp_path,
        sleep_s=0,
        backoff_sleep=lambda _s: None,
        **kwargs,
    )
    return result, seen_configs


async def _rows(session, shop_id) -> list[ShopDiagnosisReport]:
    stmt = select(ShopDiagnosisReport).where(ShopDiagnosisReport.shop_id == shop_id)
    return list((await session.execute(stmt)).scalars().all())


# ---------------------------------------------------------------------------
# AC-7.1 -- the daily job
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_job_builds_and_stores_the_report_from_tiktok_reads(session, factory, tmp_path):
    shop = await _make_shop(session, label="alpha")
    resources = FakeTikTokReadResources()

    result, configs = await _build(factory, shop.id, resources, tmp_path)

    assert result.built and result.end_date == END
    assert sorted(result.rankings) == ["30d", "60d"]
    assert result.new_daily_files == DAYS
    # The shop's OWN credential signed the client.
    assert configs[0].merchant_auth_id == "merchant-alpha"
    assert configs[0].access_token == "access-alpha"
    # 60 daily A-34 reads ending END, all read-only methods.
    a34_days = sorted(c[1] for c in resources.calls if c[0] == "a34")
    assert len(a34_days) == DAYS
    assert a34_days[-1] == END.isoformat()

    rows = await _rows(session, shop.id)
    assert {r.ranking for r in rows} == {"60d", "30d"}
    stored = next(r for r in rows if r.ranking == "60d")
    assert stored.end_date == END
    assert set(stored.report) == REPORT_KEYS
    assert stored.report["shop_name"] == "alpha shop"
    assert stored.report["end"] == END.isoformat()
    assert stored.report["ranking"] == "60d"
    assert stored.report["orders_present"] is True
    assert stored.report["profiles"], "hero profiles were built"


@pytest.mark.asyncio
async def test_buyer_level_order_data_is_never_stored_or_left_on_disk(session, factory, tmp_path):
    shop = await _make_shop(session, label="buyers")

    await _build(factory, shop.id, FakeTikTokReadResources(), tmp_path)

    for row in await _rows(session, shop.id):
        dumped = json.dumps(row.report, ensure_ascii=False)
        for marker in BUYER_MARKERS:
            assert marker not in dumped
        assert "o-2026" not in dumped, "no order ids in the stored report"
    assert list(tmp_path.iterdir()) == [], "the temporary snapshot was deleted"


@pytest.mark.asyncio
async def test_the_job_is_idempotent_per_shop_and_end_date(session, factory, tmp_path):
    shop = await _make_shop(session, label="idem")
    await _build(factory, shop.id, FakeTikTokReadResources(), tmp_path)

    again = FakeTikTokReadResources()
    result, configs = await _build(factory, shop.id, again, tmp_path)

    assert not result.built and result.skipped_reason == "already_built"
    assert again.calls == [] and configs == [], "no TikTok call for a report already built"
    count = await session.scalar(
        select(func.count())
        .select_from(ShopDiagnosisReport)
        .where(ShopDiagnosisReport.shop_id == shop.id)
    )
    assert count == 2


@pytest.mark.asyncio
async def test_a_new_analytics_day_builds_a_new_report(session, factory, tmp_path):
    shop = await _make_shop(session, label="nextday")
    session.add(ShopIngestionState(shop_id=shop.id, analytics_through_date=END - timedelta(days=1)))
    await session.commit()
    first, _ = await _build(factory, shop.id, FakeTikTokReadResources(), tmp_path)
    assert first.end_date == END - timedelta(days=1)

    state = await session.get(ShopIngestionState, shop.id)
    state.analytics_through_date = END
    await session.commit()
    second, _ = await _build(factory, shop.id, FakeTikTokReadResources(), tmp_path)

    assert second.built and second.end_date == END
    latest = await ShopDiagnosisReportsRepo(session).latest(shop.id, "60d")
    assert latest is not None and latest.end_date == END


def test_the_end_date_is_the_last_analytics_day_capped_at_yesterday():
    assert report_end_date(None, now=NOW) == END
    assert report_end_date(END - timedelta(days=3), now=NOW) == END - timedelta(days=3)
    assert report_end_date(END + timedelta(days=2), now=NOW) == END


def test_json_safe_drops_non_finite_numbers():
    assert json_safe({"a": [1.0, float("nan")], "b": float("inf"), "c": "x"}) == {
        "a": [1.0, None],
        "b": None,
        "c": "x",
    }


@pytest.mark.asyncio
async def test_a_failed_fetch_stores_nothing(session, factory, tmp_path):
    shop = await _make_shop(session, label="broken")

    with pytest.raises(RuntimeError, match="analytics unavailable"):
        await _build(factory, shop.id, FakeTikTokReadResources(fail_a34=True), tmp_path)

    assert await _rows(session, shop.id) == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_a_shop_without_a_read_credential_is_refused_before_any_call(
    session, factory, tmp_path
):
    from juli_backend.core.security import NoReadCredentialForShop

    shop = await _make_shop(session, label="nocred", with_credential=False)
    resources = FakeTikTokReadResources()

    with pytest.raises(NoReadCredentialForShop):
        await _build(factory, shop.id, resources, tmp_path)
    assert resources.calls == []


@pytest.mark.asyncio
async def test_a_credential_owned_by_another_shop_is_refused(session, factory, tmp_path):
    from juli_backend.core.security import resolve_read_credential_for_shop

    shop_a = await _make_shop(session, label="owner-a")
    shop_b = await _make_shop(session, label="owner-b")
    resources = FakeTikTokReadResources()

    async def other_shops(sess, _shop_id):
        return await resolve_read_credential_for_shop(sess, shop_b.id)

    with pytest.raises(ValueError, match="owned by"):
        await _build(factory, shop_a.id, resources, tmp_path, resolve_credential=other_shops)
    assert resources.calls == []
    assert await _rows(session, shop_a.id) == []


@pytest.mark.asyncio
async def test_the_task_body_logs_a_failure_instead_of_raising(session, factory, tmp_path, caplog):
    from juli_backend.workers.tasks.shop_diagnosis import run_build_shop_diagnosis

    shop = await _make_shop(session, label="tasklog")
    result = await run_build_shop_diagnosis(
        str(shop.id),
        session_factory=factory,
        app_key="k",
        app_secret="s",
        create_resources=lambda _c: FakeTikTokReadResources(fail_a34=True),
        now=NOW,
        tmp_root=tmp_path,
        sleep_s=0,
    )
    assert result is None
    assert any(r.message == "shop_diagnosis_failed" for r in caplog.records)


# ---------------------------------------------------------------------------
# AC-7.1 -- hooked after the daily analytics pass and the bootstrap fast phase
# ---------------------------------------------------------------------------


class _NullSession:
    async def commit(self):
        return None


def _enqueuers(diagnoses: list[str], *, fail: bool = False):
    from juli_backend.workers.tasks.shop_ingestion import Enqueuers

    def diagnosis(shop_id: str) -> str:
        if fail:
            raise ConnectionError("broker down")
        diagnoses.append(shop_id)
        return "d"

    return Enqueuers(
        bootstrap=lambda *a, **k: "b",
        history=lambda *a, **k: "h",
        poll=lambda shop_id: "p",
        diagnosis=diagnosis,
    )


def _factory_of(session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield session

    return factory


async def _no_collaborators(_session):
    return {}


@pytest.mark.asyncio
@pytest.mark.parametrize(("analytics_ran", "expected"), [(True, 1), (False, 0)])
async def test_a_poll_cycle_enqueues_the_report_only_after_a_daily_analytics_pass(
    analytics_ran, expected
):
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import run_poll_shop_task

    diagnoses: list[str] = []
    shop_id = str(uuid.uuid4())

    async def cycle_fn(**_kwargs):
        return SimpleNamespace(
            needs_bootstrap=False, history_done=True, analytics_ran=analytics_ran
        )

    await run_poll_shop_task(
        shop_id,
        session_factory=_factory_of(_NullSession()),
        lock=InMemoryShopIngestLock(),
        collaborators=_no_collaborators,
        enqueuers=_enqueuers(diagnoses),
        cycle_fn=cycle_fn,
    )
    assert diagnoses == [shop_id] * expected


@pytest.mark.asyncio
async def test_the_bootstrap_fast_phase_enqueues_the_report_once():
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import run_bootstrap_task

    diagnoses: list[str] = []
    shop_id = str(uuid.uuid4())

    async def fast_fn(**_kwargs):
        return SimpleNamespace(skipped=False, reason=None)

    await run_bootstrap_task(
        shop_id,
        session_factory=_factory_of(_NullSession()),
        lock=InMemoryShopIngestLock(),
        collaborators=_no_collaborators,
        enqueuers=_enqueuers(diagnoses),
        fast_fn=fast_fn,
    )
    assert diagnoses == [shop_id]


@pytest.mark.asyncio
async def test_a_failing_enqueue_never_breaks_the_poll_cycle():
    from juli_backend.workers.services.polling.shop_lock import InMemoryShopIngestLock
    from juli_backend.workers.tasks.shop_ingestion import run_poll_shop_task

    cycle_result = SimpleNamespace(needs_bootstrap=False, history_done=True, analytics_ran=True)

    async def cycle_fn(**_kwargs):
        return cycle_result

    result = await run_poll_shop_task(
        str(uuid.uuid4()),
        session_factory=_factory_of(_NullSession()),
        lock=InMemoryShopIngestLock(),
        collaborators=_no_collaborators,
        enqueuers=_enqueuers([], fail=True),
        cycle_fn=cycle_fn,
    )
    assert result is cycle_result


def test_the_build_task_is_registered():
    from juli_backend.workers.celery_app import celery_app
    from juli_backend.workers.tasks.shop_diagnosis import BUILD_SHOP_DIAGNOSIS_TASK

    celery_app.loader.import_default_modules()
    assert BUILD_SHOP_DIAGNOSIS_TASK in celery_app.tasks


# ---------------------------------------------------------------------------
# AC-7.2 -- GET /v1/demo/analysis
# ---------------------------------------------------------------------------


async def _store(session, shop_id, *, end: date, ranking: str = "60d", name: str = "x"):
    await ShopDiagnosisReportsRepo(session).save(
        shop_id,
        end_date=end,
        ranking=ranking,
        report={"shop_name": name, "end": end.isoformat(), "ranking": ranking},
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


@pytest.mark.asyncio
async def test_the_route_returns_the_latest_report_for_the_callers_shop(engine, session, two_shops):
    shop_a, _ = two_shops
    await _store(session, shop_a.id, end=END - timedelta(days=1), name="old")
    await _store(session, shop_a.id, end=END, name="new")
    await _store(session, shop_a.id, end=END, ranking="30d", name="new-30d")

    async with _client(engine, shop_a) as client:
        resp = await client.get("/v1/demo/analysis")
        resp_30 = await client.get("/v1/demo/analysis", params={"ranking": "30d"})
        resp_bad = await client.get("/v1/demo/analysis", params={"ranking": "7d"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"as_of", "built_at", "ranking", "report"}
    assert body["as_of"] == END.isoformat()
    assert body["ranking"] == "60d"
    assert body["report"]["shop_name"] == "new"
    assert resp_30.status_code == 200 and resp_30.json()["report"]["shop_name"] == "new-30d"
    assert resp_bad.status_code == 422


@pytest.mark.asyncio
async def test_the_route_404s_when_the_shop_has_no_report(engine, two_shops):
    shop_a, _ = two_shops
    async with _client(engine, shop_a) as client:
        resp = await client.get("/v1/demo/analysis")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_shop_a_never_reads_shop_bs_report(engine, session, two_shops):
    shop_a, shop_b = two_shops
    await _store(session, shop_b.id, end=END, name="shop-b-secret")

    async with _client(engine, shop_a) as client:
        resp = await client.get("/v1/demo/analysis", params={"shop_id": str(shop_b.id)})
    assert resp.status_code == 404
    assert "shop-b-secret" not in resp.text

    await _store(session, shop_a.id, end=END - timedelta(days=5), name="shop-a-own")
    async with _client(engine, shop_a) as client:
        resp = await client.get("/v1/demo/analysis")
    assert resp.status_code == 200
    assert resp.json()["report"]["shop_name"] == "shop-a-own"


@pytest.mark.asyncio
async def test_the_route_401s_without_a_jwt(engine, two_shops):
    shop_a, _ = two_shops
    async with _client(engine, shop_a, authenticated=False) as client:
        resp = await client.get("/v1/demo/analysis", headers={"X-Shop-Id": str(shop_a.id)})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_the_migration_matches_the_model_and_chains_onto_075():
    root = Path(__file__).resolve().parents[2]
    text = (
        root / "backend/src/juli_backend/database/migrations/versions/076_shop_diagnosis_reports.py"
    ).read_text(encoding="utf-8")
    assert 'revision: str = "076_shop_diagnosis_reports"' in text
    assert len("076_shop_diagnosis_reports") <= 32
    assert 'down_revision: str | None = "075_analytics_breakdown"' in text
    for column in ShopDiagnosisReport.__table__.columns:
        assert f'"{column.name}"' in text, column.name
    assert "ENABLE ROW LEVEL SECURITY" in text
    assert "app_current_shop_id()" in text
