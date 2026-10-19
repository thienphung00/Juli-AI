"""P59 / D69: Search Inventory's 12019008 must not wedge the shop's sync.

Production (2026-10-19, release 98b36adf): ``bootstrap_shop``'s fast phase
failed every 15 minutes at the inventory step with ``[12019008] Invalid
Parameter. Parameter `product_ids` is invalid because must contain product IDs
accepted by this endpoint``. The vendor rejects the WHOLE page when any one id
in it is refused, ``sync_inventory`` re-raises (deliberately, #1948), so the
bootstrap never set ``fast_done_at`` and retried forever.

Behaviours under test:

- deleted / draft products are never sent; unknown or empty statuses are kept;
- a rejected page is bisected, the rejected ids are skipped and logged, every
  other id still syncs;
- the extra calls are bounded per step and drawn from their own rate-limiter
  bucket, so isolation never exhausts the step's own bucket;
- every OTHER vendor error still raises, and a step where not one call was
  accepted still raises (the #1948 shape);
- TikTok exceptions survive a pickle round-trip (Celery result backend).

All ids are synthetic.
"""

from __future__ import annotations

import json
import logging
import pickle
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from juli_backend.integrations.tiktok.client import (
    TikTokPaginationTimeoutError,
    TikTokPaginationTruncatedError,
)
from juli_backend.integrations.tiktok.constants import INVENTORY_SEARCH_PATH
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
    RateLimitError,
    TikTokAPIError,
    TransportGuardError,
    error_from_response,
)
from juli_backend.integrations.tiktok.resources.analytics import VideoPerformanceError
from juli_backend.workers.services.polling import orchestrate
from juli_backend.workers.services.polling.sync import (
    INVENTORY_BISECT_MAX_CALLS,
    INVENTORY_ISOLATE_RATE_KEY,
    INVENTORY_REJECTED_PRODUCT_IDS_CODE,
    inventory_searchable_status,
    sync_inventory,
)

SHOP = "shop-p59"
APP = "app-p59"


def _ids(count: int, prefix: str = "p") -> list[str]:
    return [f"{prefix}-{n:03d}" for n in range(count)]


def _rejection() -> TikTokAPIError:
    return TikTokAPIError(
        INVENTORY_REJECTED_PRODUCT_IDS_CODE,
        "Invalid Parameter. Parameter `product_ids` is invalid because must contain "
        "product IDs accepted by this endpoint.",
    )


class _VendorInventory:
    """Answers like Search Inventory: one sku per accepted id, whole-request 12019008."""

    def __init__(self, rejected: set[str] | None = None, *, error: Exception | None = None):
        self.rejected = set(rejected or ())
        self.error = error
        self.calls: list[list[str]] = []

    def search(self, *, product_ids: list[str], sku_ids: list[str] | None = None) -> dict:
        if not product_ids:
            raise ValueError("product_ids must be non-empty")
        self.calls.append(list(product_ids))
        if self.error is not None:
            raise self.error
        if self.rejected & set(product_ids):
            raise _rejection()
        return {
            "inventory": [
                {
                    "product_id": pid,
                    "skus": [
                        {
                            "id": f"sku-{pid}",
                            "total_available_quantity": 5,
                            "warehouse_inventory": [
                                {"available_quantity": 5, "warehouse_id": "wh-1"}
                            ],
                        }
                    ],
                }
                for pid in product_ids
            ]
        }


class _CountingLimiter:
    """The real ``RateLimiter`` arithmetic (INCR then compare), without Redis."""

    def __init__(self, *, preload: dict[str, int] | None = None) -> None:
        self.counts: dict[str, int] = dict(preload or {})

    def acquire(
        self, app_id: str, shop_id: str, endpoint: str, max_requests: int, window_seconds: int
    ) -> bool:
        self.counts[endpoint] = self.counts.get(endpoint, 0) + 1
        return self.counts[endpoint] <= max_requests

    def is_exhausted(self, app_id: str, shop_id: str, endpoint: str, max_requests: int) -> bool:
        return self.counts.get(endpoint, 0) >= max_requests

    def time_until_reset(self, app_id: str, shop_id: str, endpoint: str) -> int:
        return 0


async def _run(
    resource: _VendorInventory,
    product_ids: list[str],
    *,
    limiter: _CountingLimiter | None = None,
    page_size: int = 30,
) -> tuple[Any, list[str], dict[str, Any]]:
    handed: list[str] = []
    state: dict[str, Any] = {}

    async def handoff(channel: str, shop_key: str, value: bytes) -> None:
        handed.append(value.decode())

    async def list_ids() -> list[str]:
        return list(product_ids)

    outcome = await sync_inventory(
        resource=resource,
        rate_limiter=limiter or _CountingLimiter(),
        handoff_fn=handoff,
        app_id=APP,
        shop_id=SHOP,
        sync_state=state,
        list_product_ids=list_ids,
        page_size=page_size,
    )
    return outcome, handed, state


def _handed_products(handed: list[str]) -> set[str]:
    return {json.loads(row)["product_id"] for row in handed}


def _skipped_log_ids(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.product_id
        for record in caplog.records
        if record.getMessage() == "sync_inventory_product_skipped"
    ]


class TestStatusFilter:
    @pytest.mark.parametrize("status", ["DELETED", "DRAFT", "deleted", " Draft "])
    def test_deleted_and_draft_are_not_searchable(self, status: str) -> None:
        assert inventory_searchable_status(status) is False

    @pytest.mark.parametrize(
        "status",
        [
            "ACTIVATE",
            "PENDING",
            "FAILED",
            "SELLER_DEACTIVATED",
            "PLATFORM_DEACTIVATED",
            "FREEZE",
            "ACTIVE",
            "unknown",
            "",
            None,
        ],
    )
    def test_every_other_or_unknown_status_is_kept(self, status: str | None) -> None:
        assert inventory_searchable_status(status) is True

    @pytest.mark.asyncio
    async def test_product_id_source_drops_deleted_and_draft_only(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        rows = [
            SimpleNamespace(id=uuid.uuid4(), tiktok_product_id="p-live", status="ACTIVATE"),
            SimpleNamespace(id=uuid.uuid4(), tiktok_product_id="p-gone", status="DELETED"),
            SimpleNamespace(id=uuid.uuid4(), tiktok_product_id="p-draft", status="DRAFT"),
            SimpleNamespace(id=uuid.uuid4(), tiktok_product_id="p-frozen", status="FREEZE"),
            SimpleNamespace(id=uuid.uuid4(), tiktok_product_id="p-blank", status=""),
            SimpleNamespace(id=uuid.uuid4(), tiktok_product_id="", status="ACTIVATE"),
        ]

        class _Repo:
            def __init__(self, session: Any) -> None:
                pass

            async def list(self, shop_id: uuid.UUID, *, limit: int, after: Any) -> list[Any]:
                return rows if after is None else []

        monkeypatch.setattr(orchestrate, "ProductsRepo", _Repo)
        caplog.set_level(logging.INFO, logger=orchestrate.logger.name)

        session: Any = object()  # the fake repo never touches it
        ids = await orchestrate._synced_product_ids_fn(session, uuid.uuid4())()

        assert ids == ["p-live", "p-frozen", "p-blank"]
        [record] = [
            r
            for r in caplog.records
            if r.getMessage() == "sync_inventory_products_excluded_by_status"
        ]
        assert record.excluded == 2
        assert record.statuses == {"DELETED": 1, "DRAFT": 1}


class TestBisection:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_index", [0, 1, 14, 15, 29])
    async def test_isolates_one_rejected_id_in_a_page_of_30(
        self, bad_index: int, caplog: pytest.LogCaptureFixture
    ) -> None:
        ids = _ids(30)
        bad = ids[bad_index]
        resource = _VendorInventory({bad})
        caplog.set_level(logging.WARNING)

        outcome, handed, state = await _run(resource, ids)

        assert _handed_products(handed) == set(ids) - {bad}
        assert _skipped_log_ids(caplog) == [bad]
        assert outcome.skipped_product_ids == 1
        assert outcome.ok
        assert outcome.persisted == 29
        assert "inventory_last_sync_at" in state
        # 1 primary call + at most the per-step isolation budget.
        assert len(resource.calls) <= 1 + INVENTORY_BISECT_MAX_CALLS
        # Each accepted id was fetched exactly once -- no row handed off twice.
        assert len(handed) == 29

    @pytest.mark.asyncio
    async def test_every_position_of_one_rejected_id_resolves_within_budget(self) -> None:
        ids = _ids(30)
        for bad in ids:
            resource = _VendorInventory({bad})
            outcome, handed, _ = await _run(resource, ids)
            assert outcome.skipped_product_ids == 1, bad
            assert len(handed) == 29, bad

    @pytest.mark.asyncio
    async def test_mixed_pages_only_the_bad_page_is_bisected(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        ids = _ids(75)  # pages of 30, 30, 15
        bad = ids[40]  # in the second page
        resource = _VendorInventory({bad})
        caplog.set_level(logging.WARNING)

        outcome, handed, _ = await _run(resource, ids)

        assert _handed_products(handed) == set(ids) - {bad}
        assert _skipped_log_ids(caplog) == [bad]
        assert resource.calls[0] == ids[0:30]
        assert resource.calls[-1] == ids[60:75]
        assert outcome.skipped_product_ids == 1
        assert outcome.ok

    @pytest.mark.asyncio
    async def test_all_rejected_page_beside_good_pages_is_skipped_not_raised(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        good = _ids(30, "good")
        bad = _ids(30, "bad")
        resource = _VendorInventory(set(bad))
        caplog.set_level(logging.WARNING)

        outcome, handed, state = await _run(resource, good + bad)

        assert _handed_products(handed) == set(good)
        # 1 + 1 primary calls + the bounded isolation; never the 58 a full resolve needs.
        assert len(resource.calls) == 2 + INVENTORY_BISECT_MAX_CALLS
        assert outcome.skipped_product_ids == 30
        assert outcome.ok
        assert "inventory_last_sync_at" in state
        messages = [r.getMessage() for r in caplog.records]
        assert "sync_inventory_bisect_budget_exhausted" in messages
        assert "sync_inventory_batch_unresolved" in messages

    @pytest.mark.asyncio
    async def test_every_id_rejected_still_raises_the_1948_way(self) -> None:
        """Nothing accepted at all is the #1948 shape, not 'a few bad ids'."""
        ids = _ids(30)
        resource = _VendorInventory(set(ids))

        with pytest.raises(TikTokAPIError) as excinfo:
            await _run(resource, ids)

        assert excinfo.value.code == INVENTORY_REJECTED_PRODUCT_IDS_CODE
        assert len(resource.calls) == 1 + INVENTORY_BISECT_MAX_CALLS

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error",
        [
            TikTokAPIError(36009004, "some other invalid parameter"),
            RateLimitError(100005, "throttled"),
            AuthenticationError(100002, "expired"),
        ],
    )
    async def test_any_other_vendor_error_still_raises_without_bisecting(
        self, error: TikTokAPIError
    ) -> None:
        ids = _ids(30)
        resource = _VendorInventory(error=error)

        with pytest.raises(type(error)):
            await _run(resource, ids)

        assert resource.calls == [ids]

    @pytest.mark.asyncio
    async def test_other_error_during_bisection_still_raises(self) -> None:
        ids = _ids(30)

        class _FailsOnSecondCall(_VendorInventory):
            def search(self, *, product_ids: list[str], sku_ids: list[str] | None = None) -> dict:
                if len(self.calls) == 1:
                    self.calls.append(list(product_ids))
                    raise RateLimitError(100005, "throttled")
                return super().search(product_ids=product_ids, sku_ids=sku_ids)

        resource = _FailsOnSecondCall({ids[3]})

        with pytest.raises(RateLimitError):
            await _run(resource, ids)

        assert len(resource.calls) == 2


class TestRateLimitInteraction:
    @pytest.mark.asyncio
    async def test_isolation_uses_its_own_bucket_and_leaves_the_step_bucket_alone(self) -> None:
        ids = _ids(30)
        limiter = _CountingLimiter()
        resource = _VendorInventory({ids[0]})  # worst-case position: 10 extra calls

        outcome, handed, _ = await _run(resource, ids, limiter=limiter)

        assert len(handed) == 29
        assert limiter.counts[INVENTORY_SEARCH_PATH] == 1  # the step's own acquire only
        assert limiter.counts[INVENTORY_ISOLATE_RATE_KEY] == INVENTORY_BISECT_MAX_CALLS
        assert outcome.skipped_product_ids == 1

    @pytest.mark.asyncio
    async def test_exhausted_isolation_bucket_skips_the_page_and_stops_asking(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        good = _ids(30, "good")
        bad_page = _ids(30, "mix")
        limiter = _CountingLimiter(preload={INVENTORY_ISOLATE_RATE_KEY: 10})
        resource = _VendorInventory({bad_page[7]})
        caplog.set_level(logging.WARNING)

        outcome, handed, _ = await _run(resource, good + bad_page, limiter=limiter)

        # No extra vendor calls at all, and exactly ONE refused acquire: a
        # refused acquire still INCRs the real Redis counter, so it must not repeat.
        assert len(resource.calls) == 2
        assert limiter.counts[INVENTORY_ISOLATE_RATE_KEY] == 11
        assert _handed_products(handed) == set(good)
        assert outcome.skipped_product_ids == 30
        assert outcome.ok
        [exhausted] = [
            r for r in caplog.records if r.getMessage() == "sync_inventory_bisect_budget_exhausted"
        ]
        assert exhausted.reason == "rate_limited"

    @pytest.mark.asyncio
    async def test_step_bucket_refusal_still_skips_before_any_call(self) -> None:
        limiter = _CountingLimiter(preload={INVENTORY_SEARCH_PATH: 10})
        resource = _VendorInventory()

        outcome, handed, _ = await _run(resource, _ids(3), limiter=limiter)

        assert outcome.skipped
        assert resource.calls == []
        assert handed == []


class TestSkipLogShape:
    @pytest.mark.asyncio
    async def test_skip_log_carries_only_shop_product_and_code(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        ids = _ids(4)
        caplog.set_level(logging.WARNING)

        await _run(_VendorInventory({ids[2]}), ids)

        [record] = [r for r in caplog.records if r.getMessage() == "sync_inventory_product_skipped"]
        assert record.shop_id == SHOP
        assert record.product_id == ids[2]
        assert record.error_code == INVENTORY_REJECTED_PRODUCT_IDS_CODE
        assert not hasattr(record, "url")
        assert not hasattr(record, "access_token")


class TestExceptionsPickle:
    @pytest.mark.parametrize(
        "exc",
        [
            TikTokAPIError(12019008, "Invalid Parameter", request_id="req-1"),
            RateLimitError(100005, "throttled"),
            VideoPerformanceError(code=0, message="video v-1 missing from batch response"),
            TransportGuardError(capability="cap", method="POST", path="/x", message="blocked"),
            TikTokPaginationTruncatedError(path="/x", pages=4, items=40, max_pages=4),
            TikTokPaginationTimeoutError(
                path="/x", pages=2, items=20, budget_seconds=30.0, elapsed_seconds=31.5
            ),
        ],
        ids=lambda exc: type(exc).__name__,
    )
    def test_round_trips(self, exc: BaseException) -> None:
        restored = pickle.loads(pickle.dumps(exc))

        assert type(restored) is type(exc)
        assert str(restored) == str(exc)
        assert restored.__dict__ == exc.__dict__

    def test_error_from_response_result_round_trips(self) -> None:
        exc = error_from_response({"code": 100002, "message": "expired", "request_id": "r"})
        assert exc is not None

        restored = pickle.loads(pickle.dumps(exc))

        assert isinstance(restored, AuthenticationError)
        assert (restored.code, restored.message, restored.request_id) == (100002, "expired", "r")
