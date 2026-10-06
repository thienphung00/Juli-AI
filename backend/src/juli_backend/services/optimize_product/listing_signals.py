"""Listing evidence: TikTok diagnosis codes, or Juli's local reading of them.

ADR-090 decision 3 and ADR-106 decision 4: a content angle needs a diagnosis
code behind it. The authoritative source is
``GET /product/202405/products/diagnoses`` (parsed by
:func:`parse_tiktok_diagnoses`). Until that endpoint is captured, the same
VN "Rest of World" codes can be *approximated* from the product itself —
title length, description length and line breaks, main-image count,
duplicates, first-image resolution — by :func:`derive_local_evidence`.

Every :class:`Evidence` carries its :class:`EvidenceSource`, and card copy
reads it: ``"TikTok đánh dấu…"`` only for ``TIKTOK``, ``"Juli đánh giá…"``
for ``LOCAL`` (OP-NFR-2 — never borrowed authority). Codes that need image
understanding (background, text overlay, collage) cannot be derived locally
and are listed in :data:`TIKTOK_ONLY_CODES` so a report can say what the
scan could not see.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from juli_backend.services.optimize_product.config import StageDiagnosisConfig


class EvidenceSource(str, Enum):
    TIKTOK = "tiktok"
    LOCAL = "local"


#: Field → codes, VN "Rest of World" table of the Partner Center
#: listing-quality reference (read 2026-10-06).
TITLE_CODES = frozenset({"TITLE_LESS_THAN_40_CHARACTERS", "SEO_DIAGNOSTIC_ITEM"})
DESCRIPTION_CODES = frozenset({"DESC_LESS_THAN_FIVE_HUNDRED_CHARS", "DESC_NO_NEW_LINE"})
FIRST_IMAGE_CODES = frozenset(
    {
        "MAIN_IMG_FIRST_IMG_BACKGROUND_UNTIDY",
        "MAIN_IMG_FIRST_IMG_BLACK_BORDER",
        "MAIN_IMG_FIRST_IMG_FAKE_MODEL",
        "MAIN_IMG_FIRST_IMG_INCLUDE_NON_LOCAL_LANGUAGE",
        "MAIN_IMG_FIRST_IMG_LOW_QUALITY",
        "MAIN_IMG_FIRST_IMG_MISSING_PRODUCT_SUBSTANCE",
        "MAIN_IMG_FIRST_IMG_NOT_CLEAR",
        "MAIN_IMG_FIRST_IMG_PRODUCT_SUBJECT_NOT_COMPLETE",
        "MAIN_IMG_FIRST_IMG_SPLICED_PICTURE",
        "MAIN_IMG_FIRST_IMG_TEXT_OVERLOAD",
        "MAIN_IMG_FIRST_IMG_WHITE_BORDER",
    }
)
IMAGE_SET_CODES = frozenset({"MAIN_IMG_DUPLICATE", "MAIN_IMG_NUMBER_LESS_THAN_FIVE"})
IMAGE_CODES = FIRST_IMAGE_CODES | IMAGE_SET_CODES

#: Codes only TikTok's image understanding can produce.
TIKTOK_ONLY_CODES = FIRST_IMAGE_CODES - {"MAIN_IMG_FIRST_IMG_LOW_QUALITY"} | {"SEO_DIAGNOSTIC_ITEM"}

_TAG_RE = re.compile(r"<[^>]+>")
_LINE_BREAK_RE = re.compile(r"<br\s*/?>|</p>|<p[\s>]|<li[\s>]|\n", re.IGNORECASE)


@dataclass(frozen=True)
class Evidence:
    """One diagnosis code with where it came from and a one-line fact."""

    code: str
    source: EvidenceSource
    detail: str = ""
    how_to_solve: str = ""

    @property
    def field_name(self) -> str:
        if self.code in TITLE_CODES:
            return "title"
        if self.code in DESCRIPTION_CODES:
            return "description"
        if self.code in IMAGE_CODES:
            return "image"
        return "other"


@dataclass(frozen=True)
class ListingSignals:
    """What the scan can read off a GetProduct payload without TikTok's diagnosis."""

    product_id: str
    title: str
    status: str | None
    title_chars: int
    description_text_chars: int
    description_has_line_breaks: bool
    main_image_count: int
    duplicate_image_count: int
    first_image_min_side_px: int | None
    sku_count: int
    min_sale_price: str | None
    excluded_reason: str | None = None
    extra: dict = field(default_factory=dict)


def listing_signals_from_product(product: dict, config: StageDiagnosisConfig) -> ListingSignals:
    """Read the listing facts the local evidence derivation needs.

    Accepts either the raw ``data`` object of GetProduct or the
    :class:`~juli_backend.integrations.tiktok.schemas.TikTokProduct` dump —
    both keep ``title``, ``description``, ``main_images``, ``skus``, ``status``.
    """
    title = str(product.get("title") or "")
    description = str(product.get("description") or "")
    text = _TAG_RE.sub("", description).strip()
    images = [img for img in (product.get("main_images") or []) if isinstance(img, dict)]
    uris = [str(img.get("uri") or "") for img in images]
    duplicates = len(uris) - len({u for u in uris if u})
    first = images[0] if images else {}
    width, height = first.get("width"), first.get("height")
    min_side = min(int(width), int(height)) if width and height else None
    skus = [s for s in (product.get("skus") or []) if isinstance(s, dict)]
    prices = [
        str((s.get("price") or {}).get("sale_price") or "")
        for s in skus
        if isinstance(s.get("price"), dict)
    ]
    prices = [p for p in prices if p]
    excluded = None
    lowered = title.lower()
    for pattern in config.exclude_title_patterns:
        if pattern in lowered:
            excluded = f"title matches '{pattern}'"
            break
    return ListingSignals(
        product_id=str(product.get("id") or ""),
        title=title,
        status=product.get("status"),
        title_chars=len(title),
        description_text_chars=len(text),
        description_has_line_breaks=bool(_LINE_BREAK_RE.search(description)),
        main_image_count=len(images),
        duplicate_image_count=max(duplicates, 0),
        first_image_min_side_px=min_side,
        sku_count=len(skus),
        min_sale_price=min(prices, key=lambda p: float(p)) if prices else None,
        excluded_reason=excluded,
    )


def derive_local_evidence(signals: ListingSignals, config: StageDiagnosisConfig) -> list[Evidence]:
    """Approximate the VN diagnosis codes from listing facts (source LOCAL)."""
    out: list[Evidence] = []
    if signals.title_chars < config.title_min_chars:
        out.append(
            Evidence(
                "TITLE_LESS_THAN_40_CHARACTERS",
                EvidenceSource.LOCAL,
                f"tiêu đề {signals.title_chars} ký tự, chuẩn ≥ {config.title_min_chars}",
            )
        )
    if signals.description_text_chars < config.description_min_chars:
        out.append(
            Evidence(
                "DESC_LESS_THAN_FIVE_HUNDRED_CHARS",
                EvidenceSource.LOCAL,
                f"mô tả {signals.description_text_chars} ký tự chữ, chuẩn ≥ "
                f"{config.description_min_chars}",
            )
        )
    if signals.description_text_chars > 0 and not signals.description_has_line_breaks:
        out.append(
            Evidence(
                "DESC_NO_NEW_LINE", EvidenceSource.LOCAL, "mô tả là một khối, không xuống dòng"
            )
        )
    if signals.main_image_count < config.main_images_min_count:
        out.append(
            Evidence(
                "MAIN_IMG_NUMBER_LESS_THAN_FIVE",
                EvidenceSource.LOCAL,
                f"{signals.main_image_count} ảnh chính, chuẩn ≥ {config.main_images_min_count}",
            )
        )
    if signals.duplicate_image_count > 0:
        out.append(
            Evidence(
                "MAIN_IMG_DUPLICATE",
                EvidenceSource.LOCAL,
                f"{signals.duplicate_image_count} ảnh chính trùng nhau",
            )
        )
    if (
        signals.first_image_min_side_px is not None
        and signals.first_image_min_side_px < config.first_image_min_side_px
    ):
        out.append(
            Evidence(
                "MAIN_IMG_FIRST_IMG_LOW_QUALITY",
                EvidenceSource.LOCAL,
                f"ảnh bìa cạnh ngắn {signals.first_image_min_side_px}px, chuẩn ≥ "
                f"{config.first_image_min_side_px}px",
            )
        )
    return out


def parse_tiktok_diagnoses(product_entry: dict) -> list[Evidence]:
    """Parse one ``data.products[]`` entry of the diagnoses endpoint (source TIKTOK)."""
    out: list[Evidence] = []
    for diag in product_entry.get("diagnoses") or []:
        if not isinstance(diag, dict):
            continue
        for result in diag.get("diagnosis_results") or []:
            if not isinstance(result, dict) or not result.get("code"):
                continue
            out.append(
                Evidence(
                    str(result["code"]),
                    EvidenceSource.TIKTOK,
                    detail=str(diag.get("field") or ""),
                    how_to_solve=str(result.get("how_to_solve") or ""),
                )
            )
    return out
