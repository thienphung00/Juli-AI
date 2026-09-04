"""The changed-file query must not answer "nothing changed" when it failed (#1571).

``git_changed_files`` in ``agent-runtime/scripts/ci/common.py`` is the input to
every diff-driven validate gate. It had two compounding faults:

1. A nominally read-only query *mutated the repository it queried* — it ran
   ``git fetch origin <base> --depth=1``, which shallow-grafts the base ref, so
   the three-dot diff that follows needs a merge base that no longer exists.
2. On failure it returned ``[]``, which no caller can tell apart from a
   genuinely empty diff. Every gate downstream reads that as "no relevant
   change → nothing to check → PASS".

``actions/checkout`` is depth-1 by default, so CI reproduced this on nearly
every job. It is the root cause under #1529 (``check_adr`` saw ``changed=[]``
with an ADR committed in the tree) and #1570.

Every test here plants a lie and asserts it is caught. There is no happy-path-only
test: a green that means "did not look" is the exact defect under repair. The
repositories are real — built on disk and cloned with a real ``--depth=1`` — because
a mocked ``subprocess`` would prove only that the code calls git, not that git
answers.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load_seam():
    """Import ``common``, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    the module-level imports needs an E402 suppression comment, and the repo's
    debt ratchet counts suppression identities per file.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import common

    return common


common = _load_seam()


# --------------------------------------------------------------------------
# Real-git fixtures. Nothing below stubs subprocess: the whole defect lives in
# what git actually does to a shallow repository.
# --------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, relpath: str, body: str, message: str) -> None:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")
    _git(repo, "add", "--", relpath)
    _git(repo, "commit", "-m", message)


def _make_origin(path: Path, *, history: int = 5) -> Path:
    """An upstream repo on ``main`` with enough history that depth=1 truncates."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "--initial-branch=main", "--quiet")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "config", "commit.gpgsign", "false")
    for index in range(history):
        _commit(path, "README.md", f"revision {index}\n", f"base commit {index}")
    return path


def _clone(origin: Path, dest: Path, *, depth: int | None) -> Path:
    # `file://` is required, not cosmetic: cloning a bare local *path* uses git's
    # local transport, which ignores --depth entirely and hands back a complete
    # repo. A test that cloned by path would silently never be shallow, and the
    # shallow-checkout assertions below would prove nothing.
    args = ["git", "clone", "--quiet"]
    if depth is not None:
        # Exactly what actions/checkout does by default.
        args += ["--depth", str(depth), "--no-single-branch"]
    args += [f"file://{origin}", str(dest)]
    subprocess.run(args, capture_output=True, text=True, check=True)
    _git(dest, "config", "user.email", "test@example.com")
    _git(dest, "config", "user.name", "Test")
    _git(dest, "config", "commit.gpgsign", "false")
    return dest


def _is_shallow(repo: Path) -> bool:
    return _git(repo, "rev-parse", "--is-shallow-repository") == "true"


@pytest.fixture
def origin(tmp_path: Path) -> Path:
    return _make_origin(tmp_path / "origin")


# --------------------------------------------------------------------------
# 1. Failure must not wear the costume of an empty diff.
# --------------------------------------------------------------------------


def test_unresolvable_base_raises_instead_of_returning_empty(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lie: "no files changed", told by a query that could not answer.

    A base ref that does not exist and cannot be fetched is *unresolvable*. The
    old code returned ``[]`` here, so a gate could not tell this apart from a PR
    that genuinely changed nothing — and passed.
    """
    clone = _clone(origin, tmp_path / "clone", depth=None)
    _commit(clone, "docs/architecture/map.md", "| module | tier |\n", "arch change")
    monkeypatch.setenv("GITHUB_BASE_REF", "a-branch-that-was-never-pushed")

    with pytest.raises(common.ChangedFilesUnresolved) as excinfo:
        common.git_changed_files(repo_root=clone)

    # The reason must be recorded, not swallowed — the harness degrades with a
    # named cause (cf. harness_bootstrap_pin.py, #1540), never to a silent pass.
    assert "a-branch-that-was-never-pushed" in str(excinfo.value)


def test_genuinely_empty_diff_still_returns_empty_list(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the contract: ``[]`` must still mean "nothing changed".

    Without this, "raise on everything" would pass the test above while
    destroying the distinction it exists to protect.
    """
    clone = _clone(origin, tmp_path / "clone", depth=None)
    _git(clone, "checkout", "--quiet", "-b", "feature/no-op")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    assert common.git_changed_files(repo_root=clone) == []


# --------------------------------------------------------------------------
# 2. A read-only query must not mutate the repository it queries.
# --------------------------------------------------------------------------


def test_query_does_not_shallow_the_repository_it_queries(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lie: a "read-only" changed-file query that truncates the base ref.

    ``git fetch origin <base> --depth=1`` writes ``.git/shallow`` into a complete
    checkout. This asserts the complete repository is still complete afterwards —
    which is precisely what the old implementation broke.
    """
    clone = _clone(origin, tmp_path / "clone", depth=None)
    assert not _is_shallow(clone), "fixture precondition: clone starts complete"
    _git(clone, "checkout", "--quiet", "-b", "feature/x")
    _commit(clone, "backend/src/juli_backend/api/routes/thing.py", "x = 1\n", "add route")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    changed = common.git_changed_files(repo_root=clone)

    assert changed == ["backend/src/juli_backend/api/routes/thing.py"]
    assert not _is_shallow(clone), "the changed-file query shallow-grafted the repo"


def test_full_history_is_preserved_so_the_merge_base_survives(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A complete checkout must keep every commit the query started with.

    Counting commits is the discriminating assertion: a ``--depth=1`` graft
    leaves ``origin/main`` reachable by name while destroying the history behind
    it, so a name-only check would pass against the defect.
    """
    clone = _clone(origin, tmp_path / "clone", depth=None)
    before = _git(clone, "rev-list", "--count", "origin/main")
    _git(clone, "checkout", "--quiet", "-b", "feature/x")
    _commit(clone, "notes.md", "hi\n", "add notes")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    common.git_changed_files(repo_root=clone)

    assert _git(clone, "rev-list", "--count", "origin/main") == before


# --------------------------------------------------------------------------
# 3. The shallow checkout CI actually runs: a committed file must be seen.
# --------------------------------------------------------------------------


def test_committed_file_is_seen_on_a_real_shallow_checkout(
    origin: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lie under #1529: a file committed in the tree, reported as unchanged.

    This is a real ``--depth=1`` clone — the default for ``actions/checkout`` —
    with the branch behind the base tip, which is the normal case for a PR.
    """
    clone = _clone(origin, tmp_path / "clone", depth=1)
    assert _is_shallow(clone), "fixture precondition: clone must be shallow"

    _git(clone, "checkout", "--quiet", "-b", "feature/issue-1571")
    _commit(clone, "docs/adr/092-some-decision.md", "## Context\n", "add ADR-092")

    # The base advances after the branch is cut: the merge base is now behind
    # both tips, so a depth-1 base has no merge base with HEAD at all.
    _commit(origin, "README.md", "moved on\n", "base advances")

    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    changed = common.git_changed_files(repo_root=clone)

    assert "docs/adr/092-some-decision.md" in changed


def test_check_adr_gate_fails_on_a_shallow_checkout_it_used_to_pass(
    origin: Path, tmp_path: Path
) -> None:
    """End-to-end #1529: the gate itself, run as CI runs it, on a shallow clone.

    An architectural change (``docs/architecture/map.md``) with no ADR must FAIL.
    Against the defect the gate printed ``adr_requirement: PASS — No architectural
    change detected`` while the change sat committed in the tree.

    The gate scripts are copied into the clone because they resolve ``REPO_ROOT``
    from their own ``__file__``; running the repo's own copy would diff the repo,
    not the fixture.
    """
    clone = _clone(origin, tmp_path / "clone", depth=1)
    scripts_root = clone / "agent-runtime" / "scripts"
    scripts_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(CI_DIR, scripts_root / "ci")
    shutil.copytree(REPO_ROOT / "agent-runtime" / "scripts" / "validate", scripts_root / "validate")

    _git(clone, "checkout", "--quiet", "-b", "feature/issue-1571")
    _commit(clone, "docs/architecture/map.md", "| `backend/api` | 1 |\n", "arch change, no ADR")
    _commit(origin, "README.md", "moved on\n", "base advances")

    result = subprocess.run(
        [sys.executable, str(scripts_root / "validate" / "check_adr.py"), "--issue", "1571"],
        cwd=clone,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "GITHUB_BASE_REF": "main"},
    )

    combined = result.stdout + result.stderr
    assert "adr_requirement: FAIL" in combined, combined
    assert "No architectural change detected" not in combined, combined
    assert result.returncode != 0


# --------------------------------------------------------------------------
# 4. Callers must degrade to a *recorded* failure, never a silent pass.
# --------------------------------------------------------------------------

VALIDATE_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "validate"

# check_adr is deliberately absent: it is owned by another slice this wave and
# is not edited here. It inherits the fail-closed path instead — see
# test_unedited_gate_fails_closed_rather_than_passing_vacuously below.
DEGRADING_GATES = ("check_module_boundaries", "check_module_drift", "check_handoff")


def _load_gate(name: str):
    if str(VALIDATE_DIR) not in sys.path:
        sys.path.insert(0, str(VALIDATE_DIR))
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    return __import__(name)


@pytest.mark.parametrize("gate_name", DEGRADING_GATES)
def test_gate_records_a_reason_instead_of_passing_vacuously(
    gate_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lie: "no relevant change → nothing to check → PASS".

    When the changed-file set is unresolvable, each gate must return a FAIL that
    names the cause — the same shape ``harness_bootstrap_pin.py`` degrades to
    (#1540): never to HEAD, and never to a silent pass.
    """
    gate = _load_gate(gate_name)

    def _unresolvable(base_ref: str | None = None, repo_root: Path | None = None) -> list[str]:
        # Bound to the real signature on purpose: a **kwargs double would prove
        # routing, not that the real call site still type-checks.
        raise common.ChangedFilesUnresolved("origin/main", "planted: base truncated")

    monkeypatch.setattr(gate, "git_changed_files", _unresolvable)

    passed, description, details = gate.run_check(1571)

    assert passed is False, f"{gate_name} passed on an unresolvable diff"
    assert "planted: base truncated" in description or "planted: base truncated" in str(details)


@pytest.mark.parametrize("gate_name", DEGRADING_GATES)
def test_gate_still_passes_on_a_genuinely_empty_diff(
    gate_name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The guard on the guard: ``[]`` must remain a legitimate pass.

    Without this, "fail whenever the list is empty" would satisfy the test above
    while making every no-op PR red.
    """
    gate = _load_gate(gate_name)

    def _empty(base_ref: str | None = None, repo_root: Path | None = None) -> list[str]:
        return []

    monkeypatch.setattr(gate, "git_changed_files", _empty)

    passed, _, _ = gate.run_check(1571)

    assert passed is True, f"{gate_name} failed on a genuinely empty diff"


def test_unedited_gate_fails_closed_rather_than_passing_vacuously(tmp_path: Path) -> None:
    """``check_adr`` is not edited by this slice, and must still not pass vacuously.

    It is owned by another slice this wave, so it does not catch
    ``ChangedFilesUnresolved``. That is safe by construction rather than by
    accident: the exception propagates, the gate prints no ``adr_requirement:
    PASS|FAIL`` verdict line, and pr.yml's ``verdict_re`` treats a missing
    verdict as "the gate could not answer" — a non-zero result, not a pass.

    Asserting the *absence* of a PASS line is the point. Before #1571 this exact
    path printed ``adr_requirement: PASS``.
    """
    repo = tmp_path / "repo"
    scripts_root = repo / "agent-runtime" / "scripts"
    scripts_root.mkdir(parents=True)
    shutil.copytree(CI_DIR, scripts_root / "ci")
    shutil.copytree(VALIDATE_DIR, scripts_root / "validate")
    _git(repo, "init", "--initial-branch=main", "--quiet")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _commit(repo, "docs/architecture/map.md", "| `backend/api` | 1 |\n", "arch change")

    # No `origin` remote at all: the base is unresolvable and unfetchable.
    result = subprocess.run(
        [sys.executable, str(scripts_root / "validate" / "check_adr.py"), "--issue", "1571"],
        cwd=repo,
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "GITHUB_BASE_REF": "main"},
    )

    combined = result.stdout + result.stderr
    assert "adr_requirement: PASS" not in combined, combined
    assert "ChangedFilesUnresolved" in combined, combined
    assert result.returncode != 0
