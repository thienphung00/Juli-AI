"""Unit tests for differential_tdd — mechanical red→green verification.

The existing TDD gate reads a self-reported ``exitCode`` the Executor wrote by
hand, so narration satisfies it (see #1318: no ``failingTestEvidence`` key at
all, gate still PASSed). These tests pin the replacement: red and green are
*measured* by running the probe tests against base source and head source.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
sys.path.insert(0, str(CI_DIR))

from differential_tdd import (  # noqa: E402
    VERDICT_INCONCLUSIVE,
    VERDICT_NO_DISCRIMINATION,
    VERDICT_RED_GREEN,
    VERDICT_STILL_FAILING,
    classify_probe,
    materialize_base_tree,
    overlay_probes,
    run_python_probes,
    select_probe_tests,
)


def _artifact(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "testsAdded": ["tests/unit/test_alpha.py"],
        "testsUpdated": [],
    }
    base.update(overrides)
    return base


# --- select_probe_tests -------------------------------------------------


def test_selects_added_and_updated_tests() -> None:
    artifact = _artifact(
        testsAdded=["tests/unit/test_alpha.py"],
        testsUpdated=["tests/unit/test_beta.py"],
    )
    assert select_probe_tests(artifact) == [
        "tests/unit/test_alpha.py",
        "tests/unit/test_beta.py",
    ]


def test_dedupes_a_test_listed_as_both_added_and_updated() -> None:
    artifact = _artifact(
        testsAdded=["tests/unit/test_alpha.py"],
        testsUpdated=["tests/unit/test_alpha.py"],
    )
    assert select_probe_tests(artifact) == ["tests/unit/test_alpha.py"]


def test_ignores_paths_that_are_not_tests() -> None:
    """A source file listed under testsAdded must not become a probe."""
    artifact = _artifact(
        testsAdded=[
            "tests/unit/test_alpha.py",
            "backend/src/juli_backend/services/scoring/signals.py",
        ]
    )
    assert select_probe_tests(artifact) == ["tests/unit/test_alpha.py"]


def test_accepts_js_and_ts_test_paths() -> None:
    artifact = _artifact(
        testsAdded=["apps/demo/src/__tests__/run-ledger.test.ts"],
        testsUpdated=[],
    )
    assert select_probe_tests(artifact) == ["apps/demo/src/__tests__/run-ledger.test.ts"]


def test_missing_and_malformed_fields_yield_no_probes() -> None:
    assert select_probe_tests({}) == []
    assert select_probe_tests({"testsAdded": None, "testsUpdated": None}) == []
    assert select_probe_tests({"testsAdded": "tests/unit/test_alpha.py"}) == []
    assert select_probe_tests({"testsAdded": [None, 17]}) == []


# --- classify_probe -----------------------------------------------------


def test_fails_at_base_and_passes_at_head_is_red_green() -> None:
    verdict, _ = classify_probe(base_exit=1, head_exit=0)
    assert verdict == VERDICT_RED_GREEN


def test_passing_at_base_does_not_discriminate_the_change() -> None:
    """The hole this gate exists to close: a test that never went red.

    ``assert True`` passes at base and at head, satisfying the old gate's
    ``exitCode == 0`` check while proving nothing about the change.
    """
    verdict, reason = classify_probe(base_exit=0, head_exit=0)
    assert verdict == VERDICT_NO_DISCRIMINATION
    assert "base" in reason.lower()


def test_failing_at_head_is_still_failing_regardless_of_base() -> None:
    for base_exit in (0, 1):
        verdict, _ = classify_probe(base_exit=base_exit, head_exit=1)
        assert verdict == VERDICT_STILL_FAILING


def test_unrunnable_base_is_inconclusive_not_a_pass() -> None:
    """Fail-closed: an unmaterializable base must never read as red→green."""
    verdict, _ = classify_probe(base_exit=None, head_exit=0)
    assert verdict == VERDICT_INCONCLUSIVE


def test_only_red_green_is_a_passing_verdict() -> None:
    passing = {
        verdict
        for verdict in (
            VERDICT_RED_GREEN,
            VERDICT_NO_DISCRIMINATION,
            VERDICT_STILL_FAILING,
            VERDICT_INCONCLUSIVE,
        )
        if classify_probe(
            base_exit={"red_green": 1, "no_discrimination": 0}.get(verdict, 0),
            head_exit=0 if verdict in (VERDICT_RED_GREEN, VERDICT_NO_DISCRIMINATION) else 1,
        )[0]
        == VERDICT_RED_GREEN
    }
    assert passing == {VERDICT_RED_GREEN}


# --- end-to-end differential mechanism ----------------------------------
#
# These prove the property the pure functions above only describe: that a real
# probe run against a real base commit actually goes red, and the same probe
# goes green at head. If this mechanism breaks, the gate silently degrades to
# the narration-accepting behaviour it replaced.

import subprocess  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.invalid")
    _git(repo, "config", "user.name", "t")


def _build_repo_with_fix(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose HEAD fixes a bug and adds the test that catches it."""
    repo = tmp_path / "repo"
    _init_repo(repo)

    src = repo / "backend" / "src" / "widget"
    src.mkdir(parents=True)
    (src / "__init__.py").write_text("")
    # base: the bug — discount is ignored
    (src / "pricing.py").write_text("def net(amount, discount):\n    return amount\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    # head: the fix, plus the probe that proves it
    (src / "pricing.py").write_text("def net(amount, discount):\n    return amount - discount\n")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_pricing.py").write_text(
        "from widget.pricing import net\n\n\n"
        "def test_discount_is_applied():\n"
        "    assert net(100, 10) == 90\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "head")
    return repo, base_sha


def test_probe_goes_red_at_base_and_green_at_head(tmp_path: Path) -> None:
    """The whole point: red and green are measured, not asserted by the author."""
    repo, base_sha = _build_repo_with_fix(tmp_path)
    probes = ["tests/test_pricing.py"]

    base_tree = tmp_path / "base"
    assert materialize_base_tree(repo, base_sha, base_tree) is True
    # the probe must not exist at base until we overlay it
    assert not (base_tree / "tests" / "test_pricing.py").exists()
    assert overlay_probes(repo, base_tree, probes) == probes

    base_exit, base_output = run_python_probes(base_tree, probes, sys.executable)
    head_exit, _ = run_python_probes(repo, probes, sys.executable)

    assert base_exit not in (0, None), f"probe should fail at base, got {base_exit}"
    assert head_exit == 0, f"probe should pass at head, got {head_exit}"
    assert "test_discount_is_applied" in base_output
    assert classify_probe(base_exit, head_exit)[0] == VERDICT_RED_GREEN


def test_vacuous_probe_is_caught_as_non_discriminating(tmp_path: Path) -> None:
    """``assert True`` satisfies the old gate. It must not satisfy this one."""
    repo, base_sha = _build_repo_with_fix(tmp_path)
    vacuous = repo / "tests" / "test_vacuous.py"
    vacuous.write_text("def test_nothing():\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "vacuous probe")

    probes = ["tests/test_vacuous.py"]
    base_tree = tmp_path / "base_vacuous"
    assert materialize_base_tree(repo, base_sha, base_tree) is True
    overlay_probes(repo, base_tree, probes)

    base_exit, _ = run_python_probes(base_tree, probes, sys.executable)
    head_exit, _ = run_python_probes(repo, probes, sys.executable)

    assert base_exit == 0 and head_exit == 0
    verdict, reason = classify_probe(base_exit, head_exit)
    assert verdict == VERDICT_NO_DISCRIMINATION
    assert "does not discriminate" in reason
