"""Onboarding progress for the client strip and Ops (fast track P17, D26 / D25.12).

``GET /v1/shops/me/onboarding`` (contract ``fasttrack/contracts/p17-onboarding-speed.md``
§2) reads only ``shop_ingestion_state`` and whether the shop's first diagnosis
report exists -- no TikTok call. Three steps:

1. **quick_scan** -- the "quét nhanh" (``quick_scan.run_quick_scan``);
2. **backfill_diagnosis** -- the fast phase, history to 60 days and the first
   ADR-108 diagnosis report;
3. **history** -- the nightly extension to 180 days (D25.12).

``history_days_available`` (:func:`history_days_available`) is the field P16's
simulation reads to unlock its 90-day window (2 × 90 days).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.ingestion import (
    BOOTSTRAP_FAILED,
    QUICK_SCAN_DONE,
    QUICK_SCAN_FAILED,
    QUICK_SCAN_RUNNING,
    QUICK_SCAN_SKIPPED,
    ShopIngestionState,
)
from juli_backend.services.onboarding.history import connect_days, history_target_days

STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_DONE = "done"
STEP_SKIPPED = "skipped"
STEP_FAILED = "failed"
TERMINAL = frozenset({STEP_DONE, STEP_SKIPPED, STEP_FAILED})

TOTAL_STEPS = 3
#: D25.12: the 90-day window compares two 90-day halves.
WINDOW_90D_DAYS = 180
ACTIVE_POLL_SECONDS = 15
HISTORY_POLL_SECONDS = 300

TYPICAL_SECONDS_ENV = "ONBOARDING_FULL_DIAGNOSIS_TYPICAL_SECONDS"
DEFAULT_TYPICAL_SECONDS = 900
#: A quick scan "running" for longer than this died with its worker.
QUICK_SCAN_STALE = timedelta(minutes=15)

STEP_LABELS = {
    "quick_scan": "Quét nhanh 14 ngày",
    "backfill_diagnosis": "Đọc 60 ngày và chẩn đoán đầy đủ",
    "history": "Tải lịch sử nền",
}


def typical_full_diagnosis_seconds() -> int:
    try:
        return max(60, int(os.getenv(TYPICAL_SECONDS_ENV, str(DEFAULT_TYPICAL_SECONDS))))
    except ValueError:
        return DEFAULT_TYPICAL_SECONDS


def history_days_available(state: ShopIngestionState | None) -> int:
    """Contiguous local days of analytics stored: through-date − earliest date + 1.

    0 before the fast phase has landed any day. The through-date is the last
    fully-fetched day (``analytics_through_date``), else TikTok's latest
    available date.
    """
    if state is None or state.fast_done_at is None or state.history_earliest_date is None:
        return 0
    through = state.analytics_through_date or state.latest_available_date
    if through is None:
        return 0
    return max(0, (through - state.history_earliest_date).days + 1)


@dataclass(frozen=True)
class HistoryProgress:
    days_available: int
    target_days: int
    complete: bool

    @property
    def remaining(self) -> int:
        return max(self.target_days - self.days_available, 0)

    @property
    def window_90d_available(self) -> bool:
        return self.days_available >= WINDOW_90D_DAYS


def history_progress(state: ShopIngestionState | None) -> HistoryProgress:
    """Days available vs the target (180, or what TikTok had once the walk ended)."""
    days = history_days_available(state)
    complete = state is not None and state.history_done_at is not None
    target = days if complete else history_target_days()
    if not complete and days >= target:
        complete = True
    return HistoryProgress(days_available=days, target_days=max(target, 0), complete=complete)


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None) if moment.tzinfo else moment


def _step(
    key: str,
    status: str,
    *,
    percent: int | None = None,
    eta_seconds: int | None = None,
    detail: str | None = None,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": STEP_LABELS[key],
        "status": status,
        "percent": percent,
        "eta_seconds": eta_seconds,
        "detail": detail,
    }


def _quick_step(state: ShopIngestionState | None, now: datetime) -> dict[str, Any]:
    raw = state.quick_scan_status if state is not None else None
    cards = (state.quick_scan_cards or 0) if state is not None else 0
    if raw == QUICK_SCAN_DONE:
        detail = f"{cards} đề xuất nhanh" if cards else "Chưa có đề xuất nhanh"
        return _step("quick_scan", STEP_DONE, percent=100, detail=detail)
    if raw == QUICK_SCAN_SKIPPED:
        return _step("quick_scan", STEP_SKIPPED, percent=100)
    if raw == QUICK_SCAN_FAILED:
        return _step("quick_scan", STEP_FAILED, percent=100)
    if raw == QUICK_SCAN_RUNNING:
        started = state.quick_scan_started_at if state is not None else None
        if started is not None and now - started > QUICK_SCAN_STALE:
            return _step("quick_scan", STEP_FAILED, percent=100)
        return _step("quick_scan", STEP_RUNNING, percent=50)
    if state is not None and state.fast_done_at is not None:
        # A shop connected before P17, or the scan never ran: nothing to wait for.
        return _step("quick_scan", STEP_SKIPPED, percent=100)
    return _step("quick_scan", STEP_PENDING, percent=0)


def _backfill_step(
    state: ShopIngestionState | None,
    history: HistoryProgress,
    *,
    report_exists: bool,
    now: datetime,
) -> dict[str, Any]:
    window = connect_days()
    days = min(history.days_available, window)
    percent = round(70 * days / window) + (30 if report_exists else 0)
    detail = f"{days}/{window} ngày"
    if state is None or state.fast_started_at is None:
        return _step("backfill_diagnosis", STEP_PENDING, percent=0, detail=detail)
    if state.status == BOOTSTRAP_FAILED and state.failed_phase == "fast":
        return _step("backfill_diagnosis", STEP_FAILED, percent=percent, detail=detail)
    window_ready = state.fast_done_at is not None and (
        history.days_available >= window or history.complete
    )
    if window_ready and report_exists:
        return _step("backfill_diagnosis", STEP_DONE, percent=100, detail=detail)
    elapsed = (now - state.fast_started_at).total_seconds()
    eta = max(0, round(typical_full_diagnosis_seconds() - elapsed))
    return _step(
        "backfill_diagnosis",
        STEP_RUNNING,
        percent=min(percent, 99),
        eta_seconds=eta,
        detail=detail,
    )


def _history_step(history: HistoryProgress, *, previous_done: bool) -> dict[str, Any]:
    target = history.target_days or 1
    percent = min(100, round(100 * history.days_available / target))
    if history.complete:
        return _step("history", STEP_DONE, percent=100, detail=f"{history.days_available} ngày")
    detail = f"Đang tải lịch sử · còn {history.remaining} ngày"
    status = STEP_RUNNING if previous_done else STEP_PENDING
    return _step("history", status, percent=percent, detail=detail)


def build_onboarding_status(
    state: ShopIngestionState | None,
    *,
    shop_id: uuid.UUID,
    report_exists: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The contract §2 response for one shop. Pure."""
    moment = _naive(now or datetime.now(UTC))
    history = history_progress(state)
    quick = _quick_step(state, moment)
    backfill = _backfill_step(state, history, report_exists=report_exists, now=moment)
    hist = _history_step(history, previous_done=backfill["status"] == STEP_DONE)
    steps = [quick, backfill, hist]
    active = quick["status"] not in TERMINAL or backfill["status"] not in TERMINAL
    current = next(
        (index for index, step in enumerate(steps, start=1) if step["status"] not in TERMINAL),
        None,
    )
    if active:
        label: str | None = f"Juli đang đọc dữ liệu shop · bước {current}/{TOTAL_STEPS}"
        poll: int | None = ACTIVE_POLL_SECONDS
    elif current == TOTAL_STEPS:
        label = f"Đang tải lịch sử · còn {history.remaining} ngày"
        poll = HISTORY_POLL_SECONDS
    else:
        label, poll = None, None
    return {
        "shop_id": str(shop_id),
        "active": active,
        "current_step": current,
        "total_steps": TOTAL_STEPS,
        "label": label,
        "poll_interval_seconds": poll,
        "steps": steps,
        "history_days_available": history.days_available,
        "history_target_days": history.target_days,
        "history_days_remaining": history.remaining,
        "history_complete": history.complete,
        "window_90d_available": history.window_90d_available,
    }


async def onboarding_status(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> dict[str, Any]:
    """Read the state and the report flag under the caller's shop scope, then build."""
    from juli_backend.models.shop_diagnosis import ShopDiagnosisReport
    from juli_backend.repositories import ShopIngestionStateRepo

    state = await ShopIngestionStateRepo(session).find(shop_id)
    reports = await session.execute(
        select(func.count())
        .select_from(ShopDiagnosisReport)
        .where(ShopDiagnosisReport.shop_id == shop_id)
    )
    return build_onboarding_status(
        state, shop_id=shop_id, report_exists=bool(reports.scalar_one()), now=now
    )


__all__ = [
    "ACTIVE_POLL_SECONDS",
    "HISTORY_POLL_SECONDS",
    "TOTAL_STEPS",
    "WINDOW_90D_DAYS",
    "HistoryProgress",
    "build_onboarding_status",
    "history_days_available",
    "history_progress",
    "onboarding_status",
]
