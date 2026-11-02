"""Contract tests for the Optimize Product v5 prompt file (fast track P85, D78.2;
ADR-072 decisions 1, 3, 4, 5).

v5.md is derived from v4.md. It keeps the eight ADR-072 sections, the one
`{playbook}` slot, edits-never-a-rewrite and Prohibitions 8 and 9. v5 adds:

1. The seller reads no model prose: the model reports codes (report_status) and
   Juli writes the line; any text reply is one plain sentence, no Markdown, no
   tool or step names (Section 7, Prohibition 2).
2. Paragraph splitting taught explicitly (P81), one replace_span per original span
   (P80), `old` copied from description_sections.
3. Length floors: >= 500 characters when DESC_LESS_THAN_FIVE_HUNDRED_CHARS is flagged,
   >= the current length; title >= 40 with brand and number tokens kept; only facts
   already present.
4. Reason codes come from edit_codes (P79).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from juli_backend.services.agent.prompts.composer import compose
from juli_backend.services.agent.runner.coded_status import PlanCode
from juli_backend.services.agent.sanitize import load_banned_patterns

PROMPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "backend/src/juli_backend/services/agent/prompts/optimize_product/v5.md"
)
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
_VI = re.compile("[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđĐ]")


@pytest.fixture(scope="module")
def prompt_text() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    spans: dict[str, str] = {}
    for i, heading in enumerate(SECTION_HEADINGS):
        start = text.index(heading) + len(heading)
        end = text.index(SECTION_HEADINGS[i + 1]) if i + 1 < len(SECTION_HEADINGS) else len(text)
        spans[heading] = " ".join(text[start:end].split())
    return spans


def test_eight_sections_in_order_and_one_template_slot(prompt_text):
    indices = [prompt_text.index(h) for h in SECTION_HEADINGS]
    assert indices == sorted(indices)
    assert re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", prompt_text) == ["{playbook}"]
    for heading, body in _sections(prompt_text).items():
        assert len(body) > 150, heading


def test_the_model_reports_codes_and_writes_no_prose_for_the_seller(prompt_text):
    section_7 = _sections(prompt_text)["## 7. Output Guidance + Worked Example"]
    assert "Call report_status once, in the same turn as update_product_listing" in section_7
    for plan in PlanCode:
        assert plan.value in section_7, plan
    assert "no Markdown" in section_7 and "no tool or step names" in section_7
    assert "never shown to the seller" in section_7
    section_8 = _sections(prompt_text)["## 8. Prohibited Behaviors"]
    assert "Prohibition 2: No prose for the seller." in section_8
    assert "Prohibition 9: Never rewrite the listing wholesale." in section_8


def test_paragraph_splitting_and_op_hygiene_are_taught(prompt_text):
    section_6 = _sections(prompt_text)["## 6. Recommend Within Scope"]
    for fact in (
        "When DESC_NO_NEW_LINE or DESC_LESS_THAN_FIVE_HUNDRED_CHARS is flagged",
        "may hold blank lines; each blank line starts a new paragraph",
        "Never empty a section or merge two sections",
        "One replace_span per original span",
        "Copy every old span exactly from description_sections",
        "a code edit_codes lists for that field",
    ):
        assert fact in section_6, fact


def test_length_floors_and_fact_only_edits_are_stated(prompt_text):
    section_6 = _sections(prompt_text)["## 6. Recommend Within Scope"]
    for fact in (
        "at least 40 characters",
        "20 % shorter",
        "brand and every number with its unit",
        "at least as long as now",
        "at least 500 characters of text",
        "never invent a spec",
    ):
        assert fact in section_6, fact


def test_instructions_are_english_and_only_the_worked_example_is_vietnamese(prompt_text):
    sections = _sections(prompt_text)
    for heading, body in sections.items():
        if heading != "## 7. Output Guidance + Worked Example":
            assert not _VI.search(body), heading
    example = "\n".join(line for line in prompt_text.splitlines() if line.startswith(">"))
    assert _VI.search(example)
    assert [p.pattern for p in load_banned_patterns() if p.search(example)] == []


def test_report_status_and_op_names_are_never_backticked(prompt_text):
    """The playbook-consistency gate reads every backticked snake_case token as a tool."""
    for name in ("report_status", "replace_span", "insert_after", "description_sections"):
        assert f"`{name}`" not in prompt_text


def test_v5_composes():
    assert "{playbook}" not in compose("optimize_product_2", 5)
