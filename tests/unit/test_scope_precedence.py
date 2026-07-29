"""Unit tests for scope-precedence slice-id extraction."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from scope_precedence import (  # noqa: E402
    compare_authority_chains,
    slice_ids_in_reason,
)


def test_slice_ids_in_reason_supports_dotted_phase_ids() -> None:
    reason = "Phase/slice law — P2.10-A1"
    assert "P2.10-A1" in slice_ids_in_reason(reason)


def test_slice_ids_in_reason_keeps_hyphenated_ids() -> None:
    reason = "Phase/slice law — P2-OPS-1"
    assert "P2-OPS-1" in slice_ids_in_reason(reason)


def test_compare_authority_accepts_dotted_slice_in_execution_reason() -> None:
    cached = [
        {"rank": 1, "source": "EXECUTION.md", "reason": "Phase/slice law — P2.10-A1"},
        {"rank": 2, "source": "parent-cache-issue-524", "reason": "Epic constant"},
        {"rank": 3, "source": "GitHub issue #525", "reason": "Child acceptance criteria"},
        {
            "rank": 4,
            "source": "docs/product/phases/phase-2.10/PRD.md",
            "reason": "Epic handoff",
        },
    ]
    expected = [
        {
            "rank": 1,
            "source": "EXECUTION.md",
            "reason": "Phase/slice law — P2.10-A1",
            "sliceId": "P2.10-A1",
        },
        {
            "rank": 2,
            "source": "parent-cache-issue-524",
            "reason": "Epic constant",
            "sliceId": None,
        },
        {
            "rank": 3,
            "source": "GitHub issue #525",
            "reason": "Child acceptance criteria",
            "sliceId": None,
        },
        {
            "rank": 4,
            "source": "docs/product/phases/phase-2.10/PRD.md",
            "reason": "Epic handoff",
            "sliceId": None,
        },
    ]
    assert compare_authority_chains(cached, expected) == []
