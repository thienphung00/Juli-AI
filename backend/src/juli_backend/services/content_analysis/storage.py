"""Temporary storage of uploads on the VPS disk, and the signed upload token (fast track P15).

Layout: ``<CONTENT_ANALYSIS_UPLOAD_DIR>/<shop_id>/<analysis_id>.upload`` --
directories 0700, files 0600, never under a web-served path, never executed.
The name is Juli's own (the seller's file name is only stored as text), so no
user-controlled string reaches the filesystem.

A file is deleted as soon as its analysis ends (``delete``); ``sweep`` deletes
anything older than ``CONTENT_ANALYSIS_FILE_MAX_AGE_HOURS`` (24 h) -- an
analysis that failed and was not retried, an upload abandoned half-way. Only
derived data is kept (``content_analyses``).

The upload URL carries a token: HMAC-SHA256 over (analysis id, shop id,
expiry) with ``CONTENT_UPLOAD_SIGNING_SECRET`` (else ``SUPABASE_JWT_SECRET``,
domain-separated). The upload request must ALSO carry the seller's session and
``X-Shop-Id``; the token binds the bytes to that one upload slot and expires
with it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path

from juli_backend.services.content_analysis.config import AnalysisSettings

logger = logging.getLogger(__name__)

SUFFIX = ".upload"
_TOKEN_DOMAIN = b"juli-content-upload-v1"


def root(conf: AnalysisSettings) -> Path:
    path = Path(conf.upload_dir)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def storage_key(shop_id: uuid.UUID, analysis_id: uuid.UUID) -> str:
    return f"{shop_id}/{analysis_id}{SUFFIX}"


def path_of(conf: AnalysisSettings, key: str) -> Path:
    base = root(conf).resolve()
    path = (base / key).resolve()
    if base not in path.parents:
        raise ValueError("storage key escapes the upload directory")
    return path


def append_chunk(conf: AnalysisSettings, key: str, offset: int, data: bytes) -> int:
    """Write ``data`` at ``offset`` (must equal the current size); returns the new size."""
    path = path_of(conf, key)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        size = os.fstat(fd).st_size
        if size != offset:
            raise ValueError(f"offset {offset} does not match the stored size {size}")
        os.lseek(fd, offset, os.SEEK_SET)
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        return offset + len(data)
    finally:
        os.close(fd)


def size_of(conf: AnalysisSettings, key: str) -> int:
    try:
        return path_of(conf, key).stat().st_size
    except FileNotFoundError:
        return 0


def delete(conf: AnalysisSettings, key: str | None) -> bool:
    if not key:
        return False
    try:
        path_of(conf, key).unlink()
        return True
    except FileNotFoundError:
        return False


def sweep(conf: AnalysisSettings, *, now: float | None = None) -> int:
    """Delete uploads (and stray work dirs) older than the max age. Returns files removed."""
    base = Path(conf.upload_dir)
    if not base.is_dir():
        return 0
    limit = (now or time.time()) - conf.file_max_age_hours * 3600
    removed = 0
    for entry in base.rglob("*"):
        try:
            if entry.is_symlink():
                entry.unlink()
                continue
            if entry.is_file() and entry.stat().st_mtime < limit:
                entry.unlink()
                removed += 1
            elif entry.is_dir() and entry.name.startswith("work-"):
                if entry.stat().st_mtime < limit:
                    shutil.rmtree(entry, ignore_errors=True)
        except FileNotFoundError:
            continue
    return removed


def work_dir(conf: AnalysisSettings, analysis_id: uuid.UUID) -> Path:
    path = root(conf) / f"work-{analysis_id}"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


# -- signed upload token --------------------------------------------------------------------


def _secret() -> bytes:
    raw = (
        os.environ.get("CONTENT_UPLOAD_SIGNING_SECRET", "").strip()
        or os.environ.get("SUPABASE_JWT_SECRET", "").strip()
    )
    if not raw:
        raise RuntimeError("no signing secret for content uploads")
    return hmac.new(raw.encode(), _TOKEN_DOMAIN, hashlib.sha256).digest()


def sign(analysis_id: uuid.UUID, shop_id: uuid.UUID, expires_at: datetime) -> str:
    expiry = (
        int(expires_at.timestamp())
        if expires_at.tzinfo
        else int((expires_at - datetime(1970, 1, 1)).total_seconds())
    )
    message = f"{analysis_id}:{shop_id}:{expiry}".encode()
    digest = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return f"{expiry}.{digest}"


def verify(
    token: str, analysis_id: uuid.UUID, shop_id: uuid.UUID, *, now: float | None = None
) -> bool:
    try:
        expiry_raw, digest = token.split(".", 1)
        expiry = int(expiry_raw)
    except (ValueError, AttributeError):
        return False
    if expiry < (now or time.time()):
        return False
    message = f"{analysis_id}:{shop_id}:{expiry}".encode()
    expected = hmac.new(_secret(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, digest)


__all__ = [
    "append_chunk",
    "delete",
    "path_of",
    "root",
    "sign",
    "size_of",
    "storage_key",
    "sweep",
    "verify",
    "work_dir",
]
