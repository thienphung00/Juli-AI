"""The content runs' poll cycle: auto-detect, and the measurement readings (P14-E).

Run hourly per shop by the ``content_runs_poll`` beat (``workers/tasks/
content_runs.py``), read-only on TikTok:

- a run **waiting for the video / the LIVE** (``content_publish``): a new
  video tagging the product with impressions, or a LIVE session selling it,
  since the seller chose the script → the run is marked published
  (``published_by="auto"``) and resumed; it then confirms with
  ``find_new_content`` and starts measuring;
- a run **measuring**: video — the new videos' and the old videos' product
  impressions / clicks (day 7 and day 14 readings kept once); LIVE — the
  product's clicks / SKU orders in the next 3 sessions selling it and in the
  session(s) before (``prior_ctor``).

Only the run's content state is written (``run_state``); nothing here calls a
model. The caller commits, then enqueues the resumes it is handed.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.models import Product
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.content_cards import run_state
from juli_backend.services.content_cards.constants import CONTENT_WORKFLOW_KEYS, VIDEO
from juli_backend.services.content_cards.tools import (
    find_new_sessions,
    find_new_videos,
    list_sessions,
    list_videos,
    live_product_counts,
    session_product,
    shop_today,
)

logger = logging.getLogger(__name__)

#: A finished content run is polled for readings this long after it started measuring.
MEASURE_POLL_DAYS = 45
OLD_WINDOW_DAYS = 30
PRIOR_SESSIONS = 3


@dataclass
class PollReport:
    detected: list[uuid.UUID] = field(default_factory=list)
    measured: list[uuid.UUID] = field(default_factory=list)
    errors: int = 0


def _f(value: Any) -> float:
    if isinstance(value, Mapping):
        value = value.get("amount")
    try:
        return float(str(value).rstrip("%")) if value is not None else 0.0
    except ValueError:
        return 0.0


def _tags(row: Mapping[str, Any], product_id: str) -> bool:
    return any(
        isinstance(p, Mapping) and str(p.get("id") or "") == product_id
        for p in row.get("products") or []
    )


def _posted(row: Mapping[str, Any]) -> date | None:
    raw = str(row.get("video_post_time") or "").strip()
    try:
        return (
            datetime.fromisoformat(raw.replace("T", " ").removesuffix("Z")).date() if raw else None
        )
    except ValueError:
        return None


def video_reading(resources: Any, product_id: str, day0: date, today: date) -> dict[str, Any]:
    """New vs old videos of the product, as of ``today`` (window capped at day 14)."""
    end = min(today, day0 + timedelta(days=14))
    new_rows = [
        r
        for r in list_videos(resources, day0.isoformat(), (end + timedelta(days=1)).isoformat())
        if _tags(r, product_id) and (_posted(r) or date.min) >= day0
    ]
    old_rows = [
        r
        for r in list_videos(
            resources, (day0 - timedelta(days=OLD_WINDOW_DAYS)).isoformat(), day0.isoformat()
        )
        if _tags(r, product_id) and (_posted(r) or date.max) < day0
    ]
    new_impr = sum(_f(r.get("product_impressions")) for r in new_rows)
    new_clicks = sum(_f(r.get("product_clicks")) for r in new_rows)
    old_impr = sum(_f(r.get("product_impressions")) for r in old_rows)
    old_clicks = sum(_f(r.get("product_clicks")) for r in old_rows)
    return {
        "as_of": end.isoformat(),
        "days": (end - day0).days,
        "videos": len(new_rows),
        "new_impressions": int(new_impr),
        "new_clicks": int(new_clicks),
        "new_rate": new_clicks / new_impr if new_impr else None,
        "old_impressions": int(old_impr),
        "old_clicks": int(old_clicks),
        "old_rate": old_clicks / old_impr if old_impr else None,
    }


def apply_video_reading(readings: dict[str, Any], reading: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the latest reading; freeze the day-7 and day-14 ones the first time they are due."""
    readings = dict(readings)
    readings["latest"] = dict(reading)
    days = int(reading.get("days") or 0)
    if days >= 7 and not isinstance(readings.get("day7"), Mapping):
        readings["day7"] = dict(reading)
    if days >= 14 and not isinstance(readings.get("day14"), Mapping):
        readings["day14"] = dict(reading)
    return readings


def _session_day(row: Mapping[str, Any]) -> date | None:
    raw = str(row.get("start_time") or "").strip()
    if not raw.isdigit():
        return None
    return (datetime.fromtimestamp(int(raw), tz=UTC) + timedelta(hours=7)).date()


def prior_live_ctor(resources: Any, product_id: str, day0: date) -> float | None:
    """The product's CTOR over its last ≤ 3 sessions before day 0 (30 days back)."""
    sessions = [
        s
        for s in list_sessions(
            resources, (day0 - timedelta(days=OLD_WINDOW_DAYS)).isoformat(), day0.isoformat()
        )
        if (_session_day(s) or date.max) < day0
    ]
    sessions.sort(key=lambda s: -int(_f(s.get("start_time"))))
    clicks = orders = 0
    used = 0
    for session in sessions:
        if used >= PRIOR_SESSIONS:
            break
        live_id = str(session.get("id") or "")
        if not live_id:
            continue
        product, _pos, _n = session_product(resources, live_id, product_id)
        if product is None:
            continue
        _impr, c, o = live_product_counts(product)
        clicks += c
        orders += o
        used += 1
    return orders / clicks if clicks else None


def live_readings(
    resources: Any, product_id: str, day0: date, today: date, readings: Mapping[str, Any]
) -> dict[str, Any]:
    out = dict(readings)
    if "prior_ctor" not in out:
        out["prior_ctor"] = prior_live_ctor(resources, product_id, day0)
    found = find_new_sessions(resources, product_id, day0, today, limit=3)
    out["sessions"] = [
        {
            "ref": f.ref,
            "day": f.day,
            "clicks": f.product_clicks,
            "orders": f.product_sku_orders,
            "ctor": (f.product_sku_orders / f.product_clicks) if f.product_clicks else None,
        }
        for f in found[:3]
    ]
    return out


async def _content_runs(
    session: AsyncSession, shop_id: uuid.UUID, now: datetime
) -> list[WorkflowRunRow]:
    since = (now - timedelta(days=MEASURE_POLL_DAYS)).replace(tzinfo=None)
    rows = (
        await session.execute(
            select(WorkflowRunRow).where(
                WorkflowRunRow.shop_id == shop_id,
                WorkflowRunRow.workflow_key.in_(CONTENT_WORKFLOW_KEYS),
                WorkflowRunRow.created_at >= since,
                WorkflowRunRow.status.in_(("waiting_external", "completed")),
            )
        )
    ).scalars()
    return list(rows)


async def has_pollable_runs(
    session: AsyncSession, shop_id: uuid.UUID, *, now: datetime | None = None
) -> bool:
    for run in await _content_runs(session, shop_id, now or datetime.now(UTC)):
        state = run_state.state_of(run) or {}
        if (
            run.status == "waiting_external"
            and run.external_wait_reason == run_state.AWAITING_PUBLISH
        ):
            return True
        if run.status == "completed" and state.get("stage") == run_state.STAGE_MEASURING:
            return True
    return False


async def poll_shop(
    session: AsyncSession,
    shop_id: uuid.UUID,
    resources: Any,
    *,
    now: datetime | None = None,
) -> PollReport:
    """One poll of one shop's content runs (module docstring). No commit."""
    now = now or datetime.now(UTC)
    today = shop_today(now)
    report = PollReport()
    for run in await _content_runs(session, shop_id, now):
        state = run_state.state_of(run)
        if state is None or run.product_id is None:
            continue
        product = await session.get(Product, run.product_id)
        if product is None:
            continue
        pid = str(product.tiktok_product_id)
        video = state.get("kind") == VIDEO
        try:
            if (
                run.status == "waiting_external"
                and run.external_wait_reason == run_state.AWAITING_PUBLISH
            ):
                since = date.fromisoformat(str(state.get("chosen_at") or today.isoformat())[:10])
                found = (
                    find_new_videos(resources, pid, since, today)
                    if video
                    else find_new_sessions(resources, pid, since, today, limit=1)
                )
                if not found:
                    continue
                state["detected"] = found[0].model_dump(mode="json")
                state["stage"] = run_state.STAGE_PUBLISHED
                state["published_by"] = "auto"
                state["published_at"] = state.get("published_at") or now.isoformat()
                state["detect_rounds"] = int(state.get("detect_rounds") or 0) + 1
                run_state.save_state(run, state)
                report.detected.append(run.id)
                continue
            if run.status == "completed" and state.get("stage") == run_state.STAGE_MEASURING:
                start = state.get("measurement_start")
                if not isinstance(start, str):
                    continue
                day0 = date.fromisoformat(start)
                readings = state.get("readings") or {}
                if video:
                    if isinstance(readings.get("day14"), Mapping):
                        continue
                    readings = apply_video_reading(
                        readings, video_reading(resources, pid, day0, today)
                    )
                else:
                    if len(readings.get("sessions") or []) >= 3:
                        continue
                    readings = live_readings(resources, pid, day0, today, readings)
                state["readings"] = readings
                run_state.save_state(run, state)
                report.measured.append(run.id)
        except Exception:  # one run's TikTok failure never stops the shop's other runs
            report.errors += 1
            logger.warning("content_run_poll_failed", extra={"run_id": str(run.id)}, exc_info=True)
    await session.flush()
    return report


__all__ = [
    "PollReport",
    "apply_video_reading",
    "has_pollable_runs",
    "live_readings",
    "poll_shop",
    "prior_live_ctor",
    "video_reading",
]
