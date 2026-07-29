"""Doc contract tests for DVR-A0 ephemeral design reference bundles (Issue #583)."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BUNDLE_DIR = REPO_ROOT / "docs/handoffs/dvr-a0-reference-bundles"

REQUIRED_BUNDLE_FILES = (
    "README.md",
    "home.md",
    "analytics.md",
    "recommendations.md",
)

ADR015_TOKEN_MARKERS = (
    "--primary",
    "--background",
    "--success",
    "--destructive",
    "--warning",
    "--info",
    "var(--",
)

COPY_AUTHORITY_MARKERS = (
    "dictionary.md",
    "design-context.md",
)

EPHEMERAL_MARKERS = (
    "ephemeral",
    "DVR-A0",
    "not registered",
)

DESTINATION_MARKERS = {
    "home.md": (
        "launchpad",
        "nav.decisions",
        "nav.analytics",
        "ADR-023",
    ),
    "analytics.md": (
        "KPI",
        "chart",
        "Main KPI",
        "ADR-023",
    ),
    "recommendations.md": (
        "five-stage",
        "Why",
        "Approve",
        "decisions.recommendation",
    ),
}


@pytest.fixture
def bundle_readme() -> str:
    return (BUNDLE_DIR / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("filename", REQUIRED_BUNDLE_FILES)
def test_dvr_a0_bundle_file_exists(filename: str):
    """Each PRD-scoped reference bundle artifact exists on disk."""
    path = BUNDLE_DIR / filename
    assert path.is_file(), f"missing bundle file: {path.relative_to(REPO_ROOT)}"


def test_dvr_a0_readme_documents_ephemeral_scope_and_destinations(bundle_readme: str):
    """README states ephemeral scope, destinations, and ADR-015 adaptation."""
    lower = bundle_readme.lower()
    for marker in EPHEMERAL_MARKERS:
        assert marker.lower() in lower, f"README missing ephemeral marker: {marker}"
    for dest in ("Home", "Analytics", "Recommendations"):
        assert dest in bundle_readme, f"README missing destination: {dest}"
    assert any(token in bundle_readme for token in ADR015_TOKEN_MARKERS), (
        "README must document ADR-015 semantic token adaptation"
    )


def test_dvr_a0_bundles_document_copy_authority_and_mcp_provenance():
    """Each destination bundle cites copy authority and external reference provenance."""
    for filename in ("home.md", "analytics.md", "recommendations.md"):
        text = (BUNDLE_DIR / filename).read_text(encoding="utf-8")
        for marker in COPY_AUTHORITY_MARKERS:
            assert marker in text, f"{filename} missing copy authority: {marker}"
        assert "mobbin.com/screens/" in text, f"{filename} missing Mobbin screen link"
        assert "Open Design" in text or "DESIGN.md" in text, (
            f"{filename} missing Open Design provenance"
        )
        for marker in DESTINATION_MARKERS[filename]:
            assert marker.lower() in text.lower(), (
                f"{filename} missing destination marker: {marker}"
            )


def test_dvr_a0_hitl_waiver_documented():
    """HITL product/design sign-off is waived and recorded in the handoff note."""
    note = (REPO_ROOT / "docs/handoffs/dvr-a0-handoff-note.md").read_text(encoding="utf-8")
    lower = note.lower()
    assert "waiv" in lower, "handoff note must record HITL waiver"
    assert "583" in note or "DVR-A0" in note
