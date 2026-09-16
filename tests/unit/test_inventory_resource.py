"""InventoryResource — Search Inventory request body (#1948).

The defect this issue exists to close lived in ONE line: the Search Inventory
body carried ``sku_ids`` and never ``product_ids``, which the endpoint
requires, so every call failed vendor-side with ``[12019008] Invalid
Parameter`` and ``inventory_items`` took zero rows in the lifetime of the
production database.

Every other test of that fix reaches this resource only through a
hand-written double, so none of them can see the body this class actually
posts: reverting ``"product_ids"`` out of the dict below, while keeping the
keyword argument in the signature, would leave the rest of the suite green.
This module is the only thing that reads the wire body, so it is the only
thing that can fail on the original defect.
"""

from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.constants import INVENTORY_SEARCH_PATH
from juli_backend.integrations.tiktok.resources.inventory import InventoryResource


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.post.return_value = {"code": 0, "data": {"inventory": []}}
    return client


class TestInventoryResourceSearch:
    def test_search_sends_product_ids_in_the_request_body(self, mock_client):
        InventoryResource(mock_client).search(product_ids=["prod-1", "prod-2"])

        mock_client.post.assert_called_once()
        assert mock_client.post.call_args[0][0] == INVENTORY_SEARCH_PATH
        assert mock_client.post.call_args[1]["body"] == {"product_ids": ["prod-1", "prod-2"]}

    def test_search_sends_both_ids_when_both_are_supplied(self, mock_client):
        InventoryResource(mock_client).search(product_ids=["prod-1"], sku_ids=["sku-1"])

        assert mock_client.post.call_args[1]["body"] == {
            "product_ids": ["prod-1"],
            "sku_ids": ["sku-1"],
        }

    def test_search_omits_absent_ids_rather_than_sending_null(self, mock_client):
        """#1990's caller still searches by ``sku_ids`` alone; it must not
        start posting ``"product_ids": null``, which is a different request
        from one that omits the field."""
        InventoryResource(mock_client).search(sku_ids=["sku-1"])

        assert mock_client.post.call_args[1]["body"] == {"sku_ids": ["sku-1"]}
