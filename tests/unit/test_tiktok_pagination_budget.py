"""Cold-start backfill budget vs incremental page cap, and fetch progress (#1969).

The 20-page cap is right for a routine incremental poll and wrong for the
onboarding's first read: it silently truncated a cold-start backfill with a
warning nobody reads. These tests pin the split, the failure-not-warning
verdict during a backfill, the per-page progress record, and the wall-clock
budget that bounds a paginated fetch between pages.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok import client as client_module
from juli_backend.integrations.tiktok.client import (
    TikTokClient,
    TikTokPaginationTimeoutError,
    TikTokPaginationTruncatedError,
    pagination_scope,
)

ORDERS_PATH = "/order/202309/orders/search"


@pytest.fixture
def client() -> TikTokClient:
    c = TikTokClient(
        app_key="key",
        app_secret="secret",
        access_token="token",
        shop_cipher="cipher",
    )
    c.post = MagicMock()
    c.get = MagicMock()
    return c


def _endless_pages(items_key: str):
    """A vendor that always offers another cursor -- the shape the cap exists for."""
    counter = {"n": 0}

    def _page(*_args, **_kwargs) -> dict:
        counter["n"] += 1
        return {
            items_key: [{"id": f"x{counter['n']}"}],
            "next_page_token": f"cursor-{counter['n']}",
            "total_count": 100_000,
        }

    return _page


class TestIncrementalCapUnchanged:
    def test_incremental_fetch_still_truncates_at_twenty_pages_with_a_warning(self, client, caplog):
        client.post.side_effect = _endless_pages("orders")

        with caplog.at_level(logging.WARNING, logger=client_module.__name__):
            items = client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert len(items) == 20
        assert "tiktok_pagination_max_pages_reached" in caplog.text

    def test_incremental_cap_is_the_default_when_no_scope_is_open(self, client):
        client.post.side_effect = _endless_pages("orders")

        items = client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert len(items) == 20


class TestBackfillBudget:
    def test_backfill_gets_a_larger_budget_than_the_incremental_cap(self, client):
        client.post.side_effect = _endless_pages("orders")

        with pytest.raises(TikTokPaginationTruncatedError) as excinfo:
            with pagination_scope(backfill=True):
                client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        # Far past the incremental cap: the backfill budget is a separate number.
        assert excinfo.value.pages > 20
        assert excinfo.value.pages == client_module.backfill_max_pages()

    def test_backfill_truncation_is_a_failure_not_a_warning(self, client, monkeypatch):
        monkeypatch.setenv("TIKTOK_BACKFILL_MAX_PAGES", "3")
        client.post.side_effect = _endless_pages("orders")

        with pytest.raises(TikTokPaginationTruncatedError) as excinfo:
            with pagination_scope(backfill=True):
                client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        err = excinfo.value
        assert err.path == ORDERS_PATH
        assert err.pages == 3
        assert err.items == 3
        assert err.total_count == 100_000

    def test_a_backfill_that_completes_inside_its_budget_does_not_raise(self, client):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "next_page_token": "c2"},
            {"orders": [{"id": "o2"}]},
        ]

        with pagination_scope(backfill=True) as scope:
            items = client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert [o["id"] for o in items] == ["o1", "o2"]
        assert scope.truncated is False
        assert scope.pages == 2
        assert scope.items == 2

    def test_get_paginator_honours_the_backfill_budget_too(self, client, monkeypatch):
        monkeypatch.setenv("TIKTOK_BACKFILL_MAX_PAGES", "2")
        client.get.side_effect = _endless_pages("skus")

        with pytest.raises(TikTokPaginationTruncatedError):
            with pagination_scope(backfill=True):
                client.get_all_pages_get(path="/analytics/skus", params={}, items_key="skus")


class TestScopeReportsProgress:
    def test_scope_counts_pages_and_items_for_the_caller(self, client):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}, {"id": "o2"}], "next_page_token": "c2"},
            {"orders": [{"id": "o3"}]},
        ]

        with pagination_scope() as scope:
            client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert scope.pages == 2
        assert scope.items == 3

    def test_every_page_emits_a_progress_record(self, client, caplog):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "next_page_token": "c2"},
            {"orders": [{"id": "o2"}]},
        ]

        with caplog.at_level(logging.INFO, logger=client_module.__name__):
            client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        pages = [r for r in caplog.records if r.message == "tiktok_pagination_page"]
        assert [r.page for r in pages] == [1, 2]
        assert [r.items_total for r in pages] == [1, 2]
        assert all(r.path == ORDERS_PATH for r in pages)

    def test_get_paginator_emits_a_summary_too(self, client, caplog):
        client.get.return_value = {"skus": [{"id": "s1"}]}

        with caplog.at_level(logging.INFO, logger=client_module.__name__):
            client.get_all_pages_get(path="/analytics/skus", params={}, items_key="skus")

        assert any(r.message == "tiktok_pagination_summary" for r in caplog.records)


class TestFetchWallClockBudget:
    def test_a_fetch_that_outruns_its_budget_raises_between_pages(self, client):
        # Clock injected, never patched: the assertion is about the budget rule,
        # not about how long anything really took.
        ticks = [0.0, 0.0, 5.0, 61.0]

        def clock() -> float:
            return ticks.pop(0) if len(ticks) > 1 else ticks[0]

        client.post.side_effect = _endless_pages("orders")

        with pytest.raises(TikTokPaginationTimeoutError) as excinfo:
            with pagination_scope(budget_seconds=60.0, clock=clock):
                client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert excinfo.value.budget_seconds == 60.0
        assert excinfo.value.path == ORDERS_PATH
        assert excinfo.value.pages >= 1

    def test_a_fetch_inside_its_budget_is_untouched(self, client):
        client.post.side_effect = [{"orders": [{"id": "o1"}]}]

        with pagination_scope(budget_seconds=600.0):
            items = client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert len(items) == 1


class TestNestedScopesComposeByMinimum:
    """#1969 review: the cycle budget and the fetch budget used to ADD.

    `orchestrate.py` opens an outer scope carrying the cycle's remaining wall
    clock. Without the cap below, a 1800s cycle could still start a 600s fetch
    at 1799s — a ~40-minute composed worst case, which is the duration this
    issue was filed for.
    """

    def test_an_inner_scope_cannot_outlive_its_enclosing_scope(self):
        with pagination_scope(budget_seconds=30.0):
            with pagination_scope(backfill=True) as inner:
                assert inner.budget_seconds == 30.0

    def test_an_inner_scope_may_be_stricter_than_its_enclosing_scope(self):
        with pagination_scope(budget_seconds=300.0):
            with pagination_scope(budget_seconds=5.0) as inner:
                assert inner.budget_seconds == 5.0

    def test_an_unnested_scope_takes_the_default_fetch_budget(self):
        with pagination_scope() as scope:
            assert scope.budget_seconds == client_module.default_fetch_budget_seconds()

    def test_the_cap_is_enforced_at_fetch_time_not_just_recorded(self, client):
        ticks = [0.0, 0.0, 1.0, 11.0]

        def clock() -> float:
            return ticks.pop(0) if len(ticks) > 1 else ticks[0]

        client.post.side_effect = _endless_pages("orders")

        # Enclosing budget 10s; the inner scope asks for the 600s default and
        # must still be stopped at 10.
        with pagination_scope(budget_seconds=10.0):
            with pytest.raises(TikTokPaginationTimeoutError) as excinfo:
                with pagination_scope(clock=clock):
                    client.get_all_pages(path=ORDERS_PATH, body={}, items_key="orders")

        assert excinfo.value.budget_seconds == 10.0
