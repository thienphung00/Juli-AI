"""The body we sign must be the body we send.

TikTok recomputes the request signature over the bytes it receives. The client
signed a compact, key-sorted serialization and then handed the dict to requests,
which re-serialized it with its own separators and key order. The two strings
differ, so TikTok's recomputed signature never matched ours.

Empty bodies hid this completely: json.dumps({}) is "{}" under both settings. So
the very first orders sync — which has no update_time_from and therefore an empty
body — succeeded, wrote sync_state, and every run afterwards sent a non-empty body
and failed with:

    {"code":106001,"message":"Invalid credentials. The 'sign' query parameter is invalid."}

That is a latent bug armed by its own first success, which is why it looked like
an external change.
"""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def client():
    from juli_backend.integrations.tiktok.client import TikTokClient

    return TikTokClient(
        app_key="test-key",
        app_secret="test-secret",
        access_token="test-token",
    )


class _CapturingSession:
    """Records exactly what was handed to requests."""

    def __init__(self):
        self.calls: list[dict] = []

    def _record(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})

        class _Resp:
            status_code = 200

            @staticmethod
            def raise_for_status():
                return None

            @staticmethod
            def json():
                return {"code": 0, "data": {}}

        return _Resp()

    def post(self, url, **kwargs):
        return self._record("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self._record("PUT", url, **kwargs)


@pytest.mark.parametrize("verb", ["post", "put"])
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"update_time_from": 1786000000},
        # key order chosen so sorted() reorders it — the exact shape that broke
        {"update_time_from": 1786000000, "page_size": 50},
        {"z": 1, "a": 2, "m": {"nested": True}},
    ],
)
def test_sent_body_is_byte_identical_to_signed_body(client, verb, body):
    session = _CapturingSession()
    client._session = session

    getattr(client, verb)("/order/202309/orders/search", body=body)

    call = session.calls[0]
    assert "json" not in call, (
        "must not pass json=; requests would re-serialize and break the signature"
    )
    sent = call["data"]
    expected = json.dumps(body, separators=(",", ":"), sort_keys=True)
    assert sent == expected, (
        f"sent body {sent!r} differs from the signed serialization {expected!r}"
    )


@pytest.mark.parametrize("verb", ["post", "put"])
def test_content_type_is_json_when_sending_raw_bytes(client, verb):
    """requests only sets Content-Type automatically for json=, not data=."""
    session = _CapturingSession()
    client._session = session

    getattr(client, verb)("/order/202309/orders/search", body={"a": 1})

    headers = session.calls[0]["headers"]
    assert headers.get("Content-Type") == "application/json"


def test_non_empty_body_would_have_differed_under_the_old_behaviour():
    """Pins why this went unnoticed: empty bodies serialize identically."""
    empty: dict = {}
    assert json.dumps(empty, separators=(",", ":"), sort_keys=True) == json.dumps(empty)

    populated = {"update_time_from": 1786000000, "page_size": 50}
    assert json.dumps(populated, separators=(",", ":"), sort_keys=True) != json.dumps(populated)
