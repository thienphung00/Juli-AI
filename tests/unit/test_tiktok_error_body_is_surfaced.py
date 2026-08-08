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
