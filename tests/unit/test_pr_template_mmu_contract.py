"""MMU-4 PR template and review-guidance contract (#553).

Verifies the modular-monolith four review questions appear as required
checklist items in the GitHub PR template and align with code-review guidance.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PR_TEMPLATE_PATH = REPO_ROOT / ".github" / "pull_request_template.md"
CODE_REVIEW_RULE_PATH = REPO_ROOT / ".cursor" / "rules" / "code-review.mdc"
SLICE_ROUTING_PATH = REPO_ROOT / "agent-runtime" / "config" / "slice-routing.yml"
PRD_PATH = REPO_ROOT / "docs" / "product" / "phases" / "modular-monolith-upgrade" / "PRD.md"

pytestmark = pytest.mark.mmu_contract

# Canonical wording from docs/product/phases/modular-monolith-upgrade/PRD.md § PR review
MMU_PR_REVIEW_QUESTIONS: tuple[tuple[str, str], ...] = (
    ("Does it work?", "Tests (unit / integration / E2E as applicable)"),
    (
        "Does it belong in this module?",
        "Ownership (routes, models, services, tables, tasks, Redis keys, integrations)",
    ),
    ("Did it create forbidden dependencies?", "Import-linter + cycle check"),
    (
        "Can this module still be extracted later?",
        "Architecture (deep module / facade discipline",
    ),
)

CHECKBOX_PATTERN = re.compile(r"^\s*-\s*\[\s\]\s+", re.MULTILINE)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.fixture
def pr_template_text() -> str:
    assert PR_TEMPLATE_PATH.is_file(), f"missing PR template: {PR_TEMPLATE_PATH}"
    return _read(PR_TEMPLATE_PATH)


@pytest.fixture
def code_review_text() -> str:
    assert CODE_REVIEW_RULE_PATH.is_file()
    return _read(CODE_REVIEW_RULE_PATH)


def test_pr_template_exists() -> None:
    assert PR_TEMPLATE_PATH.is_file(), (
        "GitHub PR template must exist at .github/pull_request_template.md"
    )


def test_pr_template_includes_four_required_checklist_items(pr_template_text: str) -> None:
    checkboxes = CHECKBOX_PATTERN.findall(pr_template_text)
    assert len(checkboxes) >= 4, (
        "PR template must include at least four unchecked checklist items "
        "for modular-monolith review"
    )
    for heading, detail in MMU_PR_REVIEW_QUESTIONS:
        assert heading in pr_template_text, f"missing question heading: {heading}"
        assert detail in pr_template_text, f"missing question detail: {detail}"


def test_pr_template_questions_are_checklist_items(pr_template_text: str) -> None:
    for heading, _detail in MMU_PR_REVIEW_QUESTIONS:
        pattern = re.compile(
            rf"^\s*-\s*\[\s\]\s+.*{re.escape(heading)}",
            re.MULTILINE,
        )
        assert pattern.search(pr_template_text), (
            f"question must be a required checkbox item: {heading}"
        )


def test_code_review_rule_references_same_four_questions(code_review_text: str) -> None:
    for heading, detail in MMU_PR_REVIEW_QUESTIONS:
        assert heading in code_review_text, f"code-review.mdc missing: {heading}"
        assert detail in code_review_text, f"code-review.mdc missing detail: {detail}"


def test_code_review_points_at_pr_template(code_review_text: str) -> None:
    assert "pull_request_template.md" in code_review_text


def test_prd_and_template_headings_align(pr_template_text: str) -> None:
    prd_text = _read(PRD_PATH)
    for heading, _detail in MMU_PR_REVIEW_QUESTIONS:
        assert heading in prd_text, f"PRD missing canonical heading: {heading}"
        assert heading in pr_template_text


def test_slice_routing_bootstraps_mmu_four() -> None:
    routing = _read(SLICE_ROUTING_PATH)
    assert "MMU-4:" in routing
    assert ".github/pull_request_template.md" in routing


def test_no_ci_behavior_change_in_mmu_four_slice() -> None:
    """AC3: MMU-4 must not change CI gates (owned by MMU-3 #556)."""
    routing = _read(SLICE_ROUTING_PATH)
    mmu4_block = routing.split("MMU-4:")[1].split("\nMMU-")[0]
    required_section = mmu4_block.split("requiredModules:", 1)[-1].split("loadWhenNeeded:", 1)[0]
    assert ".github/workflows" not in required_section
