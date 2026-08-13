"""Hard size caps with always-signalled truncation (ADR-070 decision 2).

The base model is nano-class with a small context window: one unbounded tool
result can crowd out the instructions that keep a run safe. Equally, a model
that cannot tell a complete list from a truncated one will reason confidently
about missing data — so **no cut is ever silent**. Every cap in this module
follows the same shape: cut deterministically, and if anything was cut, say
so with an accurate count. If nothing was cut, the marker keys are absent
entirely — a caller can check ``"truncated" in payload`` rather than trust a
boolean that might itself be wrong.

Three cuts, one convention each:

- ``cap_list`` — lists capped to their top ``LIST_ITEM_CAP`` (20) entries, in
  whatever order the caller passed them. This module never sorts or
  reorders; the vendor's own relevance ordering is the caller's
  responsibility to preserve *before* calling in, and this module's job is
  only to cut, never to re-rank.
- ``cap_text`` — free text capped at ``FREE_TEXT_CHAR_CAP`` (~1,500)
  characters. Text at or under the cap passes through **verbatim,
  byte-for-byte** — not re-encoded, not stripped, not normalized.
- ``sanitize_images`` — raw vendor image payloads reduced to a bare
  ``{count, dimensions}`` shape. No nested vendor field (URL, id, alt text,
  vendor metadata) survives; only width/height per image, and only for the
  top ``LIST_ITEM_CAP`` images, with the same truncation-marker convention as
  ``cap_list``. ``count`` always reports the true total, even when
  ``dimensions`` is itself truncated, because the total count is small and
  useful on its own and never risks reintroducing a raw vendor payload.

Every result type here is a frozen dataclass whose ``__post_init__``
enforces the ``truncated``/``omitted_count`` invariant structurally (mirrors
``Money`` and the provenance envelopes in this package): ``omitted_count``
must be exactly zero when ``truncated`` is ``False``, and strictly positive
when ``truncated`` is ``True``. There is no code path that can produce an
inconsistent marker.

Compaction here is deterministic server code — no branching on wall-clock
time, randomness, environment, or model output. The same input always
produces a byte-identical serialized result (asserted by
``tests/unit/test_agent_sanitize_caps.py``), which is load-bearing for the
golden-file gate (#995): if this module's output ever varied run to run, a
golden fixture could never be considered ground truth. No model call is
made anywhere in this module — the cuts are pure Python slicing.

Token counting: this repo does not depend on any vendor tokenizer (no
``tiktoken`` or equivalent is declared in ``backend/pyproject.toml`` or
pinned in ``backend/constraints.txt``, and none is added here). ``
estimate_tokens`` uses a stdlib-only, deterministic proxy — roughly four
characters per token, the same rough-order-of-magnitude approximation
commonly used for English/Latin-script text when an exact tokenizer isn't
available — rounded *up* so the estimate is conservative (never
under-counts) against the ~2,000-token per-result ceiling.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

#: Per-tool-result ceiling (ADR-070 decision 2). A sanitized result must stay
#: at or under this estimate.
PER_RESULT_TOKEN_CEILING = 2000

#: Design target — comfortably under the ceiling, leaving headroom for the
#: rest of the turn (system prompt, other tool results, conversation so far)
#: on a small nano-class context window.
PER_RESULT_TOKEN_TARGET = 800

#: Lists are cut to their top N entries, in the caller's own ordering.
LIST_ITEM_CAP = 20

#: Free text is cut at this many characters.
FREE_TEXT_CHAR_CAP = 1500

#: Stdlib-only token estimate: characters per token, rounded up per call so
#: the estimate never under-counts. This is a deliberate approximation, not
#: a real tokenizer — see the module docstring.
_CHARS_PER_TOKEN_ESTIMATE = 4


def estimate_tokens(text: str) -> int:
    """Deterministic, stdlib-only token estimate for ``text``.

    Not a real tokenizer — a conservative (rounds up) character-count proxy,
    documented in the module docstring. Empty text estimates to zero tokens;
    any non-empty text estimates to at least one.
    """
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE)


def estimate_result_tokens(result: Mapping[str, Any]) -> int:
    """Deterministic token estimate for a JSON-serializable tool result.

    Serializes ``result`` with stable, deterministic ``json.dumps`` settings
    (no key sorting — sorting would not change the estimate but would be one
    more thing that could silently reorder a vendor-ordered list nested
    inside) and estimates tokens over the serialized text.
    """
    serialized = json.dumps(result, ensure_ascii=False)
    return estimate_tokens(serialized)


def _validate_truncation_marker(*, truncated: bool, omitted_count: int, label: str) -> None:
    """Shared invariant for every capped shape in this module.

    ``omitted_count`` must be exactly zero when nothing was cut, and
    strictly positive when something was — the pairing this module exists
    to keep from ever going out of sync.
    """
    if truncated and omitted_count <= 0:
        raise ValueError(
            f"{label}: truncated=True requires a positive omitted_count, got {omitted_count!r}"
        )
    if not truncated and omitted_count != 0:
        raise ValueError(
            f"{label}: truncated=False requires omitted_count == 0, got {omitted_count!r}"
        )


# ---------------------------------------------------------------------------
# Lists: top-N in caller order, marker only when something was cut
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CappedList:
    """A list cut to at most ``LIST_ITEM_CAP`` entries, order preserved.

    ``to_dict()`` omits the ``truncated``/``omitted_count`` keys entirely
    when nothing was cut — an at-or-under-cap list emits no marker at all,
    per ADR-070 decision 2, rather than a marker whose ``truncated`` value
    happens to be ``False``.
    """

    items: tuple[Any, ...]
    truncated: bool
    omitted_count: int

    def __post_init__(self) -> None:
        _validate_truncation_marker(
            truncated=self.truncated, omitted_count=self.omitted_count, label="CappedList"
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"items": list(self.items)}
        if self.truncated:
            payload["truncated"] = True
            payload["omitted_count"] = self.omitted_count
        return payload


def cap_list(items: Sequence[Any], *, cap: int = LIST_ITEM_CAP) -> CappedList:
    """Cut ``items`` to its top ``cap`` entries, preserving input order.

    Never sorts or reorders — the caller is responsible for having already
    put ``items`` in the vendor's own relevance order; this only cuts.
    """
    items = tuple(items)
    total = len(items)
    if total <= cap:
        return CappedList(items=items, truncated=False, omitted_count=0)
    return CappedList(items=items[:cap], truncated=True, omitted_count=total - cap)


# ---------------------------------------------------------------------------
# Free text: verbatim under the cap, cut with a marker over it
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CappedText:
    """Free text cut at ``FREE_TEXT_CHAR_CAP`` characters.

    Text at or under the cap is preserved **verbatim, byte-for-byte** — this
    dataclass never strips, normalizes, or re-encodes it.
    """

    text: str
    truncated: bool
    omitted_count: int

    def __post_init__(self) -> None:
        _validate_truncation_marker(
            truncated=self.truncated, omitted_count=self.omitted_count, label="CappedText"
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": self.text}
        if self.truncated:
            payload["truncated"] = True
            payload["omitted_count"] = self.omitted_count
        return payload


def cap_text(text: str, *, cap: int = FREE_TEXT_CHAR_CAP) -> CappedText:
    """Cut ``text`` at ``cap`` characters if it exceeds the cap.

    Text at or under ``cap`` characters is returned unchanged (the same
    string object, even) — the verbatim, byte-for-byte guarantee ADR-070
    decision 2 requires for text under the cap.
    """
    total = len(text)
    if total <= cap:
        return CappedText(text=text, truncated=False, omitted_count=0)
    return CappedText(text=text[:cap], truncated=True, omitted_count=total - cap)


# ---------------------------------------------------------------------------
# Images: {count, dimensions} only — no raw nested vendor payload
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImageDimensions:
    """A single image's width/height — the only fields that survive."""

    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {"width": self.width, "height": self.height}


@dataclass(frozen=True)
class CappedImages:
    """Raw vendor images reduced to a bare ``{count, dimensions}`` shape.

    ``count`` is always the true total number of images, even when
    ``dimensions`` itself is truncated to the top ``LIST_ITEM_CAP`` — a bare
    integer total carries no vendor payload risk and is useful context on
    its own. ``dimensions`` follows the same marker convention as
    ``CappedList``: no ``truncated``/``omitted_count`` keys when the image
    count is at or under the cap.
    """

    count: int
    dimensions: tuple[ImageDimensions, ...]
    truncated: bool
    omitted_count: int

    def __post_init__(self) -> None:
        _validate_truncation_marker(
            truncated=self.truncated, omitted_count=self.omitted_count, label="CappedImages"
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "count": self.count,
            "dimensions": [d.to_dict() for d in self.dimensions],
        }
        if self.truncated:
            payload["truncated"] = True
            payload["omitted_count"] = self.omitted_count
        return payload


def sanitize_images(
    images: Sequence[Mapping[str, Any]], *, cap: int = LIST_ITEM_CAP
) -> CappedImages:
    """Reduce raw vendor image payloads to ``{count, dimensions}``.

    Reads only ``width`` and ``height`` off each image mapping — every other
    key (URL, id, alt text, vendor-specific metadata) is dropped, never
    copied into the result. References to the original vendor payload are
    the caller's concern to hold server-side; this function does not accept
    or emit anything that could carry one through.

    Raises ``KeyError`` if an image mapping is missing ``width`` or
    ``height`` — a malformed vendor image fails loudly here rather than
    silently reporting a wrong dimension.
    """
    total = len(images)
    kept = images[:cap]
    dimensions = tuple(
        ImageDimensions(width=image["width"], height=image["height"]) for image in kept
    )
    if total <= cap:
        return CappedImages(count=total, dimensions=dimensions, truncated=False, omitted_count=0)
    return CappedImages(
        count=total, dimensions=dimensions, truncated=True, omitted_count=total - cap
    )


__all__ = [
    "FREE_TEXT_CHAR_CAP",
    "LIST_ITEM_CAP",
    "PER_RESULT_TOKEN_CEILING",
    "PER_RESULT_TOKEN_TARGET",
    "CappedImages",
    "CappedList",
    "CappedText",
    "ImageDimensions",
    "cap_list",
    "cap_text",
    "estimate_result_tokens",
    "estimate_tokens",
    "sanitize_images",
]
