"""`ToolSpec.seller_rationale_vi` — issue #1904 (W6-FIX).

The Đề xuất option picker was rendering `spec.description` — the LLM-facing
English tool description — verbatim to a Vietnamese seller on the screen
where a click authorizes a real mutation (confirmed in the live
`run_confirmations` row for a real sandbox run). The fix: `ToolSpec` gains a
required, dictionary-governed `seller_rationale_vi` field, distinct from
`description`, which stays exactly as it was because the model reads it.

This module proves three things:

1. `ToolSpec` cannot be constructed without `seller_rationale_vi` (a required
   dataclass field — a construction omitting it is a `TypeError`), and an
   empty string is a `ValueError` (mirrors the existing `description` check).
2. Every ToolSpec in the REAL, currently-registered universe
   (`composition.build_product_tool_registry()` — not a hardcoded name list,
   so a future tool without a rationale fails this test without anyone
   remembering to add a case) has a `seller_rationale_vi` that (a) contains
   at least one Vietnamese diacritic, (b) contains no bare `[a-z]+_[a-z]+`
   snake_case identifier (the exact defect this issue fixes — a raw
   tool/field name leaking into seller copy), and (c) trips zero entries in
   the shared `packages/contracts/seller-copy-banned-patterns.json` source,
   read via the existing loader (`juli_backend.services.agent.sanitize
   .load_banned_patterns`) — never a local copy of the list.
3. Every registered tool's `seller_rationale_vi` is sourced from
   `dictionary.md`'s own `run.option_rationale.<tool_name>` entry — parsed
   directly from the file, never hand-copied — so the dictionary stays the
   single source of truth `dictionary.md`'s own preamble requires.
4. `spec.description` is unchanged, byte-for-byte, for every tool — the
   model's view does not move. Guards against a future edit accidentally
   touching the English string while making `seller_rationale_vi` right.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from juli_backend.services.agent.composition import build_product_tool_registry
from juli_backend.services.agent.sanitize import load_banned_patterns
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolSpec,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DICTIONARY_PATH = REPO_ROOT / "dictionary.md"

_SNAKE_CASE_IDENTIFIER = re.compile(r"\b[a-z]+_[a-z]+\b")

# Vietnamese vowels-with-diacritics + đ/Đ, upper and lower. Explicit
# enumeration rather than a codepoint range: Vietnamese diacritic characters
# are not contiguous in Unicode, so a range like `à-ỹ` silently includes
# unrelated codepoints and silently excludes real Vietnamese letters.
_VIETNAMESE_LETTERS = "àáâãăằắẳẵặầấẩẫậèéêềếểễệìíĩỉịòóôõơồốổỗộờớởỡợùúũưừứửữựỳýỵỷỹđ"
_VIETNAMESE_DIACRITIC = re.compile(f"[{_VIETNAMESE_LETTERS}{_VIETNAMESE_LETTERS.upper()}]")

# Byte-for-byte snapshot of every registered tool's model-facing
# `description`, unchanged by this issue -- the model's view does not move.
# Duplicated here deliberately (rather than derived) so a future edit to a
# tool's description in source is caught by THIS test comparing against a
# frozen expectation, not by comparing the source against itself.
EXPECTED_DESCRIPTIONS: dict[str, str] = {
    "get_product_information": (
        "Read the bound product's listing: title, description, status, "
        "last-updated time, SKU count and prices, total inventory, and image sizes."
    ),
    "get_seo_keywords": (
        "Get SEO keyword suggestions and title/description suggestions for the "
        "bound product, combined into one result."
    ),
    "check_product_status": (
        "Get an in-run snapshot of the bound product's current status. This snapshot is "
        "not authoritative — the confirmed status arrives later, outside this tool call."
    ),
    "inspect_product_image": (
        "Check whether the product's main photo matches its title and description. "
        "Returns findings and recommended image edits -- it does not change the photo. "
        "A photo dominated by promotional banners or price overlays is a finding even "
        "when the product shown is correct."
    ),
    "upload_product_image": (
        "Screen and upload the seller-supplied candidate listing image staged for this "
        "run. The image is not applied to the listing until update_product_listing is "
        "called with attach_staged_image=True."
    ),
    "update_product_listing": (
        "Apply agent-authored title/description (and, if attach_staged_image is true, "
        "the run's staged image) to the bound product's listing."
    ),
    "update_product_price": (
        "Apply new SKU prices (by opaque sku_ref) to the bound product. Independently "
        "rejectable from update_product_listing."
    ),
    "conclude_without_changes": (
        "Conclude this optimization run without proposing any changes. Use this "
        "when you have completed your analysis and determined that the product "
        "is already well-optimized, or when you need more information to make "
        "a recommendation. Provide a brief, honest reason for your conclusion."
    ),
}


def _parse_option_rationale_entries() -> dict[str, str]:
    """{tool_name: VI text} for every `run.option_rationale.<tool_name>`
    entry in `dictionary.md` — a direct parse of the canonical file, never a
    hand-copied list (mirrors
    `test_agent_prompt_copy_governance_gate.py::_parse_dictionary_entries`'s
    own "no Python loader for dictionary.md exists elsewhere" rationale,
    extended here to also capture the VI value, not just `_Avoid_`)."""
    text = DICTIONARY_PATH.read_text(encoding="utf-8")
    entries: dict[str, str] = {}
    for block in re.split(r"\n(?=\*\*`[\w.]+`\*\*)", text):
        key_match = re.match(r"\*\*`(run\.option_rationale\.[\w.]+)`\*\*", block)
        if not key_match:
            continue
        vi_match = re.search(r"^- VI:\s*(.+)$", block, re.MULTILINE)
        assert vi_match, f"{key_match.group(1)} has no VI: line in dictionary.md"
        tool_name = key_match.group(1).removeprefix("run.option_rationale.")
        entries[tool_name] = vi_match.group(1).strip()
    return entries


@pytest.fixture(scope="module")
def registry_specs() -> tuple[ToolSpec, ...]:
    return tuple(build_product_tool_registry().list_all())


@pytest.fixture(scope="module")
def dictionary_rationales() -> dict[str, str]:
    entries = _parse_option_rationale_entries()
    assert entries, "dictionary.md parsed to zero run.option_rationale entries"
    return entries


# --- 1. Construction is required and validated -----------------------------


class _FixtureInput(BaseModel):
    pass


class _FixtureOutput(BaseModel):
    pass


def _base_kwargs() -> dict:
    return {
        "name": "fixture_tool",
        "description": "A fixture tool description.",
        "input_model": _FixtureInput,
        "output_model": _FixtureOutput,
        "classification": ToolClassification.READ,
        "policy": ToolPolicy.AUTO,
        "timeout_seconds": 10,
        # #1704: every spec names a tool domain. A fixture spec is not a real
        # capability, so it names a fixture domain -- `ToolRegistry.register`
        # requires *a* domain, and "names a registered domain" is asserted
        # against the real registry in `test_tool_dispatcher_domains.py`.
        "domain": "fixture",
    }


def test_tool_spec_requires_seller_rationale_vi_a_construction_call_missing_it_is_a_type_error():
    with pytest.raises(TypeError):
        ToolSpec(**_base_kwargs())


def test_tool_spec_rejects_an_empty_seller_rationale_vi():
    with pytest.raises(ValueError, match="seller_rationale_vi"):
        ToolSpec(seller_rationale_vi="", **_base_kwargs())


def test_tool_spec_accepts_a_non_empty_seller_rationale_vi():
    spec = ToolSpec(seller_rationale_vi="Xem thông tin sản phẩm này.", **_base_kwargs())
    assert spec.seller_rationale_vi == "Xem thông tin sản phẩm này."


# --- 2. Every registered tool's seller_rationale_vi is seller-safe ---------


class TestEveryRegisteredToolHasASellerSafeRationale:
    def test_registry_is_non_empty_so_this_gate_is_not_vacuous(self, registry_specs):
        assert len(registry_specs) >= 8

    def test_every_seller_rationale_vi_contains_a_vietnamese_diacritic(self, registry_specs):
        offenders = [
            spec.name
            for spec in registry_specs
            if not _VIETNAMESE_DIACRITIC.search(spec.seller_rationale_vi)
        ]
        assert offenders == [], f"no Vietnamese diacritic in rationale for: {offenders}"

    def test_no_seller_rationale_vi_contains_a_snake_case_identifier(self, registry_specs):
        offenders = {
            spec.name: _SNAKE_CASE_IDENTIFIER.findall(spec.seller_rationale_vi)
            for spec in registry_specs
            if _SNAKE_CASE_IDENTIFIER.search(spec.seller_rationale_vi)
        }
        assert offenders == {}, f"snake_case identifier leaked into rationale: {offenders}"

    def test_no_seller_rationale_vi_trips_the_shared_banned_pattern_source(self, registry_specs):
        compiled = load_banned_patterns()
        offenders = {
            spec.name: [p.pattern for p in compiled if p.search(spec.seller_rationale_vi)]
            for spec in registry_specs
        }
        offenders = {name: hits for name, hits in offenders.items() if hits}
        assert offenders == {}, f"banned-pattern hit(s) in rationale: {offenders}"


# --- 3. dictionary.md is the source of truth -------------------------------


class TestSellerRationaleIsSourcedFromDictionary:
    def test_every_registered_tool_has_a_dictionary_entry(
        self, registry_specs, dictionary_rationales
    ):
        missing = [spec.name for spec in registry_specs if spec.name not in dictionary_rationales]
        assert missing == [], f"missing dictionary.md run.option_rationale entries: {missing}"

    def test_seller_rationale_vi_matches_the_dictionary_entry_verbatim(
        self, registry_specs, dictionary_rationales
    ):
        mismatches = {
            spec.name: (spec.seller_rationale_vi, dictionary_rationales[spec.name])
            for spec in registry_specs
            if spec.seller_rationale_vi != dictionary_rationales[spec.name]
        }
        assert mismatches == {}, f"seller_rationale_vi drifted from dictionary.md: {mismatches}"


# --- 4. spec.description is unchanged, byte-for-byte ------------------------


class TestModelFacingDescriptionIsUnchanged:
    def test_every_registered_tool_has_an_expectation(self, registry_specs):
        missing = [spec.name for spec in registry_specs if spec.name not in EXPECTED_DESCRIPTIONS]
        assert missing == [], f"no frozen description expectation for: {missing}"

    def test_description_is_byte_identical_to_the_frozen_expectation(self, registry_specs):
        mismatches = {
            spec.name: (spec.description, EXPECTED_DESCRIPTIONS[spec.name])
            for spec in registry_specs
            if spec.description != EXPECTED_DESCRIPTIONS[spec.name]
        }
        assert mismatches == {}, (
            f"spec.description moved -- the model's view must not change: {mismatches}"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
