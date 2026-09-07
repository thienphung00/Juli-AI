"""Tests for the harness bootstrap pin (#1540, CI-WAVE-1).

The gate's job is to detect *harness drift*: has the bootstrap source under
``.cursor/skills`` / ``agent-runtime/docs`` changed out from under this run since
the point the run bootstrapped from.

It could not do that job. ``agent-runtime.config.yml`` pinned ``pinBranch: HEAD``,
and ``HEAD`` is symbolic — it re-resolves at *check* time to whatever branch is
currently checked out, which on an issue branch is that branch's own tip. So the
gate compared the branch against itself and failed the moment the branch had any
commit at all, while never once looking at whether the harness had changed. Two
W4 reviewers hit it; ``eval/gate_scoring.py`` documents the same discovery
("committing this very branch flipped that gate from PASS to FAIL").

Every test below is written in the shape the epic demands: the anchor must be
stable under the branch's own work, *and* the gate must still bite on real drift.
A fix that only did the first half would be a gate that cannot fail — strictly
worse than the bug it replaced.

All git mutation in this module happens inside pytest ``tmp_path`` throwaway
repositories. Nothing here touches the working repository.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"
SCRIPTS_DIR = REPO_ROOT / "agent-runtime" / "scripts"
AGENT_RUNTIME_CONFIG = REPO_ROOT / "agent-runtime" / "config" / "agent-runtime.config.yml"


def _load_seam():
    """Import the pin module and the config loader, both outside any package root.

    Done inside a function deliberately: hoisting the ``sys.path`` inserts above
    the module-level imports needs an ``E402`` suppression, and the repo's debt
    ratchet counts suppression identities.
    """
    for directory in (CI_DIR, SCRIPTS_DIR):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    import harness_bootstrap_pin
    from build_runtime import load_simple_yaml

    return harness_bootstrap_pin, load_simple_yaml


pin, load_simple_yaml = _load_seam()


SKILL_REL = ".cursor/skills/domain/backend/SKILL.md"
DOCS_REL = "agent-runtime/docs/agent-runtime.md"
SOURCE_PATHS = [".cursor/skills", "agent-runtime/docs"]
BOOTSTRAP_CONFIG: dict[str, Any] = {"sourcePaths": SOURCE_PATHS}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write(repo: Path, relative: str, body: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@e.x", "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _set_upstream(repo: Path, checked_out_branch: str, target_branch: str) -> None:
    """Point ``checked_out_branch``'s ``@{u}`` at ``origin/<target_branch>``.

    ``git branch --set-upstream-to`` refuses a bare ``update-ref``'d
    remote-tracking ref ("not stored as a remote-tracking branch") unless a
    real remote is registered, because it validates against
    ``remote.<name>.fetch``'s refspec, not just ref existence. A placeholder
    URL is enough -- nothing here ever fetches.
    """
    if not _git(repo, "remote"):
        _git(repo, "remote", "add", "origin", "https://example.invalid/placeholder.git")
    _git(repo, "config", f"branch.{checked_out_branch}.remote", "origin")
    _git(repo, "config", f"branch.{checked_out_branch}.merge", f"refs/heads/{target_branch}")


@pytest.fixture
def harness_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo with a ``main`` base commit and a feature branch forked from it.

    Returns ``(repo, fork_point_sha)``. The fork point is what a correct anchor
    must resolve to, from the feature branch, no matter how many commits the
    feature branch subsequently accumulates.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _write(repo, SKILL_REL, "# backend skill\noriginal body\n")
    _write(repo, DOCS_REL, "# agent runtime\noriginal body\n")
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = []\n")
    fork_point = _commit(repo, "base: harness at bootstrap")
    _git(repo, "switch", "-c", "feature/issue-1540-bootstrap-pin")
    return repo, fork_point


def _parent(branch: str, commit_sha: str) -> dict[str, Any]:
    return {
        "bootstrapRef": {
            "branch": branch,
            "commitSha": commit_sha,
            "copiedAt": "2026-09-03T00:00:00Z",
        }
    }


CHILD: dict[str, Any] = {"harnessUtility": {"skills": [{"path": SKILL_REL}]}}


def _validate(repo: Path, parent: dict[str, Any]) -> tuple[bool, str, dict[str, Any]]:
    return pin.validate_bootstrap_ref(
        parent,
        CHILD,
        bootstrap_config=BOOTSTRAP_CONFIG,
        repo_root=repo,
    )


# ---------------------------------------------------------------------------
# The anchor must not follow the branch it is meant to measure.
# ---------------------------------------------------------------------------


def test_symbolic_head_anchor_is_rejected(harness_repo: tuple[Path, str]) -> None:
    """``HEAD`` re-resolves to the branch tip, so it can never measure drift.

    This is the defect itself. Fail closed and say why, rather than pass now and
    fail on the next commit for a reason that has nothing to do with the harness.
    """
    repo, fork_point = harness_repo
    passed, description, _ = _validate(repo, _parent("HEAD", fork_point))
    assert passed is False
    assert "symbolic" in description.lower()


@pytest.mark.parametrize("spec", ["HEAD", "@", "HEAD~1", "HEAD^", "head"])
def test_self_referential_anchor_specs_are_all_rejected(
    harness_repo: tuple[Path, str], spec: str
) -> None:
    """Every spelling that tracks the checked-out tip, not just the literal ``HEAD``."""
    repo, fork_point = harness_repo
    passed, description, _ = _validate(repo, _parent(spec, fork_point))
    assert passed is False
    assert "symbolic" in description.lower()


@pytest.mark.parametrize(
    "spec",
    [
        "merge-base:HEAD",
        "merge-base:@",
        "merge-base:HEAD~1",
        "feature/issue-1540-bootstrap-pin",
        "refs/heads/feature/issue-1540-bootstrap-pin",
        "merge-base:feature/issue-1540-bootstrap-pin",
    ],
)
def test_self_reference_cannot_return_through_the_new_syntax(
    harness_repo: tuple[Path, str], spec: str
) -> None:
    """The defect must not be reachable by a one-line config edit.

    Two shapes the string guard alone does not see. ``merge-base:HEAD`` slips
    past a check applied only to the whole spec, because the prefix is stripped
    afterwards and ``git merge-base HEAD HEAD`` is HEAD. Naming the checked-out
    branch does the same without the word HEAD appearing at all. Both restore
    exactly the bug #1540 exists to remove, so both must fail closed at the
    resolver, not merely be caught by the shipped-config assertion below.
    """
    repo, fork_point = harness_repo
    passed, description, _ = _validate(repo, _parent(spec, fork_point))
    assert passed is False
    assert "symbolic" in description.lower() or "checked-out branch" in description


@pytest.mark.parametrize(
    "spec_builder",
    [
        pytest.param(lambda branch, sha, short: f"merge-base:{branch}", id="name-bare"),
        pytest.param(
            lambda branch, sha, short: f"merge-base:refs/heads/{branch}", id="name-refs-heads"
        ),
        pytest.param(lambda branch, sha, short: f"merge-base:{sha}", id="sha-full"),
        pytest.param(lambda branch, sha, short: f"merge-base:{short}", id="sha-abbrev"),
    ],
)
def test_merge_base_anchor_is_screened_by_resolved_identity_not_spelling(
    harness_repo: tuple[Path, str],
    spec_builder,
) -> None:
    """#1611: a raw or abbreviated SHA equal to HEAD's own commit must never be
    silently accepted -- exactly like naming the checked-out branch itself.

    ``current_branch_names`` enumerates name spellings only (bare name,
    ``refs/heads/<name>``, ``heads/<name>``, ``origin/<name>``). A
    ``merge-base:`` base ref that is HEAD's own SHA -- raw or abbreviated --
    names none of those spellings, so the string guard lets it through and,
    before this fix, ``resolve_bootstrap_anchor_with_note`` returned HEAD's
    own SHA with ``note=None``: the self-referential defect ADR-095 exists to
    prevent, reached through a spelling nobody enumerated.

    Parametrised over both name spellings and SHA spellings in one test so
    the guard is proven to screen by resolved commit identity, not by which
    strings happen to be listed. The two are not required to fail the same
    way: a name spelling of the checked-out branch itself is unambiguous and
    raises outright (unchanged, pre-existing behaviour); a SHA/abbreviated-SHA
    that merely *resolves* to HEAD's commit right now is indistinguishable
    from the ordinary fresh-fork case (see
    ``identity_coincides_with_head_note``) and so degrades with a recorded
    reason instead -- but never silently returns ``note=None``. That is the
    one property proven for every variant here.
    """
    repo, _fork_point = harness_repo
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    _commit(repo, "feat: give the checked-out branch a commit of its own")
    branch = "feature/issue-1540-bootstrap-pin"
    head_sha = _git(repo, "rev-parse", "HEAD")
    head_short = _git(repo, "rev-parse", "--short", "HEAD")

    spec = spec_builder(branch, head_sha, head_short)
    try:
        resolved, note = pin.resolve_bootstrap_anchor_with_note(spec, repo)
    except RuntimeError as excinfo:
        message = str(excinfo)
        assert "symbolic" in message or "checked-out branch" in message
    else:
        assert resolved == head_sha
        assert note is not None, (
            f"{spec!r} silently resolved to HEAD's own commit ({head_sha[:12]}) "
            "with no degradation note -- exactly the defect #1611 exists to close"
        )
        assert "own commit" in note


def test_self_referential_specs_are_refused_at_cache_write_time(
    harness_repo: tuple[Path, str],
) -> None:
    """Fail closed when the pin is *written*, not only when it is read.

    Architect lock 2: recording a ref that will re-resolve differently is the
    thing that must never happen, so ``bootstrap_ref_from_git`` refuses rather
    than storing a pin the reader will later reject.
    """
    repo, _ = harness_repo
    for spec in ("HEAD", "merge-base:HEAD", "feature/issue-1540-bootstrap-pin"):
        with pytest.raises(RuntimeError) as excinfo:
            pin.bootstrap_ref_from_git(spec, repo)
        message = str(excinfo.value)
        # Naming the spec is the point: a refusal that does not say which value
        # was refused sends the next reader back to the config to guess.
        assert spec in message
        assert "symbolic" in message or "checked-out branch" in message


def test_a_self_referential_spec_cannot_launder_committed_harness_drift(
    harness_repo: tuple[Path, str],
) -> None:
    """The end-to-end lock-6 assertion: real drift, re-pinned, must stay red.

    After #1667, committed drift passes (AC1). But a self-referential anchor
    cannot be used to hide even uncommitted drift, because anchoring to the
    checked-out tip would make all history invisible.

    This test uses committed drift with an uncommitted edit on top, so the
    gate fails on the uncommitted part. The self-referential anchor still
    cannot be used because it raises at pin time.
    """
    repo, fork_point = harness_repo
    _write(repo, SKILL_REL, "# backend skill\nreal committed harness drift\n")
    _commit(repo, "chore: drift the harness")
    # Add uncommitted drift on top so the gate fails.
    _write(repo, DOCS_REL, "# agent runtime\nuncommitted drift\n")

    # The correct anchor should fail on the uncommitted part.
    passed, description, _ = _validate(repo, _parent("merge-base:main", fork_point))
    assert passed is False
    assert DOCS_REL in description

    # And no self-referential re-pin can be used anyway, at write time.
    for spec in ("merge-base:HEAD", "feature/issue-1540-bootstrap-pin"):
        with pytest.raises(RuntimeError):
            pin.bootstrap_ref_from_git(spec, repo)
        # Even at read time, the uncommitted drift should fail.
        laundered, _, _ = _validate(repo, _parent(spec, _git(repo, "rev-parse", "HEAD")))
        assert laundered is False


def test_pin_survives_branch_commits_without_harness_drift(
    harness_repo: tuple[Path, str],
) -> None:
    """The green half: a branch that has done real work, but no harness work, passes.

    Under the old anchor this failed on commit number one.
    """
    repo, fork_point = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    _commit(repo, "feat: product work, no harness change")
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a', 'b']\n")
    _commit(repo, "feat: more product work")

    passed, description, details = _validate(repo, parent)
    assert passed is True, description
    assert details["pinnedCommitSha"] == fork_point
    assert details["resolvedAnchorSha"] == fork_point


def test_merge_base_anchor_resolves_to_the_fork_point_not_the_tip(
    harness_repo: tuple[Path, str],
) -> None:
    """The anchor is a property of where the branch forked, not of its tip."""
    repo, fork_point = harness_repo
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    tip = _commit(repo, "feat: work")

    resolved = pin.resolve_bootstrap_anchor("merge-base:main", repo)
    assert resolved == fork_point
    assert resolved != tip


# ---------------------------------------------------------------------------
# The gate must still bite. Each of these plants real harness drift.
# ---------------------------------------------------------------------------


def test_gate_passes_when_cursor_skills_drift_is_committed(
    harness_repo: tuple[Path, str],
) -> None:
    """AC1: Committed harness drift passes.

    After #1667, committed drift is recognized as reviewed and passes. The
    detail names the reviewed paths so reviewers see them.
    """
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, SKILL_REL, "# backend skill\nEDITED under the run\n")
    _commit(repo, "chore: quietly edit the harness")

    passed, description, details = _validate(repo, parent)
    assert passed is True, description
    assert SKILL_REL in description
    assert SKILL_REL in details["committedDrift"]


def test_gate_fails_when_cursor_skills_drift_uncommitted(
    harness_repo: tuple[Path, str],
) -> None:
    """Working-tree drift counts. The harness the run is reading is the one on disk."""
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, SKILL_REL, "# backend skill\nEDITED but never committed\n")

    passed, description, details = _validate(repo, parent)
    assert passed is False
    assert SKILL_REL in description
    assert details["driftedHarnessPaths"] == [SKILL_REL]


def test_gate_passes_when_agent_runtime_docs_drift_is_committed(
    harness_repo: tuple[Path, str],
) -> None:
    """AC1: Every configured bootstrap sourcePath is watched, and committed
    drift passes."""
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, DOCS_REL, "# agent runtime\nEDITED\n")
    _commit(repo, "docs: quietly edit the runtime doc")

    passed, description, details = _validate(repo, parent)
    assert passed is True, description
    assert DOCS_REL in details["committedDrift"]


def test_gate_fails_on_a_new_untracked_harness_file(harness_repo: tuple[Path, str]) -> None:
    """Adding a skill is drift too — a run can load a file that was not in the pin."""
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, ".cursor/skills/domain/smuggled/SKILL.md", "# smuggled\n")

    passed, description, details = _validate(repo, parent)
    assert passed is False
    assert ".cursor/skills/domain/smuggled/SKILL.md" in details["driftedHarnessPaths"]


def test_gate_fails_when_a_harness_file_is_deleted(harness_repo: tuple[Path, str]) -> None:
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    (repo / DOCS_REL).unlink()

    passed, _, details = _validate(repo, parent)
    assert passed is False
    assert DOCS_REL in details["driftedHarnessPaths"]


def test_gate_fails_when_the_fork_point_moved_under_the_pin(
    harness_repo: tuple[Path, str],
) -> None:
    """A stale pin — main advanced and the branch absorbed it — is drift, not a pass."""
    repo, fork_point = harness_repo
    _git(repo, "switch", "main")
    _write(repo, SKILL_REL, "# backend skill\nmain moved on\n")
    _commit(repo, "chore: main advances the harness")
    _git(repo, "switch", "feature/issue-1540-bootstrap-pin")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@e.x", "merge", "--no-edit", "main")

    passed, description, details = _validate(repo, _parent("merge-base:main", fork_point))
    assert passed is False
    assert "anchor" in description.lower()
    assert details["pinnedCommitSha"] == fork_point
    assert details["resolvedAnchorSha"] != fork_point


# ---------------------------------------------------------------------------
# Shallow checkouts. `actions/checkout` is depth-1 by default and this working
# repository is itself grafted, so "no merge base exists" is the common case,
# not an exotic one. It must degrade to a named, recorded fallback — never to
# HEAD, and never to a silent pass.
# ---------------------------------------------------------------------------


def _shallow_clone(source: Path, destination: Path) -> Path:
    _git(
        source,
        "clone",
        "--depth",
        "1",
        "--no-local",
        "--branch",
        "feature/issue-1540-bootstrap-pin",
        f"file://{source}",
        str(destination),
    )
    return destination


def test_shallow_checkout_falls_back_to_the_base_ref_and_says_so(
    harness_repo: tuple[Path, str], tmp_path: Path
) -> None:
    repo, _ = harness_repo
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    _commit(repo, "feat: work")

    shallow = _shallow_clone(repo, tmp_path / "shallow")
    assert _git(shallow, "rev-parse", "--is-shallow-repository") == "true"
    _git(shallow, "fetch", "--depth", "1", "origin", "main:refs/remotes/origin/main")

    sha, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/main", shallow)
    assert sha == _git(shallow, "rev-parse", "origin/main")
    assert note is not None and "shallow" in note
    assert sha != _git(shallow, "rev-parse", "HEAD")


def test_shallow_fallback_still_detects_drift(
    harness_repo: tuple[Path, str], tmp_path: Path
) -> None:
    """The degraded anchor must not degrade the thing the gate is for."""
    repo, _ = harness_repo
    # Give the feature branch a commit of its own first, so that at depth 1 the
    # two histories are genuinely disjoint and the fallback is actually taken.
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    _commit(repo, "feat: work")

    shallow = _shallow_clone(repo, tmp_path / "shallow")
    _git(shallow, "fetch", "--depth", "1", "origin", "main:refs/remotes/origin/main")
    anchor, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/main", shallow)
    assert note is not None

    _write(shallow, SKILL_REL, "# backend skill\nEDITED in a shallow checkout\n")

    passed, description, details = _validate(shallow, _parent("merge-base:origin/main", anchor))
    assert passed is False
    assert SKILL_REL in description
    assert details["anchorDegraded"] is True


def test_missing_base_ref_fails_closed(harness_repo: tuple[Path, str]) -> None:
    """No anchor means no measurement. Red, not lenient."""
    repo, _ = harness_repo
    with pytest.raises(RuntimeError, match="rev-parse") as excinfo:
        pin.resolve_bootstrap_anchor("merge-base:origin/nonexistent", repo)
    # The unresolvable ref must appear, not just the failing git subcommand,
    # or the operator cannot tell which side of the anchor spec is broken.
    assert "origin/nonexistent" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Behaviour that must survive the fix.
# ---------------------------------------------------------------------------


def test_missing_bootstrap_ref_still_fails(harness_repo: tuple[Path, str]) -> None:
    repo, _ = harness_repo
    passed, description, _ = _validate(repo, {})
    assert passed is False
    assert "bootstrapRef" in description


def test_harness_skill_path_absent_at_the_pin_still_fails(
    harness_repo: tuple[Path, str],
) -> None:
    """A child cache citing a skill that did not exist at the pin is unreproducible."""
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))
    child = {"harnessUtility": {"skills": [{"path": ".cursor/skills/domain/ghost/SKILL.md"}]}}

    passed, description, _ = pin.validate_bootstrap_ref(
        parent, child, bootstrap_config=BOOTSTRAP_CONFIG, repo_root=repo
    )
    assert passed is False
    assert "missing at pinned" in description


def test_empty_source_paths_still_fails(harness_repo: tuple[Path, str]) -> None:
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))
    passed, description, _ = pin.validate_bootstrap_ref(
        parent, CHILD, bootstrap_config={"sourcePaths": []}, repo_root=repo
    )
    assert passed is False
    assert "sourcePaths" in description


def test_bootstrap_ref_from_git_records_the_spec_and_the_resolved_sha(
    harness_repo: tuple[Path, str],
) -> None:
    """``ensure_workflow_cache`` calls this positionally — keep the shape."""
    repo, fork_point = harness_repo
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    _commit(repo, "feat: work")

    ref = pin.bootstrap_ref_from_git("merge-base:main", repo, copied_at="2026-09-03T00:00:00Z")
    assert ref == {
        "branch": "merge-base:main",
        "commitSha": fork_point,
        "copiedAt": "2026-09-03T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# The shipped configuration must not re-introduce the defect.
# ---------------------------------------------------------------------------


def test_shipped_config_pin_branch_is_not_self_referential() -> None:
    """The config value is the defect's home. Assert it directly, at its source."""
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    spec = config["workflow_prompt_cache"]["bootstrap"]["pinBranch"]
    assert isinstance(spec, str) and spec.strip()
    assert not pin.is_self_referential_anchor(spec), (
        f"agent-runtime.config.yml pins bootstrap to {spec!r}, which re-resolves to "
        "the checked-out branch tip and makes the drift gate measure nothing"
    )


def test_shipped_config_pin_branch_resolves_against_this_repository() -> None:
    """Not merely non-symbolic — actually resolvable here, or the gate is dead weight."""
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    spec = config["workflow_prompt_cache"]["bootstrap"]["pinBranch"]
    resolved = pin.resolve_bootstrap_anchor(spec, REPO_ROOT)
    assert len(resolved) == 40

    def _rev(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()

    # The invariant that must hold however this checkout was fetched: the anchor
    # is not the branch tip. That is the whole defect in one assertion.
    assert resolved != _rev("rev-parse", "HEAD")

    if _rev("rev-parse", "--is-shallow-repository") == "false":
        # With real history available the anchor must also be behind HEAD, or
        # every drift diff computed against it would be noise rather than signal.
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", resolved, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert ancestor.returncode == 0, f"{spec!r} resolved to {resolved}, not behind HEAD"


def test_shipped_config_pin_branch_uses_the_base_ref_token() -> None:
    """#1608: the base half must be the dynamic token, not a hardcoded branch name.

    Locks the config value itself so a future edit cannot quietly reintroduce
    `merge-base:origin/main` -- a hardcoded base is wrong at issue tier (see the
    module docstring for #1608's exhibit) and this is the one place a reviewer
    would not otherwise be forced to notice the regression.
    """
    config = load_simple_yaml(AGENT_RUNTIME_CONFIG)
    spec = config["workflow_prompt_cache"]["bootstrap"]["pinBranch"]
    assert spec == f"merge-base:origin/{pin.BASE_REF_TOKEN}", (
        f"agent-runtime.config.yml pins bootstrap to {spec!r}; expected the "
        f"BASE_REF token so the anchor resolves against this run's actual "
        "integration base (github.base_ref) instead of a hardcoded branch"
    )


# ---------------------------------------------------------------------------
# #1608 — the base ref half of the anchor must be the run's actual integration
# base, not a hardcoded `main`. At issue tier that base is a wave branch which
# can carry harness commits `main` does not: PR #1561's live failure was the
# wave having landed #1529's status-record.schema.json change under
# `agent-runtime/docs`, a `sourcePaths` entry, before `main` had it. Anchoring
# to `origin/main` treated that landed, reviewed wave commit as drift on every
# subsequent issue-tier PR on the wave -- a false positive, not a real one.
# ---------------------------------------------------------------------------


@pytest.fixture
def wave_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """``main`` -> ``wave`` (one additional harness commit) -> ``issue-branch``.

    Returns ``(repo, main_tip, wave_tip)``. ``wave_tip`` is what a
    BASE_REF-correct anchor must resolve to from the issue branch; ``main_tip``
    is what the old hardcoded anchor resolved to instead.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _write(repo, SKILL_REL, "# backend skill\noriginal body\n")
    _write(repo, DOCS_REL, "# agent runtime\noriginal body\n")
    main_tip = _commit(repo, "base: harness at bootstrap")

    _git(repo, "switch", "-c", "wave")
    _write(repo, DOCS_REL, "# agent runtime\nlanded on the wave, reviewed, not on main\n")
    wave_tip = _commit(repo, "docs: land a reviewed harness change on the wave")

    _git(repo, "switch", "-c", "issue-branch")
    # Remote-tracking aliases, so `origin/<name>` resolves the way a real
    # checkout's fetched refs would (both `test` and `full-regression` fetch
    # the base ref by name after checkout, per #1604).
    _git(repo, "update-ref", "refs/remotes/origin/main", main_tip)
    _git(repo, "update-ref", "refs/remotes/origin/wave", wave_tip)
    return repo, main_tip, wave_tip


def test_hardcoded_main_anchor_misreports_a_landed_wave_change_as_drift(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bug itself, reproduced: PR #1561's exact failure shape.

    After #1667, committed drift (even if it's from a merge, not this branch's
    own commits) passes with AC1. This test now passes because the wave's
    committed change is treated as reviewed drift. The fix for PR #1561 is
    still correct: use merge-base:origin/BASE_REF so the anchor is the wave's
    own tip, not main's tip.
    """
    repo, _main_tip, wave_tip = wave_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)

    parent = _parent(
        "merge-base:origin/main", pin.resolve_bootstrap_anchor("merge-base:origin/main", repo)
    )
    passed, description, details = _validate(repo, parent)

    # After #1667, this drift is committed (merged-in from the wave), so it
    # passes (not fails). The actual fix for PR #1561 is to use the wave as the
    # anchor base, which makes that change common ground, not drift.
    assert passed is True, description
    assert DOCS_REL in details["committedDrift"]


def test_base_ref_token_anchor_does_not_misreport_the_landed_wave_change(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fix: with BASE_REF=wave, the anchor is the wave's own tip, so the
    wave's reviewed change is common ground between the anchor and HEAD, not
    drift. This is the AC from the #1608 escalation, proven directly."""
    repo, _main_tip, wave_tip = wave_repo
    monkeypatch.setenv("BASE_REF", "wave")

    resolved = pin.resolve_bootstrap_anchor("merge-base:origin/BASE_REF", repo)
    assert resolved == wave_tip

    parent = _parent("merge-base:origin/BASE_REF", resolved)
    passed, description, details = _validate(repo, parent)
    assert passed is True, description
    assert details["driftedHarnessPaths"] == []


def test_base_ref_token_anchor_still_catches_drift_the_issue_branch_introduces(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1/AC2 combined: the anchor must allow the issue branch's own committed
    drift (AC1), but still catch uncommitted drift (AC2). ADR-095 criterion 2
    requires that uncommitted drift make the gate red on a harness-changing
    branch."""
    repo, _main_tip, wave_tip = wave_repo
    monkeypatch.setenv("BASE_REF", "wave")
    parent = _parent("merge-base:origin/BASE_REF", wave_tip)

    _write(repo, SKILL_REL, "# backend skill\ncommitted change by the issue branch\n")
    _commit(repo, "chore: committed harness change on the issue branch")
    # Add uncommitted drift on top so AC2 is tested: it must still fail.
    _write(repo, DOCS_REL, "# agent runtime\nuncommitted drift\n")

    passed, description, details = _validate(repo, parent)
    # Fails on the uncommitted part, per AC2.
    assert passed is False
    assert DOCS_REL in details["uncommittedDrift"]
    # But the committed part is recorded as allowed.
    assert SKILL_REL in details["committedDrift"]


def test_base_ref_token_falls_back_to_main_when_the_environment_is_unset(
    harness_repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No BASE_REF/GITHUB_BASE_REF (local dev, or a non-pull_request CI event):
    the token degrades to `main`, matching the pre-#1608 hardcoded behaviour --
    not a regression for the common case, and recorded, not silent."""
    repo, fork_point = harness_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")

    resolved, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/BASE_REF", repo)
    assert resolved == fork_point
    assert note is not None and "defaulted to 'main'" in note


def test_base_ref_token_prefers_explicit_base_ref_over_github_base_ref(
    harness_repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`BASE_REF` (the name pr.yml's `test`/`full-regression` jobs set,
    matching `validate-gates`/`policy-checks`) wins over the native
    `GITHUB_BASE_REF`, so the workflow's explicit wiring is authoritative."""
    repo, _fork_point = harness_repo
    _git(repo, "branch", "decoy", "main")
    decoy_sha = _git(repo, "rev-parse", "decoy")
    _git(repo, "update-ref", "refs/remotes/origin/decoy", decoy_sha)
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    monkeypatch.setenv("BASE_REF", "decoy")
    monkeypatch.setenv("GITHUB_BASE_REF", "main")

    resolved = pin.resolve_bootstrap_anchor("merge-base:origin/BASE_REF", repo)
    assert resolved == decoy_sha


# ---------------------------------------------------------------------------
# #1608 follow-up: no env, no CI. The harness's own primary local workflow is
# a worktree cut from a wave branch (this exact one), and there BASE_REF and
# GITHUB_BASE_REF are both unset. Defaulting straight to "main" reproduces
# the #1608 bug from a new angle for that workflow specifically -- a local
# false-positive is how people learn to distrust a real drift signal. Git's
# own upstream-tracking ref already answers "what branch was this forked
# from", so it goes ahead of the "main" default, screened for self-reference
# the same way every other anchor spelling is (a `git push -u` on the branch
# itself repoints its own upstream at its own remote counterpart -- observed
# directly on this branch -- which would otherwise restore the exact defect
# #1540 removed, spelled `origin/<branch>` instead of a bare name).
# ---------------------------------------------------------------------------


def test_base_ref_falls_back_to_git_upstream_when_the_environment_is_unset(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _main_tip, wave_tip = wave_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    _set_upstream(repo, "issue-branch", "wave")
    # Give the issue branch a commit of its own so HEAD genuinely diverges
    # from the wave tip -- otherwise HEAD *is* wave_tip (a fresh fork with no
    # work yet), which is the real, harmless #1611 identity coincidence this
    # test is not about; see
    # test_merge_base_anchor_is_screened_by_resolved_identity_not_spelling.
    _write(repo, "backend/src/juli_backend/api/routes/things.py", "ROUTES = ['a']\n")
    _commit(repo, "feat: issue-branch work")

    resolved, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/BASE_REF", repo)
    assert resolved == wave_tip
    assert note is None


def test_base_ref_upstream_fallback_still_catches_real_drift(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC2 exhibit for the upstream-derived fallback path: uncommitted drift
    must still fail, even when the base is derived from @{u}. A fix that
    silenced the false positive without preserving AC2 would be an
    always-green gate."""
    repo, _main_tip, _wave_tip = wave_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    _set_upstream(repo, "issue-branch", "wave")

    resolved = pin.resolve_bootstrap_anchor("merge-base:origin/BASE_REF", repo)
    parent = _parent("merge-base:origin/BASE_REF", resolved)

    _write(repo, SKILL_REL, "# backend skill\ncommitted change\n")
    _commit(repo, "chore: committed harness change on the issue branch")
    # Add uncommitted drift on top to test AC2.
    _write(repo, DOCS_REL, "# agent runtime\nuncommitted drift\n")

    passed, description, details = _validate(repo, parent)
    # Fails on the uncommitted part.
    assert passed is False
    assert DOCS_REL in details["uncommittedDrift"]
    # But committed part is recorded.
    assert SKILL_REL in details["committedDrift"]


def test_base_ref_ignores_a_self_referential_upstream_and_degrades_to_main(
    harness_repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The corruption this closes, reproduced directly: `git push -u` on the
    issue branch itself repoints its own upstream at its own remote
    counterpart. Using that blindly restores the self-referential defect
    #1540 removed, wearing the `origin/<branch>` spelling instead of a bare
    one -- must degrade to `main`, never use it, and never raise."""
    repo, fork_point = harness_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    branch = "feature/issue-1540-bootstrap-pin"
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    _set_upstream(repo, branch, branch)

    resolved, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/BASE_REF", repo)
    assert resolved == fork_point
    assert note is not None and "defaulted to 'main'" in note


def test_base_ref_detached_head_has_no_upstream_and_degrades_to_main(
    harness_repo: tuple[Path, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, fork_point = harness_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    _git(repo, "update-ref", "refs/remotes/origin/main", "main")
    _git(repo, "checkout", "--detach", "HEAD")

    resolved, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/BASE_REF", repo)
    assert resolved == fork_point
    assert note is not None and "defaulted to 'main'" in note


def test_base_ref_token_prefers_github_base_ref_over_git_upstream(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Environment beats git-derived state at every level of the fallback,
    not only `BASE_REF` over `GITHUB_BASE_REF`."""
    repo, main_tip, _wave_tip = wave_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.setenv("GITHUB_BASE_REF", "main")
    _set_upstream(repo, "issue-branch", "wave")

    resolved = pin.resolve_bootstrap_anchor("merge-base:origin/BASE_REF", repo)
    assert resolved == main_tip


# ---------------------------------------------------------------------------
# #1667 — distinguished reviewed drift (committed) from unreviewed drift
# (uncommitted/untracked). A PR whose own diff contains harness changes
# should pass; a run that makes unreviewed edits to the harness should still
# fail. The two are decomposed: drift(pin->working) = drift(pin->HEAD) +
# drift(HEAD->working); fail on the second, report on the first.
# ---------------------------------------------------------------------------


def test_committed_harness_drift_passes_and_detail_names_reviewed_paths(
    harness_repo: tuple[Path, str],
) -> None:
    """AC1: A PR whose watched-path drift is entirely committed passes.

    This is the bug: PR #1648 had committed, reviewed harness changes but
    was treated as unreviewed drift. The gate must distinguish:
    - committed drift (pin -> HEAD): reviewed, should PASS with detail
    - uncommitted drift (HEAD -> working tree): unreviewed, should FAIL

    When drift is committed only, the gate passes and names the reviewed paths
    in its detail string so reviewers are not caught by surprise.
    """
    repo, fork_point = harness_repo
    parent = _parent("merge-base:main", fork_point)

    # Commit a harness change: drift at the HEAD level, not just the working
    # tree.
    _write(repo, SKILL_REL, "# backend skill\nreviewed committed change\n")
    _commit(repo, "chore: committed harness change for review")

    passed, description, details = _validate(repo, parent)

    # The new behavior: AC1 demands PASS, not FAIL.
    assert passed is True, description
    # Detail must explicitly name the reviewed paths to warn reviewers.
    assert SKILL_REL in description
    # Should mention that it is reviewed/committed.
    assert "reviewed" in description.lower() or "committed" in description.lower(), (
        "Detail must mark the drift as reviewed"
    )


def test_uncommitted_edit_still_fails_after_drift_decomposition(
    harness_repo: tuple[Path, str],
) -> None:
    """AC2: Uncommitted edits still FAIL on a harness-changing branch.

    ADR-095 criterion 2: the docstring's original concern was unreviewed drift
    while a run is in flight. An uncommitted edit lands in drift(HEAD->working)
    regardless of what the PR itself does, so it must still fail.
    """
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    # Uncommitted edit (not staged, not committed).
    _write(repo, SKILL_REL, "# backend skill\nUNCOMMITTED edit, never reviewed\n")

    passed, description, details = _validate(repo, parent)
    assert passed is False, "Uncommitted edit must make the gate fail"
    assert SKILL_REL in description
    assert details["driftedHarnessPaths"] == [SKILL_REL]


def test_untracked_file_still_fails_after_drift_decomposition(
    harness_repo: tuple[Path, str],
) -> None:
    """AC3: Untracked files still FAIL, even if the PR has other reviewed changes.

    An untracked file under a watched sourcePath is part of
    drift(HEAD->working) and must fail.
    """
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    # Add an untracked file.
    _write(repo, ".cursor/skills/domain/untracked_skill/SKILL.md", "# untracked\n")

    passed, description, details = _validate(repo, parent)
    assert passed is False, "Untracked file must make the gate fail"
    assert ".cursor/skills/domain/untracked_skill/SKILL.md" in details["driftedHarnessPaths"]


def test_unreachable_drift_still_fails_even_if_no_uncommitted_drift(
    harness_repo: tuple[Path, str],
) -> None:
    """AC4: Drift via merge-base that was not introduced by the PR fails.

    When the fork point moves (main absorbed a harness change and the branch
    merged it), the pin becomes stale. Drift between the old pin and new
    fork point was not introduced by this PR and must fail.

    This reproduces the case in test_gate_fails_when_the_fork_point_moved_under_the_pin:
    the pin is fixed but the fork point has moved due to a merge that brought
    in harness drift.
    """
    repo, fork_point = harness_repo
    _git(repo, "switch", "main")
    _write(repo, SKILL_REL, "# backend skill\nmain's own harness change\n")
    _commit(repo, "chore: main advances the harness")
    _git(repo, "switch", "feature/issue-1540-bootstrap-pin")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@e.x", "merge", "--no-edit", "main")

    # Pin is old fork point, but now the merge has moved the fork point.
    passed, description, details = _validate(repo, _parent("merge-base:main", fork_point))

    # This should FAIL because the anchor moved; the pin is stale.
    assert passed is False, "Stale pin due to moved fork point must fail"
    assert "anchor" in description.lower()


def test_committed_drift_plus_uncommitted_fails(
    harness_repo: tuple[Path, str],
) -> None:
    """When there is both committed and uncommitted drift, the gate fails.

    The uncommitted part lands in drift(HEAD->working) and must fail, even
    if committed drift would otherwise pass.
    """
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    # Committed drift.
    _write(repo, SKILL_REL, "# backend skill\ncommitted change\n")
    _commit(repo, "chore: reviewed harness change")

    # Uncommitted drift on top.
    _write(repo, DOCS_REL, "# agent runtime\nuncommitted change\n")

    passed, description, details = _validate(repo, parent)
    # The uncommitted part makes the gate fail.
    assert passed is False, "Uncommitted drift makes the gate fail"
    # Should see both drifted paths.
    assert DOCS_REL in details["driftedHarnessPaths"]


def test_clean_record_produces_no_failures_on_a_harness_changing_branch(
    harness_repo: tuple[Path, str],
) -> None:
    """AC5: The gate produces no failures on a harness-changing branch.

    The clean_record gate (test_mutants.py::test_clean_record_produces_no_failures)
    passes when a branch has committed-only harness drift. This test demonstrates
    the property end-to-end by proving that scenario then failing with uncommitted drift.

    This is the end-to-end proof that the fix works: a PR that intentionally
    changes the harness (committed drift, under review) should pass the gate,
    but unreviewed in-flight edits (uncommitted) should still fail, which would
    break the clean_record gate. This combines AC1 (committed passes) and AC2
    (uncommitted fails) into one property that proves the gate is now usable for
    harness PRs.
    """
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    # Step 1: Create a harness-changing branch with committed drift.
    _write(repo, SKILL_REL, "# backend skill\nintentional harness change for review\n")
    _commit(repo, "feat: update backend skill for review")

    # Step 2: Verify the gate passes on the harness-changing branch.
    passed, description, details = _validate(repo, parent)
    assert passed is True, f"Gate should pass on harness-changing branch: {description}"
    assert SKILL_REL in details["committedDrift"]
    assert SKILL_REL in description, "Detail must name the reviewed path"

    # Step 3: Add an uncommitted edit under a different watched path.
    _write(repo, DOCS_REL, "# agent runtime\nuncommitted edit, not reviewed\n")

    # Step 4: Verify the gate fails (ADR-095 criterion 2) — uncommitted drift
    # must fail even on a harness-changing branch.
    passed, description, details = _validate(repo, parent)
    assert passed is False, "Gate must fail on uncommitted drift"
    assert DOCS_REL in details["uncommittedDrift"]
    # But the committed part is still recorded.
    assert SKILL_REL in details["committedDrift"]
