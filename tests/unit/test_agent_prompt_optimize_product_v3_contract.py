"""Contract tests for the Optimize Product v3 prompt file (issue #1367,
ADR-072 decisions 1, 3, 5).

v3.md is a targeted revision of v2.md addressing one defect found on run
37a0e14e-5d00-4816-81c6-5b21cef5d296 (gate #1226 / #1213 approval gate chain):
1. Section 7's worked example now shows ONLY seller-facing prose — no fenced
   code block, no function signature, no pseudo-code.
2. Explicit guidance: tool calls are emitted through the tool-call channel;
   a call written into response text has no effect.
3. New Prohibition 8: never render a tool call, function signature, or code
   block in seller-facing text.

Mechanics:
- v3.md is immutable once released (ADR-072 d.4) — changes become v4.md.
- All of Sections 1–6 and most of 8 are preserved from v2.
- Section 7's worked example is rewritten to show prose only.
- Prohibition 8 is added to Section 8.
- The dictionary.md terms, banned patterns, and copy-governance gates apply.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from juli_backend.services.agent.sanitize import load_banned_patterns

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
    / "v3.md"
)
DICTIONARY_PATH = REPO_ROOT / "dictionary.md"

# ADR-072 d.1's eight ordered sections, keyed by their exact v3.md heading
# — identical to v1/v2's section structure.
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
    marker, up to (not including) Section 8. For v3, this is ONLY the prose,
    with no fenced code blocks.
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
# File location + eight ordered, substantive sections (SAME AS V1/V2)
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
# {playbook} is the only template slot (SAME AS V1/V2)
# ---------------------------------------------------------------------------


def test_playbook_slot_is_the_only_template_slot(prompt_text):
    slots = re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", prompt_text)
    assert slots == ["{playbook}"], slots


# ---------------------------------------------------------------------------
# Issue #1367: Worked example contains ONLY prose, no fenced code blocks
# ---------------------------------------------------------------------------


def test_worked_example_contains_no_fenced_code_blocks(prompt_text):
    """The worked example for v3 must show ONLY seller-facing Vietnamese
    prose, without any code blocks. The tool call is emitted through the
    tool-call channel; it is never rendered as a fence in the example.
    """
    section_7 = _sections(prompt_text)["## 7. Output Guidance + Worked Example"]

    # Find the worked example section
    marker = "Worked example"
    start = section_7.index(marker)
    # Extract from the marker to the next section
    end = section_7.find("## 8. Prohibited Behaviors")
    if end == -1:
        # If no Section 8 found in Section 7 (which shouldn't happen),
        # just use the end of the text
        end = len(section_7)

    worked_example_section = section_7[start:end]

    # Check for any fenced code blocks (``` ... ```)
    fenced_blocks = re.findall(r"```[\w]*\n(.*?)\n```", worked_example_section, re.DOTALL)
    assert fenced_blocks == [], (
        f"v3 worked example must not contain fenced code blocks, "
        f"but found {len(fenced_blocks)}: {fenced_blocks}"
    )


def test_tool_calls_mechanism_described_in_section_7(prompt_text):
    """v3 must explicitly state that tool calls are emitted through the
    tool-call channel, not rendered as text."""
    section_7 = _sections(prompt_text)["## 7. Output Guidance + Worked Example"]
    collapsed = " ".join(section_7.split()).lower()

    # Check for the explicit mechanism description
    assert "tool" in collapsed and "channel" in collapsed


def test_prohibition_8_covers_no_tool_calls_in_text(prompt_text):
    """v3 must have a Prohibition 8 that forbids rendering tool calls,
    function signatures, or code in seller-facing text."""
    section_8 = _sections(prompt_text)["## 8. Prohibited Behaviors"]
    assert "Prohibition 8" in section_8
    # Check it mentions the key concepts
    prohibition_8_section = section_8[section_8.index("Prohibition 8") :]
    p8_text = " ".join(prohibition_8_section.split()).lower()
    assert "tool" in p8_text
    assert "code" in p8_text or "fenced" in p8_text


# ---------------------------------------------------------------------------
# Worked example: zero banned-pattern hits, zero _Avoid_ aliases (SAME AS V1/V2)
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
# Language split: English instructions, Vietnamese worked example (SAME AS V1/V2)
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
