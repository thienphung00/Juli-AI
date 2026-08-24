"""Unit tests for the hidden-text stripper (ADR-070/075 decision 5, issue #1218).

`strip_hidden_text` is the character-level primitive: control characters
(Unicode category `Cc`, minus `\\t`/`\\n`/`\\r`) and format characters
(category `Cf` -- which is where every zero-width character AND every
bidirectional-override control character lives; see the module docstring
for why one category sweep closes both channels) are removed. Vietnamese
combining diacritics (category `Mn`) and ordinary single-codepoint emoji
(category `So`/`Sk`) are untouched -- over-stripping is the failure mode
this file guards hardest against, per the issue's acceptance criteria.

`strip_hidden_text_from_vendor_fields` is the structural wrapper
`chokepoints.py` calls: it walks a tool-result-shaped structure and strips
only the `text` value of nodes shaped `{"source": "vendor", "text": ...}`
-- `seller`/`juli` provenance envelopes, and any plain (unwrapped) string,
are left alone, because ADR-075 decision 5 scopes stripping to vendor text
only.
"""

from __future__ import annotations

import unicodedata

from juli_backend.services.agent.sanitize.hidden_text import (
    strip_hidden_text,
    strip_hidden_text_from_vendor_fields,
)


class TestStripHiddenTextControlCharacters:
    def test_removes_bel_escape_and_form_feed(self):
        raw = "Ao thun cotton\x07\x1b\x0cban chay nhat"
        assert strip_hidden_text(raw) == "Ao thun cottonban chay nhat"

    def test_preserves_tab_newline_and_carriage_return(self):
        raw = "line one\tindented\nline two\r\n"
        assert strip_hidden_text(raw) == raw

    def test_removes_null_byte(self):
        assert strip_hidden_text("a\x00b") == "ab"


class TestStripHiddenTextZeroWidthAndInvisible:
    def test_removes_zero_width_space_joiner_and_non_joiner(self):
        raw = "ig​nore‌all‍previous"
        assert strip_hidden_text(raw) == "ignoreallprevious"

    def test_removes_zero_width_no_break_space_bom(self):
        raw = "value﻿"
        assert strip_hidden_text(raw) == "value"

    def test_removes_word_joiner_and_soft_hyphen(self):
        raw = "wo⁠rd­ break"
        assert strip_hidden_text(raw) == "word break"


class TestStripHiddenTextBidiOverrides:
    def test_removes_rlo_and_pdf(self):
        raw = "before‮reversed‬after"
        assert strip_hidden_text(raw) == "beforereversedafter"

    def test_removes_lro_rli_lri_fsi_pdi_lrm_rlm_alm(self):
        raw = "‪‭⁦⁧⁨⁩‎‏؜clean"
        assert strip_hidden_text(raw) == "clean"


class TestStripHiddenTextDoesNotEatLegitimateContent:
    def test_vietnamese_combining_diacritics_survive_byte_for_byte(self):
        nfc = "Cảm ơn quý khách đã tin tưởng và ủng hộ sản phẩm của chúng tôi"
        nfd = unicodedata.normalize("NFD", nfc)
        assert strip_hidden_text(nfd) == nfd

    def test_vietnamese_precomposed_diacritics_survive_byte_for_byte(self):
        nfc = "Giao hàng nhanh, chất lượng tốt, cảm ơn quý khách đã ủng hộ"
        assert strip_hidden_text(nfc) == nfc

    def test_simple_single_codepoint_emoji_survive_byte_for_byte(self):
        raw = "Giao hang nhanh 🚚 chat luong tot 👍 cam on 🎉"
        assert strip_hidden_text(raw) == raw

    def test_emoji_skin_tone_modifier_survives(self):
        # EMOJI MODIFIER FITZPATRICK TYPE-1-2 is category Sk, not Cf -- must
        # not be treated as an invisible/format character.
        raw = "thanks \U0001f44d\U0001f3fb"
        assert strip_hidden_text(raw) == raw

    def test_empty_string_and_plain_ascii_are_unaffected(self):
        assert strip_hidden_text("") == ""
        assert strip_hidden_text("Plain ASCII product title") == "Plain ASCII product title"


class TestStripHiddenTextFromVendorFieldsStructuralWrapper:
    def test_strips_only_the_text_of_a_vendor_tagged_node(self):
        value = {"description": {"source": "vendor", "text": "hidden​text"}}
        result = strip_hidden_text_from_vendor_fields(value)
        assert result == {"description": {"source": "vendor", "text": "hiddentext"}}

    def test_does_not_strip_seller_tagged_text(self):
        value = {"note": {"source": "seller", "text": "keep​this"}}
        result = strip_hidden_text_from_vendor_fields(value)
        assert result == {"note": {"source": "seller", "text": "keep​this"}}

    def test_does_not_strip_juli_tagged_text(self):
        value = {"summary": {"source": "juli", "text": "keep​this"}}
        result = strip_hidden_text_from_vendor_fields(value)
        assert result == {"summary": {"source": "juli", "text": "keep​this"}}

    def test_does_not_touch_plain_unwrapped_strings(self):
        value = {"status": "ACTIVE​"}
        result = strip_hidden_text_from_vendor_fields(value)
        assert result == {"status": "ACTIVE​"}

    def test_recurses_into_lists_and_nested_dicts(self):
        value = {
            "items": [
                {"source": "vendor", "text": "a​b"},
                {"nested": {"source": "vendor", "text": "c​d"}},
            ]
        }
        result = strip_hidden_text_from_vendor_fields(value)
        assert result == {
            "items": [
                {"source": "vendor", "text": "ab"},
                {"nested": {"source": "vendor", "text": "cd"}},
            ]
        }

    def test_does_not_mutate_the_input(self):
        value = {"description": {"source": "vendor", "text": "hidden​text"}}
        strip_hidden_text_from_vendor_fields(value)
        assert value == {"description": {"source": "vendor", "text": "hidden​text"}}
