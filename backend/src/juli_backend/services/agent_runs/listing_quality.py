"""Đo lường on the sandbox shop: TikTok's own listing-quality diagnosis, before → now (P71).

The sandbox shop has no buyers and no traffic, so its runs are never measured on CTR,
views or CTOR (P66/P67). What it does have is TikTok's product diagnosis ("Tiêu đề quá
ngắn", "Mô tả chưa xuống dòng" ...): a listing-edit run's first step reads it
(``get_product_diagnoses``), and the run's stored conversation keeps that tool result.

* **Ngày 0** -- the issues the run's own diagnosis step read, from the run's stored
  state (``workflow_runs.state.conversation_window``). Nothing is stored anew.
* **Now** -- TikTok's diagnosis of the same product, re-read on demand when the sandbox
  reviewer's runs list is read (``GET /v1/demo/runs``, what Đo lường shows), cached per
  product for :data:`READ_TTL`. On-demand rather than a scheduled day-7 check: the
  measurement scheduler measures traffic metrics and has no sandbox reading, and a
  scheduled check would need somewhere new to store its result (a migration). The read
  is one TikTok call per product, only for the sandbox reviewer, only for listing-edit
  runs TikTok confirmed.

* **Sau sửa (TikTok kiểm tra)** -- P76-5: TikTok's own diagnosis of the draft the seller
  confirmed, asked right before the write (``diagnose_optimize``, stored on the write's
  ledger outcome by ``services/agent/tools/draft_scoring``). TikTok's live diagnosis of the
  sandbox lags (edge case D31: "4 lỗi → 4 lỗi" a day after an edit that met the criteria),
  so a title / description code the live reading still lists but that check cleared is
  labelled as TikTok's not-yet-updated diagnosis, not as "chưa cải thiện".

When the run's diagnosis step found nothing readable, or TikTok cannot be read now,
the side is ``None`` -- never a guessed count.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DIAGNOSIS_TOOL = "get_product_diagnoses"
#: How long one product's re-read diagnosis is reused (the runs list is polled).
READ_TTL_SECONDS = 600.0
#: A failed read is retried sooner.
FAILED_TTL_SECONDS = 60.0
#: At most this many runs get a re-read per list (newest first).
MAX_RUNS = 5


@dataclass(frozen=True)
class DiagnosisReading:
    """TikTok's diagnosis of one listing: how many issues and their short VN labels."""

    count: int
    issues: tuple[str, ...]
    read_at: str | None = None
    #: The codes behind ``issues`` (not serialized; the stale check compares codes).
    codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ListingQuality:
    """Ngày 0 (the run's own diagnosis step), now (re-read) and -- P76-5 -- TikTok's check
    of the written draft (``checked``); any may be unknown. ``stale_issues``: the labels of
    the ``after`` issues TikTok's check had cleared (internal; on the wire they are marked in
    ``after.issues``)."""

    before: DiagnosisReading | None
    after: DiagnosisReading | None
    checked: DiagnosisReading | None = None
    stale_issues: tuple[str, ...] = ()


#: (shop id, TikTok product id) -> (monotonic time read, reading or None when unread).
_cache: dict[tuple[uuid.UUID, str], tuple[float, DiagnosisReading | None]] = {}


def reset_cache() -> None:
    _cache.clear()


def _labels(codes: Any) -> tuple[str, ...]:
    labels: list[str] = []
    for code in codes if isinstance(codes, list) else []:
        label = code.get("label_vi") if isinstance(code, dict) else None
        if isinstance(label, str) and label and label not in labels:
            labels.append(label)
    return tuple(labels)


def day0_reading(state: Any) -> DiagnosisReading | None:
    """The first readable ``get_product_diagnoses`` result in the run's stored conversation."""
    window = state.get("conversation_window") if isinstance(state, dict) else None
    for message in window if isinstance(window, list) else []:
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        if message.get("tool_name") != DIAGNOSIS_TOOL:
            continue
        content = message.get("content")
        if not isinstance(content, dict) or content.get("unavailable") is True:
            continue
        codes = content.get("codes")
        count = content.get("count")
        if not isinstance(count, int) or isinstance(count, bool):
            count = len(codes) if isinstance(codes, list) else 0
        return DiagnosisReading(count=count, issues=_labels(codes))
    return None


def checked_reading(score: Any) -> DiagnosisReading | None:
    """P76-5: the "Sau sửa (TikTok kiểm tra)" reading from a stored ``DraftScore``;
    ``None`` when the draft was not scored or TikTok's check was not read."""
    from juli_backend.services.agent.tools.diagnosis_labels import diagnosis_label_vi
    from juli_backend.services.agent.tools.draft_scoring import STATUS_SCORED

    if score is None or getattr(score, "status", None) != STATUS_SCORED:
        return None
    codes = tuple(score.codes_after)
    labels = tuple(dict.fromkeys(diagnosis_label_vi(code) for code in codes))
    return DiagnosisReading(count=len(codes), issues=labels, read_at=score.scored_at, codes=codes)


def mark_stale(
    now: DiagnosisReading | None, checked: DiagnosisReading | None
) -> tuple[DiagnosisReading | None, tuple[str, ...]]:
    """``now`` with each title / description code TikTok's check of the draft cleared but
    the live diagnosis still lists relabelled as TikTok's stale diagnosis, and those labels.

    Only title / description codes: those are what a listing edit changes; any other code
    the two readings disagree on is left as TikTok reads it now.
    """
    from juli_backend.services.agent.tools.diagnosis_labels import (
        diagnosis_label_vi,
        stale_diagnosis_label_vi,
    )
    from juli_backend.services.optimize_product.listing_signals import (
        is_description_code,
        is_title_code,
    )

    if now is None or checked is None:
        return now, ()
    cleared = {
        code
        for code in now.codes
        if code not in checked.codes and (is_title_code(code) or is_description_code(code))
    }
    if not cleared:
        return now, ()
    labels = tuple(
        dict.fromkeys(
            stale_diagnosis_label_vi(code) if code in cleared else diagnosis_label_vi(code)
            for code in now.codes
        )
    )
    stale = tuple(
        dict.fromkeys(stale_diagnosis_label_vi(code) for code in now.codes if code in cleared)
    )
    return DiagnosisReading(
        count=now.count, issues=labels, read_at=now.read_at, codes=now.codes
    ), stale


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _read_now(resources: Any, product_id: str) -> DiagnosisReading:
    from juli_backend.services.agent.tools.product import parse_diagnosis_codes

    raw = resources.products.get_diagnoses([product_id])
    codes = parse_diagnosis_codes(raw if isinstance(raw, dict) else {}, product_id=product_id)
    return DiagnosisReading(
        count=len(codes),
        issues=_labels(codes),
        read_at=_now_iso(),
        codes=tuple(str(code["code"]) for code in codes),
    )


async def _resources(session: AsyncSession, shop_id: uuid.UUID) -> Any:
    """The sandbox shop's TikTok read resources (a seam for tests)."""
    from juli_backend.services.agent.composition import build_read_resources

    return await build_read_resources(session, shop_id)


async def current_readings(
    session: AsyncSession,
    shop_id: uuid.UUID,
    product_ids: list[str],
    *,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, DiagnosisReading | None]:
    """TikTok's diagnosis of each product now (cached :data:`READ_TTL_SECONDS`).

    A product TikTok could not be read for maps to ``None`` (also cached, so a failing
    TikTok is not hammered by the poll).
    """
    now = clock()
    found: dict[str, DiagnosisReading | None] = {}
    missing: list[str] = []
    for product_id in dict.fromkeys(product_ids):
        cached = _cache.get((shop_id, product_id))
        if cached is not None:
            ttl = READ_TTL_SECONDS if cached[1] is not None else FAILED_TTL_SECONDS
            if now - cached[0] < ttl:
                found[product_id] = cached[1]
                continue
        missing.append(product_id)
    if not missing:
        return found
    try:
        resources = await _resources(session, shop_id)
    except Exception:
        logger.warning("listing_quality_unread", extra={"shop_id": str(shop_id)}, exc_info=True)
        for product_id in missing:
            _cache[(shop_id, product_id)] = (now, None)
            found[product_id] = None
        return found

    async def read(product_id: str) -> DiagnosisReading | None:
        try:
            return await asyncio.to_thread(_read_now, resources, product_id)
        except Exception:
            # TikTok / credential / network: unknown, never "0 lỗi".
            logger.warning(
                "listing_quality_unread",
                extra={"shop_id": str(shop_id), "product_id": product_id},
                exc_info=True,
            )
            return None

    readings = await asyncio.gather(*(read(product_id) for product_id in missing))
    for product_id, reading in zip(missing, readings, strict=True):
        _cache[(shop_id, product_id)] = (now, reading)
        found[product_id] = reading
    return found


__all__ = [
    "FAILED_TTL_SECONDS",
    "MAX_RUNS",
    "READ_TTL_SECONDS",
    "DiagnosisReading",
    "ListingQuality",
    "checked_reading",
    "current_readings",
    "day0_reading",
    "mark_stale",
    "reset_cache",
]
