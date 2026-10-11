"""History-window settings shared by the ingestion walk and the onboarding status (P17, D25.12).

- ``SHOP_HISTORY_MAX_LOOKBACK_DAYS`` (default **180**, was 1095): how far back
  the history walk goes. The Partner docs for the shop analytics reads Juli uses
  (A-34 202605 product list; 202509 shop / product / SKU / video / LIVE) state no
  maximum look-back; the only documented limit in ``api-reference/analytics/``
  is 180 days (Get Video Performances 202403: "start_time must be within the
  last 180 days"), and the hourly shop read keeps 30 days. The walk targets 180
  and stops earlier at TikTok's real limit when TikTok refuses a window
  (``28001022``, halved down to the exact day) or returns two empty chunks.
- ``SHOP_HISTORY_CONNECT_DAYS`` (60): the history chain right after connect
  stops once this many days exist; the rest is the nightly extension.
- ``SHOP_HISTORY_NIGHTLY_CHUNKS`` (2) × ``SHOP_HISTORY_NIGHTLY_CHUNK_DAYS`` (15):
  what one nightly run reads (60 -> 180 days in 4 nights).
"""

from __future__ import annotations

import os

MAX_LOOKBACK_DAYS_ENV = "SHOP_HISTORY_MAX_LOOKBACK_DAYS"
CONNECT_DAYS_ENV = "SHOP_HISTORY_CONNECT_DAYS"
NIGHTLY_CHUNKS_ENV = "SHOP_HISTORY_NIGHTLY_CHUNKS"
NIGHTLY_CHUNK_DAYS_ENV = "SHOP_HISTORY_NIGHTLY_CHUNK_DAYS"

DEFAULT_MAX_LOOKBACK_DAYS = 180
#: D25.12's target: 180 days, i.e. two 90-day halves.
HISTORY_TARGET_DAYS = 180
DEFAULT_CONNECT_DAYS = 60
DEFAULT_NIGHTLY_CHUNKS = 2
DEFAULT_NIGHTLY_CHUNK_DAYS = 15


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    return max(minimum, value)


def max_lookback_days() -> int:
    return _env_int(MAX_LOOKBACK_DAYS_ENV, DEFAULT_MAX_LOOKBACK_DAYS)


def history_target_days() -> int:
    return min(HISTORY_TARGET_DAYS, max_lookback_days())


def connect_days() -> int:
    return _env_int(CONNECT_DAYS_ENV, DEFAULT_CONNECT_DAYS)


def nightly_chunks() -> int:
    return _env_int(NIGHTLY_CHUNKS_ENV, DEFAULT_NIGHTLY_CHUNKS)


def nightly_chunk_days() -> int:
    return _env_int(NIGHTLY_CHUNK_DAYS_ENV, DEFAULT_NIGHTLY_CHUNK_DAYS)


__all__ = [
    "CONNECT_DAYS_ENV",
    "DEFAULT_MAX_LOOKBACK_DAYS",
    "HISTORY_TARGET_DAYS",
    "MAX_LOOKBACK_DAYS_ENV",
    "NIGHTLY_CHUNKS_ENV",
    "NIGHTLY_CHUNK_DAYS_ENV",
    "connect_days",
    "history_target_days",
    "max_lookback_days",
    "nightly_chunk_days",
    "nightly_chunks",
]
