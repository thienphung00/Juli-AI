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

    Anchoring to the branch tip and regenerating the cache would make every
    change made before *now* invisible — clearing a red by editing gate
    configuration, which is precisely what lock 6 forbids.
    """
    repo, fork_point = harness_repo
    _write(repo, SKILL_REL, "# backend skill\nreal committed harness drift\n")
    _commit(repo, "chore: drift the harness")

    # The correct anchor bites.
    passed, description, _ = _validate(repo, _parent("merge-base:main", fork_point))
    assert passed is False
    assert SKILL_REL in description

    # And no self-referential re-pin can un-bite it, at write time or read time.
    for spec in ("merge-base:HEAD", "feature/issue-1540-bootstrap-pin"):
        with pytest.raises(RuntimeError):
            pin.bootstrap_ref_from_git(spec, repo)
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


def test_gate_fails_when_cursor_skills_drift_in_a_commit(
    harness_repo: tuple[Path, str],
) -> None:
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, SKILL_REL, "# backend skill\nEDITED under the run\n")
    _commit(repo, "chore: quietly edit the harness")

    passed, description, details = _validate(repo, parent)
    assert passed is False
    assert SKILL_REL in description
    assert details["driftedHarnessPaths"] == [SKILL_REL]


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


def test_gate_fails_when_agent_runtime_docs_drift(harness_repo: tuple[Path, str]) -> None:
    """Every configured bootstrap sourcePath is watched, not only ``.cursor/skills``."""
    repo, _ = harness_repo
    parent = _parent("merge-base:main", pin.resolve_bootstrap_anchor("merge-base:main", repo))

    _write(repo, DOCS_REL, "# agent runtime\nEDITED\n")
    _commit(repo, "docs: quietly edit the runtime doc")

    passed, description, details = _validate(repo, parent)
    assert passed is False
    assert details["driftedHarnessPaths"] == [DOCS_REL]


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
    """The bug itself, reproduced: PR #1561's exact failure shape."""
    repo, _main_tip, _wave_tip = wave_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)

    parent = _parent(
        "merge-base:origin/main", pin.resolve_bootstrap_anchor("merge-base:origin/main", repo)
    )
    passed, description, details = _validate(repo, parent)

    assert passed is False
    assert DOCS_REL in details["driftedHarnessPaths"]
    assert "Harness drift" in description


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
    """ADR-092 criterion 2, exhibited: the corrected anchor must still bite on
    real drift the issue branch itself introduces on top of the wave. A fix
    that only silenced the false positive, without preserving this, would turn
    the gate always-green -- strictly worse than the bug it replaces."""
    repo, _main_tip, wave_tip = wave_repo
    monkeypatch.setenv("BASE_REF", "wave")
    parent = _parent("merge-base:origin/BASE_REF", wave_tip)

    _write(repo, SKILL_REL, "# backend skill\nEDITED by the issue branch itself\n")
    _commit(repo, "chore: quietly edit the harness on the issue branch")

    passed, description, details = _validate(repo, parent)
    assert passed is False
    assert SKILL_REL in details["driftedHarnessPaths"]
    assert "Harness drift" in description


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

    resolved, note = pin.resolve_bootstrap_anchor_with_note("merge-base:origin/BASE_REF", repo)
    assert resolved == wave_tip
    assert note is None


def test_base_ref_upstream_fallback_still_catches_real_drift(
    wave_repo: tuple[Path, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lock-6 exhibit, for the upstream-derived path specifically: a fix
    that only silenced the no-env false positive, without preserving this,
    would be an always-green gate for every local run."""
    repo, _main_tip, _wave_tip = wave_repo
    monkeypatch.delenv("BASE_REF", raising=False)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    _set_upstream(repo, "issue-branch", "wave")

    resolved = pin.resolve_bootstrap_anchor("merge-base:origin/BASE_REF", repo)
    parent = _parent("merge-base:origin/BASE_REF", resolved)

    _write(repo, SKILL_REL, "# backend skill\nEDITED by the issue branch itself\n")
    _commit(repo, "chore: quietly edit the harness on the issue branch")

    passed, description, details = _validate(repo, parent)
    assert passed is False
    assert SKILL_REL in details["driftedHarnessPaths"]
    assert "Harness drift" in description


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
