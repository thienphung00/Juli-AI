"""The replay harness must come from a protected ref the PR cannot edit (#1459).

Every test here plants a lie and asserts it is caught. The lies are the three
ways a PR could grade itself with its own copy of the grader:

1. Edit the harness in the PR and let the edited copy do the grading.
2. Point ``HARNESS_REF`` at something unresolvable and fall back to the branch.
3. Resolve the harness but never record *which* harness ran, so the claim
   "this was graded by the protected harness" is unfalsifiable afterwards.

The exit-code split is asserted directly rather than through a message string:
``2`` means the harness is invalid (the check could not run), ``1`` means the
change under test is bad. Collapsing them recreates the defect this slice
exists to remove.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_seam():
    """Import ``eval.harness_ref`` without an E402 suppression.

    ``eval/`` sits at the repo root rather than on an installed package path, so
    the import needs a ``sys.path`` entry. Hoisting that above the module-level
    imports would need a ``# noqa: E402`` comment, and ``eval`` is inside
    ``eval.ratchets.SUPPRESSION_ROOTS`` — the suppression would be a new tracked
    debt identity. Paying real debt for import cosmetics is a bad trade.
    """
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from eval import harness_ref

    return harness_ref


harness_ref = _load_seam()


# ---------------------------------------------------------------------------
# A real git repository, because every claim here is a claim about git.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr}"
    return proc


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def harness_repo(tmp_path: Path) -> Path:
    """A repo with a protected ``main`` carrying a harness, and a feature branch."""
    repo = tmp_path / "repo"
    (repo / "eval").mkdir(parents=True)
    (repo / "backend").mkdir()
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))

    (repo / "eval" / "gate_scoring.py").write_text("VERSION = 1\n")
    (repo / "eval" / "artifact_mutants.py").write_text("OPERATORS = ()\n")
    (repo / "backend" / "app.py").write_text("value = 1\n")
    _commit(repo, "harness")

    _git(repo, "branch", "protected")
    _git(repo, "checkout", "-q", "-b", "feature")
    return repo


# ---------------------------------------------------------------------------
# AC1 — resolved from the protected ref, and the sha lands in the run record.
# ---------------------------------------------------------------------------


def test_harness_resolved_from_protected_ref_and_sha_recorded(harness_repo: Path) -> None:
    """A clean PR resolves the harness from the protected ref and records the sha.

    The lie under test: a run record that says nothing about which harness
    graded it. Without the sha, "the protected harness graded this" is a claim
    no one can check later — exactly the self-assessment this slice removes.
    """
    protected_sha = _git(harness_repo, "rev-parse", "protected").stdout.strip()

    # The PR changes product code only; it never touches eval/.
    (harness_repo / "backend" / "app.py").write_text("value = 2\n")
    head = _commit(harness_repo, "product change")

    resolution = harness_ref.resolve_harness(
        "protected", repo_root=harness_repo, base="protected", head=head
    )

    assert resolution.status == harness_ref.RESOLVED
    assert resolution.is_valid
    assert resolution.sha == protected_sha
    assert resolution.exit_code == harness_ref.EXIT_OK

    record = harness_ref.build_run_record(resolution)
    assert record["harnessRef"] == "protected"
    assert record["harnessSha"] == protected_sha
    # The record must carry the *resolved* sha, not merely echo the ref name.
    assert len(record["harnessSha"]) == 40
    assert record["harnessStatus"] == harness_ref.RESOLVED
    # Round-trips as JSON: the run record is written to disk by the workflow.
    assert json.loads(json.dumps(record))["harnessSha"] == protected_sha


def test_run_record_sha_is_the_protected_ref_not_the_branch_copy(harness_repo: Path) -> None:
    """The recorded sha follows the protected ref even when the branch moved on.

    The lie under test: recording ``HEAD``'s sha and calling it the harness sha.
    That would look identical on a clean PR and be silently wrong on every PR
    that edits anything at all.
    """
    protected_sha = _git(harness_repo, "rev-parse", "protected").stdout.strip()
    (harness_repo / "backend" / "app.py").write_text("value = 3\n")
    head = _commit(harness_repo, "product change")

    resolution = harness_ref.resolve_harness(
        "protected", repo_root=harness_repo, base="protected", head=head
    )

    assert resolution.sha == protected_sha
    assert resolution.sha != head


# ---------------------------------------------------------------------------
# AC2 — a PR touching the harness path exits 2, never 1.
# ---------------------------------------------------------------------------


def test_pr_editing_harness_exits_2_not_1(harness_repo: Path) -> None:
    """A PR that edits the grader is a harness failure, not a bad-change failure.

    The lie under test: a PR that quietly weakens ``eval/gate_scoring.py`` so the
    grader it is judged by is its own. It must not be reported with the same
    exit code as an honest failing change.
    """
    (harness_repo / "eval" / "gate_scoring.py").write_text("VERSION = 1  # always pass\n")
    head = _commit(harness_repo, "tweak the grader")

    resolution = harness_ref.resolve_harness(
        "protected", repo_root=harness_repo, base="protected", head=head
    )

    assert resolution.status == harness_ref.HARNESS_MODIFIED
    assert not resolution.is_valid
    assert resolution.exit_code == harness_ref.EXIT_HARNESS_INVALID
    assert resolution.exit_code == 2
    assert resolution.exit_code != harness_ref.EXIT_CHANGE_BAD
    assert "eval/gate_scoring.py" in resolution.touched_harness_paths
    assert "eval/gate_scoring.py" in resolution.detail


def test_pr_adding_a_new_harness_file_also_exits_2(harness_repo: Path) -> None:
    """Adding to the harness is editing it.

    The lie under test: shipping a *new* file into ``eval/`` — a second grader,
    or a fixture the grader will pick up — on the theory that only modifying an
    existing file counts as touching the harness.
    """
    (harness_repo / "eval" / "helpful_extra.py").write_text("BONUS = True\n")
    head = _commit(harness_repo, "add a harness file")

    resolution = harness_ref.resolve_harness(
        "protected", repo_root=harness_repo, base="protected", head=head
    )

    assert resolution.exit_code == 2
    assert "eval/helpful_extra.py" in resolution.touched_harness_paths


def test_pr_deleting_a_harness_file_exits_2(harness_repo: Path) -> None:
    """Deleting the grader must not read as "no harness paths changed"."""
    (harness_repo / "eval" / "artifact_mutants.py").unlink()
    head = _commit(harness_repo, "delete a harness file")

    resolution = harness_ref.resolve_harness(
        "protected", repo_root=harness_repo, base="protected", head=head
    )

    assert resolution.exit_code == 2
    assert "eval/artifact_mutants.py" in resolution.touched_harness_paths


def test_path_outside_harness_that_merely_starts_with_the_prefix_is_not_a_touch() -> None:
    """``evaluation/`` is not ``eval/``.

    The lie under test is on the other side: a prefix match sloppy enough to
    call an unrelated directory a harness edit would make the guard fire on
    innocent PRs, and a guard that cries wolf gets switched off.
    """
    assert harness_ref.harness_paths_touched(["evaluation/notes.md"]) == ()
    assert harness_ref.harness_paths_touched(["backend/eval/thing.py"]) == ()
    assert harness_ref.harness_paths_touched(["eval/gate_scoring.py"]) == ("eval/gate_scoring.py",)


def test_traversal_out_of_the_harness_directory_is_not_laundered_into_a_pass() -> None:
    """``eval/../backend/x.py`` denotes backend, and must not claim harness status,
    while a path that traverses back *into* the harness must still be caught.

    The lie under test: spelling a harness path so a naive ``startswith`` check
    misses it.
    """
    assert harness_ref.harness_paths_touched(["eval/../backend/x.py"]) == ()
    assert harness_ref.harness_paths_touched(["backend/../eval/gate_scoring.py"]) == (
        "backend/../eval/gate_scoring.py",
    )
    assert harness_ref.harness_paths_touched(["./eval/gate_scoring.py"]) == (
        "./eval/gate_scoring.py",
    )


# ---------------------------------------------------------------------------
# AC3 — an unresolvable HARNESS_REF fails closed, never falls back.
# ---------------------------------------------------------------------------


def test_unresolvable_harness_ref_fails_closed(harness_repo: Path) -> None:
    """A ref that does not exist fails; it never falls back to the branch copy.

    The lie under test is the whole vulnerability: resolve fails, so the runner
    "helpfully" uses the checked-out copy — which is the PR's own copy — and the
    protection evaporates while the run still reports success.
    """
    head = _git(harness_repo, "rev-parse", "HEAD").stdout.strip()

    resolution = harness_ref.resolve_harness(
        "refs/heads/no-such-protected-ref",
        repo_root=harness_repo,
        base="protected",
        head=head,
    )

    assert resolution.status == harness_ref.UNRESOLVABLE
    assert not resolution.is_valid
    assert resolution.exit_code == 2
    assert resolution.sha is None
    # No fallback: it must not have silently adopted the branch's own commit.
    assert resolution.sha != head
    assert harness_ref.build_run_record(resolution)["harnessSha"] is None


def test_unset_harness_ref_fails_closed(harness_repo: Path) -> None:
    """An unset ref is unconfigured, not permission to use the local copy.

    The lie under test: treating a missing ``HARNESS_REF`` as "no protection
    requested" and grading with the branch. Absence of configuration is the most
    likely way this protection would be lost in practice.
    """
    head = _git(harness_repo, "rev-parse", "HEAD").stdout.strip()

    resolution = harness_ref.resolve_harness(
        "", repo_root=harness_repo, base="protected", head=head
    )

    assert resolution.status == harness_ref.UNSET
    assert resolution.exit_code == 2
    assert resolution.sha is None


def test_ref_resolving_to_a_commit_without_the_harness_fails_closed(tmp_path: Path) -> None:
    """A ref that resolves but carries no harness is unusable, not usable.

    The lie under test: ``git rev-parse`` succeeded, so the runner declares the
    harness resolved and then silently grades with whatever ``eval/`` is on
    disk — the branch's copy again, by a different route.
    """
    repo = tmp_path / "empty"
    (repo / "backend").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    (repo / "backend" / "app.py").write_text("value = 1\n")
    _commit(repo, "no harness here")
    _git(repo, "branch", "protected")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "backend" / "app.py").write_text("value = 2\n")
    head = _commit(repo, "change")

    resolution = harness_ref.resolve_harness(
        "protected", repo_root=repo, base="protected", head=head
    )

    assert resolution.status == harness_ref.HARNESS_ABSENT
    assert resolution.exit_code == 2


# ---------------------------------------------------------------------------
# Shallow checkouts — CI checks out shallow for most jobs.
# ---------------------------------------------------------------------------


def test_shallow_checkout_missing_the_protected_ref_fails_closed_and_says_so(
    tmp_path: Path, harness_repo: Path
) -> None:
    """In a shallow clone without the protected ref, the answer is "cannot grade".

    The lie under test: assuming depth. A shallow checkout is CI's normal state,
    and a resolver that assumes full history would either crash or, worse,
    conclude the harness is fine and grade with the branch copy. The verdict is
    exit 2 and the *reason* must name shallowness, so the remedy (fetch the ref)
    is actionable rather than a mystery.
    """
    _git(harness_repo, "checkout", "-q", "main")
    shallow = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{harness_repo}", str(shallow)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert harness_ref.is_shallow_repository(shallow) is True

    head = _git(shallow, "rev-parse", "HEAD").stdout.strip()
    resolution = harness_ref.resolve_harness(
        "refs/heads/definitely-not-fetched",
        repo_root=shallow,
        base=head,
        head=head,
        allow_fetch=False,
    )

    assert resolution.exit_code == 2
    assert resolution.status == harness_ref.UNRESOLVABLE
    assert resolution.shallow is True
    assert "shallow" in resolution.detail.lower()


def test_shallow_checkout_is_detected_rather_than_assumed(harness_repo: Path) -> None:
    """A full checkout must not be reported as shallow."""
    assert harness_ref.is_shallow_repository(harness_repo) is False


def test_diff_against_an_unreachable_base_fails_closed_not_open(
    tmp_path: Path, harness_repo: Path
) -> None:
    """If the diff cannot be computed, we cannot know the harness was untouched.

    The lie under test: a shallow checkout where ``git diff base...head`` fails
    because the base is beyond the graft, and the empty output is read as "no
    harness files changed". An empty diff that was never computed is not
    evidence of innocence.
    """
    _git(harness_repo, "checkout", "-q", "main")
    shallow = tmp_path / "shallow2"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{harness_repo}", str(shallow)],
        capture_output=True,
        text=True,
        check=True,
    )
    head = _git(shallow, "rev-parse", "HEAD").stdout.strip()

    resolution = harness_ref.resolve_harness(
        head,
        repo_root=shallow,
        base="0" * 40,  # a base this checkout cannot reach
        head=head,
        allow_fetch=False,
    )

    assert resolution.exit_code == 2
    assert resolution.status == harness_ref.DIFF_UNAVAILABLE
    assert "shallow" in resolution.detail.lower()


# ---------------------------------------------------------------------------
# The exit-code split at the entrypoint.
# ---------------------------------------------------------------------------


def test_entrypoint_exits_1_when_the_change_under_test_is_bad(
    harness_repo: Path, tmp_path: Path
) -> None:
    """A valid harness plus a failing change is exit 1, not 2.

    This is the other half of the split. If this returned 2, "the work is bad"
    and "the check could not run" would be indistinguishable again.
    """
    (harness_repo / "backend" / "app.py").write_text("value = 99\n")
    head = _commit(harness_repo, "a genuinely bad change")
    record_path = tmp_path / "run.json"

    code = harness_ref.main(
        [
            "--harness-ref",
            "protected",
            "--repo-root",
            str(harness_repo),
            "--base",
            "protected",
            "--head",
            head,
            "--run-record",
            str(record_path),
            "--eval-command",
            f"{sys.executable} -c 'raise SystemExit(1)'",
        ]
    )

    assert code == harness_ref.EXIT_CHANGE_BAD
    assert code == 1
    # The harness still resolved, and the run record still names which one.
    record = json.loads(record_path.read_text())
    assert record["harnessStatus"] == harness_ref.RESOLVED
    assert len(record["harnessSha"]) == 40
    assert record["exitCode"] == 1


def test_entrypoint_exits_0_when_harness_valid_and_change_good(
    harness_repo: Path, tmp_path: Path
) -> None:
    (harness_repo / "backend" / "app.py").write_text("value = 4\n")
    head = _commit(harness_repo, "a good change")
    record_path = tmp_path / "run.json"

    code = harness_ref.main(
        [
            "--harness-ref",
            "protected",
            "--repo-root",
            str(harness_repo),
            "--base",
            "protected",
            "--head",
            head,
            "--run-record",
            str(record_path),
            "--eval-command",
            f"{sys.executable} -c 'raise SystemExit(0)'",
        ]
    )

    assert code == harness_ref.EXIT_OK
    assert json.loads(record_path.read_text())["harnessSha"]


def test_entrypoint_never_runs_the_evaluation_when_the_harness_is_invalid(
    harness_repo: Path, tmp_path: Path
) -> None:
    """An invalid harness short-circuits before the evaluation runs.

    The lie under test: running the evaluation anyway and letting its verdict
    stand. A grader the PR edited must produce no verdict at all — a passing
    result from a compromised harness is worse than no result.
    """
    (harness_repo / "eval" / "gate_scoring.py").write_text("VERSION = 2\n")
    head = _commit(harness_repo, "touch the harness")
    record_path = tmp_path / "run.json"
    sentinel = tmp_path / "evaluation_ran"

    code = harness_ref.main(
        [
            "--harness-ref",
            "protected",
            "--repo-root",
            str(harness_repo),
            "--base",
            "protected",
            "--head",
            head,
            "--run-record",
            str(record_path),
            "--eval-command",
            f"{sys.executable} -c "
            f'\'open({str(sentinel)!r}, "w").write("ran"); raise SystemExit(0)\'',
        ]
    )

    assert code == 2
    assert not sentinel.exists(), "the evaluation ran under a harness the PR had edited"
    assert json.loads(record_path.read_text())["harnessStatus"] == (harness_ref.HARNESS_MODIFIED)


def test_canary_that_passes_is_a_harness_failure_exit_2(harness_repo: Path) -> None:
    """A canary is a record that MUST fail. If it passes, the grader is broken.

    The lie under test: a harness so degraded it approves everything. It would
    otherwise report a clean sweep — the most convincing possible false green.
    """
    head = _git(harness_repo, "rev-parse", "HEAD").stdout.strip()
    resolution = harness_ref.resolve_harness(
        "protected", repo_root=harness_repo, base="protected", head=head
    )
    assert resolution.is_valid

    # A canary that correctly fails leaves the harness valid.
    assert harness_ref.canary_exit_code(resolution, canary_exit_codes=[1, 1]) is None
    # A canary that passed means the harness cannot be trusted to fail anything.
    assert harness_ref.canary_exit_code(resolution, canary_exit_codes=[1, 0]) == 2


def test_evaluation_that_cannot_launch_is_2_not_1(harness_repo: Path, tmp_path: Path) -> None:
    """ "The evaluation could not start" is a harness problem, not a bad change.

    The lie under test: mapping every non-zero outcome to 1, so a broken runner
    is charged to the PR's account.
    """
    (harness_repo / "backend" / "app.py").write_text("value = 5\n")
    head = _commit(harness_repo, "fine change")

    code = harness_ref.main(
        [
            "--harness-ref",
            "protected",
            "--repo-root",
            str(harness_repo),
            "--base",
            "protected",
            "--head",
            head,
            "--run-record",
            str(tmp_path / "run.json"),
            "--eval-command",
            "definitely-not-an-executable-on-this-machine --go",
        ]
    )

    assert code == 2


def test_exit_codes_are_three_distinct_values() -> None:
    """The split is the point; assert the constants never collapse."""
    codes = {
        harness_ref.EXIT_OK,
        harness_ref.EXIT_CHANGE_BAD,
        harness_ref.EXIT_HARNESS_INVALID,
    }
    assert codes == {0, 1, 2}


# ---------------------------------------------------------------------------
# The real repository: this slice guards the harness that actually exists.
# ---------------------------------------------------------------------------


def test_the_real_harness_paths_exist_in_this_repository() -> None:
    """A guard over a path that does not exist protects nothing."""
    for prefix in harness_ref.HARNESS_PATHS:
        assert (REPO_ROOT / prefix.rstrip("/")).exists(), f"{prefix} is not in the repo"


def test_the_scored_surface_is_inside_the_guarded_paths() -> None:
    """The modules this slice exists to protect are actually covered."""
    for path in ("eval/gate_scoring.py", "eval/artifact_mutants.py"):
        assert harness_ref.harness_paths_touched([path]) == (path,)
