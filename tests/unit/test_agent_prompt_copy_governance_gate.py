"""Mechanical copy governance gate -- issue #1039 (W2-A/P12-4, ADR-072
decision 6, gate 4 of 4).

Zero `packages/contracts/seller-copy-banned-patterns.json` entries and zero
`dictionary.md` `_Avoid_` aliases in the Vietnamese exemplar -- checked
against the shared sources via the existing loader
(`juli_backend.services.agent.sanitize.load_banned_patterns`) and a direct
parse of `dictionary.md`, **never** a hand-copied list (#1002 is an open
defect precisely because a third copy already exists; this file does not
add a fourth).

## Scope: the worked example only, not the whole composed prompt

Per #1037's acceptance criteria and this issue's own scope note, the
English instruction text legitimately contains words the banned-pattern
source forbids in *seller-facing* copy -- `endpoint` (Prohibition 2's own
prohibition text: "never put ... an API endpoint ... into text the seller
reads") and `workflow_key` (Section 4's illustrative `juli` context
payload field name, which ADR-072 d.1 requires this prompt to document).
Scanning the whole composed prompt for banned patterns would flag both as
false positives. `dictionary.md`'s mini-glossary (Section 7) is reference
material by design: its "Never use" column *literally lists* the `_Avoid_`
aliases this gate forbids, so scanning that table would also
false-positive on the very column that documents the prohibition.

This gate is therefore scoped exactly like #1037's own
`test_worked_example_has_zero_banned_pattern_hits` /
`test_worked_example_has_zero_avoid_aliases_from_dictionary`
(`tests/unit/test_agent_prompt_optimize_product_v1_contract.py`) -- the
worked example's Vietnamese blockquote body, extracted by marker, and
nothing else. The difference from #1037's tests: this gate runs the
extraction against `compose()`'s **rendered output**, the artifact that
actually ships to the model, rather than against the raw `v1.md` source
file directly -- closing the loop for what a future prose edit or a
future second workflow's composed prompt would actually be checked
against. `_extract_worked_example` below mirrors #1037's helper of the
same name and purpose (adapted to operate on composed text, where the
marker positions are unchanged by playbook rendering -- rendering only
touches Section 5's `{playbook}` slot, never Section 7 or Section 8).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from juli_backend.services.agent.playbooks.optimize_product import WORKFLOW_KEY
from juli_backend.services.agent.prompts.composer import compose
from juli_backend.services.agent.sanitize import load_banned_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]
DICTIONARY_PATH = REPO_ROOT / "dictionary.md"

_WORKED_EXAMPLE_MARKER = "**Worked example — final seller-facing response (Vietnamese):**"
_SECTION_8_HEADING = "## 8. Prohibited Behaviors"


def _extract_worked_example(composed: str) -> str:
    """The worked example's final Vietnamese response -- the blockquote
    body directly under the "Worked example" marker in Section 7, up to
    (not including) Section 8's heading. Mirrors
    `test_agent_prompt_optimize_product_v1_contract.py::_worked_example_block`
    (#1037), operating on the composed prompt string rather than the raw
    prose file.
    """
    start = composed.index(_WORKED_EXAMPLE_MARKER) + len(_WORKED_EXAMPLE_MARKER)
    end = composed.index(_SECTION_8_HEADING)
    block = composed[start:end]
    lines = [
        line[2:] if line.startswith("> ") else line[1:]
        for line in block.splitlines()
        if line.startswith(">")
    ]
    return "\n".join(lines)


def _parse_dictionary_entries() -> dict[str, dict[str, list[str]]]:
    """Parse `dictionary.md` into {key: {"avoid": [str, ...]}}.

    Mirrors `test_agent_prompt_optimize_product_v1_contract.py::_parse_dictionary_entries`
    (#1037) -- no Python loader for `dictionary.md` exists elsewhere in the
    repo, so this parses the canonical file directly rather than
    hand-copying its `_Avoid_` entries.
    """
    text = DICTIONARY_PATH.read_text(encoding="utf-8")
    entries: dict[str, dict[str, list[str]]] = {}
    for block in re.split(r"\n(?=\*\*`[\w.]+`\*\*)", text):
        key_match = re.match(r"\*\*`([\w.]+)`\*\*", block)
        if not key_match:
            continue
        avoid_match = re.search(r"^- _Avoid_:\s*(.+)$", block, re.MULTILINE)
        avoid: list[str] = []
        if avoid_match:
            for item in avoid_match.group(1).split(","):
                cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", item.strip()).strip()
                if cleaned:
                    avoid.append(cleaned)
        entries[key_match.group(1)] = {"avoid": avoid}
    return entries


@pytest.fixture(scope="module")
def dictionary_entries() -> dict[str, dict[str, list[str]]]:
    assert DICTIONARY_PATH.is_file()
    entries = _parse_dictionary_entries()
    assert entries, "dictionary.md parsed to zero entries -- parser is broken"
    return entries


def _assert_no_banned_pattern_hits(text: str) -> None:
    compiled = load_banned_patterns()
    hits = [pattern.pattern for pattern in compiled if pattern.search(text)]
    assert hits == [], f"banned-pattern hit(s) in Vietnamese exemplar: {hits}"


def _assert_no_avoid_aliases(
    text: str, dictionary_entries: dict[str, dict[str, list[str]]]
) -> None:
    text_cf = text.casefold()
    hits: list[tuple[str, str]] = []
    for key, entry in dictionary_entries.items():
        for alias in entry["avoid"]:
            if alias and alias.casefold() in text_cf:
                hits.append((key, alias))
    assert hits == [], f"_Avoid_ alias hit(s) in Vietnamese exemplar: {hits}"


# ---------------------------------------------------------------------------
# The real gate: the composed prompt's worked example has zero hits.
# ---------------------------------------------------------------------------


def test_worked_example_extraction_is_non_empty():
    composed = compose(WORKFLOW_KEY, 1)
    exemplar = _extract_worked_example(composed)
    assert exemplar.strip(), "worked example extracted empty from composed prompt"


def test_composed_prompt_worked_example_has_zero_banned_pattern_hits():
    composed = compose(WORKFLOW_KEY, 1)
    exemplar = _extract_worked_example(composed)
    _assert_no_banned_pattern_hits(exemplar)


def test_composed_prompt_worked_example_has_zero_avoid_aliases(dictionary_entries):
    composed = compose(WORKFLOW_KEY, 1)
    exemplar = _extract_worked_example(composed)
    _assert_no_avoid_aliases(exemplar, dictionary_entries)


# ---------------------------------------------------------------------------
# Scope proof: the whole composed prompt legitimately contains banned words
# outside the worked example (the false-positive surface the module
# docstring describes) -- confirms this gate's narrower scope is
# load-bearing, not incidental.
# ---------------------------------------------------------------------------


def test_the_whole_composed_prompt_would_false_positive_on_banned_patterns_if_unscoped():
    composed = compose(WORKFLOW_KEY, 1)
    compiled = load_banned_patterns()
    hits = [pattern.pattern for pattern in compiled if pattern.search(composed)]
    assert hits, (
        "expected the unscoped composed prompt to contain at least one legitimate "
        "banned-word usage (e.g. 'endpoint', 'workflow_key') -- if this is now "
        "empty, the scope note in this module's docstring may be stale"
    )
    # And confirm the worked example on its own does not carry those hits --
    # the false positives live outside the scope this gate actually checks.
    exemplar = _extract_worked_example(composed)
    exemplar_hits = [pattern.pattern for pattern in compiled if pattern.search(exemplar)]
    assert exemplar_hits == []


# ---------------------------------------------------------------------------
# Synthetic drift detection -- prove the checking mechanism itself catches a
# real hit and names it, independent of whether the real exemplar ever
# regresses. Issue #1039 acceptance criterion: inject an _Avoid_ alias
# drawn from dictionary.md.
# ---------------------------------------------------------------------------


class TestSyntheticDriftDetection:
    def test_a_real_banned_pattern_in_synthetic_text_is_caught_and_named(self):
        # "confirm" is a real entry in the shared banned-pattern source
        # (packages/contracts/seller-copy-banned-patterns.json, id
        # "confirm", \bconfirm\b, case-insensitive) -- an
        # internal-implementation-detail word that should never reach
        # seller-facing text.
        synthetic_text = "Vui lòng confirm đơn hàng trước khi tiếp tục."
        with pytest.raises(AssertionError, match="confirm"):
            _assert_no_banned_pattern_hits(synthetic_text)

    def test_text_with_no_banned_pattern_hits_does_not_fail(self):
        synthetic_text = "Chào bạn, đây là một câu ví dụ hoàn toàn hợp lệ."
        # Must not raise.
        _assert_no_banned_pattern_hits(synthetic_text)

    def test_a_real_avoid_alias_drawn_from_dictionary_md_is_caught_and_named(
        self, dictionary_entries
    ):
        # "Gợi ý hành động" is dictionary.md's own documented _Avoid_ alias
        # for decisions.recommendation -- confirmed against the parsed
        # dictionary itself, not asserted as a hardcoded fact (issue
        # #1039's own mutation-proof acceptance criterion: inject an
        # _Avoid_ alias drawn from dictionary.md).
        alias = "Gợi ý hành động"
        assert any(alias in entry["avoid"] for entry in dictionary_entries.values()), (
            "expected alias missing from the parsed dictionary.md -- fixture is stale"
        )

        synthetic_text = f"Đây là {alias} dành cho bạn."
        with pytest.raises(AssertionError, match=re.escape(alias)):
            _assert_no_avoid_aliases(synthetic_text, dictionary_entries)

    def test_injecting_the_avoid_alias_into_a_real_worked_example_copy_is_caught(
        self, dictionary_entries
    ):
        """Closer to the real gate's shape than the bare-string test above:
        take the real composed worked example (currently clean) and inject
        a real dictionary.md _Avoid_ alias into a COPY of it -- proves the
        gate would catch a regression in the actual artifact it protects,
        not just an isolated helper call on unrelated text.
        """
        composed = compose(WORKFLOW_KEY, 1)
        real_exemplar = _extract_worked_example(composed)
        _assert_no_avoid_aliases(real_exemplar, dictionary_entries)  # sanity: clean today

        alias = "Gợi ý hành động"
        mutated_exemplar = real_exemplar + f"\n{alias} dành cho bạn."

        with pytest.raises(AssertionError, match=re.escape(alias)):
            _assert_no_avoid_aliases(mutated_exemplar, dictionary_entries)

        # The real composed prompt itself is untouched by building a copy.
        assert _extract_worked_example(compose(WORKFLOW_KEY, 1)) == real_exemplar

    def test_text_with_no_avoid_aliases_does_not_fail(self, dictionary_entries):
        synthetic_text = "Chào bạn, đây là một câu ví dụ hoàn toàn hợp lệ."
        # Must not raise.
        _assert_no_avoid_aliases(synthetic_text, dictionary_entries)


# ---------------------------------------------------------------------------
# Checked against the shared sources themselves -- never a hand-copied list.
# ---------------------------------------------------------------------------


def test_banned_patterns_are_loaded_via_the_existing_shared_loader():
    from juli_backend.services.agent.sanitize.banned_patterns import BANNED_PATTERNS_JSON_PATH

    assert BANNED_PATTERNS_JSON_PATH.is_file()
    compiled = load_banned_patterns()
    assert len(compiled) > 0


def test_avoid_aliases_are_read_from_dictionary_md_not_hardcoded(dictionary_entries):
    assert "decisions.recommendation" in dictionary_entries
    assert "Gợi ý hành động" in dictionary_entries["decisions.recommendation"]["avoid"]


def test_dictionary_parse_is_non_empty_so_the_avoid_check_is_not_vacuous(dictionary_entries):
    """Issue #1039's own instruction: assert the parse is non-empty, since
    a regex matching nothing passes everything."""
    total_avoid_aliases = sum(len(entry["avoid"]) for entry in dictionary_entries.values())
    assert len(dictionary_entries) > 0
    assert total_avoid_aliases > 0


def test_banned_pattern_source_parse_is_non_empty_so_the_banned_check_is_not_vacuous():
    """Same non-vacuity requirement applied to the other shared source."""
    compiled = load_banned_patterns()
    assert len(compiled) > 0
