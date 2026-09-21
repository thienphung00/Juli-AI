"""A poll cycle that failed must not report success (#1950 criteria 2 and 3).

#1969 (PR #2009) gave every step a `SyncOutcome` and made a step that fetched
rows and persisted none raise. It left two holes open, and named one of them as
this issue's work:

1. **A failed FETCH still completed the cycle.** `sync_orders`,
   `sync_products` and `sync_returns` catch `TikTokAPIError` around the vendor
   call and `return step.report(error=exc)`. The outcome carries `ok=False`,
   and nothing read it: `_poll` discarded every return value, the Celery task
   exited zero, nothing retried. A cycle in which all five endpoints failed
   their vendor call was byte-for-byte a clean cycle from outside the process.
2. **The analytics watermarks were never gated.** The four search steps gate
   theirs on `outcome.persisted`. `sync_analytics` wrote
   `sync_state[<endpoint>_last_sync_at] = synced_at` the instant its LIST call
   returned -- before one row had been offered to the ETL. That is mechanism 2
   of this issue (#1949) with a different variable name.

The doubles are bound to the real signatures (`OrdersResource.search_all`,
`HandoffFn`, `TikTokSyncStateRepo.load/save/record_outcomes`), so a contract
change breaks these tests rather than sliding past a `**kwargs` stand-in.
"""

from __future__ import annotations

import inspect
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from juli_backend.core.security.tiktok_oauth import TikTokOAuthService
from juli_backend.integrations.tiktok.auth import TikTokAuth
from juli_backend.integrations.tiktok.exceptions import TikTokSystemError
from juli_backend.integrations.tiktok.merchant import PRODUCTION_AUTH_ID, TikTokCapability
from juli_backend.integrations.tiktok.rate_limiter import RateLimiter as RealRateLimiter
from juli_backend.models.models import Shop, User
from juli_backend.repositories.repos import TikTokCredentialRepo, TikTokSyncStateRepo
from juli_backend.workers.services.polling import orchestrate as orchestrate_module
from juli_backend.workers.services.polling import sync as sync_module
from juli_backend.workers.services.polling.orchestrate import (
    FujiwaPollConfig,
    PollCycleFailedError,
    _assert_cycle_succeeded,
    run_fujiwa_poll_cycle,
)
from juli_backend.workers.services.polling.sync import SyncOutcome, sync_analytics
from tests.support.tiktok_fakes import FakeAnalyticsResource, RecordingRateLimiter

APP_KEY = "test_app_key"
APP_SECRET = "test_app_secret"

SHOP_ID = "7494001234567890123"
NOW = datetime(2026, 7, 14, 12, 0, tzinfo=UTC)


async def no_handoff(channel: str, shop_key: str, value: bytes) -> None:
    """Bound to `HandoffFn = Callable[[str, str, bytes], Awaitable[None]]`."""
    return None


class RefusingHandoff:
    """An ETL that rejects every row -- the shape both production bugs had."""

    def __init__(self, *, refuse_channels: tuple[str, ...] | None = None) -> None:
        self.refuse_channels = refuse_channels
        self.accepted: list[str] = []

    async def __call__(self, channel: str, shop_key: str, value: bytes) -> None:
        if self.refuse_channels is None or channel in self.refuse_channels:
            raise RuntimeError("etl refused the row")
        self.accepted.append(channel)


def _outcome(resource: str, **fields: Any) -> SyncOutcome:
    return SyncOutcome(resource=resource, shop_id=SHOP_ID, **fields)


# ---------------------------------------------------------------------------
# Criterion 2 -- the cycle's own verdict.
# ---------------------------------------------------------------------------


class TestTheCycleRefusesToCallAFailedStepASuccess:
    def test_a_step_that_failed_its_fetch_fails_the_whole_cycle(self, caplog):
        """The residual gap #2009 recorded and deferred to this issue.

        `sync_orders`'s `except TikTokAPIError` arm returns rather than raises,
        so this outcome is what a totally failed vendor call looks like from
        `_poll`: `fetched == 0`, `persisted == 0`, and an `error`. Before this
        change the cycle completed on it.
        """
        failed = _outcome("orders", error="TikTokSystemError(100006)")
        assert failed.ok is False

        shop_id = uuid.uuid4()
        with caplog.at_level(logging.INFO, logger=orchestrate_module.__name__):
            with pytest.raises(PollCycleFailedError) as excinfo:
                _assert_cycle_succeeded(
                    [_outcome("products", fetched=3, persisted=3), failed], shop_id=shop_id
                )

        assert excinfo.value.failures == [failed]
        assert "orders" in str(excinfo.value)
        (record,) = [r for r in caplog.records if r.message == "poll_cycle_outcome"]
        assert record.failed_steps == 1
        assert record.ok is False

    def test_a_step_that_dropped_every_row_fails_the_cycle_too(self):
        dropped = _outcome("inventory", fetched=3581, persisted=0, failed=3581)
        assert dropped.dropped_everything is True
        with pytest.raises(PollCycleFailedError):
            _assert_cycle_succeeded([dropped], shop_id=uuid.uuid4())

    def test_a_cycle_where_every_step_worked_is_not_failed(self, caplog):
        outcomes = [
            _outcome("orders", fetched=2, persisted=2),
            _outcome("products", fetched=0, persisted=0),
            _outcome("returns", skipped=True),
        ]
        with caplog.at_level(logging.INFO, logger=orchestrate_module.__name__):
            _assert_cycle_succeeded(outcomes, shop_id=uuid.uuid4())

        (record,) = [r for r in caplog.records if r.message == "poll_cycle_outcome"]
        assert record.ok is True
        assert record.failed_steps == 0
        assert record.fetched == 2
        assert record.persisted == 2

    def test_a_rate_limited_and_an_empty_step_are_not_failures(self):
        """The two ways a step legitimately does nothing.

        Treating either as a failure would make the cycle raise on an ordinary
        quiet hour, which is how a loud signal gets turned off again.
        """
        _assert_cycle_succeeded(
            [_outcome("orders", skipped=True), _outcome("returns", fetched=0, persisted=0)],
            shop_id=uuid.uuid4(),
        )


# ---------------------------------------------------------------------------
# Criterion 3 -- the analytics watermarks, which were never gated.
# ---------------------------------------------------------------------------


#: Vendor-shaped payloads. They have to be real enough to produce ROWS: a
#: response the expanders turn into zero rows offers the ETL nothing, and a
#: watermark gate that reads "nothing offered" would then advance for the
#: honest reason rather than the one under test. The shapes are the ones
#: `tests/integration/test_analytics_poll_etl_upsert.py` captured from the
#: vendor (A-31 SKU detail, A-36 shop performance).
ANALYTICS_LIST_PAYLOAD: dict[str, Any] = {
    "list_sku_performance_all": [{"id": "sku-1", "product_id": "prod-1"}],
    "get_sku_performance": {
        "latest_available_date": "2026-07-15",
        "performance": {
            "sku_id": "sku-1",
            "product_id": "prod-1",
            "intervals": [
                {
                    "start_date": "2026-07-13",
                    "end_date": "2026-07-14",
                    "gmv": {"amount": "916678.00", "currency": "VND"},
                    "sku_orders": 4,
                    "items_sold": 4,
                }
            ],
        },
    },
    "list_product_performance_all": [],
    "get_shop_performance": {
        "latest_available_date": "2026-07-14",
        "performance": {
            "intervals": [
                {
                    "start_date": "2026-07-13",
                    "end_date": "2026-07-14",
                    "sales": {
                        "gmv": {"overall": {"amount": "6408074.00", "currency": "VND"}},
                        "orders_count": 26,
                        "sku_orders_count": 29,
                        "items_sold": 32,
                    },
                    "traffic": {"avg_visitors": 303, "avg_conversation_rate": "0.0759"},
                }
            ]
        },
    },
}

SKU_CHANNEL = "tiktok.analytics.sku.raw"
SHOP_CHANNEL = "tiktok.analytics.shop.raw"


async def _run_analytics(*, handoff, sync_state: dict[str, Any]) -> None:
    """Run the analytics step against `sync_state`, which the caller keeps.

    The dict is mutated in place, so it is still inspectable when the step
    raises -- which is the case these tests care about most.
    """
    await sync_analytics(
        resource=FakeAnalyticsResource(dict(ANALYTICS_LIST_PAYLOAD)),
        promotion_resource=None,
        rate_limiter=RecordingRateLimiter(),
        handoff_fn=handoff,
        app_id="app1",
        shop_id=SHOP_ID,
        sync_state=sync_state,
        now=NOW,
    )


class TestAnalyticsWatermarksFollowTheRows:
    @pytest.mark.asyncio
    async def test_an_endpoint_whose_rows_were_all_refused_does_not_advance(self, caplog):
        """The whole point: rows came back, none landed, the cursor must not move.

        Before this change `sync_state["shop_sku_performance_last_sync_at"]`
        was written the instant `list_sku_performance_all` returned, so this
        state dict came back looking exactly like a healthy sync.
        """
        sync_state: dict[str, Any] = {}
        with caplog.at_level(logging.INFO, logger=sync_module.__name__):
            with pytest.raises(sync_module.PollStepDroppedRowsError):
                await _run_analytics(handoff=RefusingHandoff(), sync_state=sync_state)

        # The two endpoints that actually offered rows here. The others in this
        # payload return an empty list or `{}` and offer nothing at all, so
        # their cursors advance for the honest reason -- a genuine
        # `fetched == 0`, which the issue says must still advance.
        for key in ("shop_sku_performance_last_sync_at", "shop_performance_last_sync_at"):
            assert key not in sync_state, f"{key} advanced over rows that never landed"

        held = {
            record.watermark
            for record in caplog.records
            if record.message == "poll_watermark_held_back"
        }
        assert held == {"shop_sku_performance_last_sync_at", "shop_performance_last_sync_at"}

    @pytest.mark.asyncio
    async def test_an_endpoint_whose_rows_landed_does_advance(self):
        """The gate must not be a blanket refusal -- a working sync still syncs."""
        sync_state: dict[str, Any] = {}
        await _run_analytics(handoff=no_handoff, sync_state=sync_state)
        assert sync_state["shop_sku_performance_last_sync_at"] == int(NOW.timestamp())
        assert sync_state["shop_performance_last_sync_at"] == int(NOW.timestamp())

    @pytest.mark.asyncio
    async def test_one_endpoints_rows_do_not_unlock_a_siblings_held_back_cursor(self):
        """Per-endpoint, not per-step.

        `sync_analytics` is ONE `_StepRun` with one pair of counters shared by
        ~10 endpoints. A gate that asked "did this STEP persist anything" would
        advance the SKU cursor on the strength of the shop-performance rows,
        which is the same wrong answer with more arithmetic.
        """
        sync_state: dict[str, Any] = {}
        handoff = RefusingHandoff(refuse_channels=(SKU_CHANNEL,))
        await _run_analytics(handoff=handoff, sync_state=sync_state)

        assert SHOP_CHANNEL in handoff.accepted, "the sibling endpoint persisted nothing either"
        assert "shop_sku_performance_last_sync_at" not in sync_state
        assert sync_state["shop_performance_last_sync_at"] == int(NOW.timestamp())

    @pytest.mark.asyncio
    async def test_an_endpoint_with_an_empty_window_still_advances(self):
        """A genuine `fetched == 0` is not a failure and must not be refetched forever.

        `bestselling_products` hands off nothing at all -- it is fetched for
        rate-limit and freshness bookkeeping only -- so a gate that demanded
        `persisted > 0` unconditionally would freeze its cursor permanently.
        """
        sync_state: dict[str, Any] = {}
        await _run_analytics(handoff=no_handoff, sync_state=sync_state)
        assert sync_state["bestselling_products_last_sync_at"] == int(NOW.timestamp())

    @pytest.mark.asyncio
    async def test_the_watermarks_that_did_land_survive_an_exception_later_in_the_step(self):
        """`_poll` saves partial state before re-raising; the ledger must not undo that.

        The staged watermarks are flushed from `_StepRun.__exit__`, not only
        from the explicit call before `report`, so a step that dies at endpoint
        4 of 10 keeps the cursors of the three that worked. Discarding them
        would make the next cycle refetch rows that already landed -- under the
        incremental page cap, where over-running only warns.
        """

        class ExplodingShopPerformance(FakeAnalyticsResource):
            def get_shop_performance(self, *, start_date_ge: str, end_date_lt: str):
                raise RuntimeError("vendor payload is junk")

        sync_state: dict[str, Any] = {}
        with pytest.raises(RuntimeError, match="vendor payload is junk"):
            await sync_analytics(
                resource=ExplodingShopPerformance(dict(ANALYTICS_LIST_PAYLOAD)),
                promotion_resource=None,
                rate_limiter=RecordingRateLimiter(),
                handoff_fn=no_handoff,
                app_id="app1",
                shop_id=SHOP_ID,
                sync_state=sync_state,
                now=NOW,
            )

        assert sync_state["shop_sku_performance_last_sync_at"] == int(NOW.timestamp())
        assert "shop_performance_last_sync_at" not in sync_state


# ---------------------------------------------------------------------------
# A whole cycle: one shop, one production-read credential, one set of vendor
# resources. Defined here rather than imported from another test module so the
# fixtures cannot be renamed out from under this file.
# ---------------------------------------------------------------------------


class NeverExhaustedRateLimiter:
    """Bound to the real `RateLimiter` signatures, positionally included.

    Keyword-only parameters here would be a fake contract: the real methods
    take these positionally-or-by-keyword, so a caller switching to positional
    arguments would break production and not this test.
    """

    def acquire(
        self,
        app_id: str,
        shop_id: str,
        endpoint: str,
        max_requests: int,
        window_seconds: int,
    ) -> bool:
        return True

    def is_exhausted(self, app_id: str, shop_id: str, endpoint: str, max_requests: int) -> bool:
        return False

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        return 0


def test_the_rate_limiter_double_matches_the_real_signatures():
    for name in ("acquire", "is_exhausted", "time_until_reset"):
        real = inspect.signature(getattr(RealRateLimiter, name))
        double = inspect.signature(getattr(NeverExhaustedRateLimiter, name))
        assert list(real.parameters) == list(double.parameters), name
        assert [p.kind for p in real.parameters.values()] == [
            p.kind for p in double.parameters.values()
        ], name


async def _stub_binding_verifier(session, *, capability, access_token) -> str:
    return "ROW_stub_cipher"


@pytest_asyncio.fixture
async def cycle_shop(session, user_id):
    session.add(User(id=user_id, phone="+84901234577"))
    await session.flush()
    shop = Shop(
        id=uuid.uuid4(),
        user_id=user_id,
        shop_name="Verdict Test Shop",
        tiktok_shop_id=PRODUCTION_AUTH_ID,
    )
    session.add(shop)
    await session.flush()
    return shop


@pytest_asyncio.fixture
async def cycle_credential(session, cycle_shop):
    return await TikTokCredentialRepo(session).create(
        shop_id=cycle_shop.id,
        access_token="fujiwa_access",
        refresh_token="fujiwa_refresh",
        token_expires_at=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=7),
        merchant_authorization_id=PRODUCTION_AUTH_ID,
        capability=TikTokCapability.PRODUCTION_READ.value,
        shop_cipher="ROW_test_cipher",
    )


@pytest.fixture
def cycle_oauth_service(session):
    return TikTokOAuthService(
        tiktok_auth=TikTokAuth(
            app_key=APP_KEY,
            app_secret=APP_SECRET,
            base_url="https://open-api.tiktokglobalshop.com",
        ),
        session=session,
        redirect_uri="https://example.com/callback",
        app_secret=APP_SECRET,
        binding_verifier=_stub_binding_verifier,
    )


@pytest.fixture
def cycle_resources():
    resources = MagicMock()
    resources.orders.search_all.return_value = [{"id": "o1", "update_time": 1700000100}]
    resources.products.search_all.return_value = []
    resources.returns.search_returns_all.return_value = []
    resources.inventory.search.return_value = {"inventory": []}
    resources.analytics.list_sku_performance_all.return_value = []
    resources.analytics.list_product_performance_all.return_value = []
    resources.analytics.get_shop_performance.return_value = {}
    resources.analytics.get_shop_performance_per_hour.return_value = {}
    resources.analytics.get_bestselling_products.return_value = {}
    resources.analytics.get_bestselling_videos.return_value = {}
    resources.promotion.get_activity.return_value = {}
    return resources


# ---------------------------------------------------------------------------
# The same thing end to end, through `run_fujiwa_poll_cycle`.
#
# The assertions above exercise `_assert_cycle_succeeded` directly, which proves
# the rule but not that anything calls it. These run a whole cycle whose orders
# endpoint fails its vendor call -- the literal shape of the swallow #2009 left
# in place -- and require the cycle to fail on it.
# ---------------------------------------------------------------------------


class RecordingSyncStateRepo:
    """Bound to the three `TikTokSyncStateRepo` methods `_poll` calls.

    `record_outcomes` is declared here rather than left off: `_record_cycle`
    calls it inside a guarded `try`, so a double missing the method would make
    these tests pass while production logged `poll_cycle_outcome_record_failed`
    on every cycle. `test_the_sync_state_double_matches_the_real_repo` pins the
    shapes so the double cannot drift from what it stands in for.
    """

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.recorded: list[list[SyncOutcome]] = []

    async def load(self, shop_id: uuid.UUID) -> dict[str, Any]:
        return {}

    async def save(self, shop_id: uuid.UUID, sync_state: dict[str, Any]) -> None:
        self.saved.append(dict(sync_state))

    async def record_outcomes(self, shop_id: uuid.UUID, outcomes: Sequence[Any]) -> None:
        self.recorded.append(list(outcomes))


def test_the_sync_state_double_matches_the_real_repo():
    for name in ("load", "save", "record_outcomes"):
        real = inspect.signature(getattr(TikTokSyncStateRepo, name))
        double = inspect.signature(getattr(RecordingSyncStateRepo, name))
        assert list(real.parameters) == list(double.parameters), name


class TestAFailedVendorCallFailsTheCycle:
    @pytest.mark.asyncio
    async def test_a_cycle_whose_orders_fetch_failed_does_not_complete(
        self,
        session,
        cycle_credential,
        cycle_oauth_service,
        cycle_resources,
    ):
        """`sync_orders` swallows this error and returns; the CYCLE must not.

        This is the case #2009's PR body recorded as "residual gap, deliberate
        ... turning a fetch error into a cycle failure is #1950's structural
        work". Before this change `run_fujiwa_poll_cycle` returned normally
        here and the Celery task exited zero.
        """
        cycle_resources.orders.search_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )
        repo = RecordingSyncStateRepo()

        with pytest.raises(PollCycleFailedError) as excinfo:
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=cycle_oauth_service,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=no_handoff,
                resolve_credential=AsyncMock(return_value=cycle_credential),
                create_resources=lambda _cfg: cycle_resources,
                sync_state_repo=repo,
            )

        assert [failure.resource for failure in excinfo.value.failures] == ["orders"]

    @pytest.mark.asyncio
    async def test_the_verdict_is_recorded_before_the_cycle_fails(
        self,
        session,
        cycle_credential,
        cycle_oauth_service,
        cycle_resources,
    ):
        """Evidence first, exception second.

        Raising before the write would leave the one durable record of what
        failed unwritten -- which is the position this issue started from.
        """
        cycle_resources.orders.search_all.side_effect = TikTokSystemError(
            code=100006, message="System error"
        )
        repo = RecordingSyncStateRepo()

        with pytest.raises(PollCycleFailedError):
            await run_fujiwa_poll_cycle(
                session=session,
                config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
                oauth_service=cycle_oauth_service,
                rate_limiter=NeverExhaustedRateLimiter(),
                handoff_fn=no_handoff,
                resolve_credential=AsyncMock(return_value=cycle_credential),
                create_resources=lambda _cfg: cycle_resources,
                sync_state_repo=repo,
            )

        assert repo.recorded, "the cycle failed without recording a single outcome"
        by_resource = {outcome.resource: outcome for outcome in repo.recorded[-1]}
        assert by_resource["orders"].ok is False
        assert by_resource["orders"].error
        # Every step is accounted for, not only the one that failed -- an
        # endpoint missing from the record is an endpoint nobody can ask about.
        assert set(by_resource) == {"orders", "products", "returns", "inventory", "analytics"}

    @pytest.mark.asyncio
    async def test_a_clean_cycle_still_completes_and_records(
        self,
        session,
        cycle_credential,
        cycle_oauth_service,
        cycle_resources,
    ):
        """The verdict must not be a blanket refusal -- a working poll still polls."""
        repo = RecordingSyncStateRepo()

        await run_fujiwa_poll_cycle(
            session=session,
            config=FujiwaPollConfig(app_key=APP_KEY, app_secret=APP_SECRET),
            oauth_service=cycle_oauth_service,
            rate_limiter=NeverExhaustedRateLimiter(),
            handoff_fn=no_handoff,
            resolve_credential=AsyncMock(return_value=cycle_credential),
            create_resources=lambda _cfg: cycle_resources,
            sync_state_repo=repo,
        )

        assert all(outcome.ok for outcome in repo.recorded[-1])
