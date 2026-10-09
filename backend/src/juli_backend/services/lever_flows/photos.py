"""The cover-image run's two photos: stored, served, and parsed (fast track P10-B, §4).

- ``after`` -- the seller's photo, accepted by ``POST /v1/demo/runs/{id}/photo``
  once every check passes. Its bytes are what ``upload_product_image`` screens
  and uploads; the TikTok URI that upload returns is kept on the same row
  (``tiktok_uri``), so the write that follows the seller's consent -- on a later
  worker leg -- can attach it.
- ``before`` -- the listing's current cover, fetched once by the worker when the
  run starts waiting for the photo, so the consent step shows "before" from our
  own storage instead of a short-lived, pre-signed TikTok CDN URL.

Both are served at ``/v1/demo/photos/{shop_id}/{public_token}``: an ``<img>``
cannot send the auth header, so the URL itself is the capability -- a random
32-byte token per photo, never derived from anything guessable, never a TikTok
URL or credential. The shop id only picks the row-level-security scope for the
lookup.
"""

from __future__ import annotations

import email.parser
import email.policy
import io
import logging
import secrets
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from PIL import Image
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from juli_backend.models.lever_flows import PHOTO_AFTER, PHOTO_BEFORE, RunLeverPhoto
from juli_backend.services.lever_flows import photo_checks

logger = logging.getLogger(__name__)

PHOTO_URL_PREFIX = "/v1/demo/photos/"

#: Hosts the listing's current cover may be fetched from (TikTok Shop's image
#: CDNs). Anything else is refused: the URL comes from a vendor payload.
TIKTOK_IMAGE_HOST_SUFFIXES: tuple[str, ...] = (
    ".ibyteimg.com",
    ".tiktokcdn.com",
    ".tiktokcdn-us.com",
    ".tiktokcdn-eu.com",
    ".byteimg.com",
    ".ttwstatic.com",
)
_FETCH_TIMEOUT_S = 10.0

#: (url) -> image bytes. Injected so tests never touch the network.
ImageFetcher = Callable[[str], bytes]


class MultipartError(ValueError):
    """The request body is not a multipart form with a ``file`` part."""


def photo_url(photo: RunLeverPhoto | None) -> str | None:
    """``/v1/demo/photos/{shop_id}/{token}`` -- the shop id only selects the tenant
    scope for the lookup; the token is what grants access."""
    if photo is None:
        return None
    return f"{PHOTO_URL_PREFIX}{photo.shop_id}/{photo.public_token}"


def new_token() -> str:
    return secrets.token_urlsafe(32)


async def get_photo(
    session: AsyncSession, shop_id: uuid.UUID, run_id: uuid.UUID, role: str
) -> RunLeverPhoto | None:
    result = await session.execute(
        select(RunLeverPhoto).where(
            RunLeverPhoto.shop_id == shop_id,
            RunLeverPhoto.workflow_run_id == run_id,
            RunLeverPhoto.role == role,
        )
    )
    return result.scalar_one_or_none()


async def photo_by_token(
    session: AsyncSession, shop_id: uuid.UUID, token: str
) -> RunLeverPhoto | None:
    """The photo behind a served URL, for this shop only."""
    if not token or len(token) > 64:
        return None
    result = await session.execute(
        select(RunLeverPhoto).where(
            RunLeverPhoto.shop_id == shop_id, RunLeverPhoto.public_token == token
        )
    )
    return result.scalar_one_or_none()


async def save_photo(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    run_id: uuid.UUID,
    role: str,
    data: bytes,
    report: photo_checks.PhotoReport,
) -> RunLeverPhoto:
    """Insert or replace the ``role`` photo of a run. Flush, no commit.

    Replacing the seller's photo clears the staged TikTok URI: it belonged to
    the previous bytes.
    """
    photo = await get_photo(session, shop_id, run_id, role)
    if photo is None:
        photo = RunLeverPhoto(
            shop_id=shop_id,
            workflow_run_id=run_id,
            role=role,
            public_token=new_token(),
            content_type=report.content_type or "application/octet-stream",
            data=data,
            width=report.width,
            height=report.height,
            checks=report.checks_json(),
        )
        session.add(photo)
    else:
        photo.content_type = report.content_type or "application/octet-stream"
        photo.data = data
        photo.width = report.width
        photo.height = report.height
        photo.checks = report.checks_json()
        photo.public_token = new_token()
        photo.tiktok_uri = None
    await session.flush()
    return photo


class SqlStagedUriRecorder:
    """Keeps the URI ``upload_product_image`` staged on the run's ``after`` photo.

    Called by the executor inside the worker leg, on the ledger's sync session
    (already under the run's shop scope), and committed at once: the consent
    that follows may be answered from a different worker process.
    """

    def __init__(self, session: Session, *, shop_id: uuid.UUID, workflow_run_id: uuid.UUID):
        self._session = session
        self._shop_id = shop_id
        self._run_id = workflow_run_id

    def __call__(self, uri: str) -> None:
        self._session.execute(
            update(RunLeverPhoto)
            .where(
                RunLeverPhoto.shop_id == self._shop_id,
                RunLeverPhoto.workflow_run_id == self._run_id,
                RunLeverPhoto.role == PHOTO_AFTER,
            )
            .values(tiktok_uri=uri)
        )
        self._session.commit()
        logger.info(
            "lever_photo_staged",
            extra={"shop_id": str(self._shop_id), "run_id": str(self._run_id)},
        )


# --- multipart ------------------------------------------------------------------


def parse_multipart_file(content_type: str | None, body: bytes, *, field: str = "file") -> bytes:
    """The bytes of the ``field`` part of a ``multipart/form-data`` body.

    Parsed with the standard library's MIME parser: the API takes one small
    upload, and this avoids a new runtime dependency for it.
    """
    if not content_type or not content_type.lower().startswith("multipart/form-data"):
        raise MultipartError("expected multipart/form-data")
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(header + body)
    if not message.is_multipart():
        raise MultipartError("body is not multipart")
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if part.get_param("name", header="content-disposition") == field or (
            f'name="{field}"' in str(disposition)
        ):
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                return payload
    raise MultipartError(f"no {field!r} part")


# --- the listing's current cover --------------------------------------------------


def cover_image_url(product_detail: Mapping[str, Any] | None) -> str | None:
    """The first URL of the listing's first main image, from a raw detail read."""
    images = (product_detail or {}).get("main_images") or []
    first = images[0] if images and isinstance(images[0], Mapping) else {}
    urls = first.get("urls") or []
    url = urls[0] if urls else None
    return str(url) if url else None


def allowed_image_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(
        host.endswith(suffix) for suffix in TIKTOK_IMAGE_HOST_SUFFIXES
    )


def fetch_image(url: str) -> bytes:
    """GET a TikTok CDN image (https, allowlisted host, no redirects, ≤ 5 MB)."""
    import httpx

    if not allowed_image_url(url):
        raise ValueError("cover image URL is not on a TikTok image host")
    with httpx.Client(timeout=_FETCH_TIMEOUT_S, follow_redirects=False) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > photo_checks.MAX_PHOTO_BYTES:
                    raise ValueError("cover image is larger than 5 MB")
                chunks.append(chunk)
    return b"".join(chunks)


@dataclass(frozen=True)
class BeforeSnapshot:
    data: bytes
    report: photo_checks.PhotoReport


def snapshot_cover(
    product_detail: Mapping[str, Any] | None, fetcher: ImageFetcher
) -> BeforeSnapshot | None:
    """Fetch and measure the current cover. ``None`` when there is none or it fails."""
    url = cover_image_url(product_detail)
    if url is None or not allowed_image_url(url):
        return None
    try:
        data = fetcher(url)
    except Exception:  # best effort: the consent can show "before" as unavailable
        logger.warning("lever_photo_before_fetch_failed", exc_info=True)
        return None
    report = photo_checks.check_photo(data)
    if report.content_type is None:
        # A WebP or other format TikTok served: keep the bytes, record the size.
        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                fmt = (image.format or "").lower()
        except Exception:
            return None
        report = photo_checks.PhotoReport(
            checks=report.checks, content_type=f"image/{fmt or 'jpeg'}", width=width, height=height
        )
    return BeforeSnapshot(data=data, report=report)


__all__ = [
    "PHOTO_AFTER",
    "PHOTO_BEFORE",
    "PHOTO_URL_PREFIX",
    "BeforeSnapshot",
    "ImageFetcher",
    "MultipartError",
    "SqlStagedUriRecorder",
    "allowed_image_url",
    "cover_image_url",
    "fetch_image",
    "get_photo",
    "new_token",
    "parse_multipart_file",
    "photo_by_token",
    "photo_url",
    "save_photo",
    "snapshot_cover",
]
