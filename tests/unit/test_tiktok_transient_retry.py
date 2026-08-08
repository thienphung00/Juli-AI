"""Retry Partner failures only when the body says retrying can help (#871 research).

TikTok tunnels application errors over HTTP 500 — #855's invalid-sign arrived as a
500 — so a status code alone can never justify a retry. Classification reads the
response envelope: 100005 (rate limit) and 100006 (documented transient system
error) retry with backoff; unparseable 5xx bodies (an edge's HTML page) retry;
everything else fails fast. Blind retry-on-5xx would have re-sent the broken
signature three times per page for two days.
"""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
import requests

from juli_backend.integrations.tiktok import client as client_mod
from juli_backend.integrations.tiktok.client import TikTokClient, transient_partner_error
from juli_backend.integrations.tiktok.exceptions import (
    AuthenticationError,
    RateLimitError,
    TikTokAPIError,
    TikTokSystemError,
)
from juli_backend.integrations.tiktok.resources.orders import OrdersResource

URL = "https://open-api.tiktokglobalshop.com/order/202309/orders/search"


def _response(status: int, body: dict | str) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    text = json.dumps(body) if isinstance(body, dict) else body
    resp._content = text.encode()
    resp.url = URL
    resp.request = requests.Request("POST", URL).prepare()
    return resp


def _envelope(**data) -> dict:
    return {"code": 0, "message": "Success", "data": data}


def _http_error(status: int, body: dict | str) -> requests.HTTPError:
    resp = _response(status, body)
    return requests.HTTPError(f"{status} Server Error", response=resp)


@pytest.fixture
def sleeps(monkeypatch):
    recorded: list[float] = []
    monkeypatch.setattr(client_mod.time, "sleep", recorded.append)
    return recorded


def _client() -> TikTokClient:
    client = TikTokClient(app_key="k", app_secret="s", access_token="t")
    client._session = Mock()
    return client


class TestClassification:
    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (requests.ConnectionError("reset"), True),
            (requests.Timeout("read timeout"), True),
            (_http_error(500, "<html>502 from some edge</html>"), True),
            (requests.HTTPError("no response attached"), True),
            (_http_error(500, {"code": 100006, "message": "internal error"}), True),
            # Captured live 2026-08-08 — the body that explained three days of 500s,
            # and whose own message instructs "Please try again."
            (
                _http_error(
                    500, {"code": 36009003, "message": "Internal error. Please try again."}
                ),
                True,
            ),
            (_http_error(500, {"code": 100005, "message": "throttled"}), True),
            # The proven trap: a deterministic app error wearing a 500 status.
            (_http_error(500, {"code": 106001, "message": "sign invalid"}), False),
            (_http_error(401, {"code": 100002, "message": "token expired"}), False),
            (_http_error(403, "<html>edge forbidden</html>"), False),
            (RateLimitError(100005, "throttled"), True),
            (TikTokSystemError(100006, "transient"), True),
            (AuthenticationError(100002, "expired"), False),
            (TikTokAPIError(123456, "unknown code"), False),
        ],
        ids=[
            "connection",
            "timeout",
            "5xx_unparseable",
            "no_response",
            "5xx_code_100006",
            "5xx_code_36009003_vendor_internal",
            "5xx_code_100005",
            "5xx_code_106001_sign",
            "401_auth",
            "4xx_unparseable",
            "envelope_rate_limit",
            "envelope_system_error",
            "envelope_auth",
            "envelope_unknown_code",
        ],
    )
    def test_transient_partner_error(self, exc, expected):
        assert transient_partner_error(exc) is expected


class TestGetRetries:
    def test_transient_5xx_retries_then_succeeds(self, sleeps):
        client = _client()
        client._session.get.side_effect = [
            _response(500, "<html>bad gateway</html>"),
            _response(500, {"code": 100006, "message": "internal error"}),
            _response(200, _envelope(orders=[{"id": "1"}])),
        ]

        data = client.get("/x")

        assert data == {"orders": [{"id": "1"}]}
        assert client._session.get.call_count == 3
        assert sleeps == [1.0, 3.0]

    def test_deterministic_500_fails_fast(self, sleeps):
        """A sign error over HTTP 500 must not burn retries."""
        client = _client()
        client._session.get.side_effect = [
            _response(500, {"code": 106001, "message": "sign invalid"}),
        ]

        with pytest.raises(requests.HTTPError):
            client.get("/x")

        assert client._session.get.call_count == 1
        assert sleeps == []

    def test_exhausted_retries_raise_the_last_error(self, sleeps):
        client = _client()
        client._session.get.side_effect = [
            _response(500, "<html>edge</html>"),
            _response(500, "<html>edge</html>"),
            _response(500, "<html>edge</html>"),
        ]

        with pytest.raises(requests.HTTPError):
            client.get("/x")

        assert client._session.get.call_count == 3
        assert sleeps == [1.0, 3.0]

    def test_each_attempt_is_freshly_signed(self, sleeps, monkeypatch):
        """A retry must rebuild sign and timestamp — the signing window is 5 minutes,
        and re-sending stale signed bytes recreates the #855 class of failure."""
        signed = []
        real_sign = client_mod.sign_request

        def counting_sign(**kwargs):
            signed.append(1)
            return real_sign(**kwargs)

        monkeypatch.setattr(client_mod, "sign_request", counting_sign)
        client = _client()
        client._session.get.side_effect = [
            _response(500, "<html>edge</html>"),
            _response(200, _envelope()),
        ]

        client.get("/x")

        assert len(signed) == 2


class TestPostRetryIsOptIn:
    def test_default_post_never_retries(self, sleeps):
        """POST serves writes; a retried write after an ambiguous 5xx can execute
        twice. Single attempt unless the caller declares the endpoint a read."""
        client = _client()
        client._session.post.side_effect = [_response(500, "<html>edge</html>")]

        with pytest.raises(requests.HTTPError):
            client.post("/write", body={"package_id": "1"})

        assert client._session.post.call_count == 1
        assert sleeps == []

    def test_opted_in_search_post_retries(self, sleeps):
        client = _client()
        client._session.post.side_effect = [
            _response(500, "<html>edge</html>"),
            _response(200, _envelope(orders=[])),
        ]

        client.post("/search", body={"update_time_ge": 1}, retry_transient=True)

        assert client._session.post.call_count == 2
        assert sleeps == [1.0]


class TestPaginationRetries:
    def test_mid_pagination_transient_failure_recovers(self, sleeps):
        """The production shape: page 2 of the hourly orders crawl 500s. One page
        retry must not abort the crawl — before this, a single transient failure
        cost the whole 20-page fetch and the cursor never advanced."""
        client = _client()
        client._session.post.side_effect = [
            _response(200, _envelope(orders=[{"id": "1"}], next_page_token="t2", total_count=120)),
            _response(500, "<html>edge</html>"),
            _response(200, _envelope(orders=[{"id": "2"}])),
        ]

        orders = OrdersResource(client).search_all(update_time_from=1)

        assert [o["id"] for o in orders] == ["1", "2"]
        assert client._session.post.call_count == 3
        assert sleeps == [1.0]

    def test_pagination_summary_reports_backlog(self, caplog):
        client = _client()
        client._session.post.side_effect = [
            _response(200, _envelope(orders=[{"id": "1"}], total_count=2817)),
        ]

        with caplog.at_level("INFO"):
            client.get_all_pages(path="/search", body={}, items_key="orders")

        record = next(r for r in caplog.records if r.message == "tiktok_pagination_summary")
        assert record.total_count == 2817
        assert record.items == 1
        assert record.truncated is False

    def test_truncated_crawl_is_labelled(self, caplog, monkeypatch):
        monkeypatch.setenv("TIKTOK_MAX_PAGES", "1")
        client = _client()
        client._session.post.side_effect = [
            _response(
                200, _envelope(orders=[{"id": "1"}], next_page_token="more", total_count=999)
            ),
        ]

        with caplog.at_level("INFO"):
            items = client.get_all_pages(path="/search", body={}, items_key="orders")

        assert len(items) == 1
        record = next(r for r in caplog.records if r.message == "tiktok_pagination_summary")
        assert record.truncated is True
        assert record.total_count == 999
