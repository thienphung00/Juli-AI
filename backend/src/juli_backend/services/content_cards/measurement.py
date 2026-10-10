"""Measurement of a content run (contract §4, D24.18).

- **Video**: CTR of the NEW videos tagging the product (posted on or after day
  0 = the new video's post day, else the "Tôi đã đăng video" day) against the
  product's OLD videos (posted in the 30 days before day 0), read at day 7
  (preliminary) and day 14 (final).
- **LIVE**: the product's CTOR over the next **3** sessions selling it against
  the session(s) before day 0. 1–2 sessions = preliminary, 3 = final.

Readings are taken by the hourly poll (``poll``) from TikTok and kept in the
run's content state; this module only turns them into the P10 §6 body, so the
GET never calls TikTok. The final label and the per-lever calibration
(``video_script`` / ``live_script``) follow P10: progress toward the target is
the realised share of the expected GMV, ≥ 100 % and target reached = Đạt,
70–99 % = Gần đạt, < 70 % = Không đạt, too little data = Chưa kết luận (no
calibration update). Stored once in ``run_measurement_finals``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from juli_backend.models.lever_flows import RunMeasurementFinal
from juli_backend.models.models import ActionCard
from juli_backend.models.models import WorkflowRun as WorkflowRunRow
from juli_backend.services.content_cards import run_state
from juli_backend.services.content_cards.constants import (
    SPEC_BY_WORKFLOW,
    VIDEO,
    ContentKind,
)
from juli_backend.services.content_cards.copy import pct
from juli_backend.services.content_cards.emission import payload_of
from juli_backend.services.lever_flows import measurement as p10

#: Too little data for a conclusion: product impressions on the new videos
#: (video) / product clicks over the new sessions (LIVE).
MIN_NEW_IMPRESSIONS = 1_000
MIN_NEW_CLICKS = 30
LIVE_SESSIONS = 3

STAGE_WAITING = p10.STAGE_WAITING
STAGE_DAY7 = p10.STAGE_DAY7
STAGE_FINAL = p10.STAGE_FINAL


def progress_pct(before: float | None, after: float | None, target: float | None) -> int | None:
    """How far the rate moved toward the target, in % of the gap (the expected GMV's share)."""
    if before is None or after is None or target is None or target <= before:
        return None
    share = Decimal(str((after - before) / (target - before))) * 100
    return int(share.to_integral_value(rounding=ROUND_HALF_UP))


def _verdict(before: float | None, actual: float | None, target: float | None) -> tuple[str, str]:
    if actual is None or before is None:
        return "Chưa có số liệu", "muted"
    if target is not None and actual >= target:
        return "Đạt mục tiêu", "ok"
    if actual > before:
        return "Đang tăng", "ok"
    if actual < before:
        return "Đang giảm", "warn"
    return "Ổn định", "muted"


def video_stage(readings: Mapping[str, Any]) -> str:
    if isinstance(readings.get("day14"), Mapping):
        return STAGE_FINAL
    if isinstance(readings.get("day7"), Mapping):
        return STAGE_DAY7
    return STAGE_WAITING


def live_stage(readings: Mapping[str, Any]) -> str:
    sessions = [s for s in readings.get("sessions") or [] if isinstance(s, Mapping)]
    if len(sessions) >= LIVE_SESSIONS:
        return STAGE_FINAL
    return STAGE_DAY7 if sessions else STAGE_WAITING


def live_totals(readings: Mapping[str, Any]) -> tuple[int, int, float | None]:
    sessions = [s for s in readings.get("sessions") or [] if isinstance(s, Mapping)][:LIVE_SESSIONS]
    clicks = sum(int(s.get("clicks") or 0) for s in sessions)
    orders = sum(int(s.get("orders") or 0) for s in sessions)
    return clicks, orders, (orders / clicks if clicks else None)


def _rows_video(reading: Mapping[str, Any] | None, target: float | None) -> list[dict[str, Any]]:
    if not isinstance(reading, Mapping):
        return []
    before = reading.get("old_rate")
    actual = reading.get("new_rate")
    verdict, tone = _verdict(before, actual, target)
    return [
        {
            "key": "video_ctr",
            "label": "CTR video mới (chỉ số chính)",
            "before": before,
            "expected": pct(target),
            "actual": actual,
            "verdict": verdict,
            "tone": tone,
        },
        {
            "key": "new_videos",
            "label": "Video mới gắn sản phẩm",
            "before": None,
            "expected": "≥ 1",
            "actual": reading.get("videos"),
            "verdict": "Đã có" if (reading.get("videos") or 0) > 0 else "Chưa có",
            "tone": "muted",
        },
        {
            "key": "impressions",
            "label": "Lượt hiển thị sản phẩm từ video mới",
            "before": reading.get("old_impressions"),
            "expected": "—",
            "actual": reading.get("new_impressions"),
            "verdict": "Sơ bộ",
            "tone": "muted",
        },
    ]


def _rows_live(readings: Mapping[str, Any], target: float | None) -> list[dict[str, Any]]:
    sessions = [s for s in readings.get("sessions") or [] if isinstance(s, Mapping)][:LIVE_SESSIONS]
    if not sessions:
        return []
    before = readings.get("prior_ctor")
    _clicks, _orders, overall = live_totals(readings)
    verdict, tone = _verdict(before, overall, target)
    rows = [
        {
            "key": "live_ctor",
            "label": "CTOR trong LIVE (chỉ số chính)",
            "before": before,
            "expected": pct(target),
            "actual": overall,
            "verdict": verdict,
            "tone": tone,
        }
    ]
    for index, session in enumerate(sessions, start=1):
        v, t = _verdict(before, session.get("ctor"), target)
        day = str(session.get("day") or "")
        rows.append(
            {
                "key": f"session_{index}",
                "label": f"Phiên {index}"
                + (f" · {day[8:10]}/{day[5:7]}" if len(day) >= 10 else ""),
                "before": before,
                "expected": pct(target),
                "actual": session.get("ctor"),
                "verdict": v,
                "tone": t,
            }
        )
    return rows


async def _final(
    session: AsyncSession,
    *,
    shop_id: uuid.UUID,
    run: WorkflowRunRow,
    lever: str,
    before: float | None,
    actual: float | None,
    target: float | None,
    expected_per_day: float | None,
    thin: bool,
) -> dict[str, Any]:
    stored = (
        await session.execute(
            select(RunMeasurementFinal).where(
                RunMeasurementFinal.shop_id == shop_id,
                RunMeasurementFinal.workflow_run_id == run.id,
            )
        )
    ).scalar_one_or_none()
    if stored is not None:
        return p10._final_body(stored)
    share = progress_pct(before, actual, target)
    reached = actual is not None and target is not None and actual >= target
    label = p10.final_label(target_reached=reached, pct_of_expected=share, inconclusive=thin)
    gmv_actual = (
        Decimal(str(expected_per_day)) * Decimal(share) / 100
        if share is not None and expected_per_day is not None
        else None
    )
    if label == p10.LABEL_CHUA_KET_LUAN or share is None:
        cal_from = cal_to = await p10.current_calibration(session, shop_id, lever)
    else:
        cal_from, cal_to = await p10._update_calibration(
            session, shop_id, lever, Decimal(share) / 100
        )
    row = RunMeasurementFinal(
        shop_id=shop_id,
        workflow_run_id=run.id,
        lever=lever,
        label=label,
        gmv_actual_per_day=(
            gmv_actual.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            if gmv_actual is not None
            else None
        ),
        pct_of_expected=share,
        calibration_from=cal_from,
        calibration_to=cal_to,
    )
    session.add(row)
    await session.flush()
    return p10._final_body(row)


async def measure_content_run(
    session: AsyncSession, shop_id: uuid.UUID, run: WorkflowRunRow
) -> dict[str, Any]:
    """The contract §4 body for a content run; ``NotMeasurable`` before it starts."""
    spec = SPEC_BY_WORKFLOW.get(run.workflow_key)
    state = run_state.state_of(run)
    if run.shop_id != shop_id or spec is None or state is None:
        raise p10.NotMeasurable("not_found", "Không tìm thấy lượt chạy.")
    start = state.get("measurement_start")
    if state.get("stage") != run_state.STAGE_MEASURING or not isinstance(start, str):
        raise p10.NotMeasurable(
            "not_started",
            "Juli chưa thấy video hay phiên LIVE mới, nên chưa bắt đầu đo.",
        )
    kind: ContentKind = spec.kind
    card = await session.get(ActionCard, run.action_card_id) if run.action_card_id else None
    content = (
        payload_of(card).get("content") if card is not None and card.shop_id == shop_id else None
    )
    content = content if isinstance(content, Mapping) else {}
    target = (
        content.get("target")
        if isinstance(content.get("target"), int | float)
        else state.get("target")
    )
    current = (
        content.get("current")
        if isinstance(content.get("current"), int | float)
        else state.get("current")
    )
    expected = content.get("recoverable_gmv_per_day")
    expected = float(expected) if isinstance(expected, int | float) else None
    readings = state.get("readings") or {}
    d0 = date.fromisoformat(start)
    out_extra: dict[str, Any]
    if kind == VIDEO:
        stage = video_stage(readings)
        reading = readings.get("day14") if stage == STAGE_FINAL else readings.get("day7")
        before = reading.get("old_rate") if isinstance(reading, Mapping) else current
        rows = _rows_video(reading if stage != STAGE_WAITING else None, target)
        actual = reading.get("new_rate") if isinstance(reading, Mapping) else None
        thin = (
            not isinstance(reading, Mapping)
            or int(reading.get("new_impressions") or 0) < MIN_NEW_IMPRESSIONS
            or reading.get("old_rate") is None
        )
        dates = {
            "day7": (d0 + timedelta(days=7)).isoformat(),
            "day14": (d0 + timedelta(days=14)).isoformat(),
        }
        latest = readings.get("latest") if isinstance(readings.get("latest"), Mapping) else {}
        out_extra = {
            "kind": kind,
            "sessions_done": None,
            "sessions_needed": None,
            "new_videos": latest.get("videos") if isinstance(latest, Mapping) else None,
        }
    else:
        stage = live_stage(readings)
        before = readings.get("prior_ctor", current)
        clicks, _orders, actual = live_totals(readings)
        rows = _rows_live(readings, target)
        thin = clicks < MIN_NEW_CLICKS or before is None
        sessions = [s for s in readings.get("sessions") or [] if isinstance(s, Mapping)]
        days = [str(s.get("day")) for s in sessions if s.get("day")]
        dates = {
            "day7": days[0] if days else (d0 + timedelta(days=7)).isoformat(),
            "day14": days[2] if len(days) >= 3 else (d0 + timedelta(days=14)).isoformat(),
        }
        out_extra = {
            "kind": kind,
            "sessions_done": min(len(sessions), LIVE_SESSIONS),
            "sessions_needed": LIVE_SESSIONS,
            "new_videos": None,
        }
    final = None
    if stage == STAGE_FINAL:
        final = await _final(
            session,
            shop_id=shop_id,
            run=run,
            lever=spec.lever_code,
            before=before if isinstance(before, int | float) else None,
            actual=actual if isinstance(actual, int | float) else None,
            target=float(target) if isinstance(target, int | float) else None,
            expected_per_day=expected,
            thin=thin,
        )
    return {
        "stage": stage,
        "dates": dates,
        "target": {
            "label": spec.kpi_label,
            "current": current,
            "target": target,
            "progress_from": before if isinstance(before, int | float) else current,
            "unit": "ratio",
        },
        "expected_gmv_per_day": round(expected) if expected is not None else None,
        "bands": [],
        "rows": rows if stage != STAGE_WAITING else [],
        "day7": None,
        "final": final,
        "content": out_extra,
    }


def is_content_run(run: WorkflowRunRow) -> bool:
    return run.workflow_key in SPEC_BY_WORKFLOW


__all__ = [
    "LIVE_SESSIONS",
    "MIN_NEW_CLICKS",
    "MIN_NEW_IMPRESSIONS",
    "is_content_run",
    "live_stage",
    "live_totals",
    "measure_content_run",
    "progress_pct",
    "video_stage",
]
