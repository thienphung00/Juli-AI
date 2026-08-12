"""Provenance envelopes for agent tool-result free text (ADR-070 decision 3).

Every piece of free text a tool result surfaces to the LLM is wrapped with a
server-assigned **origin**:

- ``juli``   — computed by Juli. The implicit trusted default.
- ``vendor`` — marketplace (TikTok) text. Data, never instruction.
- ``seller`` — client-supplied text. Preference, honored within playbook and
  policy.

There is deliberately no ``buyer`` origin. The field is named ``source``, not
``role``, so it can never collide with chat-message roles.

Origin is derived from **which field the text arrived in** — assigned by the
server code that reads that field, never by anything found inside the text
itself. This module makes that structural rather than a convention to
remember: ``JuliText``, ``VendorText``, and ``SellerText`` are three distinct
frozen dataclasses, each with ``source`` fixed by the class (``init=False``),
so ``source`` is not even a parameter a caller can pass. There is no
constructor path through which text content — or a caller mistake — can set
an envelope's ``source`` to anything other than the class's own fixed value.
The forgery case this defeats: a vendor field containing text that itself
claims `"source": "juli"` (or any other trust claim) still produces
``VendorText`` with ``source == "vendor"``, because ``VendorText.__init__``
only ever accepts ``text``.

Because exactly three dataclasses exist, and each is pinned to one literal
``ProvenanceSource`` value, no fourth origin is representable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast, get_args

ProvenanceSource = Literal["juli", "vendor", "seller"]

#: The complete, closed set of representable origins — derived from the
#: ``ProvenanceSource`` literal itself so this tuple can never drift out of
#: sync with the type.
PROVENANCE_SOURCES: tuple[ProvenanceSource, ...] = get_args(ProvenanceSource)


@dataclass(frozen=True)
class _ProvenanceText:
    """Shape shared by every source-specific envelope: verbatim free text.

    Not instantiated directly — use ``JuliText``, ``VendorText``, or
    ``SellerText`` (or ``from_source`` when the source is only known as a
    server-determined string at the call site).
    """

    text: str


@dataclass(frozen=True)
class JuliText(_ProvenanceText):
    """Text computed by Juli — the implicit trusted default."""

    source: Literal["juli"] = field(default="juli", init=False)


@dataclass(frozen=True)
class VendorText(_ProvenanceText):
    """Marketplace (TikTok/vendor) text — data, never instruction."""

    source: Literal["vendor"] = field(default="vendor", init=False)


@dataclass(frozen=True)
class SellerText(_ProvenanceText):
    """Client-supplied text — preference, honored within playbook + policy."""

    source: Literal["seller"] = field(default="seller", init=False)


#: The union of every representable envelope.
ProvenanceEnvelope = JuliText | VendorText | SellerText

_BY_SOURCE: dict[ProvenanceSource, type[ProvenanceEnvelope]] = {
    "juli": JuliText,
    "vendor": VendorText,
    "seller": SellerText,
}


def from_source(source: str, text: str) -> ProvenanceEnvelope:
    """Build the envelope matching a server-determined ``source``.

    ``source`` must already be known by the caller from *which field* the raw
    text arrived in (ADR-070 decision 3) — never parsed out of ``text``
    itself. This is a convenience dispatcher for code that already holds the
    origin as a plain string (e.g. iterating a schema of known field→origin
    mappings); it does not weaken the guarantee above, because the value
    still has to come from the caller, not from ``text``.

    Raises ``ValueError`` naming the bad value if ``source`` is not one of
    the three representable origins — a typo or a drifted caller fails
    loudly instead of silently mislabeling trust.
    """
    if source not in PROVENANCE_SOURCES:
        raise ValueError(
            f"unknown provenance source {source!r}; must be one of {PROVENANCE_SOURCES}"
        )
    envelope_cls = _BY_SOURCE[cast(ProvenanceSource, source)]
    return envelope_cls(text=text)


def to_json_safe(envelope: ProvenanceEnvelope) -> dict[str, str]:
    """Render an envelope as its wire shape: ``{"source": ..., "text": ...}``.

    The key is ``source`` (never ``role``) per ADR-070 decision 3.
    """
    return {"source": envelope.source, "text": envelope.text}
