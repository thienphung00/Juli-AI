"""Pydantic schema validation for TikTok Partner API responses."""

import pytest

from juli_backend.integrations.tiktok.schemas import (
    CreatorContentDetail,
    FinanceStatement,
    MarketplaceCreator,
    MarketplaceCreatorsSearchData,
    OrdersSearchData,
    TikTokSchemaError,
    validate_data,
    validate_items,
)


class TestOrdersSearchData:
    def test_parses_orders_with_next_page_token(self):
        data = validate_data(
            OrdersSearchData,
            {
                "orders": [{"id": "o1", "user_id": "b1", "payment": {"total_amount": "10"}}],
                "next_page_token": "tok-2",
            },
        )
        assert data.orders[0].id == "o1"
        assert data.next_page_token == "tok-2"


class TestMarketplaceCreators:
    def test_parses_marketplace_creators_search(self):
        data = validate_data(
            MarketplaceCreatorsSearchData,
            {"marketplace_creators": [{"creator_user_id": "c1", "nickname": "Alice"}]},
        )
        assert data.marketplace_creators[0].creator_user_id == "c1"


class TestFinanceStatement:
    def test_validate_items_raises_on_invalid_payload(self):
        with pytest.raises(TikTokSchemaError):
            validate_items(MarketplaceCreator, [{"follower_count": "not-a-number"}])

    def test_creator_content_detail_extra_fields_preserved(self):
        item = CreatorContentDetail.model_validate({
            "room_id": "ls1",
            "total_sale_gmv_amt": 99.5,
            "custom_field": "kept",
        })
        dumped = item.model_dump()
        assert dumped["room_id"] == "ls1"
        assert dumped["custom_field"] == "kept"

    def test_finance_statement_maps_statement_id(self):
        stmt = FinanceStatement.model_validate({
            "statement_id": "st-1",
            "settlement_amount": "100.00",
            "statement_time": 1700000000,
        })
        assert stmt.statement_id == "st-1"
