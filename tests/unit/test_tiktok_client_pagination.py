"""Pagination behavior for TikTokClient.get_all_pages."""

import os
from unittest.mock import MagicMock, patch

import pytest

from juli_backend.integrations.tiktok.client import TikTokClient


@pytest.fixture
def client():
    c = TikTokClient(
        app_key="key",
        app_secret="secret",
        access_token="token",
        shop_cipher="cipher",
    )
    c.post = MagicMock()
    c.get = MagicMock()
    return c


class TestGetAllPages:
    def test_reads_next_page_token_from_response(self, client):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "next_page_token": "cursor-2"},
            {"orders": [{"id": "o2"}]},
        ]

        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={"order_status": "AWAITING_SHIPMENT"},
            items_key="orders",
            page_size=25,
        )

        assert [o["id"] for o in result] == ["o1", "o2"]
        assert client.post.call_count == 2
        second_params = client.post.call_args_list[1][1]["params"]
        assert second_params["page_token"] == "cursor-2"
        assert second_params["page_size"] == "25"

    def test_page_size_and_page_token_are_query_params_not_body(self, client):
        client.post.return_value = {"orders": [{"id": "o1"}]}

        client.get_all_pages(
            path="/order/202309/orders/search",
            body={"order_status": "UNPAID"},
            items_key="orders",
            page_size=10,
        )

        _, kwargs = client.post.call_args
        assert kwargs["body"] == {"order_status": "UNPAID"}
        assert "page_size" not in kwargs["body"]
        assert kwargs["params"]["page_size"] == "10"

    def test_falls_back_to_page_token_when_next_page_token_missing(self, client):
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "page_token": "legacy-cursor"},
            {"orders": [{"id": "o2"}]},
        ]

        result = client.get_all_pages(
            path="/api/orders/search",
            body={},
            items_key="orders",
        )

        assert len(result) == 2
        assert client.post.call_args_list[1][1]["params"]["page_token"] == "legacy-cursor"

    def test_stops_when_no_cursor_returned(self, client):
        client.post.return_value = {"orders": [{"id": "o1"}]}

        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={},
            items_key="orders",
        )

        assert result == [{"id": "o1"}]
        client.post.assert_called_once()

    def test_unbounded_loop_with_echoed_cursor_old_code(self, client, caplog):
        """Demonstrates the bug: when API echoes back the page_token, old code loops forever.

        This test proves the old code would loop forever without a fix.
        The fix catches this via non-advancing cursor detection.
        """

        # Simulate an API that echoes the page_token back, which would cause
        # an infinite loop in the old code
        def echo_cursor_response(path, body, params):
            cursor = params.get("page_token", "cursor-1")
            return {"orders": [{"id": f"o-{cursor}"}], "page_token": cursor}

        client.post.side_effect = echo_cursor_response

        # Without a fix, this would loop forever. With the fix, it should
        # terminate via the non-advancing cursor detection (when the returned
        # token equals the previously sent token).
        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={},
            items_key="orders",
        )

        # Should stop after 2 pages (first has cursor-1, second returns cursor-1 again)
        assert len(result) == 2
        # Should have called post 2 times (stops when cursor doesn't advance)
        assert client.post.call_count == 2

        # Should log warning about non-advancing cursor
        assert any(
            "non_advancing_cursor" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

    def test_max_pages_cap_enforced_post(self, client, caplog):
        """Test that get_all_pages stops at max page count and logs warning."""

        def infinite_cursor_response(path, body, params):
            cursor = params.get("page_token", "cursor-0")
            next_cursor = f"cursor-{int(cursor.split('-')[1]) + 1}"
            return {"orders": [{"id": f"o-{cursor}"}], "next_page_token": next_cursor}

        client.post.side_effect = infinite_cursor_response

        with patch.dict(os.environ, {"TIKTOK_MAX_PAGES": "5"}):
            result = client.get_all_pages(
                path="/order/202309/orders/search",
                body={},
                items_key="orders",
                page_size=10,
            )

        # Should have exactly 5 pages
        assert len(result) == 5
        assert client.post.call_count == 5

        # Should log a warning about hitting max pages
        assert any(
            "tiktok_pagination_max_pages_reached" in record.message
            or "pagination_bounded" in record.message
            or "max_pages" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

    def test_non_advancing_cursor_stops_early_post(self, client, caplog):
        """Test that get_all_pages stops when cursor doesn't advance."""
        # Cursor that doesn't advance: always returns the same token
        client.post.side_effect = [
            {"orders": [{"id": "o1"}], "next_page_token": "static-cursor"},
            {"orders": [{"id": "o2"}], "next_page_token": "static-cursor"},  # Same cursor
            {"orders": [{"id": "o3"}], "next_page_token": "static-cursor"},  # Still same
        ]

        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={},
            items_key="orders",
        )

        # Should stop early when cursor doesn't advance (after 2nd call)
        assert client.post.call_count == 2
        assert len(result) == 2

        # Should log warning about non-advancing cursor
        assert any(
            "non_advancing_cursor" in record.message.lower()
            or "cursor_not_advancing" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

    def test_normal_pagination_still_works_post(self, client):
        """Regression test: normal multi-page pagination must still work."""
        client.post.side_effect = [
            {"orders": [{"id": "o1"}, {"id": "o2"}], "next_page_token": "cursor-2"},
            {"orders": [{"id": "o3"}, {"id": "o4"}], "next_page_token": "cursor-3"},
            {"orders": [{"id": "o5"}]},  # No cursor = last page
        ]

        result = client.get_all_pages(
            path="/order/202309/orders/search",
            body={},
            items_key="orders",
        )

        assert len(result) == 5
        assert [o["id"] for o in result] == ["o1", "o2", "o3", "o4", "o5"]
        assert client.post.call_count == 3


class TestGetAllPagesGet:
    @pytest.fixture
    def client(self):
        c = TikTokClient(
            app_key="key",
            app_secret="secret",
            access_token="token",
            shop_cipher="cipher",
        )
        c.get = MagicMock()
        return c

    def test_max_pages_cap_enforced_get(self, client, caplog):
        """Test that get_all_pages_get stops at max page count and logs warning."""

        def infinite_cursor_response(path, params):
            cursor = params.get("page_token", "cursor-0")
            next_cursor = f"cursor-{int(cursor.split('-')[1]) + 1}"
            return {"items": [{"id": f"i-{cursor}"}], "next_page_token": next_cursor}

        client.get.side_effect = infinite_cursor_response

        with patch.dict(os.environ, {"TIKTOK_MAX_PAGES": "4"}):
            result = client.get_all_pages_get(
                path="/api/v2/data",
                params={"filter": "test"},
                items_key="items",
                page_size=20,
            )

        # Should have exactly 4 pages
        assert len(result) == 4
        assert client.get.call_count == 4

        # Should log a warning about hitting max pages
        assert any(
            "tiktok_pagination_max_pages_reached" in record.message
            or "pagination_bounded" in record.message
            or "max_pages" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

    def test_non_advancing_cursor_stops_early_get(self, client, caplog):
        """Test that get_all_pages_get stops when cursor doesn't advance."""
        client.get.side_effect = [
            {"items": [{"id": "i1"}], "next_page_token": "static-cursor"},
            {"items": [{"id": "i2"}], "next_page_token": "static-cursor"},  # Same cursor
        ]

        result = client.get_all_pages_get(
            path="/api/v2/data",
            params={},
            items_key="items",
        )

        # Should stop early when cursor doesn't advance
        assert client.get.call_count == 2
        assert len(result) == 2

        # Should log warning about non-advancing cursor
        assert any(
            "non_advancing_cursor" in record.message.lower()
            or "cursor_not_advancing" in record.message.lower()
            for record in caplog.records
            if record.levelname == "WARNING"
        )

    def test_normal_pagination_still_works_get(self, client):
        """Regression test: normal multi-page pagination must still work for GET."""
        client.get.side_effect = [
            {"items": [{"id": "i1"}, {"id": "i2"}], "next_page_token": "cursor-2"},
            {"items": [{"id": "i3"}, {"id": "i4"}], "next_page_token": "cursor-3"},
            {"items": [{"id": "i5"}]},  # No cursor = last page
        ]

        result = client.get_all_pages_get(
            path="/api/v2/data",
            params={"filter": "active"},
            items_key="items",
        )

        assert len(result) == 5
        assert [i["id"] for i in result] == ["i1", "i2", "i3", "i4", "i5"]
        assert client.get.call_count == 3
