"""Release packaging shape contract (Issue #836, slice P0-DEL-PKG, PRD #820).

PRD #820 left one packaging question open: are applications delivered as
self-contained build output (Next.js ``output: 'standalone'``) or as build output
plus a production dependency install? #836 fixes that decision on the evidence
from the #835 slot-indirection spike.

This module pins three things a later change could silently drift:

1. the decision is *recorded* with its reasoning, in the repo's decision-record
   convention (``docs/adr/``), indexed like every other ADR;
2. the recorded decision cites the #835 evidence rather than asserting a
   preference, because the criterion is "confirmed or refuted with evidence";
3. the shape the decision names is the shape **both** public Next.js apps are
   actually configured to produce — ``apps/landing`` was previously unpinned,
   so only ``apps/demo`` was protected (see ``test_demo_runtime_packaging``).

"The chosen shape is what the artifact build produces" is #837's CI work; what
this module can assert here is that the decision states the contract #837 must
satisfy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ADR_PATH = REPO_ROOT / "docs/adr/058-release-packaging-shape.md"
ADR_INDEX_PATH = REPO_ROOT / "docs/adr/README.md"
NEXT_CONFIGS = {
    "demo": REPO_ROOT / "apps/demo/next.config.ts",
    "landing": REPO_ROOT / "apps/landing/next.config.ts",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _strip_comments(text: str) -> str:
    """Drop ``#`` and ``//`` line comments so prose about a mode is not read as the mode."""
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        if "//" in line:
            line = line.split("//", 1)[0]
        lines.append(line)
    return "\n".join(lines)


def _has_standalone_output(text: str) -> bool:
    return bool(re.search(r"""output\s*:\s*['"]standalone['"]""", _strip_comments(text)))


@pytest.fixture
def adr_text() -> str:
    return _read(ADR_PATH)


def test_packaging_decision_is_recorded_as_an_accepted_adr(adr_text: str) -> None:
    """AC: 'Decision recorded with its reasoning' — in the repo's decision-record convention."""
    assert ADR_PATH.is_file(), f"packaging decision record missing at {ADR_PATH}"
    assert "**Status:** Accepted" in adr_text, "the packaging decision must be Accepted, not draft"
    assert "## Decision" in adr_text and "## Context" in adr_text, (
        "ADR must carry both the decision and the reasoning that produced it"
    )


def test_packaging_adr_is_indexed_like_every_other_adr() -> None:
    index = _read(ADR_INDEX_PATH)
    assert "058-release-packaging-shape.md" in index, (
        "ADR-058 must appear in docs/adr/README.md so the decision is discoverable"
    )


def test_packaging_adr_evaluates_both_options_on_all_three_stated_axes(
    adr_text: str,
) -> None:
    """AC: 'Both options evaluated against artifact size, start time, and server memory'."""
    lowered = adr_text.lower()
    for axis in ("artifact size", "start time", "server memory"):
        assert axis in lowered, f"ADR-058 must evaluate the options against {axis!r}"
    assert "standalone" in lowered, "ADR-058 must name the self-contained option it evaluated"


def test_packaging_adr_settles_the_rationale_against_835_evidence(
    adr_text: str,
) -> None:
    """AC: existing rationale 'confirmed or refuted with evidence from #835'."""
    assert "#835" in adr_text, "the decision must cite the #835 spike it is evidenced by"
    lowered = adr_text.lower()
    assert "confirm" in lowered or "refut" in lowered, (
        "ADR-058 must state whether the prior rationale is confirmed or refuted, "
        "not merely restate it"
    )


def test_packaging_adr_states_what_the_artifact_build_must_produce(
    adr_text: str,
) -> None:
    """AC: 'The chosen shape is what the artifact build produces' — #837 implements it."""
    assert "#837" in adr_text, (
        "ADR-058 must name the contract #837's CI artifact build has to satisfy"
    )


@pytest.mark.parametrize("app", sorted(NEXT_CONFIGS))
def test_both_public_next_apps_produce_the_chosen_shape(app: str) -> None:
    """The decision is only real if both deployed apps are configured to match it."""
    path = NEXT_CONFIGS[app]
    assert path.is_file(), f"{path} missing"
    assert not _has_standalone_output(_read(path)), (
        f"apps/{app} must not use output: 'standalone' — ADR-058 chose build output "
        "plus a production dependency install"
    )


@pytest.mark.parametrize("app", sorted(NEXT_CONFIGS))
def test_both_public_next_apps_point_at_the_decision_record(app: str) -> None:
    """A bare 'do not use standalone' comment lost its 'why' once; make the why reachable."""
    assert "ADR-058" in _read(NEXT_CONFIGS[app]), (
        f"apps/{app}/next.config.ts must cite ADR-058 so the next reader finds the reasoning"
    )
