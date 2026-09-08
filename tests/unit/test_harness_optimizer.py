"""#1732 AC2 — `harness_optimizer` reports an unmeasured run as unmeasured.

`as_int({"available": False, ...})` used to raise inside a try/except and
silently return 0, undoing the schema fix (#1441/#1539) one layer down.
These exhibits plant that exact unavailable shape and assert the harness
never turns it into a number a threshold can be compared against.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
AGENT_RUNTIME_CONFIG = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"


def _ho():
    """Import the module behind its path shim, without an E402 suppression.

    A module-level sys.path.insert followed by a late import is an E402, and
    silencing it adds a suppression identity the ratchet carries forever.
    Deferring the import keeps the debt set unchanged.
    """
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts"))
    import harness_optimizer

    return harness_optimizer


def load_simple_yaml(*args, **kwargs):
    """Same shim for the one build_runtime helper these tests use."""
    sys.path.insert(0, str(REPO_ROOT / "agent-runtime" / "scripts"))
    import build_runtime

    return build_runtime.load_simple_yaml(*args, **kwargs)


def collect_metrics(*args, **kwargs):
    return _ho().collect_metrics(*args, **kwargs)


def detect_tool_overuse(*args, **kwargs):
    return _ho().detect_tool_overuse(*args, **kwargs)


def evaluate_before_after(*args, **kwargs):
    return _ho().evaluate_before_after(*args, **kwargs)


def fix_tool_overuse(*args, **kwargs):
    return _ho().fix_tool_overuse(*args, **kwargs)


def _implementation(**overrides: object) -> dict:
    base = {
        "issueId": 1732,
        "executorDomain": "backend",
        "phaseRunId": "1732-test",
        "executionDurationMs": {"available": False, "reason": "no wall-clock instrumentation"},
        "tokenUsage": {"available": False, "reason": "token usage not instrumented"},
        "toolInvocationCount": {"available": False, "reason": "tool instrumentation unavailable"},
        "contextFilesLoaded": ["a.md"],
        "skillsLoaded": ["backend"],
    }
    base.update(overrides)
    return base


def test_unavailable_token_usage_total_is_not_zero() -> None:
    """ADR-092 exhibit: an unmeasured run's tokenUsageTotal must not read 0 —
    a 0 is indistinguishable from a real zero-token run and is the more
    convincing lie."""
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    implementation = _implementation()

    metrics = collect_metrics(implementation, None, None, config)

    assert metrics["baselineMetrics"]["tokenUsageTotal"] != 0
    assert metrics["baselineMetrics"]["tokenUsageTotal"] is None


def test_unavailable_execution_duration_is_not_zero() -> None:
    """Sibling of the token-usage exhibit: executionTimeMs must not read 0 for
    an unmeasured run either."""
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    implementation = _implementation()

    metrics = collect_metrics(implementation, None, None, config)

    assert metrics["baselineMetrics"]["executionTimeMs"] != 0
    assert metrics["baselineMetrics"]["executionTimeMs"] is None
    assert metrics["executionDurationMs"] == {
        "available": False,
        "reason": "no wall-clock instrumentation",
    }


def test_tool_overuse_does_not_fire_on_unmeasured_count() -> None:
    """An unmeasured count cannot exceed a limit. The detector must not fire,
    and must not crash comparing a dict to an int."""
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    config.setdefault("tools", {})["max_invocations_per_run"] = 1  # trivially low
    implementation = _implementation()

    metrics = collect_metrics(implementation, None, None, config)

    assert metrics["toolInvocationCount"] == {
        "available": False,
        "reason": "tool instrumentation unavailable",
    }
    assert detect_tool_overuse(metrics) is False


def test_fix_tool_overuse_never_invents_a_threshold_from_unmeasured_data() -> None:
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    config.setdefault("tools", {})["max_invocations_per_run"] = 1
    implementation = _implementation()
    metrics = collect_metrics(implementation, None, None, config)

    fix = fix_tool_overuse(metrics)

    assert fix.value is None
    assert "unmeasured" in fix.summary.lower()
    assert "unavailable" in fix.details.lower()


def test_evaluate_before_after_marks_unmeasured_metric_instead_of_a_fake_delta() -> None:
    """as_float(None) previously returned 0.0, comparing an invented zero
    against a real reading and calling the delta "improved" by accident."""
    before = {
        "baselineMetrics": {
            "executionTimeMs": None,
            "tokenUsageTotal": 200,
            "reviewFailureRate": 0,
            "validationFailureRate": 0,
            "retryCount": 0,
        }
    }
    after = {
        "baselineMetrics": {
            "executionTimeMs": 5000,
            "tokenUsageTotal": 150,
            "reviewFailureRate": 0,
            "validationFailureRate": 0,
            "retryCount": 0,
        }
    }

    result = evaluate_before_after(before, after)

    assert result["comparisons"]["executionTimeMs"]["status"] == "unmeasured"
    assert result["comparisons"]["executionTimeMs"]["delta"] is None
