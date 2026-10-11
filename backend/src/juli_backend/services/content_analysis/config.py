"""Settings of the content-analysis pipeline (fast track P15), from the environment.

Every value has a default; nothing here is a secret. The OpenAI key is read by
the OpenAI calls themselves (``require_env("OPENAI_API_KEY")``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

VIDEO = "video"
LIVE = "live"
KINDS = (VIDEO, LIVE)

#: The only containers accepted (ffprobe ``format_name`` of the mov demuxer).
CONTENT_TYPES: dict[str, str] = {"video/mp4": ".mp4", "video/quicktime": ".mov"}
EXTENSIONS = (".mp4", ".mov")

MB = 1024 * 1024

#: USD per audio minute, OpenAI transcription (to verify against the price page
#: when the model changes; an unlisted model is priced at the highest rate).
ASR_USD_PER_MINUTE: dict[str, float] = {
    "whisper-1": 0.006,
    "gpt-4o-transcribe": 0.006,
    "gpt-4o-mini-transcribe": 0.003,
}
ASR_DEFAULT_USD_PER_MINUTE = 0.006


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    try:
        return float(raw) if raw else default
    except ValueError:
        return default


def _str(name: str, default: str) -> str:
    return os.environ.get(name, "").strip() or default


@dataclass(frozen=True)
class AnalysisSettings:
    #: Where uploads are written. NOT web-served; mode 0700, files 0600.
    upload_dir: str
    video_max_bytes: int
    video_max_seconds: float
    live_max_bytes: int
    live_max_seconds: float
    #: Each upload request carries at most this many bytes (Cloudflare caps a
    #: request body at 100 MB on the Free/Pro plans).
    chunk_bytes: int
    #: Hours an upload may take before its slot expires.
    upload_ttl_hours: int
    #: A file still on disk this long after it was written is deleted (failed runs).
    file_max_age_hours: int
    asr_model: str
    vision_model: str
    scoring_model: str
    #: LIVE without TikTok product timing: at most this many minutes are transcribed
    #: while looking for the product's mentions.
    live_scan_max_minutes: int
    live_window_before_s: float
    live_window_after_s: float
    live_max_windows: int
    keyframe_every_s: float
    ffmpeg: str
    ffprobe: str
    #: Wall-clock limit of one ffmpeg / ffprobe call (seconds).
    ffmpeg_timeout_s: float
    #: Uploads in flight (awaiting upload / queued / processing) per shop.
    max_in_flight: int


def settings() -> AnalysisSettings:
    return AnalysisSettings(
        upload_dir=_str("CONTENT_ANALYSIS_UPLOAD_DIR", "/var/lib/juli/content-uploads"),
        video_max_bytes=_int("CONTENT_ANALYSIS_VIDEO_MAX_MB", 500) * MB,
        video_max_seconds=_float("CONTENT_ANALYSIS_VIDEO_MAX_SECONDS", 600.0),
        live_max_bytes=_int("CONTENT_ANALYSIS_LIVE_MAX_MB", 4096) * MB,
        live_max_seconds=_float("CONTENT_ANALYSIS_LIVE_MAX_SECONDS", 3 * 3600.0),
        chunk_bytes=_int("CONTENT_ANALYSIS_CHUNK_MB", 32) * MB,
        upload_ttl_hours=_int("CONTENT_ANALYSIS_UPLOAD_TTL_HOURS", 6),
        file_max_age_hours=_int("CONTENT_ANALYSIS_FILE_MAX_AGE_HOURS", 24),
        asr_model=_str("CONTENT_ANALYSIS_ASR_MODEL", "whisper-1"),
        vision_model=_str("CONTENT_ANALYSIS_VISION_MODEL", "gpt-5.4-nano"),
        scoring_model=_str("CONTENT_ANALYSIS_SCORING_MODEL", "gpt-5.4-nano"),
        live_scan_max_minutes=_int("CONTENT_ANALYSIS_LIVE_SCAN_MAX_MINUTES", 60),
        live_window_before_s=120.0,
        live_window_after_s=300.0,
        live_max_windows=_int("CONTENT_ANALYSIS_LIVE_MAX_WINDOWS", 3),
        keyframe_every_s=2.0,
        ffmpeg=_str("FFMPEG_BIN", "ffmpeg"),
        ffprobe=_str("FFPROBE_BIN", "ffprobe"),
        ffmpeg_timeout_s=_float("CONTENT_ANALYSIS_FFMPEG_TIMEOUT_S", 900.0),
        max_in_flight=_int("CONTENT_ANALYSIS_MAX_IN_FLIGHT", 2),
    )


def max_bytes(kind: str, conf: AnalysisSettings) -> int:
    return conf.live_max_bytes if kind == LIVE else conf.video_max_bytes


def max_seconds(kind: str, conf: AnalysisSettings) -> float:
    return conf.live_max_seconds if kind == LIVE else conf.video_max_seconds


def asr_usd_per_minute(model: str) -> float:
    return ASR_USD_PER_MINUTE.get(model, ASR_DEFAULT_USD_PER_MINUTE)


__all__ = [
    "ASR_USD_PER_MINUTE",
    "CONTENT_TYPES",
    "EXTENSIONS",
    "KINDS",
    "LIVE",
    "MB",
    "VIDEO",
    "AnalysisSettings",
    "asr_usd_per_minute",
    "max_bytes",
    "max_seconds",
    "settings",
]
