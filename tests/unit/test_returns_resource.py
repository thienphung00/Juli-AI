"""ReturnsResource — versioned return/refund paths."""

from unittest.mock import MagicMock

import pytest

from backend.integrations.catalog.domain.integrations.tiktok.constants import (
    CANCELLATION_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)
from backend.integrations.catalog.domain.integrations.tiktok.resources.returns import ReturnsResource


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post.return_value = {"return_orders": []}
    client.get_all_pages.return_value = []
    return client


class TestReturnsResource:
    def test_search_returns_uses_official_schema(self, mock_client):
        returns = ReturnsResource(mock_client)

        returns.search_returns(
            return_status="RETURN_OR_REFUND_REQUEST_PENDING",
            update_time_from=1_700_000_000,
            update_time_to=1_700_010_000,
            page_size=25,
        )

        mock_client.post.assert_called_once_with(
            RETURN_SEARCH_PATH,
            body={
                "return_status": "RETURN_OR_REFUND_REQUEST_PENDING",
                "update_time_ge": 1_700_000_000,
                "update_time_lt": 1_700_010_000,
            },
            params={"page_size": "25"},
        )

    def test_search_returns_all_paginates_return_orders(self, mock_client):
        returns = ReturnsResource(mock_client)

        returns.search_returns_all(update_time_from=1_700_000_000)

        kwargs = mock_client.get_all_pages.call_args[1]
        assert kwargs["path"] == RETURN_SEARCH_PATH
        assert kwargs["items_key"] == "return_orders"

    def test_search_cancellations_uses_versioned_path(self, mock_client):
        returns = ReturnsResource(mock_client)

        returns.search_cancellations(update_time_from=1_700_000_000, page_size=10)

        mock_client.post.assert_called_once_with(
            CANCELLATION_SEARCH_PATH,
            body={"update_time_ge": 1_700_000_000},
            params={"page_size": "10"},
        )
