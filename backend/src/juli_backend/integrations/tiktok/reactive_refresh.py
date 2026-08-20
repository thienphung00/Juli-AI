"""Reactive credential refresh (ADR-081 decision 1, row 3).

Three refresh layers exist per ADR-081: beat (every 30 min, reads the
``token_expires_at`` column), lazy (at ``resolve_*_credential``, also reads
the column), and reactive -- this module -- which reads the vendor's own
answer instead. It is the only layer that can self-heal a *lying* column:
the sandbox credential's ``token_expires_at`` was invented by a seeding
script (``now + 7d``) while the API answered ``105002 Expired``; beat and
lazy both read that same wrong column and would have skipped the row
identically.

**Catch point.** ``TikTokClient`` (``client.py``) is synchronous,
constructed once per call with a *static* ``access_token``, and holds no
credential context -- it cannot know which ``tiktok_credentials`` row it
was built from, so it cannot call ``refresh_credential`` itself. This
module is therefore the credential-aware layer that sits **one level
above** a single vendor call rather than inside ``TikTokClient``: the
caller (necessarily async, since ``refresh_credential`` is async and needs
an ``AsyncSession``) hands in the ``TikTokClient`` instance plus a zero-arg
``call`` closure that performs the already-fully-built request against it
(e.g. ``lambda: client.get(path, params=params)``). ``call`` runs via
``asyncio.to_thread`` both before and after a refresh -- the same pattern
every other async caller of a synchronous TikTok primitive in this
codebase already uses (``core/security/tiktok_oauth.py``,
``services/tiktok/verify_connection.py``): the sync client never changes
shape, only the caller adapts.

**Two error shapes, one catch point.** TikTok tunnels *application* errors
over HTTP 500 (``client.py``'s own comment), which is not the same as
saying transport 401s never happen. ``105002`` is unmapped in
``exceptions.py::_CODE_MAP`` (only ``100002``-``100006`` are), so it
surfaces as the bare ``TikTokAPIError`` base class with ``.code ==
105002``. A genuine transport ``401`` surfaces differently, as
``requests.HTTPError`` from ``TikTokClient._handle_response``'s
``resp.raise_for_status()``. ``_is_auth_expiry_signal`` below checks both
shapes explicitly rather than assuming either implies the other.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from typing import TypeVar

import requests
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.core.security import credential_refresh
from juli_backend.integrations.tiktok.client import TikTokClient
from juli_backend.integrations.tiktok.exceptions import TikTokAPIError

logger = logging.getLogger(__name__)

T = TypeVar("T")

#: TikTok's vendor code for "access token expired" -- not in
#: ``exceptions.py::_CODE_MAP``, so it always surfaces as the base
#: ``TikTokAPIError`` class rather than a dedicated subclass.
_EXPIRED_TOKEN_CODE = 105002
_UNAUTHORIZED_STATUS_CODE = 401


class ReactiveRefreshNeedsReauthError(Exception):
    """Raised when the reactive path's forced refresh cannot self-heal the
    credential (``refresh_credential`` returned ``needs_reauth``).

    The originating vendor call is **not** retried and no further vendor
    call is made for this request -- retrying against a confirmed-dead
    refresh token would only produce a second, identical failure.
    ``cause`` is the exact auth-expiry exception that triggered the refresh
    attempt, chained via ``raise ... from cause``.
    """

    def __init__(self, credential_id: uuid.UUID, cause: Exception) -> None:
        self.credential_id = credential_id
        self.cause = cause
        super().__init__(
            f"TikTok credential {credential_id} could not self-heal via reactive "
            "refresh (needs_reauth); re-OAuth is required"
        )


def _is_auth_expiry_signal(exc: Exception) -> bool:
    """True only for the two auth-expiry shapes this layer targets.

    Deliberately narrow: any other ``TikTokAPIError`` code (e.g. ``100003``
    permission-denied, ``100004`` not-found -- even ``100005``/``100006``,
    which ``TikTokClient`` itself already retries transiently at the
    transport layer) is out of scope. This is a targeted auth-expiry
    signal, not a general retry-on-error policy.
    """
    if isinstance(exc, TikTokAPIError):
        return exc.code == _EXPIRED_TOKEN_CODE
    if isinstance(exc, requests.HTTPError):
        resp = exc.response
        return resp is not None and resp.status_code == _UNAUTHORIZED_STATUS_CODE
    return False


async def call_with_reactive_refresh(
    session: AsyncSession,
    credential_id: uuid.UUID,
    *,
    auth: credential_refresh.RefreshAuth,
    client: TikTokClient,
    call: Callable[[], T],
) -> T:
    """Run a synchronous TikTok vendor call, self-healing a lying
    ``token_expires_at`` column on a ``105002``/``401`` auth-expiry signal.

    On any other exception, propagates immediately -- no refresh attempt.

    On an auth-expiry signal: calls ``refresh_credential(...,
    force=True)`` exactly once. If the outcome is ``needs_reauth``, raises
    :class:`ReactiveRefreshNeedsReauthError` (chained from the original
    exception) without retrying ``call`` and without any further vendor
    call. Otherwise, swaps the refreshed access token onto ``client`` and
    retries ``call`` **exactly once** -- whatever that retry does (succeed
    or raise) is returned or propagated directly, with no further catching,
    which is what bounds this to one retry even against a fixture that
    always raises the same auth-expiry signal.
    """
    try:
        return await asyncio.to_thread(call)
    except Exception as exc:  # noqa: BLE001 -- classified narrowly below
        if not _is_auth_expiry_signal(exc):
            raise

        logger.warning(
            "tiktok_reactive_refresh_triggered",
            extra={"credential_id": str(credential_id), "error_type": type(exc).__name__},
        )
        outcome = await credential_refresh.refresh_credential(
            session, credential_id, auth=auth, force=True
        )

        if outcome.status is credential_refresh.RefreshStatus.NEEDS_REAUTH:
            logger.error(
                "tiktok_reactive_refresh_needs_reauth",
                extra={"credential_id": str(credential_id)},
            )
            raise ReactiveRefreshNeedsReauthError(credential_id, exc) from exc

        client.access_token = outcome.credential.access_token
        return await asyncio.to_thread(call)
