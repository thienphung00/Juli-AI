"""Scene-cut detection over small luma frames (fast track P15) -- pure numpy.

Ported from the content engine's ``my-video/scripts/lib/reference_analyze.py``
``detect_cuts`` (the owner's own code): a cut is a one-frame spike in the mean
inter-frame difference, above ``max(12, 4 × median)``; spikes closer than
3 frames merge. A hard cut is a single tall spike (peak ÷ neighbours > 4); a
crossfade or camera move spreads the energy and is reported as a blend.

PySceneDetect (BSD-3-Clause) was considered: it needs OpenCV (~60 MB wheel)
for the same content-difference detector, so the port is used instead and no
new dependency is added.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Cut:
    t: float
    kind: str  # "hard" | "blend"


def detect_cuts(gray: np.ndarray, fps: float, *, offset_s: float = 0.0) -> list[Cut]:
    """Cuts in ``gray`` (``(n, h, w)`` float frames at ``fps``), times in seconds + offset."""
    if gray.shape[0] < 2:
        return []
    diff = np.abs(np.diff(gray, axis=0)).mean(axis=(1, 2))
    median = float(np.median(diff))
    threshold = max(12.0, median * 4.0)
    raw = [i + 1 for i, value in enumerate(diff) if value > threshold]
    frames: list[int] = []
    prev = -10
    for frame in raw:
        if frame - prev > 2:
            frames.append(int(frame))
        prev = frame
    cuts: list[Cut] = []
    for frame in frames:
        peak = float(diff[frame - 1])
        neighbours = np.concatenate([diff[max(0, frame - 4) : frame - 1], diff[frame : frame + 3]])
        base = float(neighbours.mean()) if neighbours.size else 0.0
        ratio = peak / max(base, 1e-6)
        cuts.append(Cut(t=round(offset_s + frame / fps, 2), kind="hard" if ratio > 4 else "blend"))
    return cuts


def cuts_per_10s(cuts: Sequence[Cut], duration_s: float) -> float | None:
    """Pacing: cuts per 10 seconds of analysed footage (one decimal)."""
    if duration_s <= 0:
        return None
    return round(len(cuts) * 10.0 / duration_s, 1)


__all__ = ["Cut", "cuts_per_10s", "detect_cuts"]
