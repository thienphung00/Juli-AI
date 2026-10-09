"""Checks on the seller's cover photo (fast track P10-B, contract §4). Pure.

ADR-109 Amendment 1 d.3: the photo must be 1:1, at least 800 px, on a plain
background, with the product filling at least 70 % of the frame. The first two
are exact; the last two are **heuristics** (``heuristic=True`` on the check,
DEBT P10-B), computed on a 256 px thumbnail so a 5 MB photo costs milliseconds:

- **Plain background.** The border strip (the outer 4 % on every side) is the
  background sample. Its per-channel median is the background colour; the
  background is plain when at least 90 % of border pixels lie within 28 (of
  255, max over R/G/B) of that colour. White, grey, pastel and any other single
  colour pass; a room, a table edge or a pattern does not.
- **Product fills ≥ 70 % of the frame.** A pixel is "product" when it differs
  from the background colour by more than 40 on some channel. Rows and columns
  with fewer than 1 % product pixels are treated as noise (shadows, dust). The
  product's bounding box divided by the frame, on its longer side
  (``max(box_w / w, box_h / h)``), must be at least 0.70 -- a tall bottle that
  spans the full height passes even though it is narrow.

A file that is not a readable JPG/PNG, or is over 5 MB, fails the ``file`` check
and nothing else is evaluated.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MIN_SIDE_PX = 800
#: Decoding cap (a 5 MB PNG can still claim a huge canvas).
MAX_PIXELS = 40_000_000
#: |w − h| / max(w, h) allowed for "1:1" (a 1000 × 1008 export still counts).
SQUARE_TOLERANCE = 0.01
BORDER_FRACTION = 0.04
BACKGROUND_TOLERANCE = 28
PLAIN_BORDER_SHARE = 0.90
FOREGROUND_DELTA = 40
NOISE_LINE_SHARE = 0.01
MIN_PRODUCT_FILL = 0.70
_THUMBNAIL_PX = 256

FORMATS: dict[str, str] = {"JPEG": "image/jpeg", "PNG": "image/png"}

LABEL_FILE = "JPG hoặc PNG, tối đa 5 MB"
LABEL_RATIO = "Tỉ lệ 1:1"
LABEL_SIZE = "Tối thiểu 800 × 800 px"
LABEL_BACKGROUND = "Nền trắng hoặc trơn"
LABEL_FILL = "Sản phẩm chiếm từ 70 % khung ảnh"


@dataclass(frozen=True)
class PhotoCheck:
    key: str
    label: str
    ok: bool
    heuristic: bool = False
    detail: str = ""

    def to_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "ok": self.ok,
            "heuristic": self.heuristic,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PhotoReport:
    checks: tuple[PhotoCheck, ...]
    content_type: str | None = None
    width: int = 0
    height: int = 0
    product_fill: float | None = None

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def checks_json(self) -> list[dict[str, object]]:
        return [check.to_json() for check in self.checks]


def _file_failure(detail: str) -> PhotoReport:
    return PhotoReport(checks=(PhotoCheck("file", LABEL_FILE, False, detail=detail),))


def too_large_report() -> PhotoReport:
    """The ``file`` check failing for a body over 5 MB, without reading it."""
    return _file_failure("Tệp lớn hơn 5 MB")


def _median(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _rgb_pixels(image: Image.Image) -> tuple[Image.Image, list[tuple[int, int, int]]]:
    thumb = image.convert("RGB")
    thumb.thumbnail((_THUMBNAIL_PX, _THUMBNAIL_PX))
    flat = getattr(thumb, "get_flattened_data", None)
    data: Any = flat() if flat is not None else thumb.getdata()
    pixels = [(int(p[0]), int(p[1]), int(p[2])) for p in data]
    return thumb, pixels


def _distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def _background(
    width: int, height: int, pixels: list[tuple[int, int, int]]
) -> tuple[tuple[int, int, int], float]:
    """The border's median colour and the share of border pixels close to it."""
    bx = max(1, round(width * BORDER_FRACTION))
    by = max(1, round(height * BORDER_FRACTION))
    border = [
        pixels[y * width + x]
        for y in range(height)
        for x in range(width)
        if x < bx or x >= width - bx or y < by or y >= height - by
    ]
    colour = (
        _median([p[0] for p in border]),
        _median([p[1] for p in border]),
        _median([p[2] for p in border]),
    )
    close = sum(1 for p in border if _distance(p, colour) <= BACKGROUND_TOLERANCE)
    return colour, close / len(border)


def _product_fill(
    width: int, height: int, pixels: list[tuple[int, int, int]], colour: tuple[int, int, int]
) -> float:
    rows = [0] * height
    cols = [0] * width
    for y in range(height):
        for x in range(width):
            if _distance(pixels[y * width + x], colour) > FOREGROUND_DELTA:
                rows[y] += 1
                cols[x] += 1
    row_floor = max(1, round(width * NOISE_LINE_SHARE))
    col_floor = max(1, round(height * NOISE_LINE_SHARE))
    ys = [y for y, count in enumerate(rows) if count >= row_floor]
    xs = [x for x, count in enumerate(cols) if count >= col_floor]
    if not ys or not xs:
        return 0.0
    box_h = (ys[-1] - ys[0] + 1) / height
    box_w = (xs[-1] - xs[0] + 1) / width
    return max(box_w, box_h)


def check_photo(data: bytes) -> PhotoReport:
    """Run the four checks on ``data`` (see module docstring)."""
    if not data:
        return _file_failure("Tệp trống")
    if len(data) > MAX_PHOTO_BYTES:
        return _file_failure("Tệp lớn hơn 5 MB")
    try:
        with Image.open(io.BytesIO(data)) as image:
            image_format = image.format or ""
            if image_format not in FORMATS:
                return _file_failure("Không phải ảnh JPG hoặc PNG")
            width, height = image.size
            if width * height > MAX_PIXELS:
                return _file_failure("Ảnh quá lớn")
            image.load()
            thumb, pixels = _rgb_pixels(image)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
        return _file_failure("Không đọc được ảnh")

    longer = max(width, height)
    square = longer > 0 and abs(width - height) / longer <= SQUARE_TOLERANCE
    size_ok = min(width, height) >= MIN_SIDE_PX
    t_width, t_height = thumb.size
    colour, plain_share = _background(t_width, t_height, pixels)
    plain = plain_share >= PLAIN_BORDER_SHARE
    fill = _product_fill(t_width, t_height, pixels, colour)
    fill_pct = round(fill * 100)

    checks = (
        PhotoCheck("ratio", LABEL_RATIO, square, detail=f"{width} × {height}"),
        PhotoCheck("size", LABEL_SIZE, size_ok, detail=f"{width} × {height} px"),
        PhotoCheck(
            "background",
            LABEL_BACKGROUND,
            plain,
            heuristic=True,
            detail="nền trơn" if plain else "nền rối",
        ),
        PhotoCheck(
            "product_fill",
            LABEL_FILL,
            fill >= MIN_PRODUCT_FILL,
            heuristic=True,
            detail=f"sản phẩm chiếm {fill_pct} % khung",
        ),
    )
    return PhotoReport(
        checks=checks,
        content_type=FORMATS[image_format],
        width=width,
        height=height,
        product_fill=fill,
    )


def describe(report: PhotoReport) -> str:
    """One line for the run timeline: ``1:1 · 1200 × 1200 px · nền trơn · sản phẩm 78 % khung``."""
    if report.content_type is None:
        return report.checks[0].detail if report.checks else ""
    ratio = "1:1" if report.checks[0].ok else "không vuông"
    background = "nền trơn" if report.checks[2].ok else "nền rối"
    fill = round((report.product_fill or 0) * 100)
    return f"{ratio} · {report.width} × {report.height} px · {background} · sản phẩm {fill} % khung"


__all__ = [
    "MAX_PHOTO_BYTES",
    "MIN_PRODUCT_FILL",
    "MIN_SIDE_PX",
    "PhotoCheck",
    "PhotoReport",
    "check_photo",
    "describe",
    "too_large_report",
]
