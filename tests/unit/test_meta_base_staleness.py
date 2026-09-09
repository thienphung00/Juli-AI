"""The Meta gate reports how far a branch is behind its base (#1731 AC1).

An executor dispatched onto a stale branch does not know it is stale: it
produces work against a base that has moved, and the first signal is a red check
minutes later. The Meta gate is the dispatch point, so the distance belongs
there — the write-time preflight only fires once an executor is already running.

These tests exist because the first version of this function shipped with none.
The review that caught that made the point exactly: a fix for "the gate does not
report staleness" is not finished while the reporting itself is unmeasured.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _meta():
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts"))
    import meta_prepare_executor

    return meta_prepare_executor


@pytest.fixture(autouse=True)
def _no_ambient_base_ref(monkeypatch):
    """Each test states its own base rather than inheriting the operator's shell."""
    monkeypatch.delenv("BASE_REF", raising=False)


def test_it_names_the_base_it_measured(monkeypatch) -> None:
    """The base must be reported, not implied.

    The defect this whole item fixes was a report that named `origin/main` while
    measuring something else, so the ref is part of the answer.
    """
    meta = _meta()
    monkeypatch.setenv("BASE_REF", "feature/harness-e-w5-wave")

    result = meta.base_staleness()

    assert result["base"] == "feature/harness-e-w5-wave"
    assert "severity" in result and "summary" in result


def test_the_reported_base_follows_base_ref(monkeypatch) -> None:
    """Two different bases must give two different answers.

    Without this the function could hardcode anything and still look right in a
    single-base test.
    """
    meta = _meta()

    monkeypatch.setenv("BASE_REF", "main")
    against_main = meta.base_staleness()
    monkeypatch.setenv("BASE_REF", "feature/harness-e-w5-wave")
    against_wave = meta.base_staleness()

    assert against_main["base"] == "main"
    assert against_wave["base"] == "feature/harness-e-w5-wave"
    assert against_main != against_wave, "the base ref made no difference to the reading"


def test_a_measurement_failure_degrades_and_never_raises(monkeypatch) -> None:
    """A broken advisory must not stop dispatch.

    This is the branch that decides whether a reporting bug becomes an outage.
    Blocking here would give one condition two enforcement points -- the
    preflight already owns blocking -- and would stop work on the strength of a
    measurement that failed.
    """
    meta = _meta()
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "git"))
    import checkout_preflight as pf

    def _boom(*_args, **_kwargs):
        raise RuntimeError("git is not available")

    monkeypatch.setattr(pf, "check_stale_base", _boom)

    result = meta.base_staleness()

    assert result["available"] is False
    assert "RuntimeError" in result["reason"]
    assert "git is not available" in result["reason"]


def test_the_gate_payload_carries_the_reading(monkeypatch) -> None:
    """AC1 is about what the dispatcher sees, not what a helper returns.

    A correct function whose value never reaches the payload would satisfy no
    part of the criterion.
    """
    monkeypatch.setenv("BASE_REF", "feature/harness-e-w5-wave")

    source = (REPO_ROOT / "agent-runtime" / "scripts" / "meta_prepare_executor.py").read_text()
    assert '"baseStaleness": base_staleness()' in source, (
        "the reading is computed but never placed in the gate's payload"
    )


def test_the_three_items_are_independently_landable() -> None:
    """#1731 AC4, as a checkable property rather than a claim in prose.

    The issue promised each of the three items could land on its own. That is
    only true if none imports another: staleness reporting, the wave-manifest
    merge driver, and the corpus reconcile command touch three different files
    for three different reasons, and coupling any two would mean reverting one
    takes out the others.

    The previous review recorded AC4 as unmappable because no pytest node
    expressed it. It is expressible -- this is what "independently landable"
    actually asserts.
    """
    scripts = REPO_ROOT / "agent-runtime" / "scripts"
    driver = (scripts / "git" / "merge_wave_manifest.py").read_text(encoding="utf-8")
    reconcile = (REPO_ROOT / "eval" / "quality_detectors.py").read_text(encoding="utf-8")
    preflight = (scripts / "git" / "checkout_preflight.py").read_text(encoding="utf-8")

    assert "quality_detectors" not in driver and "checkout_preflight" not in driver
    assert "merge_wave_manifest" not in reconcile and "checkout_preflight" not in reconcile
    assert "merge_wave_manifest" not in preflight and "quality_detectors" not in preflight
