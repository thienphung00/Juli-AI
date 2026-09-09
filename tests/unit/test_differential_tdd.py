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

import pytest

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
    resolve_base_sha,
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


# Spawns a real pytest run (twice: base tree and head tree), each paying full
# interpreter + conftest import cost. Unloaded these take 11-19s against
# pytest.ini's `timeout = 30` — 1.6x headroom, which contention eats: under
# 8-way CPU load they hit 25-30s and pytest-timeout kills the subprocess wait.
# The gate under test then reports `still_failing` for code that is green, so
# the timeout budget is load-bearing evidence, not test hygiene. The assertions
# below are unchanged; only the wall-clock budget is (repo precedent:
# tests/integration/test_agent_live_smoke_read_only.py).
@pytest.mark.timeout(180)
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


# Spawns a real pytest run (twice: base tree and head tree), each paying full
# interpreter + conftest import cost. Unloaded these take 11-19s against
# pytest.ini's `timeout = 30` — 1.6x headroom, which contention eats: under
# 8-way CPU load they hit 25-30s and pytest-timeout kills the subprocess wait.
# The gate under test then reports `still_failing` for code that is green, so
# the timeout budget is load-bearing evidence, not test hygiene. The assertions
# below are unchanged; only the wall-clock budget is (repo precedent:
# tests/integration/test_agent_live_smoke_read_only.py).
@pytest.mark.timeout(180)
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


# --- node ids are the canonical testsAdded format (#1498) ---------------
#
# `check_differential_tdd` — the only gate in this harness that executes
# anything — reported "No test files in testsAdded/testsUpdated to probe" and
# returned without judging, because `testsAdded` carries pytest *node ids*
# (`tests/unit/test_x.py::test_y`) and the selector dropped every entry whose
# basename did not end in `.py`. The gate passed by never looking.


def _load_gate_seam():
    """Import the gate module lazily (keeps the E402 suppression out of scope)."""
    import importlib

    validate_dir = str(REPO_ROOT / "agent-runtime" / "scripts" / "validate")
    if validate_dir not in sys.path:
        sys.path.insert(0, validate_dir)
    return importlib.import_module("check_differential_tdd")


def _load_differential_seam():
    import importlib

    return importlib.import_module("differential_tdd")


def _gate_repo(tmp_path: Path) -> Path:
    """A repo the gate can resolve a base against: origin/main points at base."""
    repo, base_sha = _build_repo_with_fix(tmp_path)
    _git(repo, "update-ref", "refs/remotes/origin/main", base_sha)
    return repo


def _impl_artifact(**overrides: Any) -> dict[str, Any]:
    artifact: dict[str, Any] = {
        "issueId": 1498,
        "executorDomain": "backend",
        # A real code change: this is what makes TDD evidence required.
        "filesModified": ["backend/src/widget/pricing.py"],
        "testsAdded": [],
        "testsUpdated": [],
        # The narration that satisfied the predecessor gate. It must not
        # satisfy this one.
        "redGreenRefactorEvidence": [
            {"cycle": 1, "commands": [{"command": "pytest -q", "exitCode": 0}]}
        ],
    }
    artifact.update(overrides)
    return artifact


def _run_gate(tmp_path: Path, monkeypatch: Any, repo: Path, artifact: dict[str, Any]) -> Any:
    import json

    import common

    impl_dir = tmp_path / "impl"
    impl_dir.mkdir(parents=True, exist_ok=True)
    (impl_dir / "implementation-issue-1498.json").write_text(json.dumps(artifact))
    monkeypatch.setattr(common, "IMPLEMENTATIONS_DIR", impl_dir)
    return _load_gate_seam().run_check(1498, repo_root=repo)


# Spawns a real pytest run (twice: base tree and head tree), each paying full
# interpreter + conftest import cost. Unloaded these take 11-19s against
# pytest.ini's `timeout = 30` — 1.6x headroom, which contention eats: under
# 8-way CPU load they hit 25-30s and pytest-timeout kills the subprocess wait.
# The gate under test then reports `still_failing` for code that is green, so
# the timeout budget is load-bearing evidence, not test hygiene. The assertions
# below are unchanged; only the wall-clock budget is (repo precedent:
# tests/integration/test_agent_live_smoke_read_only.py).
@pytest.mark.timeout(180)
def test_node_ids_are_split_and_probed(tmp_path: Path, monkeypatch: Any) -> None:
    """A node id must resolve to its file and the probe must actually execute.

    The lie: `testsAdded` holds only node ids, which the selector used to drop
    silently, so the gate returned "nothing to probe" for a change that in fact
    carried a discriminating test.
    """
    node_ids = [
        "tests/test_pricing.py::test_discount_is_applied",
        # a second id in the same file must not produce a duplicate probe
        "tests/test_pricing.py::test_discount_is_applied[edge::case]",
    ]
    assert select_probe_tests({"testsAdded": node_ids, "testsUpdated": []}) == [
        "tests/test_pricing.py"
    ]

    repo = _gate_repo(tmp_path)
    passed, description, details = _run_gate(
        tmp_path, monkeypatch, repo, _impl_artifact(testsAdded=node_ids)
    )

    assert details["probes"] == ["tests/test_pricing.py"]
    assert details["verdict"] == VERDICT_RED_GREEN, description
    # The probe genuinely ran on both trees — not a judgement made from JSON.
    assert details["baseExit"] not in (0, None)
    assert details["headExit"] == 0
    assert "test_discount_is_applied" in details["baseEvidence"]
    assert passed is True


# Spawns a real pytest run (twice: base tree and head tree), each paying full
# interpreter + conftest import cost. Unloaded these take 11-19s against
# pytest.ini's `timeout = 30` — 1.6x headroom, which contention eats: under
# 8-way CPU load they hit 25-30s and pytest-timeout kills the subprocess wait.
# The gate under test then reports `still_failing` for code that is green, so
# the timeout budget is load-bearing evidence, not test hygiene. The assertions
# below are unchanged; only the wall-clock budget is (repo precedent:
# tests/integration/test_agent_live_smoke_read_only.py).
@pytest.mark.timeout(180)
def test_no_discrimination_is_distinct_from_nothing_to_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Both fail — but conflating them is how the gate hid for an entire epic.

    The lie: a vacuous `assert True` submitted as a node id. It must be reported
    as *probed and non-discriminating*, never as *nothing to probe*, because the
    second reads as "the gate had no opinion" and got waved through.
    """
    differential = _load_differential_seam()
    assert differential.VERDICT_NOTHING_TO_PROBE != VERDICT_NO_DISCRIMINATION
    assert differential.VERDICT_NOTHING_TO_PROBE not in differential.PASSING_VERDICTS

    repo = _gate_repo(tmp_path)
    (repo / "tests" / "test_vacuous.py").write_text("def test_nothing():\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "vacuous probe")

    probed, _, probed_details = _run_gate(
        tmp_path,
        monkeypatch,
        repo,
        _impl_artifact(testsAdded=["tests/test_vacuous.py::test_nothing"]),
    )
    assert probed is False
    assert probed_details["verdict"] == VERDICT_NO_DISCRIMINATION
    # It really ran: exit codes exist, which "nothing to probe" can never have.
    assert probed_details["baseExit"] == 0
    assert probed_details["headExit"] == 0

    unprobed, _, unprobed_details = _run_gate(
        tmp_path, monkeypatch, repo, _impl_artifact(testsAdded=[], testsUpdated=[])
    )
    assert unprobed is False
    assert unprobed_details["verdict"] == differential.VERDICT_NOTHING_TO_PROBE
    assert unprobed_details["verdict"] != probed_details["verdict"]
    assert "baseExit" not in unprobed_details


def test_empty_test_list_fails_closed(tmp_path: Path, monkeypatch: Any) -> None:
    """No test entries at all must fail, not pass silently.

    The lie: an artifact that changed code, listed no tests, and attested
    `exitCode: 0` by hand. The predecessor gate accepted exactly that.
    """
    differential = _load_differential_seam()
    repo = _gate_repo(tmp_path)

    for tests_added, tests_updated in (
        ([], []),
        (None, None),
        # entries present, but none of them name a test file
        (["backend/src/widget/pricing.py"], []),
    ):
        passed, description, details = _run_gate(
            tmp_path,
            monkeypatch,
            repo,
            _impl_artifact(testsAdded=tests_added, testsUpdated=tests_updated),
        )
        assert passed is False, description
        assert details["verdict"] == differential.VERDICT_NOTHING_TO_PROBE
        assert details["requiresTddEvidence"] is True


# --- a probe may not escape the repository (review finding, #1498) -------
#
# The probe list comes from an artifact the *graded agent* writes, and every
# probe is (a) copied across trees by overlay_probes and (b) handed to pytest as
# an argument. `_is_test_path` only inspects the basename, so
# "../../OUTSIDE/test_evil.py" cleared it. Latent before #1498 — the selector
# then required the whole entry to end in ".py", so a traversal *node id* was
# dropped along with every other node id. Teaching the selector to read node ids
# is exactly what made it reachable in the canonical artifact format, so the
# guard lands in the same slice.


def test_probe_outside_the_repo_is_rejected() -> None:
    """The lie: a traversal path whose basename looks like an ordinary test."""
    for escape in (
        "../../OUTSIDE/test_evil.py",
        "../test_evil.py",
        "tests/../../test_evil.py",
        "/etc/test_evil.py",
        "//host/share/test_evil.py",
        "C:/Windows/test_evil.py",
        r"..\..\OUTSIDE\test_evil.py",
    ):
        assert select_probe_tests({"testsAdded": [escape]}) == [], escape
        assert select_probe_tests({"testsAdded": [f"{escape}::test_a"]}) == [], escape

    # The guard must not over-reach: ordinary repo-relative entries still pass,
    # including a dotted directory that merely *contains* the characters "..".
    assert select_probe_tests({"testsAdded": ["tests/unit/test_alpha.py::test_a"]}) == [
        "tests/unit/test_alpha.py"
    ]
    assert select_probe_tests({"testsAdded": ["tests/..hidden/test_alpha.py"]}) == [
        "tests/..hidden/test_alpha.py"
    ]


def test_overlay_refuses_to_write_outside_the_base_tree(tmp_path: Path) -> None:
    """Defence in depth: overlay_probes re-checks rather than trusting its caller.

    The lie: a caller that hands overlay_probes a traversal path directly. The
    payload really exists at head, so the only thing standing between it and a
    write outside the base tree is the containment check.

    Layout matters here: head and base are nested at different depths so the
    escape resolves to two *distinct* paths — the source under tmp_path/OUTSIDE
    (which this test creates on purpose) and the would-be target under
    tmp_path/base/OUTSIDE (which must never appear). Asserting on the source
    would pass no matter what the code did.
    """
    escape = "../OUTSIDE/test_evil.py"
    head = tmp_path / "head"
    base = tmp_path / "base" / "inner"
    head.mkdir(parents=True)
    base.mkdir(parents=True)

    source = head / escape
    target = base / escape
    assert source.resolve() != target.resolve(), "layout must separate source from target"

    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("raise SystemExit('pwned')\n")
    assert source.is_file(), "precondition: the payload really exists at head"

    assert overlay_probes(head, base, [escape]) == []
    assert not target.exists(), "overlay wrote outside the base tree"
    assert not (tmp_path / "base" / "OUTSIDE").exists()

    # The guard is not simply refusing all work: a legitimate probe still copies.
    (head / "tests").mkdir()
    (head / "tests" / "test_ok.py").write_text("def test_ok():\n    assert True\n")
    assert overlay_probes(head, base, ["tests/test_ok.py"]) == ["tests/test_ok.py"]
    assert (base / "tests" / "test_ok.py").is_file()


# --- resolve_base_sha follows BASE_REF, not a hardcoded origin/main (#1842) -
#
# The identical shape #1608 fixed for the bootstrap anchor and #1731 fixed for
# check_stale_base: resolve_base_sha defaulted to upstream="origin/main", so on
# an issue-tier PR whose real base is a wave branch, differential_tdd measures
# red/green against the wrong tree -- the one gate whose entire job is proving
# "this turned something red into green" does it against the wrong red.


def _commit_on(
    repo: Path, branch: str, filename: str, content: str, *, create: bool = False
) -> str:
    current = subprocess.run(
        ["git", "-C", str(repo), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    if current != branch:
        _git(repo, "switch", "-c", branch) if create else _git(repo, "switch", branch)
    (repo / filename).write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"{branch}: {filename}")
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _wave_behind_main_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """main advances past a wave; an issue branch is cut from the wave.

    Returns ``(repo, wave_tip, main_tip)`` with HEAD left on the issue branch --
    a strict descendant of ``wave_tip`` but not of ``main_tip``, so a base
    resolved against ``origin/wave`` and one resolved against ``origin/main``
    are genuinely, structurally different commits, not merely different in
    name.
    """
    repo = tmp_path / "repo"
    _init_repo(repo)
    _commit_on(repo, "main", "ROOT.md", "root\n")

    wave_tip = _commit_on(repo, "wave", "WAVE.md", "wave work\n", create=True)
    _git(repo, "update-ref", "refs/remotes/origin/wave", wave_tip)

    # the issue branch is cut from the wave, current with it
    _commit_on(repo, "issue-branch", "ISSUE.md", "issue work\n", create=True)

    # main moves on without ever picking up the wave's commit
    main_tip = _commit_on(repo, "main", "MAIN.md", "main moved on without the wave\n")
    _git(repo, "update-ref", "refs/remotes/origin/main", main_tip)

    _git(repo, "switch", "issue-branch")
    return repo, wave_tip, main_tip


@pytest.mark.timeout(60)
def test_base_resolves_to_the_wave_not_main_when_base_ref_is_the_wave(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """ADR-092 exhibit: a real repository, not an assertion about a mock.

    On a branch cut from a wave that is itself behind main, the resolved base
    sha must be the wave's own tip -- not main's, and not what a hardcoded
    ``origin/main`` upstream would have measured against instead.
    """
    repo, wave_tip, main_tip = _wave_behind_main_repo(tmp_path)

    monkeypatch.setenv("BASE_REF", "wave")
    resolved = resolve_base_sha(repo)

    assert resolved == wave_tip
    assert resolved != main_tip

    # what the old hardcoded upstream would have resolved against: a real,
    # different commit -- not merely "some other value".
    against_main = resolve_base_sha(repo, upstream="origin/main")
    assert against_main != resolved


@pytest.mark.timeout(60)
def test_resolved_base_follows_base_ref_not_a_hardcoded_upstream(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Discriminating test: change BASE_REF and the resolved base must change.

    A test pinning today's sha would keep passing even if the upstream were
    hardcoded back to ``origin/main`` and ``BASE_REF`` were never read at all.
    Only a test that varies ``BASE_REF`` and checks the *result* varies can
    catch that regression -- this is the shape AC3 asks for.
    """
    repo, wave_tip, _main_tip = _wave_behind_main_repo(tmp_path)
    root_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--max-parents=0", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    monkeypatch.setenv("BASE_REF", "wave")
    resolved_wave = resolve_base_sha(repo)

    monkeypatch.setenv("BASE_REF", "main")
    resolved_main = resolve_base_sha(repo)

    assert resolved_wave == wave_tip
    assert resolved_main == root_sha
    assert resolved_wave != resolved_main
