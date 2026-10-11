"""ffprobe / ffmpeg over an uploaded file -- read, decode, never execute (fast track P15).

Safety of an untrusted upload:

- The file is only ever *read* by ffprobe / ffmpeg, called with an argument
  list (no shell), ``-nostdin``, a wall-clock timeout, and two restrictions:
  ``-f mov`` forces the MP4 / QuickTime demuxer (no format guessing, so a
  playlist, concat list or image sequence cannot be smuggled in under a .mp4
  name) and ``-protocol_whitelist file`` stops the demuxer from opening
  anything but local files. External data references (``dref``) stay off
  (ffmpeg's default).
- Before ffprobe, ``sniff`` checks the first box of the file is an ISO-BMFF /
  QuickTime box, so a renamed executable or archive is refused without being
  parsed by anything.
- Outputs (audio, keyframes) go to a private temporary directory that is
  removed with the analysis.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - fixed binaries, argument lists, no shell
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from juli_backend.services.content_analysis.config import AnalysisSettings

#: First-box types of an MP4 / MOV file (ISO-BMFF ``ftyp``, QuickTime atoms).
_BOX_TYPES = {b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"}

#: Input options for every read of the upload.
_SAFE_INPUT = ("-f", "mov", "-protocol_whitelist", "file")

#: Gray frames for cut detection: fps and size (small on purpose: cuts are
#: whole-frame changes; 64×36 keeps a 10-minute window at ~14 MB).
CUT_FPS = 10.0
CUT_W, CUT_H = 64, 36
KEYFRAME_WIDTH = 384


class MediaError(Exception):
    """The file is not a video Juli accepts. ``code`` is the API / UI code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Probe:
    duration_s: float
    has_audio: bool
    width: int | None
    height: int | None
    video_codec: str | None


def sniff(path: Path) -> bool:
    """True when the file starts with an MP4 / QuickTime box header."""
    with path.open("rb") as handle:
        head = handle.read(12)
    return len(head) >= 8 and head[4:8] in _BOX_TYPES


def _run(args: list[str], conf: AnalysisSettings, *, capture: bool = True) -> bytes:
    try:
        done = subprocess.run(  # nosec B603 - argument list, no shell, fixed binary
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=conf.ffmpeg_timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError("media_timeout", args[0]) from exc
    except FileNotFoundError as exc:
        raise MediaError("ffmpeg_missing", args[0]) from exc
    if done.returncode != 0:
        tail = (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
        raise MediaError("media_unreadable", tail[0][:200] if tail else str(done.returncode))
    return done.stdout or b""


def probe(path: Path, conf: AnalysisSettings) -> Probe:
    if not sniff(path):
        raise MediaError("not_a_video", "first box is not mp4/mov")
    raw = _run(
        [
            conf.ffprobe,
            "-v",
            "error",
            *_SAFE_INPUT,
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(path),
        ],
        conf,
    )
    try:
        data = json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise MediaError("media_unreadable", "ffprobe output") from exc
    streams = [s for s in data.get("streams") or [] if isinstance(s, dict)]
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("no_video_stream")
    try:
        duration = float((data.get("format") or {}).get("duration") or 0.0)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise MediaError("no_duration")
    return Probe(
        duration_s=duration,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        width=int(video["width"]) if isinstance(video.get("width"), int) else None,
        height=int(video["height"]) if isinstance(video.get("height"), int) else None,
        video_codec=str(video.get("codec_name") or "") or None,
    )


def _span(start: float | None, duration: float | None) -> list[str]:
    out: list[str] = []
    if start:
        out += ["-ss", f"{max(0.0, start):.3f}"]
    if duration:
        out += ["-t", f"{max(0.0, duration):.3f}"]
    return out


def extract_audio(path: Path, out: Path, conf: AnalysisSettings) -> Path:
    """Mono 16 kHz AAC (m4a) of the whole file -- ~22 MB per hour."""
    _run(
        [
            conf.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            *_SAFE_INPUT,
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "aac",
            "-b:a",
            "48k",
            "-f",
            "ipod",
            str(out),
        ],
        conf,
        capture=False,
    )
    return out


def cut_audio(
    audio: Path, out: Path, start: float, duration: float, conf: AnalysisSettings
) -> Path:
    """A slice of the extracted audio (our own file, so no input restrictions needed)."""
    _run(
        [
            conf.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            *_span(start, None),
            "-i",
            str(audio),
            *_span(None, duration),
            "-c",
            "copy",
            "-f",
            "ipod",
            str(out),
        ],
        conf,
        capture=False,
    )
    return out


def keyframes(
    path: Path,
    out_dir: Path,
    conf: AnalysisSettings,
    *,
    start: float = 0.0,
    duration: float | None = None,
    every_s: float | None = None,
) -> list[tuple[float, Path]]:
    """One JPEG every ``every_s`` seconds (default 2 s), 384 px wide, as ``(t, path)``."""
    step = every_s or conf.keyframe_every_s
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"kf_{int(start * 1000):010d}_"
    _run(
        [
            conf.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            "-y",
            *_span(start, None),
            *_SAFE_INPUT,
            "-i",
            str(path),
            *_span(None, duration),
            "-vf",
            f"fps=1/{step:g}:round=down,scale={KEYFRAME_WIDTH}:-2",
            "-q:v",
            "5",
            str(out_dir / f"{prefix}%05d.jpg"),
        ],
        conf,
        capture=False,
    )
    files = sorted(out_dir.glob(f"{prefix}*.jpg"))
    return [(round(start + i * step, 3), f) for i, f in enumerate(files)]


def gray_frames(
    path: Path, conf: AnalysisSettings, *, start: float = 0.0, duration: float | None = None
) -> np.ndarray:
    """``(n, 36, 64)`` float32 luma frames at 10 fps for cut detection."""
    raw = _run(
        [
            conf.ffmpeg,
            "-nostdin",
            "-v",
            "error",
            *_span(start, None),
            *_SAFE_INPUT,
            "-i",
            str(path),
            *_span(None, duration),
            "-an",
            "-vf",
            f"fps={CUT_FPS:g},scale={CUT_W}:{CUT_H},format=gray",
            "-f",
            "rawvideo",
            "-",
        ],
        conf,
    )
    frame = CUT_W * CUT_H
    count = len(raw) // frame
    if count == 0:
        return np.zeros((0, CUT_H, CUT_W), dtype=np.float32)
    return (
        np.frombuffer(raw[: count * frame], dtype=np.uint8)
        .reshape(count, CUT_H, CUT_W)
        .astype(np.float32)
    )


__all__ = [
    "CUT_FPS",
    "MediaError",
    "Probe",
    "cut_audio",
    "extract_audio",
    "gray_frames",
    "keyframes",
    "probe",
    "sniff",
]
