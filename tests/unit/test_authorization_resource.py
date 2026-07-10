"""AuthorizationResource — authorized shops."""

from unittest.mock import MagicMock

import pytest

from juli_backend.integrations.tiktok.constants import AUTHORIZED_SHOPS_PATH
from juli_backend.integrations.tiktok.resources.authorization import (
    AuthorizationResource,
)


@pytest.fixture
def mock_client():
    client = MagicMock()
    client.get.return_value = {
        "shops": [{"id": "shop-1", "cipher": "cipher-1"}],
    }
    return client


class TestAuthorizationResource:
    def test_list_shops_uses_versioned_path(self, mock_client):
        auth = AuthorizationResource(mock_client)
        auth.list_shops()

        mock_client.get.assert_called_once()
        assert mock_client.get.call_args[0][0] == AUTHORIZED_SHOPS_PATH

    def test_list_all_shops_returns_shop_list(self, mock_client):
        auth = AuthorizationResource(mock_client)
        shops = auth.list_all_shops()

        assert shops == [{"id": "shop-1", "cipher": "cipher-1"}]
