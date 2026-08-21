"""Hidden-text stripping for vendor text (ADR-070/075 decision 5, issue #1218).

Closes the hidden-text and homoglyph channels: an instruction spliced into a
product description using invisible characters is invisible to the human
reviewer who approved the ActionCard, but fully visible, token-by-token, to
the model. Three categories are removed from **vendor** text only:

- **Control characters** -- Unicode category ``Cc`` (C0/C1 controls), minus
  ``\\t``/``\\n``/``\\r`` -- those three are ordinary formatting in free-text
  product copy and are deliberately preserved; every other control byte
  (NUL, BEL, ESC, form feed, ...) is a classic hidden-text/terminal-injection
  vector and is removed.
- **Zero-width / other invisible Unicode** -- category ``Cf`` (format
  characters): zero-width space/joiner/non-joiner, word joiner, the
  zero-width no-break space (BOM), soft hyphen, the Unicode "tag" block used
  by some invisible-payload smuggling techniques, and more.
- **Bidirectional overrides** -- LRE/RLE/PDF/LRO/RLO, LRI/RLI/FSI/PDI,
  LRM/RLM, ALM -- the Trojan-Source-style characters that make text render
  in a different order than it decodes. Every one of these is *also*
  category ``Cf`` (see below), so one category sweep closes both the
  invisible-Unicode and bidi-override channels at once; there is no second,
  separate bidi pass in this module.

**What survives, on purpose.** Vietnamese combining diacritics live in
Unicode category ``Mn`` (Mark, Nonspacing) -- a completely different
category from ``Cc``/``Cf`` -- so this category-based approach never touches
them, in either NFC (precomposed) or NFD (decomposed/combining-mark) form.
Ordinary single-codepoint emoji are category ``So`` (Symbol, other); emoji
skin-tone modifiers are category ``Sk`` (Symbol, modifier); the emoji
variation selector (``U+FE0F``) is category ``Mn``. None of those categories
is stripped. Over-stripping -- eating legitimate Vietnamese text or emoji --
is the failure mode this module is written to avoid, per ADR-075 decision 5
and the issue's acceptance criteria; `tests/unit/test_agent_sanitize_hidden_text.py`
and the `legitimate_vietnamese_diacritics_survive` / `legitimate_emoji_survive`
fixtures in `tests/fixtures/agent_sanitize_hidden_text/` assert this directly.

**Known, deliberate exception.** Zero-width joiner (``U+200D``) is itself
category ``Cf`` and is stripped like every other format character. Complex
multi-codepoint emoji sequences that rely on ZWJ to join separate emoji into
one glyph (e.g. family or profession emoji) will therefore split back into
their individual component emoji rather than rendering as one joined glyph.
This is an accepted trade-off, not an oversight: ZWJ is exactly the kind of
"zero-width... invisible Unicode" character ADR-075 decision 5 requires
stripping from vendor text, and a hidden-text payload could equally use ZWJ
to splice itself between visible characters. The fixtures in this suite use
simple, single-codepoint emoji (a delivery truck, a thumbs-up, a party
popper) to prove legitimate emoji survive, deliberately avoiding ZWJ
sequences so the "legitimate emoji survive" claim and the "strip zero-width
Unicode" requirement never contradict each other in the same assertion.

**Scope: vendor text only.** `strip_hidden_text_from_vendor_fields` is the
structural entry point `chokepoints.py` calls. It walks a tool-result-shaped
value the same way `chokepoints._iter_strings` does (recursing dict keys and
values, and every list/tuple element) but only ever mutates the ``text``
value of a node shaped exactly like a provenance envelope's wire form
(`sanitize.provenance.to_json_safe`'s ``{"source": ..., "text": ...}``) whose
``source`` is literally ``"vendor"``. ``seller`` and ``juli`` envelopes, and
any plain (unwrapped) string anywhere in the structure, are left untouched
-- ADR-075 decision 5 says "strip from vendor text", not from every string
in a tool result.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from typing import Any

#: `\t`/`\n`/`\r` are Unicode category `Cc` but are ordinary formatting in
#: free-text product copy -- preserved even though they are technically
#: control characters.
_PRESERVED_CONTROL_CHARS = frozenset({"\t", "\n", "\r"})

#: Unicode general-category codes stripped from vendor text:
#:   Cc - control characters (C0/C1), minus the three preserved above.
#:   Cf - format characters -- every zero-width character (ZWSP, ZWNJ, ZWJ,
#:        word joiner, the BOM/ZWNBSP, soft hyphen, Unicode tag characters)
#:        AND every bidirectional-override control character (LRE/RLE/PDF/
#:        LRO/RLO, LRI/RLI/FSI/PDI, LRM/RLM, ALM) live in this one category
#:        -- see the module docstring for why that means one sweep closes
#:        both the "invisible Unicode" and "bidi override" channels.
_STRIPPED_CATEGORIES = frozenset({"Cc", "Cf"})


def strip_hidden_text(text: str) -> str:
    """Remove control characters, zero-width/invisible Unicode, and bidi
    overrides from ``text``. See the module docstring for exactly which
    Unicode categories are stripped and which are deliberately preserved.

    Pure, deterministic, stdlib-only (``unicodedata``) -- the same character
    always strips or survives regardless of position or surrounding text.
    """
    return "".join(
        ch
        for ch in text
        if ch in _PRESERVED_CONTROL_CHARS or unicodedata.category(ch) not in _STRIPPED_CATEGORIES
    )


def _is_vendor_text_envelope(value: Any) -> bool:
    """True for a mapping shaped exactly like a vendor provenance envelope's
    wire form (`provenance.to_json_safe`'s output for a `VendorText`):
    ``{"source": "vendor", "text": <str>}``. Any other shape -- a different
    ``source``, a missing/non-string ``text``, extra keys absent -- is not
    matched, so this only ever targets what it is documented to target.
    """
    return (
        isinstance(value, Mapping)
        and value.get("source") == "vendor"
        and isinstance(value.get("text"), str)
    )


def strip_hidden_text_from_vendor_fields(value: Any) -> Any:
    """Recursively strip hidden text from every vendor-tagged ``text`` field
    inside ``value``. Returns a new structure -- ``value`` itself, and every
    container inside it, is left unmutated (see the module docstring's
    "Scope: vendor text only" section for exactly what counts as
    vendor-tagged). Walks dict keys+values and list/tuple elements the same
    way `chokepoints._iter_strings` does, so this never disagrees with the
    scan below about how deep "the whole structure" reaches.
    """
    if _is_vendor_text_envelope(value):
        stripped = dict(value)
        stripped["text"] = strip_hidden_text(value["text"])
        return stripped
    if isinstance(value, Mapping):
        return {key: strip_hidden_text_from_vendor_fields(val) for key, val in value.items()}
    if isinstance(value, list):
        return [strip_hidden_text_from_vendor_fields(item) for item in value]
    if isinstance(value, tuple):
        return tuple(strip_hidden_text_from_vendor_fields(item) for item in value)
    return value


__all__ = [
    "strip_hidden_text",
    "strip_hidden_text_from_vendor_fields",
]
