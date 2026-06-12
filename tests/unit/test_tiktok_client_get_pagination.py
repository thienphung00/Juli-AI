"""GET pagination for finance statements and creator content."""

from unittest.mock import MagicMock

import pytest

from src.modules.catalog.domain.integrations.tiktok.client import TikTokClient
from src.modules.catalog.domain.integrations.tiktok.constants import FINANCE_STATEMENTS_PATH


@pytest.fixture
def client():
    c = TikTokClient(
        app_key="key",
        app_secret="secret",
        access_token="token",
        shop_cipher="cipher",
    )
    c.get = MagicMock()
    return c


class TestGetAllPagesGet:
    def test_paginates_finance_statements(self, client):
        client.get.side_effect = [
            {"statements": [{"statement_id": "s1"}], "next_page_token": "tok-2"},
            {"statements": [{"statement_id": "s2"}]},
        ]

        result = client.get_all_pages_get(
            FINANCE_STATEMENTS_PATH,
            params={"sort_field": "statement_time"},
            items_key="statements",
            page_size=10,
        )

        assert [s["statement_id"] for s in result] == ["s1", "s2"]
        second_params = client.get.call_args_list[1][1]["params"]
        assert second_params["page_token"] == "tok-2"
