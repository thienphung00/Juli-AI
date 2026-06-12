"""ProductsResource — versioned product paths."""

from unittest.mock import MagicMock

import pytest

from src.modules.catalog.domain.integrations.tiktok.constants import (
    PRODUCT_SEARCH_PATH,
    product_detail_path,
)
from src.modules.catalog.domain.integrations.tiktok.resources.products import ProductsResource


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post.return_value = {"products": []}
    client.get.return_value = {}
    client.get_all_pages.return_value = []
    return client


class TestProductsResource:
    def test_search_uses_versioned_path_and_query_pagination(self, mock_client):
        products = ProductsResource(mock_client)

        products.search(status="ON_SALE", page_size=20, page_token="tok")

        mock_client.post.assert_called_once_with(
            PRODUCT_SEARCH_PATH,
            body={"status": "ON_SALE"},
            params={"page_size": "20", "page_token": "tok"},
        )

    def test_search_all_uses_versioned_path(self, mock_client):
        products = ProductsResource(mock_client)

        products.search_all(status="ALL", update_time_from=1_700_000_000)

        kwargs = mock_client.get_all_pages.call_args[1]
        assert kwargs["path"] == PRODUCT_SEARCH_PATH
        assert kwargs["body"] == {
            "status": "ALL",
            "update_time_ge": 1_700_000_000,
        }

    def test_get_details_uses_path_param(self, mock_client):
        products = ProductsResource(mock_client)

        products.get_details("prod-99")

        mock_client.get.assert_called_once_with(product_detail_path("prod-99"))
