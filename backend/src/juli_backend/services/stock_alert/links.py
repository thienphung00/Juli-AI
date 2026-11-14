"""The links of the stock e-mail (Part S): "Mở Juli" and the signed "Huỷ nhận email này".

The unsubscribe token names one member of one shop and is signed with HMAC-SHA256
(``STOCK_ALERT_LINK_SECRET``, else ``SUPABASE_JWT_SECRET`` -- required at boot -- under its own
domain label). It never expires: an old e-mail's link still works. It rides in the URL fragment
(``/huy-email#<token>``), so it never reaches a server log; the page posts it to confirm.
``STOCK_ALERT_APP_BASE_URL`` is the seller app (default ``https://demo.app-juli.com``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from urllib.parse import urlencode

DEFAULT_APP_BASE = "https://demo.app-juli.com"
UNSUBSCRIBE_PATH = "/huy-email"
OPEN_PATH = "/tong-quan"
_LABEL = b"juli-stock-alert-unsubscribe/v1:"


class BadToken(ValueError):
    pass


def app_base() -> str:
    return (os.environ.get("STOCK_ALERT_APP_BASE_URL", "").strip() or DEFAULT_APP_BASE).rstrip("/")


def _key() -> bytes:
    raw = os.environ.get("STOCK_ALERT_LINK_SECRET", "") or os.environ.get("SUPABASE_JWT_SECRET", "")
    if not raw:
        raise RuntimeError("no STOCK_ALERT_LINK_SECRET / SUPABASE_JWT_SECRET to sign links with")
    return hashlib.sha256(_LABEL + raw.encode()).digest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


@dataclass(frozen=True)
class Unsubscribe:
    shop_id: uuid.UUID
    user_id: uuid.UUID


def sign(shop_id: uuid.UUID, user_id: uuid.UUID) -> str:
    payload = _b64(
        json.dumps({"s": str(shop_id), "u": str(user_id)}, separators=(",", ":")).encode()
    )
    mac = hmac.new(_key(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64(mac)}"


def verify(token: str) -> Unsubscribe:
    try:
        payload, mac = token.strip().split(".", 1)
        want = hmac.new(_key(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(want, _unb64(mac)):
            raise BadToken("bad signature")
        data = json.loads(_unb64(payload))
        return Unsubscribe(uuid.UUID(data["s"]), uuid.UUID(data["u"]))
    except (ValueError, KeyError, TypeError) as exc:
        raise BadToken("bad token") from exc


def unsubscribe_url(shop_id: uuid.UUID, user_id: uuid.UUID) -> str:
    return f"{app_base()}{UNSUBSCRIBE_PATH}#{sign(shop_id, user_id)}"


def open_url(keys: Sequence[str] = ()) -> str:
    """Tổng quan › Sản phẩm, filtered to the listed variations when there are some."""
    params = {"cap": "san-pham"}
    if keys:
        params["ton_kho"] = ",".join(keys)
    return f"{app_base()}{OPEN_PATH}?{urlencode(params)}"


__all__ = ["BadToken", "Unsubscribe", "open_url", "sign", "unsubscribe_url", "verify"]
