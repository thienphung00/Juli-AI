"""Deterministic TikTok API replay from contract-collection samples (issue #367).

Patches ``requests.Session.request`` so integration tests exercise the real
TikTok client, resource modules, sync workers, and poll orchestration without
live Partner API credentials.
"""

from __future__ import annotations

import copy
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse

from juli_backend.integrations.tiktok.constants import (
    INVENTORY_SEARCH_PATH,
    ORDER_SEARCH_PATH,
    PRODUCT_SEARCH_PATH,
    RETURN_SEARCH_PATH,
)

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "docs/integrations/tiktok_api/samples"

_PATH_FIXTURES: dict[str, str] = {
    ORDER_SEARCH_PATH: "orders-search-response.json",
    PRODUCT_SEARCH_PATH: "products-search-response.json",
    RETURN_SEARCH_PATH: "returns-search-response.json",
    INVENTORY_SEARCH_PATH: "inventory-search-response.json",
}

_ITEMS_KEY_BY_PATH: dict[str, str] = {
    ORDER_SEARCH_PATH: "orders",
    PRODUCT_SEARCH_PATH: "products",
    RETURN_SEARCH_PATH: "return_orders",
    # Inventory is a full snapshot — never filter by update_time_ge.
}


def load_sample(name: str) -> dict[str, Any]:
    path = SAMPLES_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


def _path_from_url(url: str) -> str:
    return urlparse(url).path


def _mock_http_response(envelope: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = envelope
    response.raise_for_status = MagicMock()
    return response


def _filter_incremental_items(
    items: list[dict[str, Any]],
    update_from: int | None,
) -> list[dict[str, Any]]:
    if update_from is None:
        return items
    return [
        item
        for item in items
        if (item.get("update_time") or item.get("updated_at") or 0) > update_from
    ]


def build_replay_responses() -> dict[str, dict[str, Any]]:
    """Load sanitized contract samples keyed by API path."""
    return {
        path: load_sample(filename)
        for path, filename in _PATH_FIXTURES.items()
    }


@contextmanager
def recorded_tiktok_replay(*, fail_paths: frozenset[str] | None = None):
    """Replay recorded TikTok search responses for poll orchestration tests."""
    responses_by_path = build_replay_responses()
    failure_paths = fail_paths or frozenset()

    def _request(*args: Any, **kwargs: Any) -> MagicMock:
        if len(args) >= 3:
            method = str(args[1])
            url = str(args[2])
        elif len(args) == 2:
            method = str(args[0])
            url = str(args[1])
        else:
            method = str(kwargs["method"])
            url = str(kwargs["url"])
        path = _path_from_url(url)
        if path in failure_paths:
            return _mock_http_response(
                {
                    "code": 50_000,
                    "message": "Recorded replay simulated failure",
                    "data": {},
                    "request_id": "replay-failure-367",
                }
            )

        fixture = responses_by_path.get(path)
        if fixture is None:
            raise AssertionError(f"Unexpected TikTok replay request: {method} {path}")

        body = kwargs.get("json") or {}
        update_from = body.get("update_time_ge")

        envelope = copy.deepcopy(fixture["response"])
        data = envelope.get("data") or {}
        data.pop("next_page_token", None)
        data.pop("page_token", None)

        items_key = _ITEMS_KEY_BY_PATH.get(path)
        if items_key is not None:
            data[items_key] = _filter_incremental_items(
                data.get(items_key, []),
                update_from,
            )

        envelope["data"] = data
        return _mock_http_response(envelope)

    with patch("requests.Session.request", side_effect=_request):
        yield
