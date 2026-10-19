"""An HTTP failure must carry the Partner API's explanation, not just the status line.

`raise_for_status()` reports only the status and URL. When production started
returning 500 on `orders/search`, the logs held the signed URL and nothing else —
two days of diagnosis ran without ever seeing what TikTok actually said.
"""

from __future__ import annotations

import pytest
import requests

from juli_backend.integrations.tiktok.client import TikTokClient


def _response(
    status: int,
    body: str,
    url: str = "https://open-api.tiktokglobalshop.com/order/202309/orders/search",
) -> requests.Response:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    resp.url = url
    resp.request = requests.Request("POST", url).prepare()
    return resp


def test_http_error_message_includes_the_response_body():
    resp = _response(500, '{"code":10000,"message":"internal error, please retry"}')

    with pytest.raises(requests.HTTPError) as excinfo:
        TikTokClient._handle_response(resp)

    message = str(excinfo.value)
    assert "500" in message
    assert "internal error, please retry" in message
    # The original exception stays reachable for callers that inspect it.
    assert excinfo.value.response is resp


def test_oversized_body_is_truncated():
    resp = _response(502, "x" * 5000)

    with pytest.raises(requests.HTTPError) as excinfo:
        TikTokClient._handle_response(resp)

    assert len(str(excinfo.value)) < 1200


def test_empty_body_still_raises_the_plain_status_error():
    resp = _response(503, "")

    with pytest.raises(requests.HTTPError) as excinfo:
        TikTokClient._handle_response(resp)

    assert "503" in str(excinfo.value)


def test_successful_response_is_unchanged():
    resp = _response(200, '{"code":0,"message":"Success","data":{"orders":[{"id":"1"}]}}')

    assert TikTokClient._handle_response(resp) == {"orders": [{"id": "1"}]}


# -- P58-B (D67): the logged URL keeps its path, never its signed query ----------------------

SIGNED = (
    "https://open-api.tiktokglobalshop.com/order/202309/orders/search"
    "?app_key=6abc123def&timestamp=1791000000&page_size=50"
    "&sign=0f1e2d3c4b5a69788796a5b4c3d2e1f00f1e2d3c4b5a69788796a5b4c3d2e1f0"
)
BODY_106013 = (
    '{"code":106013,"message":"Missing identifier. The \'shop_cipher\' query parameter '
    'is required for this API. Please provide a valid shop_cipher.","request_id":"2025"}'
)
SECRETS = ("6abc123def", "sign=", "app_key=", "0f1e2d3c4b5a6978")


def test_http_error_drops_the_signed_query_but_keeps_path_and_body():
    resp = _response(400, BODY_106013, url=SIGNED)

    with pytest.raises(requests.HTTPError) as excinfo:
        TikTokClient._handle_response(resp)

    message = str(excinfo.value)
    assert "/order/202309/orders/search?<query redacted>" in message
    assert "106013" in message and "shop_cipher" in message
    assert not any(secret in message for secret in SECRETS)
    # The unredacted original is not chained, so a logged traceback cannot print it.
    assert excinfo.value.__suppress_context__ and excinfo.value.__cause__ is None


def test_logged_traceback_of_a_400_carries_no_signed_query(caplog):
    import logging

    resp = _response(400, BODY_106013, url=SIGNED)
    log = logging.getLogger("test.p56")
    with caplog.at_level(logging.ERROR, logger="test.p56"):
        try:
            TikTokClient._handle_response(resp)
        except requests.HTTPError:
            log.error("bootstrap_shop_failed", exc_info=True)

    text = caplog.text
    assert "106013" in text
    assert not any(secret in text for secret in SECRETS)


class _Down:
    """A requests.Session whose transport fails the way urllib3 reports it."""

    def post(self, url, params=None, **_kwargs):
        query = "&".join(f"{k}={v}" for k, v in (params or {}).items())
        path = url.split(".com", 1)[1]
        raise requests.ConnectionError(
            "HTTPSConnectionPool(host='open-api.tiktokglobalshop.com', port=443): Max "
            f"retries exceeded with url: {path}?{query} (Caused by NewConnectionError())"
        )

    get = put = post


def test_transport_error_keeps_its_type_and_loses_the_query():
    client = TikTokClient(
        app_key="6abc123def", app_secret="secret", access_token="tok", shop_cipher="ROW_x"
    )
    client._session = _Down()

    with pytest.raises(requests.ConnectionError) as excinfo:
        client.post("/order/202309/orders/search", body={"order_status": "COMPLETED"})

    message = str(excinfo.value)
    assert "url: /order/202309/orders/search?<query redacted>" in message
    assert not any(secret in message for secret in SECRETS)
    assert "ROW_x" not in message
    assert excinfo.value.__suppress_context__


def test_redact_url_query_leaves_text_without_a_url_alone():
    from juli_backend.integrations.tiktok.client import redact_url_query

    assert redact_url_query("why? because") == "why? because"
    assert redact_url_query("for url: https://h/p?a=1&b=2 next") == (
        "for url: https://h/p?<query redacted> next"
    )
