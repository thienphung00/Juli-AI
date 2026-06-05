"""Shared time-window helpers for feature builders."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd


def parse_timestamp(value: str | None) -> datetime | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value)
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def resolve_reference_date(manifest: dict[str, Any], orders: pd.DataFrame) -> datetime:
    date_range = manifest.get("date_range") or {}
    end = date_range.get("end")
    if end:
        return datetime.fromisoformat(str(end)).replace(tzinfo=UTC)

    if not orders.empty and "created_at" in orders.columns:
        timestamps = orders["created_at"].map(parse_timestamp).dropna()
        if not timestamps.empty:
            return timestamps.max()

    return datetime.now(UTC)


def window_start(reference: datetime, days: int = 30) -> datetime:
    return reference - timedelta(days=days)


def in_last_n_days(series: pd.Series, reference: datetime, days: int = 30) -> pd.Series:
    cutoff = window_start(reference, days)
    parsed = series.map(parse_timestamp)
    return parsed.map(lambda value: value is not None and cutoff <= value <= reference)
