"""``buyer_id`` as a per-shop pseudonym (ADR-116 §4, D76; grill D5).

``buyer_id`` is stored as ``HMAC-SHA256(shop_key, platform buyer id)`` (64 lower-case
hex characters) in bronze and silver alike, so a repeat buyer is still the same id
within one shop (``ai/anomaly``, repeat-buyer counts) while the same buyer in two
shops gets two unrelated ids, and none maps back to the platform without the key.

The key is a random 32 bytes per shop, created on first use and stored sealed in
``shop_pseudonym_keys`` (migration 104; ``database.token_crypto.encrypt_for_purpose``).
Deleting that row makes the shop's stored ids permanently anonymous.

Pseudonymising is idempotent: a value that already has the pseudonym's shape (64
lower-case hex) is returned unchanged. That lets every silver writer apply it to
values promoted from an already-clean bronze row, and lets the clean-up command run
twice. A TikTok buyer id is decimal digits, so it never has that shape.

The caller's session must be scoped to the shop (``with_shop_scope``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import uuid
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.database.token_crypto import decrypt_for_purpose, encrypt_for_purpose
from juli_backend.repositories.pseudonym_keys import ShopPseudonymKeysRepo

KEY_PURPOSE = "shop_pseudonym_key"
KEY_BYTES = 32
BUYER_ID_KEY = "buyer_id"
_PSEUDONYM_SHAPE = re.compile(r"^[0-9a-f]{64}$")
#: Keys opened in this session, by shop id: one lookup per shop per session.
_SESSION_CACHE = "juli_shop_pseudonym_keys"


def buyer_pseudonym(key: bytes, buyer_id: str) -> str:
    """``HMAC-SHA256(key, buyer_id)`` as lower-case hex."""
    return hmac.new(key, buyer_id.encode(), hashlib.sha256).hexdigest()


def is_pseudonym(value: Any) -> bool:
    """``True`` when ``value`` already has the pseudonym's shape."""
    return isinstance(value, str) and _PSEUDONYM_SHAPE.match(value) is not None


def _open(key_ciphertext: str) -> bytes:
    return base64.b64decode(decrypt_for_purpose(key_ciphertext, purpose=KEY_PURPOSE))


async def shop_pseudonym_key(session: AsyncSession, shop_id: uuid.UUID) -> bytes:
    """The shop's key, created (and sealed) on first use."""
    cache: dict[uuid.UUID, bytes] = session.info.setdefault(_SESSION_CACHE, {})
    if shop_id in cache:
        return cache[shop_id]
    repo = ShopPseudonymKeysRepo(session)
    row = await repo.find(shop_id)
    if row is None:
        sealed = encrypt_for_purpose(
            base64.b64encode(secrets.token_bytes(KEY_BYTES)).decode(), purpose=KEY_PURPOSE
        )
        savepoint = await session.begin_nested()
        try:
            await repo.record(shop_id, key_ciphertext=sealed)
            await savepoint.commit()
        except IntegrityError:
            # A concurrent writer created the shop's key first: use theirs.
            await savepoint.rollback()
        row = await repo.find(shop_id)
        if row is None:  # pragma: no cover - the insert or the race winner left a row
            raise RuntimeError(f"no pseudonym key for shop {shop_id}")
    key = _open(row.key_ciphertext)
    cache[shop_id] = key
    return key


async def use_ephemeral_key_if_missing(session: AsyncSession, shop_id: uuid.UUID) -> None:
    """For a dry run: a shop without a key gets a throwaway one in this session only.

    Nothing is written, so a dry run of the clean-up never creates a key; the ids it
    computes are discarded with its rollback.
    """
    cache: dict[uuid.UUID, bytes] = session.info.setdefault(_SESSION_CACHE, {})
    if shop_id not in cache and await ShopPseudonymKeysRepo(session).find(shop_id) is None:
        cache[shop_id] = secrets.token_bytes(KEY_BYTES)


async def pseudonymize_buyer_id(session: AsyncSession, shop_id: uuid.UUID, value: Any) -> Any:
    """``value`` as the shop's pseudonym; ``None`` / empty / already-pseudonymised unchanged."""
    if value is None or value == "" or is_pseudonym(value):
        return value
    return buyer_pseudonym(await shop_pseudonym_key(session, shop_id), str(value))


async def pseudonymize_buyer_ids(
    session: AsyncSession, shop_id: uuid.UUID, payload: Mapping[str, Any]
) -> dict[str, Any]:
    """A copy of ``payload`` with every ``buyer_id`` (at any depth) pseudonymised."""

    async def walk(value: Any) -> Any:
        if isinstance(value, Mapping):
            out: dict[str, Any] = {}
            for key, child in value.items():
                if key == BUYER_ID_KEY and not isinstance(child, (Mapping, list)):
                    out[key] = await pseudonymize_buyer_id(session, shop_id, child)
                else:
                    out[key] = await walk(child)
            return out
        if isinstance(value, list):
            return [await walk(item) for item in value]
        return value

    return cast(dict[str, Any], await walk(payload))
