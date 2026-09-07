from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "ci"))
sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts" / "validate"))

from check_implementation_artifact import run_check  # noqa: E402
from common import (  # noqa: E402
    build_implementation_artifact,
    implementation_artifact_template,
    write_json,
)


def test_build_implementation_artifact_includes_required_runtime_fields() -> None:
    artifact = build_implementation_artifact(247, "backend", phase_run_id="2026-06-24T1200Z")

    assert artifact["issueId"] == 247
    assert artifact["executorDomain"] == "backend"
    assert artifact["phaseRunId"] == "2026-06-24T1200Z"
    # #1505: the default is the honest unavailable shape, never a measured zero.
    assert set(artifact["tokenUsage"]) == {"available", "reason"}
    assert artifact["tokenUsage"]["available"] is False
    assert artifact["toolInvocationCount"] == 0
    assert artifact["contextFilesLoaded"] == []
    assert artifact["skillsLoaded"] == []
    assert artifact["rulesLoaded"] == []
    assert artifact["mcpsUsed"] == []


def test_build_implementation_artifact_merges_overrides_without_clobbering_domain() -> None:
    artifact = build_implementation_artifact(
        247,
        "backend",
        overrides={
            "executionDurationMs": 1200,
            "tokenUsage": {"input": 100, "output": 50},
            "toolInvocationCount": 9,
            "contextFilesLoaded": ["scripts/ci/common.py"],
            "skillsLoaded": ["focus", "backend"],
        },
    )

    assert artifact["executionDurationMs"] == 1200
    assert artifact["tokenUsage"]["total"] == 150
    assert artifact["toolInvocationCount"] == 9
    assert artifact["executorDomain"] == "backend"


def test_implementation_artifact_gate_passes_when_present(tmp_path: Path, monkeypatch) -> None:
    impl_dir = tmp_path / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)
    artifact_path = impl_dir / "implementation-issue-247.json"
    write_json(
        artifact_path,
        build_implementation_artifact(
            247,
            "backend",
            overrides={
                "executionDurationMs": 500,
                "tokenUsage": {"input": 10, "output": 5, "total": 15},
                "toolInvocationCount": 3,
                "contextFilesLoaded": ["agent-runtime.config.yml"],
                "skillsLoaded": ["focus"],
            },
            phase_run_id="2026-06-24T1200Z",
        ),
    )

    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)

    passed, description, _ = run_check(247)

    assert passed is True
    assert "backend" in description


def test_implementation_artifact_gate_fails_when_missing(tmp_path: Path, monkeypatch) -> None:
    impl_dir = tmp_path / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)

    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)

    passed, description, _ = run_check(247)

    assert passed is False
    assert "missing" in description.lower()


def test_generate_implementation_artifact_cli(tmp_path: Path, monkeypatch) -> None:
    impl_dir = tmp_path / "artifacts" / "implementations"
    impl_dir.mkdir(parents=True)

    import common

    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    monkeypatch.setattr(common, "REPO_ROOT", tmp_path)

    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps(
            {
                "executionDurationMs": 900,
                "tokenUsage": {"input": 20, "output": 10, "total": 30},
                "toolInvocationCount": 4,
                "contextFilesLoaded": ["scripts/ci/generate_implementation_artifact.py"],
                "skillsLoaded": ["focus", "backend"],
                "implementationSummary": "CLI smoke test",
            }
        ),
        encoding="utf-8",
    )

    from generate_implementation_artifact import main as generate_main

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "generate_implementation_artifact.py",
            "--issue",
            "247",
            "--executor-domain",
            "backend",
            "--input-json",
            str(overrides),
        ],
    )
    assert generate_main() == 0

    artifact = json.loads((impl_dir / "implementation-issue-247.json").read_text(encoding="utf-8"))
    assert artifact["issueId"] == 247
    assert artifact["executorDomain"] == "backend"
    assert artifact["executionDurationMs"] == 900
    assert artifact["toolInvocationCount"] == 4


# ---------------------------------------------------------------------------
# #1505: the template's default tokenUsage must pass the gate that #1441 built.
#
# #1441 taught ``check_implementation_artifact`` to reject a zeroed
# ``tokenUsage`` and added the honest ``{"available": false, "reason": ...}``
# branch. It did not change the template, so the generator's own default output
# started failing its own gate.
#
# The fix is not one line. ``build_implementation_artifact`` deep-merges the
# template *under* the caller's layer, and the normaliser then re-derives
# ``total``. Both steps corrupt a tagged union: merging the two branches yields
# a document that matches neither, and the normaliser re-creates the very
# sentinel the gate exists to reject. Each test below plants that lie.
# ---------------------------------------------------------------------------

ISSUE = 1505

#: Everything the gate requires other than ``tokenUsage``, so a failure here is
#: never ambiguous about which field caused it.
_BASE_OVERRIDES = {
    "executionDurationMs": 500,
    "toolInvocationCount": 3,
    "contextFilesLoaded": ["agent-runtime/scripts/ci/common.py"],
    "skillsLoaded": ["backend-executor"],
}


def _build_and_gate(
    tmp_path: Path,
    *,
    layer: str = "overrides",
    token_usage: dict | None = None,
) -> tuple[dict, tuple[bool, str, dict]]:
    """Build through the real builder, then gate the bytes it wrote.

    ``layer`` selects which merge path carries ``tokenUsage`` — ``overrides``
    and ``existing`` are separate deep merges and each had to be fixed.
    """
    payload = dict(_BASE_OVERRIDES)
    if token_usage is not None:
        payload["tokenUsage"] = token_usage
    kwargs = {"overrides": payload} if layer == "overrides" else {"existing": payload}
    artifact = build_implementation_artifact(
        ISSUE, "backend", phase_run_id="2026-09-02T0000Z", **kwargs
    )
    path = tmp_path / f"implementation-issue-{ISSUE}.json"
    write_json(path, artifact)
    return artifact, run_check(ISSUE, path=path)


def test_default_template_token_usage_is_unavailable_not_zero(tmp_path: Path) -> None:
    """The lie: ``{0, 0, 0}`` handed out as the generator's default.

    A zero is indistinguishable from a measurement, so the template must instead
    supply the ``unavailable()`` shape — and, critically, with no ``value`` key,
    so a consumer that skips the availability check gets a ``KeyError`` rather
    than a plausible number.
    """
    usage = implementation_artifact_template(ISSUE, "backend")["tokenUsage"]

    assert usage["available"] is False
    assert isinstance(usage["reason"], str) and usage["reason"].strip()
    assert set(usage) == {"available", "reason"}
    with pytest.raises(KeyError):
        usage["value"]

    artifact, (passed, detail, details) = _build_and_gate(tmp_path)

    assert artifact["tokenUsage"] == usage
    assert passed is True, detail
    assert details["tokenUsageAvailable"] is False


def test_the_zero_sentinel_is_still_rejected_when_a_caller_supplies_it(tmp_path: Path) -> None:
    """Supplying the honest default must not soften the gate.

    The lie: an explicit ``{0, 0, 0}``. It must still fail, or #1505 would have
    fixed the template by re-opening the hole #1441 closed.
    """
    _, (passed, detail, _) = _build_and_gate(
        tmp_path, token_usage={"input": 0, "output": 0, "total": 0}
    )

    assert passed is False
    assert "reads as a measurement" in detail


def test_measured_token_usage_still_passes(tmp_path: Path) -> None:
    """Regression: the honest default must not cost the measured path.

    The lie the deep merge would plant: the template's ``available``/``reason``
    keys surviving underneath a measured reading, which matches neither branch.
    """
    measured = {"input": 180, "output": 8_762, "total": 8_942}
    artifact, (passed, detail, details) = _build_and_gate(tmp_path, token_usage=dict(measured))

    assert artifact["tokenUsage"] == measured
    assert passed is True, detail
    assert details["tokenUsageTotal"] == 8_942


def test_measured_token_usage_without_a_total_is_still_summed(tmp_path: Path) -> None:
    """The normaliser must keep working for the branch it was written for."""
    artifact, (passed, detail, _) = _build_and_gate(
        tmp_path, token_usage={"input": 100, "output": 50}
    )

    assert artifact["tokenUsage"] == {"input": 100, "output": 50, "total": 150}
    assert passed is True, detail


@pytest.mark.parametrize("layer", ["overrides", "existing"])
def test_explicit_unavailable_survives_the_builder_uncorrupted(tmp_path: Path, layer: str) -> None:
    """The reviewer's widened criterion, on both merge paths.

    The lie: the normaliser reading ``total`` as ``None`` on the unavailable
    branch and writing ``total: 0`` back — re-creating the sentinel inside a
    document that then matches neither ``oneOf`` branch.
    """
    honest = {"available": False, "reason": "no persisted task transcript for this run"}
    caller_copy = dict(honest)

    artifact, (passed, detail, details) = _build_and_gate(
        tmp_path, layer=layer, token_usage=caller_copy
    )

    assert artifact["tokenUsage"] == honest
    assert passed is True, detail
    assert details["tokenUsageUnavailableReason"] == honest["reason"]
    assert caller_copy == honest, "the builder mutated the caller's dict"
