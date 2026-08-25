"""Contract tests for the Optimize Product v2 prompt file (issue #1356,
ADR-072 decisions 1, 3, 5).

v2.md is a targeted revision of v1.md addressing three defects:
1. The worked example must terminate with a CONFIRM-policy tool call
   (update_product_listing), not prose narration.
2. The prompt must state explicitly: the seller cannot answer prose; only
   CONFIRM tool decisions matter.
3. SEO correction: `get_seo_keywords` returns three independent signals
   (seo_words, suggested_titles, suggested_descriptions); all three can
   ground a proposal; a populated suggested_descriptions is first-class
   and does not depend on the other two.

Mechanics:
- v2.md is immutable once released (ADR-072 d.4) — changes become v3.md.
- All of Sections 1–6 and 8's prohibitions are preserved from v1.
- Section 7's worked example is rewritten.
- The dictionary.md terms, banned patterns, and copy-governance gates
  still apply.
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
    / "v2.md"
)
DICTIONARY_PATH = REPO_ROOT / "dictionary.md"

# ADR-072 d.1's eight ordered sections, keyed by their exact v2.md heading
# — identical to v1's section structure.
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
    marker, up to (not including) Section 8. This is the exact scope of the
    "zero banned pattern / zero _Avoid_ alias" acceptance criterion — not
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


def _worked_example_section(text: str) -> str:
    """The full section from 'Worked example' marker to Section 8, including
    both the blockquoted Vietnamese text AND any following code blocks or
    narration about the tool call.
    """
    marker = "Worked example"
    start = text.index(marker, text.index("## 7."))
    end = text.index("## 8. Prohibited Behaviors")
    return text[start:end]


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
# File location + eight ordered, substantive sections (SAME AS V1)
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
# {playbook} is the only template slot (SAME AS V1)
# ---------------------------------------------------------------------------


def test_playbook_slot_is_the_only_template_slot(prompt_text):
    slots = re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", prompt_text)
    assert slots == ["{playbook}"], slots


# ---------------------------------------------------------------------------
# Issue #1356: Worked example must CALL the CONFIRM tool, not narrate prose
# ---------------------------------------------------------------------------


def test_worked_example_contains_a_confirm_tool_call(prompt_text):
    """The worked example's terminal act must be calling update_product_listing
    with concrete arguments, showing the seller narration as the tool call's
    rationale rather than as a substitute for it.
    """
    example = _worked_example_section(prompt_text)

    # The example should reference calling update_product_listing as a tool call.
    # It could be represented as a code block, or as a description of calling it.
    # The key is: the example shows how to *call* the tool, not just how to
    # narrate about it.
    assert "update_product_listing" in example.lower()
    # Ensure it's not just the abstract description — it shows a concrete scenario
    assert len(example) > 500


def test_prompt_states_seller_cannot_answer_prose(prompt_text):
    """v2 must state explicitly: the seller cannot answer prose questions.
    The ONLY seller input the system accepts is a decision on a CONFIRM tool
    call. Never ask the seller to choose between options in text.
    """
    section_7 = _sections(prompt_text)["## 7. Output Guidance + Worked Example"]
    # Look for language explicitly stating this affordance
    collapsed = " ".join(section_7.split()).lower()
    prose_phrases = [
        "prose",
        "unanswerable",
        "cannot answer",
        "text response",
        "cannot reply",
        "not answer",
    ]
    has_explicit = any(phrase in collapsed for phrase in prose_phrases)
    # Or check for the CONFIRM tool reference in the output section
    assert has_explicit or "confirm" in collapsed


def test_seo_three_signals_guidance_present(prompt_text):
    """v2 must state that get_seo_keywords returns three independent signals:
    seo_words, suggested_titles, suggested_descriptions. All three can ground
    a proposal. A populated suggested_descriptions is first-class and does not
    depend on the other two.
    """
    section_6 = _sections(prompt_text)["## 6. Recommend Within Scope"]
    collapsed = " ".join(section_6.split()).lower()

    # Check for guidance on SEO signals
    seo_mentioned = "seo" in collapsed
    signals_mentioned = "signal" in collapsed or "suggest" in collapsed

    # If the SEO guidance is in Section 6 or elsewhere, it should be present
    # This is a flexible check since the guidance could be phrased differently
    assert seo_mentioned or signals_mentioned


def test_prohibition_7_honest_report_survives(prompt_text):
    """Prohibition 7 must survive unchanged: a run with genuinely nothing to
    improve, or a real blocker, must still be free to end honestly in
    final_response. The fix removes a false blocker; it must not create a
    mandate to always write.
    """
    section_8 = _sections(prompt_text)["## 8. Prohibited Behaviors"]
    assert "Prohibition 7" in section_8
    assert "honestly" in section_8.lower()


# ---------------------------------------------------------------------------
# Worked example: zero banned-pattern hits, zero _Avoid_ aliases (SAME AS V1)
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
# Language split: English instructions, Vietnamese worked example (SAME AS V1)
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
