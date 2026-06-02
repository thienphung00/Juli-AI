"""TDD tests for new TikTok resource modules (creators, livestreams, settlements).

Issue #25 — Integrations/TikTok: Creator, livestream, settlement resources.

AC1: CreatorsResource implements list/get with cursor-based pagination and respects rate limiter
AC2: LivestreamsResource implements list/get returning session metrics
AC3: SettlementsResource implements list with date-range filtering and returns net amounts
"""

import pytest
from unittest.mock import MagicMock

from src.modules.catalog.domain.integrations.tiktok.resources.creators import CreatorsResource
from src.modules.catalog.domain.integrations.tiktok.resources.livestreams import LivestreamsResource
from src.modules.catalog.domain.integrations.tiktok.resources.settlements import SettlementsResource


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post.return_value = {}
    client.get.return_value = {}
    client.get_all_pages.return_value = []
    return client


class TestCreatorsResourceListPaginated:
    """AC1: CreatorsResource.list with cursor-based pagination."""

    def test_list_posts_to_correct_path(self, mock_client):
        creators = CreatorsResource(mock_client)
        creators.list()

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == "/api/affiliate/creators/search"

    def test_list_passes_page_size(self, mock_client):
        creators = CreatorsResource(mock_client)
        creators.list(page_size=20)

        body = mock_client.post.call_args[1]["body"]
        assert body["page_size"] == 20

    def test_list_passes_page_token_for_cursor_pagination(self, mock_client):
        creators = CreatorsResource(mock_client)
        creators.list(page_token="next_cursor_abc")

        body = mock_client.post.call_args[1]["body"]
        assert body["page_token"] == "next_cursor_abc"

    def test_list_omits_none_filters(self, mock_client):
        creators = CreatorsResource(mock_client)
        creators.list()

        body = mock_client.post.call_args[1]["body"]
        assert "page_token" not in body
        assert "page_size" not in body

    def test_list_all_uses_get_all_pages(self, mock_client):
        mock_client.get_all_pages.return_value = [
            {"creator_id": "c1", "nickname": "Creator One"},
            {"creator_id": "c2", "nickname": "Creator Two"},
        ]
        creators = CreatorsResource(mock_client)

        result = creators.list_all(page_size=25)

        mock_client.get_all_pages.assert_called_once()
        call_args = mock_client.get_all_pages.call_args
        assert call_args[1]["path"] == "/api/affiliate/creators/search"
        assert call_args[1]["items_key"] == "creators"
        assert call_args[1]["page_size"] == 25
        assert result == [
            {"creator_id": "c1", "nickname": "Creator One"},
            {"creator_id": "c2", "nickname": "Creator Two"},
        ]

    def test_get_fetches_single_creator(self, mock_client):
        mock_client.get.return_value = {
            "creator_id": "c1",
            "nickname": "Top Seller",
            "follower_count": 50000,
        }
        creators = CreatorsResource(mock_client)

        result = creators.get("c1")

        mock_client.get.assert_called_once()
        assert mock_client.get.call_args[0][0] == "/api/affiliate/creators/details"
        params = mock_client.get.call_args[1]["params"]
        assert params["creator_id"] == "c1"
        assert result["nickname"] == "Top Seller"


class TestLivestreamsResourceGetSessionMetrics:
    """AC2: LivestreamsResource.list/get returning session metrics."""

    def test_list_posts_to_correct_path(self, mock_client):
        livestreams = LivestreamsResource(mock_client)
        livestreams.list()

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == "/api/affiliate/livestreams/search"

    def test_list_passes_creator_id_filter(self, mock_client):
        livestreams = LivestreamsResource(mock_client)
        livestreams.list(creator_id="c1")

        body = mock_client.post.call_args[1]["body"]
        assert body["creator_id"] == "c1"

    def test_list_passes_time_range_filter(self, mock_client):
        livestreams = LivestreamsResource(mock_client)
        livestreams.list(start_time=1700000000, end_time=1700100000)

        body = mock_client.post.call_args[1]["body"]
        assert body["start_time"] == 1700000000
        assert body["end_time"] == 1700100000

    def test_list_omits_none_filters(self, mock_client):
        livestreams = LivestreamsResource(mock_client)
        livestreams.list()

        body = mock_client.post.call_args[1]["body"]
        assert "creator_id" not in body
        assert "start_time" not in body

    def test_get_returns_session_metrics(self, mock_client):
        mock_client.get.return_value = {
            "livestream_id": "ls1",
            "duration_seconds": 3600,
            "total_viewers": 1200,
            "peak_concurrent_viewers": 350,
            "orders_placed": 45,
        }
        livestreams = LivestreamsResource(mock_client)

        result = livestreams.get("ls1")

        mock_client.get.assert_called_once()
        assert mock_client.get.call_args[0][0] == "/api/affiliate/livestreams/details"
        params = mock_client.get.call_args[1]["params"]
        assert params["livestream_id"] == "ls1"
        assert result["duration_seconds"] == 3600
        assert result["total_viewers"] == 1200
        assert result["peak_concurrent_viewers"] == 350
        assert result["orders_placed"] == 45

    def test_list_all_paginates(self, mock_client):
        mock_client.get_all_pages.return_value = [
            {"livestream_id": "ls1", "duration_seconds": 1800},
        ]
        livestreams = LivestreamsResource(mock_client)

        livestreams.list_all(creator_id="c1")

        mock_client.get_all_pages.assert_called_once()
        call_args = mock_client.get_all_pages.call_args
        assert call_args[1]["path"] == "/api/affiliate/livestreams/search"
        assert call_args[1]["items_key"] == "livestreams"
        assert call_args[1]["body"]["creator_id"] == "c1"


class TestSettlementsResourceFilterByDateRange:
    """AC3: SettlementsResource.list with date-range filtering and net amounts."""

    def test_list_posts_to_correct_path(self, mock_client):
        settlements = SettlementsResource(mock_client)
        settlements.list()

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == "/api/finance/settlements/search"

    def test_list_filters_by_date_range(self, mock_client):
        settlements = SettlementsResource(mock_client)
        settlements.list(settle_time_from=1700000000, settle_time_to=1700100000)

        body = mock_client.post.call_args[1]["body"]
        assert body["settle_time_from"] == 1700000000
        assert body["settle_time_to"] == 1700100000

    def test_list_omits_none_filters(self, mock_client):
        settlements = SettlementsResource(mock_client)
        settlements.list()

        body = mock_client.post.call_args[1]["body"]
        assert "settle_time_from" not in body
        assert "settle_time_to" not in body

    def test_list_passes_page_size(self, mock_client):
        settlements = SettlementsResource(mock_client)
        settlements.list(page_size=10)

        body = mock_client.post.call_args[1]["body"]
        assert body["page_size"] == 10

    def test_list_returns_settlement_data_with_net_amounts(self, mock_client):
        mock_client.post.return_value = {
            "settlements": [
                {
                    "settlement_id": "s1",
                    "gross_amount": "100.00",
                    "platform_fee": "5.00",
                    "shipping_fee": "10.00",
                    "net_amount": "85.00",
                    "status": "CONFIRMED",
                }
            ],
            "total_count": 1,
        }
        settlements = SettlementsResource(mock_client)

        result = settlements.list(settle_time_from=1700000000)

        assert result["settlements"][0]["net_amount"] == "85.00"
        assert result["settlements"][0]["status"] == "CONFIRMED"

    def test_list_all_paginates(self, mock_client):
        mock_client.get_all_pages.return_value = [
            {"settlement_id": "s1", "net_amount": "85.00"},
            {"settlement_id": "s2", "net_amount": "120.00"},
        ]
        settlements = SettlementsResource(mock_client)

        settlements.list_all(settle_time_from=1700000000, settle_time_to=1700100000)

        mock_client.get_all_pages.assert_called_once()
        call_args = mock_client.get_all_pages.call_args
        assert call_args[1]["path"] == "/api/finance/settlements/search"
        assert call_args[1]["items_key"] == "settlements"
        assert call_args[1]["body"]["settle_time_from"] == 1700000000
        assert call_args[1]["body"]["settle_time_to"] == 1700100000
