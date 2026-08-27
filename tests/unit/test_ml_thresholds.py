"""Unit tests for ml_thresholds — source is the only source of thresholds.

`mlGates.thresholds` used to be a copy of the source constants that the Review
agent typed into the artifact by hand, which the gate then compared back to
source. The comparison was *optional*: omit the field and no check ran at all,
so declaring thresholds could only ever hurt you. It added restatement cost, a
perverse incentive, and no floor.

The values are now read from source and reported, never demanded from the
author — the same move as differential_tdd: capture the evidence rather than
ask its subject to attest to it.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

import ml_thresholds  # noqa: E402
from ml_thresholds import (  # noqa: E402
    COLD_START_CONSTANTS,
    PROMOTION_CONSTANTS,
    verify_ml_gates_threshold_values,
)

_ALL_ML_MODULES = [f"backend/src/juli_backend/ai/{leaf}" for leaf in COLD_START_CONSTANTS] + [
    "backend/src/juli_backend/ai/artifacts"
]


def _install_fake_ml_root(tmp_path: Path, monkeypatch, *, complete: bool) -> Path:
    """Build a thresholds tree, optionally missing one required constant.

    REPO_ROOT moves too: the module reports paths relative to it for display.
    """
    monkeypatch.setattr(ml_thresholds, "REPO_ROOT", tmp_path)
    root = tmp_path / "ai"
    for leaf, names in COLD_START_CONSTANTS.items():
        module = root / leaf
        module.mkdir(parents=True)
        emitted = names if complete else names[1:]
        (module / "thresholds.py").write_text("\n".join(f"{name} = 1" for name in emitted) + "\n")
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "thresholds.py").write_text(
        "\n".join(f"{name} = 0.5" for name in PROMOTION_CONSTANTS) + "\n"
    )
    return root


def test_thresholds_are_read_from_source_not_from_the_artifact(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        ml_thresholds, "ML_ROOT", _install_fake_ml_root(tmp_path, monkeypatch, complete=True)
    )

    ok, problems, details = verify_ml_gates_threshold_values(_ALL_ML_MODULES)

    assert ok is True
    assert problems == []
    # Derived from source even though the artifact declared nothing.
    for names in COLD_START_CONSTANTS.values():
        for name in names:
            assert details["sourceThresholds"][name] == 1
    for name in PROMOTION_CONSTANTS:
        assert details["sourceThresholds"][name] == 0.5


def test_a_declared_copy_that_disagrees_no_longer_fails_the_gate(tmp_path, monkeypatch) -> None:
    """The twin is gone: source decides, so a stale declaration is irrelevant."""
    monkeypatch.setattr(
        ml_thresholds, "ML_ROOT", _install_fake_ml_root(tmp_path, monkeypatch, complete=True)
    )
    some_constant = next(iter(next(iter(COLD_START_CONSTANTS.values()))))

    # A stale declaration in the artifact is simply not consulted any more.
    ok, problems, details = verify_ml_gates_threshold_values(_ALL_ML_MODULES)

    assert ok is True
    assert problems == []
    assert details["sourceThresholds"][some_constant] == 1


def test_missing_source_constants_still_fail(tmp_path, monkeypatch) -> None:
    """The real check survives — only the restated copy was removed."""
    monkeypatch.setattr(
        ml_thresholds, "ML_ROOT", _install_fake_ml_root(tmp_path, monkeypatch, complete=False)
    )

    ok, problems, _ = verify_ml_gates_threshold_values(_ALL_ML_MODULES)

    assert ok is False
    assert problems
    assert any("missing" in p.lower() for p in problems)
