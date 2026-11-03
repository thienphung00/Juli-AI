"""The key behind ``order_ref`` (P90 step 2): one derived key per shop, handed out briefly.

An order's platform id never reaches Juli: the sender (the Ops upload page in the browser, or
``scripts/load_shopee_exports.py``) replaces it by ``HMAC-SHA256(key, "shopee-order|" +
id.strip().upper())[:32]`` before anything leaves its machine, and the affiliate lane's
``scripts.shopee_exports.parse.order_ref`` is the same function. Every sender of one shop must
use the SAME key or the two lanes cannot join an order.

- the key of a shop is ``HMAC-SHA256(master, "order-ref-key|v1|<shop uuid>")``: stable (a join
  needs it to be), different per shop (one shop's refs say nothing about another's), and
  not stored anywhere - only the master is, in the environment
  (``JULI_ORDER_REF_MASTER_KEY``);
- the HTTP endpoint hands the derived key to an authenticated, audited, operator-role session
  for one upload, with ``Cache-Control: no-store`` and a short ``expires_at``. The page keeps it
  in memory and drops it; it is never written to ``localStorage`` or a cookie. Rotating the
  master changes every ref, so a rotation is a re-load of the shop's order history, not a
  routine step (``KEY_VERSION`` is in the response so a sender can refuse a key it does not
  expect).
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

ENV_MASTER = "JULI_ORDER_REF_MASTER_KEY"
KEY_VERSION = 1
ALGORITHM = "HMAC-SHA256"
#: How long a sender may keep a handed-out key (a hint to the page; the key itself is stable).
KEY_TTL = timedelta(minutes=10)
MIN_MASTER_BYTES = 16


class OrderRefKeyUnavailable(RuntimeError):
    """No master key is configured (or it is too short to be one)."""


@dataclass(frozen=True)
class IssuedKey:
    key_hex: str
    key_version: int
    algorithm: str
    expires_at: datetime


def master_key() -> bytes:
    raw = os.environ.get(ENV_MASTER, "").strip().encode()
    if len(raw) < MIN_MASTER_BYTES:
        raise OrderRefKeyUnavailable(ENV_MASTER)
    return raw


def shop_key(master: bytes, shop_id: uuid.UUID) -> bytes:
    """The order-ref key of one shop."""
    message = f"order-ref-key|v{KEY_VERSION}|{shop_id}".encode()
    return hmac.new(master, message, hashlib.sha256).digest()


def issue(shop_id: uuid.UUID, now: datetime) -> IssuedKey:
    return IssuedKey(
        key_hex=shop_key(master_key(), shop_id).hex(),
        key_version=KEY_VERSION,
        algorithm=ALGORITHM,
        expires_at=now + KEY_TTL,
    )


def order_ref(order_id: str, key: bytes) -> str:
    """The keyed hash that stands for an order; identical to the affiliate lane's
    ``scripts.shopee_exports.parse.order_ref`` and to the browser module's."""
    message = f"shopee-order|{order_id.strip().upper()}".encode()
    return hmac.new(key, message, hashlib.sha256).hexdigest()[:32]
