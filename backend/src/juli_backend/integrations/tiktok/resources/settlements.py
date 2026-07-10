"""TikTok Shop Finance statements — settlement reconciliation."""

from __future__ import annotations

from typing import Any, Optional

from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.constants import FINANCE_STATEMENTS_PATH
from juli_backend.integrations.tiktok.mapping import normalize_statement
from juli_backend.integrations.tiktok.resources import strip_nones
from juli_backend.integrations.tiktok.schemas import (
    FinanceStatement,
    FinanceStatementsData,
    coerce_model,
    validate_items,
)


class SettlementsResource:
    """Search finance statements (replaces legacy settlements/search)."""

    def __init__(self, client: TikTokClient) -> None:
        self._client = client

    def list(
        self,
        *,
        settle_time_from: Optional[int] = None,
        settle_time_to: Optional[int] = None,
        page_size: Optional[int] = None,
        page_token: Optional[str] = None,
    ) -> dict[str, Any]:
        params = strip_nones({
            "sort_field": "statement_time",
            "statement_time_ge": str(settle_time_from) if settle_time_from is not None else None,
            "statement_time_lt": str(settle_time_to) if settle_time_to is not None else None,
            "page_size": str(page_size) if page_size is not None else None,
            "page_token": page_token,
        })
        parsed = coerce_model(
            FinanceStatementsData,
            self._client.get(
                FINANCE_STATEMENTS_PATH,
                params=params,
                response_model=FinanceStatementsData,
            ),
        )
        return parsed.model_dump()

    def list_all(
        self,
        *,
        settle_time_from: Optional[int] = None,
        settle_time_to: Optional[int] = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        params = strip_nones({
            "sort_field": "statement_time",
            "statement_time_ge": str(settle_time_from) if settle_time_from is not None else None,
            "statement_time_lt": str(settle_time_to) if settle_time_to is not None else None,
        })
        raw_items = self._client.get_all_pages_get(
            FINANCE_STATEMENTS_PATH,
            params=params,
            items_key="statements",
            page_size=page_size,
        )
        statements = validate_items(FinanceStatement, raw_items)
        return [normalize_statement(s.model_dump()) for s in statements]
