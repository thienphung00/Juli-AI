"""P2-9 HITL (#472) — live analytics backfill CLI wiring (mocked Partner)."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.integrations.tiktok.factories import ProductionReadResources
from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo
from juli_backend.services.analytics_backfill.catalog_partition import (
    CatalogCountStrategy,
    CatalogPartitionResult,
)
from juli_backend.services.analytics_backfill.live_partition import LivePartitionResult
from juli_backend.services.analytics_backfill.live_runner import (
    BackfillBudgetPause,
    BackfillPartitionFailed,
    BackfillRunSummary,
    build_partition_dispatcher,
    execute_live_backfill,
    load_backfill_cli_config,
    orchestrator_result_to_exit_code,
    summary_to_text,
)
from juli_backend.services.analytics_backfill.orchestrator import OrchestratorResult
from juli_backend.services.analytics_backfill.product_partition import ProductPartitionResult
from juli_backend.services.analytics_backfill.cli import backfill_main, build_parser

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"
REDIRECT_URI = "https://example.com/callback"
SHOP_CIPHER = "ROW_test_cipher"


@pytest.fixture(autouse=True)
def backfill_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TIKTOK_APP_KEY", APP_KEY)
    monkeypatch.setenv("TIKTOK_APP_SECRET", APP_SECRET)
    monkeypatch.setenv("TIKTOK_REDIRECT_URI", REDIRECT_URI)


@pytest_asyncio.fixture
async def fujiwa_shop(session: AsyncSession) -> Shop:
    user = User(id=uuid.uuid4(), phone="+84901234999")
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user.id,
        shop_name="Fujiwa Live Backfill Shop",
        tiktok_shop_id=PRODUCTION_AUTH_ID,
    )
    session.add_all([user, shop])
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def fujiwa_credential(session: AsyncSession, fujiwa_shop: Shop):
    expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    return await TikTokCredentialRepo(session).create(
        shop_id=fujiwa_shop.id,
        access_token="fujiwa_access",
        refresh_token="fujiwa_refresh",
        token_expires_at=expires_at,
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher=SHOP_CIPHER,
    )


@pytest.fixture
def mock_resources() -> ProductionReadResources:
    return ProductionReadResources(
        authorization=MagicMock(),
        orders=MagicMock(),
        products=MagicMock(),
        returns=MagicMock(),
        inventory=MagicMock(),
        analytics=MagicMock(),
        promotion=MagicMock(),
    )


class TestBackfillCliConfig:
    def test_load_backfill_cli_config_reads_required_env(self) -> None:
        config = load_backfill_cli_config()
        assert config.app_key == APP_KEY
        assert config.app_secret == APP_SECRET
        assert config.redirect_uri == REDIRECT_URI

    def test_parser_accepts_dry_run_flag(self) -> None:
        shop_id = str(uuid.uuid4())
        args = build_parser().parse_args(
            [
                "--shop-id",
                shop_id,
                "--end",
                "2026-03-20",
                "--dry-run",
            ]
        )
        assert args.dry_run is True


class TestPartitionDispatcher:
    pytestmark = pytest.mark.asyncio

    async def test_dispatcher_maps_buckets_to_partition_functions(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        mock_resources: ProductionReadResources,
    ) -> None:
        from juli_backend.services.analytics_backfill.budget import begin_run

        budget = begin_run(max_attempts=10, hard_limit=10)
        partition_date = date(2026, 3, 16)
        calls: list[tuple[str, date]] = []

        with (
            patch(
                "juli_backend.services.analytics_backfill.live_runner.backfill_revenue_partition",
                new_callable=AsyncMock,
                return_value="complete",
            ) as revenue_mock,
            patch(
                "juli_backend.services.analytics_backfill.live_runner.run_live_partition",
                new_callable=AsyncMock,
                return_value=LivePartitionResult(status="complete"),
            ) as live_mock,
            patch(
                "juli_backend.services.analytics_backfill.live_runner.backfill_product_partition",
                new_callable=AsyncMock,
                return_value=ProductPartitionResult(complete=True),
            ) as product_mock,
            patch(
                "juli_backend.services.analytics_backfill.live_runner.run_catalog_partition",
                new_callable=AsyncMock,
                return_value=CatalogPartitionResult(
                    status="completed",
                    partition_date=partition_date,
                    strategy=CatalogCountStrategy.DAILY,
                ),
            ) as catalog_mock,
        ):
            dispatcher = build_partition_dispatcher(
                session,
                shop_id=fujiwa_shop.id,
                resources=mock_resources,
                budget=budget,
                synced_at=1_700_000_000,
            )
            for bucket in ("revenue", "live", "product", "catalog"):
                await dispatcher(bucket, partition_date)
                calls.append((bucket, partition_date))

        assert calls == [
            ("revenue", partition_date),
            ("live", partition_date),
            ("product", partition_date),
            ("catalog", partition_date),
        ]
        revenue_mock.assert_awaited_once()
        live_mock.assert_awaited_once()
        product_mock.assert_awaited_once()
        catalog_mock.assert_awaited_once()

    async def test_dispatcher_raises_on_revenue_failed(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        mock_resources: ProductionReadResources,
    ) -> None:
        from juli_backend.services.analytics_backfill.budget import begin_run

        budget = begin_run()
        with patch(
            "juli_backend.services.analytics_backfill.live_runner.backfill_revenue_partition",
            new_callable=AsyncMock,
            return_value="failed",
        ):
            dispatcher = build_partition_dispatcher(
                session,
                shop_id=fujiwa_shop.id,
                resources=mock_resources,
                budget=budget,
                synced_at=1_700_000_000,
            )
            with pytest.raises(BackfillPartitionFailed):
                await dispatcher("revenue", date(2026, 3, 16))

    async def test_dispatcher_raises_on_live_paused(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        mock_resources: ProductionReadResources,
    ) -> None:
        from juli_backend.services.analytics_backfill.budget import begin_run

        budget = begin_run()
        with patch(
            "juli_backend.services.analytics_backfill.live_runner.run_live_partition",
            new_callable=AsyncMock,
            return_value=LivePartitionResult(status="paused"),
        ):
            dispatcher = build_partition_dispatcher(
                session,
                shop_id=fujiwa_shop.id,
                resources=mock_resources,
                budget=budget,
                synced_at=1_700_000_000,
            )
            with pytest.raises(BackfillBudgetPause):
                await dispatcher("live", date(2026, 3, 16))


class TestExecuteLiveBackfill:
    pytestmark = pytest.mark.asyncio

    async def test_shop_id_mismatch_exits_non_zero(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        fujiwa_credential,
    ) -> None:
        other_shop_id = uuid.uuid4()
        with pytest.raises(SystemExit, match="does not match"):
            await execute_live_backfill(
                session,
                shop_id=other_shop_id,
                start_date=date(2026, 3, 16),
                end_date=date(2026, 3, 16),
                buckets=("revenue",),
                oauth_service=AsyncMock(
                    refresh_merchant_tokens=AsyncMock(return_value=fujiwa_credential)
                ),
            )

    async def test_complete_run_returns_exit_ready_summary(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        fujiwa_credential,
    ) -> None:
        result = OrchestratorResult(
            stopped_reason="complete",
            skipped_partitions=0,
            completed_partitions=1,
            budget_fields={"attempts": 2, "successes": 2, "failures": 0, "rate_limited": 0, "stopped_reason": "complete"},
            shop_id=fujiwa_shop.id,
            start_date=date(2026, 3, 16),
            end_date=date(2026, 3, 16),
            buckets=("revenue",),
        )
        oauth = AsyncMock(refresh_merchant_tokens=AsyncMock(return_value=fujiwa_credential))
        with patch(
            "juli_backend.services.analytics_backfill.live_runner.backfill_analytics_history",
            new_callable=AsyncMock,
            return_value=result,
        ):
            summary = await execute_live_backfill(
                session,
                shop_id=fujiwa_shop.id,
                start_date=date(2026, 3, 16),
                end_date=date(2026, 3, 16),
                buckets=("revenue",),
                oauth_service=oauth,
                create_resources=MagicMock(return_value=MagicMock()),
            )
        assert orchestrator_result_to_exit_code(summary.result) == 0
        assert summary.result.stopped_reason == "complete"

    async def test_budget_pause_maps_to_exit_zero(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        fujiwa_credential,
    ) -> None:
        result = OrchestratorResult(
            stopped_reason="budget",
            skipped_partitions=0,
            completed_partitions=3,
            budget_fields={"attempts": 400, "successes": 390, "failures": 10, "rate_limited": 0, "stopped_reason": "budget"},
            shop_id=fujiwa_shop.id,
            start_date=date(2026, 3, 16),
            end_date=date(2026, 3, 18),
            buckets=("revenue",),
        )
        oauth = AsyncMock(refresh_merchant_tokens=AsyncMock(return_value=fujiwa_credential))
        with patch(
            "juli_backend.services.analytics_backfill.live_runner.backfill_analytics_history",
            new_callable=AsyncMock,
            return_value=result,
        ):
            summary = await execute_live_backfill(
                session,
                shop_id=fujiwa_shop.id,
                start_date=date(2026, 3, 16),
                end_date=date(2026, 3, 18),
                buckets=("revenue",),
                oauth_service=oauth,
                create_resources=MagicMock(return_value=MagicMock()),
            )
        assert orchestrator_result_to_exit_code(summary.result) == 0
        assert summary.result.stopped_reason == "budget"

    async def test_partition_failure_maps_to_exit_one(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        fujiwa_credential,
    ) -> None:
        oauth = AsyncMock(refresh_merchant_tokens=AsyncMock(return_value=fujiwa_credential))
        with patch(
            "juli_backend.services.analytics_backfill.live_runner.backfill_analytics_history",
            new_callable=AsyncMock,
            side_effect=BackfillPartitionFailed("revenue partition failed"),
        ):
            with pytest.raises(BackfillPartitionFailed):
                await execute_live_backfill(
                    session,
                    shop_id=fujiwa_shop.id,
                    start_date=date(2026, 3, 16),
                    end_date=date(2026, 3, 16),
                    buckets=("revenue",),
                    oauth_service=oauth,
                    create_resources=MagicMock(return_value=MagicMock()),
                )

    async def test_dry_run_validates_without_partner_calls(
        self,
        session: AsyncSession,
        fujiwa_shop: Shop,
        fujiwa_credential,
    ) -> None:
        oauth = AsyncMock(refresh_merchant_tokens=AsyncMock(return_value=fujiwa_credential))
        create_resources = MagicMock()
        with patch(
            "juli_backend.services.analytics_backfill.live_runner.backfill_analytics_history",
            new_callable=AsyncMock,
        ) as orchestrator_mock:
            summary = await execute_live_backfill(
                session,
                shop_id=fujiwa_shop.id,
                start_date=date(2026, 3, 16),
                end_date=date(2026, 3, 16),
                buckets=("revenue",),
                dry_run=True,
                oauth_service=oauth,
                create_resources=create_resources,
            )
        orchestrator_mock.assert_not_called()
        create_resources.assert_not_called()
        assert summary.dry_run is True
        assert orchestrator_result_to_exit_code(summary.result) == 0


class TestBackfillMainCli:
    def test_backfill_main_complete_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fujiwa_shop: Shop,
    ) -> None:
        summary = BackfillRunSummary(
            dry_run=False,
            result=OrchestratorResult(
                stopped_reason="complete",
                skipped_partitions=0,
                completed_partitions=1,
                budget_fields={"attempts": 1, "successes": 1, "failures": 0, "rate_limited": 0, "stopped_reason": "complete"},
                shop_id=fujiwa_shop.id,
                start_date=date(2026, 3, 16),
                end_date=date(2026, 3, 16),
                buckets=("revenue",),
            ),
        )

        async def _fake_run(*_args, **_kwargs):
            return summary

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr(
            "juli_backend.services.analytics_backfill.cli._run_live_backfill_session",
            _fake_run,
        )
        exit_code = backfill_main(
            [
                "--shop-id",
                str(fujiwa_shop.id),
                "--start",
                "2026-03-16",
                "--end",
                "2026-03-16",
            ]
        )
        assert exit_code == 0

    def test_backfill_main_budget_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fujiwa_shop: Shop,
    ) -> None:
        summary = BackfillRunSummary(
            dry_run=False,
            result=OrchestratorResult(
                stopped_reason="budget",
                skipped_partitions=0,
                completed_partitions=5,
                budget_fields={"attempts": 400, "successes": 395, "failures": 5, "rate_limited": 0, "stopped_reason": "budget"},
                shop_id=fujiwa_shop.id,
                start_date=date(2026, 3, 16),
                end_date=date(2026, 3, 18),
                buckets=("revenue",),
            ),
        )

        async def _fake_run(*_args, **_kwargs):
            return summary

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr(
            "juli_backend.services.analytics_backfill.cli._run_live_backfill_session",
            _fake_run,
        )
        exit_code = backfill_main(
            [
                "--shop-id",
                str(fujiwa_shop.id),
                "--end",
                "2026-03-18",
            ]
        )
        assert exit_code == 0

    def test_backfill_main_partition_failure_exit_code(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fujiwa_shop: Shop,
    ) -> None:
        async def _fail(*_args, **_kwargs):
            raise BackfillPartitionFailed("partition failed")

        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setattr(
            "juli_backend.services.analytics_backfill.cli._run_live_backfill_session",
            _fail,
        )
        exit_code = backfill_main(
            [
                "--shop-id",
                str(fujiwa_shop.id),
                "--end",
                "2026-03-16",
            ]
        )
        assert exit_code == 1


def test_summary_to_text_never_includes_tokens() -> None:
    summary = BackfillRunSummary(
        dry_run=False,
        result=OrchestratorResult(
            stopped_reason="complete",
            skipped_partitions=1,
            completed_partitions=2,
            budget_fields={"attempts": 3, "successes": 3, "failures": 0, "rate_limited": 0, "stopped_reason": "complete"},
            shop_id=uuid.uuid4(),
            start_date=date(2026, 3, 16),
            end_date=date(2026, 3, 17),
            buckets=("revenue", "live"),
        ),
    )
    text = summary_to_text(summary)
    assert "access" not in text.lower()
    assert "token" not in text.lower()
    assert "stopped_reason=complete" in text
