"""Contract tests for the Optimize Product v1 prompt file (issue #1037,
W2-A/P12-2, ADR-072 decisions 1, 3, 5).

`v1.md` is the entire hand-written tuning surface for the Optimize Product
workflow prompt: eight ordered sections (d.1), English instructions with a
Vietnamese "bạn"-form worked example (d.3), three source-role rules and
seven prohibitions (d.5), and exactly one template slot (`{playbook}`) —
run data is never spliced into the prose (ADR-070 d.3 / ADR-072 d.1).

Every check here reads a *real* source, never a hand-copied constant:
`packages/contracts/seller-copy-banned-patterns.json` via the existing
`juli_backend.services.agent.sanitize.load_banned_patterns()` loader, and
`dictionary.md` parsed directly (no Python loader exists for it elsewhere).
A test that hardcodes the expected banned terms or glossary values would
recreate exactly the drift those shared sources exist to prevent.

Out of this issue's scope, and deliberately not exercised here: `compose()`
and the four ADR-072 d.6 import-time gates (snapshot / budget / playbook
consistency / copy governance) belong to #1038 and #1039; the typed
`Playbook` artifact belongs to #1036. This file tests `v1.md` standalone —
the raw prose, with `{playbook}` left as a literal, un-rendered slot.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from juli_backend.services.agent.sanitize import estimate_tokens, load_banned_patterns

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = (
    REPO_ROOT
    / "backend"
    / "src"
    / "juli_backend"
    / "services"
    / "agent"
    / "prompts"
    / "optimize_product"
    / "v1.md"
)
DICTIONARY_PATH = REPO_ROOT / "dictionary.md"

# ADR-072 d.1's eight ordered sections, keyed by their exact v1.md heading.
SECTION_HEADINGS: tuple[str, ...] = (
    "## 1. Role",
    "## 2. Mandate & Limits",
    "## 3. Source-Role Rules",
    "## 4. Input Signals",
    "## 5. Playbook",
    "## 6. Recommend Within Scope",
    "## 7. Output Guidance + Worked Example",
    "## 8. Prohibited Behaviors",
)

SOURCE_ROLE_MARKERS: tuple[str, ...] = ("`juli`", "`vendor`", "`seller`")

PROHIBITION_KEYWORDS: dict[str, str] = {
    "Prohibition 1": "fabricat",
    "Prohibition 2": "identifier",
    "Prohibition 3": "tool result",
    "Prohibition 4": "playbook",
    "Prohibition 5": "banned pattern",
    "Prohibition 6": "scope",
    "Prohibition 7": "honestly",
}

# Reference-proven raw budget (ADR-072 d.6, #1037/#1038/#1039 W2-A run):
# with `{playbook}` left un-rendered, the released prose measured 2,687
# proxy tokens and composed (playbook slot filled by the reference
# Playbook) to 2,967 -- an observed render cost of 2,967 - 2,687 = 280
# tokens for the `{playbook}` slot's content. `estimate_tokens()` is this
# repo's stdlib, tiktoken-free proxy (backend/src/juli_backend/services/
# agent/sanitize/caps.py); ADR-072 d.6 says "tiktoken-measured" but
# `tiktoken` is an undeclared dependency (not in backend/pyproject.toml or
# constraints.txt), so this test measures with the proxy and records the
# divergence here rather than silently swapping in a different measurement.
#
# The ceiling below is chosen so this file cannot pass a raw prose that
# would compose over budget, using the reference's own observed render
# cost as the only number available from outside #1038's scope (this
# file cannot run `compose()` itself):
#
#     reserved budget   = ADR-072 d.6 ceiling - observed render cost
#                        = 3,000 - 280
#                        = 2,720
#     composed total at
#     the ceiling        = ceiling + observed render cost
#                        = 2,720 + 280
#                        = 3,000  (at, not over, the hard limit)
#
# 2,720 is the loosest ceiling that still guarantees this invariant --
# anything higher would let a raw file compose over 3,000 while this test
# still passed, which is worse than no ceiling because it reads as
# protection. Against the released v1.md's actual 2,687, this leaves 33
# tokens of headroom: tight, but v1 is immutable (ADR-072 d.4) and not
# expected to grow, so no further margin is needed or safe to add.
RAW_PROMPT_TOKEN_CEILING = 2720


@pytest.fixture(scope="module")
def prompt_text() -> str:
    assert PROMPT_PATH.is_file(), f"expected prompt file at {PROMPT_PATH}"
    return PROMPT_PATH.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    spans: dict[str, str] = {}
    for i, heading in enumerate(SECTION_HEADINGS):
        start = text.index(heading) + len(heading)
        end = text.index(SECTION_HEADINGS[i + 1]) if i + 1 < len(SECTION_HEADINGS) else len(text)
        spans[heading] = text[start:end]
    return spans


def _worked_example_block(text: str) -> str:
    """The blockquoted Vietnamese response under Section 7's worked-example
    marker, up to (not including) Section 8. This is the exact scope of the
    "zero banned pattern / zero _Avoid_ alias" acceptance criterion -- not
    the whole file, which legitimately names `_Avoid_` aliases (English
    words like the ones on the banned-pattern list) in the mini-glossary and
    in Section 8's English prose.
    """
    marker = "Worked example"
    start = text.index(marker, text.index("## 7."))
    end = text.index("## 8. Prohibited Behaviors")
    block = text[start:end]
    lines = [
        line[2:] if line.startswith("> ") else line[1:]
        for line in block.splitlines()
        if line.startswith(">")
    ]
    return "\n".join(lines)


def _parse_dictionary_entries() -> dict[str, dict[str, object]]:
    text = DICTIONARY_PATH.read_text(encoding="utf-8")
    entries: dict[str, dict[str, object]] = {}
    for block in re.split(r"\n(?=\*\*`[\w.]+`\*\*)", text):
        key_match = re.match(r"\*\*`([\w.]+)`\*\*", block)
        if not key_match:
            continue
        vi_match = re.search(r"^- VI:\s*(.+)$", block, re.MULTILINE)
        avoid_match = re.search(r"^- _Avoid_:\s*(.+)$", block, re.MULTILINE)
        avoid: list[str] = []
        if avoid_match:
            for item in avoid_match.group(1).split(","):
                cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", item.strip()).strip()
                if cleaned:
                    avoid.append(cleaned)
        entries[key_match.group(1)] = {
            "vi": vi_match.group(1).strip() if vi_match else None,
            "avoid": avoid,
        }
    return entries


@pytest.fixture(scope="module")
def dictionary_entries() -> dict[str, dict[str, object]]:
    assert DICTIONARY_PATH.is_file()
    entries = _parse_dictionary_entries()
    assert entries, "dictionary.md parsed to zero entries -- parser is broken"
    return entries


def _mini_glossary_rows(prompt_text: str) -> list[tuple[str, str, list[str]]]:
    section = _sections(prompt_text)["## 7. Output Guidance + Worked Example"]
    table = section[section.index("| Term") : section.index("Worked example")]
    rows: list[tuple[str, str, list[str]]] = []
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert len(cells) == 3, cells
        key = cells[0].strip("`")
        avoid = [] if cells[2] == "—" else [a.strip() for a in cells[2].split(";")]
        rows.append((key, cells[1], avoid))
    return rows


# ---------------------------------------------------------------------------
# File location + eight ordered, substantive sections
# ---------------------------------------------------------------------------


def test_file_exists_at_the_version_addressed_path():
    assert PROMPT_PATH.is_file()


def test_eight_section_headings_present_in_adr072_order(prompt_text):
    indices = [prompt_text.index(h) for h in SECTION_HEADINGS]
    assert indices == sorted(indices)
    assert len(indices) == len(set(indices))


def test_each_section_is_substantive_not_a_stub(prompt_text):
    for heading, body in _sections(prompt_text).items():
        collapsed = " ".join(body.split())
        assert len(collapsed) > 150, f"{heading!r} looks like a stub ({len(collapsed)} chars)"


# ---------------------------------------------------------------------------
# {playbook} is the only template slot
# ---------------------------------------------------------------------------


def test_playbook_slot_is_the_only_template_slot(prompt_text):
    slots = re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", prompt_text)
    assert slots == ["{playbook}"], slots


# ---------------------------------------------------------------------------
# No run data spliced into the prose (ADR-070 d.3 / ADR-072 d.1)
# ---------------------------------------------------------------------------


def test_no_run_data_values_outside_the_illustrative_json_shape(prompt_text):
    sections = _sections(prompt_text)
    for heading, body in sections.items():
        scoped = body
        if heading == "## 4. Input Signals":
            # The illustrative payload shape may show field names; it must
            # carry zero digits (checked separately below), so this
            # section is excluded from the percentage/currency scan below
            # without weakening coverage.
            continue
        assert not re.search(r"\d+(\.\d+)?%", scoped), heading
        assert not re.search(r"₫\s?[\d,]+", scoped), heading


def test_input_signals_json_shape_carries_no_digits(prompt_text):
    body = _sections(prompt_text)["## 4. Input Signals"]
    block = body[body.index("```json") : body.index("```", body.index("```json") + 1)]
    assert not re.search(r"\d", block)


def test_no_uuid_shaped_identifier_anywhere(prompt_text):
    pattern = re.compile(
        r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
    )
    assert not pattern.search(prompt_text)


# ---------------------------------------------------------------------------
# Three source-role rules, each distinguishable (ADR-072 d.5)
# ---------------------------------------------------------------------------


def test_three_source_role_markers_present_once_each_in_order(prompt_text):
    section = _sections(prompt_text)["## 3. Source-Role Rules"]
    positions = [section.index(marker) for marker in SOURCE_ROLE_MARKERS]
    assert positions == sorted(positions)
    for marker in SOURCE_ROLE_MARKERS:
        assert section.count(marker) == 1, marker


def test_source_role_rules_never_claim_to_unlock_tools(prompt_text):
    # Collapse whitespace first: the prose wraps at ~79 chars, so a phrase
    # can legitimately straddle a line break in the raw markdown.
    section = " ".join(_sections(prompt_text)["## 3. Source-Role Rules"].split()).lower()
    assert "does not grant you any tool" in section or "cannot unlock a tool" in section


# ---------------------------------------------------------------------------
# Seven prohibitions, each individually identifiable (ADR-072 d.5)
# ---------------------------------------------------------------------------


def test_seven_prohibitions_present_exactly_once(prompt_text):
    section = _sections(prompt_text)["## 8. Prohibited Behaviors"]
    for marker in PROHIBITION_KEYWORDS:
        assert section.count(marker) == 1, marker


@pytest.mark.parametrize("marker,keyword", list(PROHIBITION_KEYWORDS.items()))
def test_each_prohibition_carries_its_own_distinguishing_keyword(prompt_text, marker, keyword):
    section = _sections(prompt_text)["## 8. Prohibited Behaviors"]
    idx = section.index(marker)
    window = section[idx : idx + 500].lower()
    assert keyword.lower() in window, (marker, keyword)


def test_prohibition_4_covers_tool_scope_and_fresh_confirmation(prompt_text):
    section = _sections(prompt_text)["## 8. Prohibited Behaviors"]
    window = section[section.index("Prohibition 4") : section.index("Prohibition 4") + 600]
    assert "playbook" in window
    assert "fresh" in window.lower()


# ---------------------------------------------------------------------------
# Section 4: summarize-from-signals, never-invent instruction
# ---------------------------------------------------------------------------


def test_input_signals_instructs_summarize_and_never_invent(prompt_text):
    section = " ".join(_sections(prompt_text)["## 4. Input Signals"].split()).lower()
    assert "summarize" in section
    assert "never invent" in section or "do not invent" in section


# ---------------------------------------------------------------------------
# Section 6: HOW-level scope, never a new workflow
# ---------------------------------------------------------------------------


def test_recommend_within_scope_is_how_level_never_a_new_workflow(prompt_text):
    section = _sections(prompt_text)["## 6. Recommend Within Scope"]
    assert "HOW-level" in section
    assert "never a new workflow" in section


# ---------------------------------------------------------------------------
# Language split: English instructions, Vietnamese worked example, "bạn"
# ---------------------------------------------------------------------------

_VI_DIACRITICS = re.compile(
    "[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợ"
    "ùúủũụưừứửữựỳýỷỹỵđ"
    "ÀÁẢÃẠĂẰẮẲẴẶÂẦẤẨẪẬÈÉẺẼẸÊỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌÔỒỐỔỖỘƠỜỚỞỠỢ"
    "ÙÚỦŨỤƯỪỨỬỮỰỲÝỶỸỴĐ]"
)

_OUTPUT_GUIDANCE_HEADING = "## 7. Output Guidance + Worked Example"
_INSTRUCTION_HEADINGS = tuple(h for h in SECTION_HEADINGS if h != _OUTPUT_GUIDANCE_HEADING)


def test_instruction_sections_carry_no_vietnamese_text(prompt_text):
    sections = _sections(prompt_text)
    for heading in _INSTRUCTION_HEADINGS:
        assert not _VI_DIACRITICS.search(sections[heading]), heading


def test_worked_example_is_vietnamese_using_ban_address_form(prompt_text):
    example = _worked_example_block(prompt_text)
    assert example.strip()
    assert _VI_DIACRITICS.search(example)
    assert example.count("bạn") >= 2


# ---------------------------------------------------------------------------
# Mini-glossary: real dictionary.md keys/values, real _Avoid_ aliases
# ---------------------------------------------------------------------------


def test_mini_glossary_has_at_least_five_rows(prompt_text):
    assert len(_mini_glossary_rows(prompt_text)) >= 5


def test_mini_glossary_rows_match_dictionary_md_exactly(prompt_text, dictionary_entries):
    for key, vi, avoid in _mini_glossary_rows(prompt_text):
        assert key in dictionary_entries, f"{key!r} is not a real dictionary.md key"
        canonical = dictionary_entries[key]
        assert vi == canonical["vi"], (key, vi, canonical["vi"])
        canonical_avoid = set(canonical["avoid"])
        for alias in avoid:
            assert alias in canonical_avoid, (key, alias, canonical_avoid)


def test_mini_glossary_forbids_at_least_one_real_avoid_alias(prompt_text):
    total = sum(len(avoid) for _, _, avoid in _mini_glossary_rows(prompt_text))
    assert total > 0


# ---------------------------------------------------------------------------
# Worked example: zero banned-pattern hits, zero _Avoid_ aliases -- checked
# against the shared sources, never a hand-copied list (#1002).
# ---------------------------------------------------------------------------


def test_worked_example_has_zero_banned_pattern_hits(prompt_text):
    example = _worked_example_block(prompt_text)
    hits = [p.pattern for p in load_banned_patterns() if p.search(example)]
    assert hits == []


def test_worked_example_has_zero_avoid_aliases_from_dictionary(prompt_text, dictionary_entries):
    example_cf = _worked_example_block(prompt_text).casefold()
    hits = [
        (key, alias)
        for key, entry in dictionary_entries.items()
        for alias in entry["avoid"]
        if alias and alias.casefold() in example_cf
    ]
    assert hits == []


# ---------------------------------------------------------------------------
# Token budget (ADR-072 d.6): raw file, `{playbook}` left un-rendered, must
# leave realistic headroom below 3,000 once the playbook slot is filled.
# ---------------------------------------------------------------------------


def test_raw_prompt_token_estimate_leaves_headroom_for_playbook_rendering(prompt_text):
    estimate = estimate_tokens(prompt_text)
    assert estimate <= RAW_PROMPT_TOKEN_CEILING, (
        f"raw v1.md estimates to {estimate} proxy tokens, over the "
        f"{RAW_PROMPT_TOKEN_CEILING}-token ceiling reserved to leave "
        "headroom for the {playbook} slot's rendered content"
    )
