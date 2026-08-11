"""Tests for the checkout preflight gate (agent-runtime/scripts/git/checkout_preflight.py).

This suite guards a guard, so it is deliberately paranoid about the failure mode where the
gate stops being able to fail. During development the hook imported the engine without
registering it in ``sys.modules``; ``@dataclass`` then raised ``AttributeError`` on import,
the hook's fail-open handler swallowed it, and every write was allowed with exit 0 while
the gate looked installed and healthy. ``test_hook_blocks_on_stale_checkout`` and
``test_engine_imports_cleanly_the_way_the_hook_imports_it`` exist specifically to catch
that class of silent no-op — see #948's vacuous-guard lesson.

Every test builds a real throwaway git repository in tmp_path. Nothing here touches the
working repository, runs a fetch, or reaches the network.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = REPO_ROOT / "agent-runtime" / "scripts" / "git" / "checkout_preflight.py"
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "checkout_preflight_gate.py"


def load_module(path: Path, name: str):
    """Import a standalone script the same way the hook does — sys.modules first."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def engine():
    return load_module(ENGINE_PATH, "checkout_preflight_under_test")


def run_git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def commit(repo: Path, filename: str, body: str) -> str:
    (repo / filename).write_text(body)
    run_git(repo, "add", filename)
    run_git(repo, "commit", "-m", f"add {filename}", "--no-gpg-sign")
    return run_git(repo, "rev-parse", "HEAD")


@pytest.fixture
def origin_and_clone(tmp_path: Path) -> tuple[Path, Path]:
    """A bare 'origin' with a main branch, plus a clone whose primary tree is on main."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    run_git(seed, "init", "-q", "-b", "main")
    run_git(seed, "config", "user.email", "t@example.com")
    run_git(seed, "config", "user.name", "T")
    commit(seed, "README.md", "seed\n")
    run_git(seed, "clone", "-q", "--bare", str(seed), str(origin))

    clone = tmp_path / "clone"
    run_git(tmp_path, "clone", "-q", str(origin), str(clone))
    run_git(clone, "config", "user.email", "t@example.com")
    run_git(clone, "config", "user.name", "T")
    return origin, clone


def find(findings, check: str):
    match = [f for f in findings if f.check == check]
    assert match, f"no finding named {check} in {[f.check for f in findings]}"
    return match[0]


# ----------------------------------------------------------------------------- happy path


def test_fresh_checkout_on_main_is_clean(engine, origin_and_clone):
    _, clone = origin_and_clone
    findings = engine.run_checks(clone)
    assert find(findings, "STALE_BASE").severity == engine.OK
    assert find(findings, "PRIMARY_TREE").severity == engine.OK
    assert find(findings, "MAIN_LOCATION").severity == engine.OK
    assert find(findings, "WORKTREE_LOCATION").severity == engine.OK
    assert find(findings, "NESTED_CLONE").severity == engine.OK
    assert engine.worst(findings) != engine.FAIL


# --------------------------------------------------------------------------- STALE_BASE


def test_stale_base_fails_past_the_commit_threshold(engine, origin_and_clone):
    """The historical incident was 90 commits / 8.5 days behind origin/main."""
    origin, clone = origin_and_clone
    upstream = clone.parent / "upstream"
    run_git(clone.parent, "clone", "-q", str(origin), str(upstream))
    run_git(upstream, "config", "user.email", "t@example.com")
    run_git(upstream, "config", "user.name", "T")
    for i in range(engine.BEHIND_FAIL + 1):
        commit(upstream, f"f{i}.txt", f"{i}\n")
    run_git(upstream, "push", "-q", "origin", "main")

    run_git(clone, "fetch", "-q", "origin")
    finding = engine.check_stale_base(clone, "main")
    assert finding.severity == engine.FAIL
    assert finding.data["behind"] >= engine.BEHIND_FAIL
    assert finding.remedy, "a blocking finding must tell the agent what to do"


def test_stale_base_warns_in_the_middle_band(engine, origin_and_clone):
    origin, clone = origin_and_clone
    upstream = clone.parent / "upstream"
    run_git(clone.parent, "clone", "-q", str(origin), str(upstream))
    run_git(upstream, "config", "user.email", "t@example.com")
    run_git(upstream, "config", "user.name", "T")
    for i in range(engine.BEHIND_WARN + 1):
        commit(upstream, f"f{i}.txt", f"{i}\n")
    run_git(upstream, "push", "-q", "origin", "main")

    run_git(clone, "fetch", "-q", "origin")
    finding = engine.check_stale_base(clone, "main")
    assert finding.severity == engine.WARN


# ------------------------------------------------------------------------- MAIN_LOCATION


def test_main_checked_out_in_a_side_worktree_fails(engine, origin_and_clone):
    """The condition that stranded the primary tree: git refuses to check out a branch
    another worktree already holds, so the primary is stuck wherever it last was."""
    _, clone = origin_and_clone
    run_git(clone, "checkout", "-q", "-b", "feature/x")
    side = clone / ".worktrees" / "holds-main"
    run_git(clone, "worktree", "add", "-q", str(side), "main")

    trees = engine.list_worktrees(clone)
    finding = engine.check_main_location(clone, trees)
    assert finding.severity == engine.FAIL
    assert "side worktree" in finding.headline


# --------------------------------------------------------------------- WORKTREE_LOCATION


def test_worktree_outside_the_pool_fails(engine, origin_and_clone):
    """rev-issue-722 / rev-issue-724 were parked at the repo root, where every tree walk
    reads them as project source at whatever commit they were abandoned on."""
    _, clone = origin_and_clone
    run_git(clone, "worktree", "add", "-q", "--detach", str(clone / "rev-issue-999"))

    trees = engine.list_worktrees(clone)
    finding = engine.check_worktree_location(clone, trees)
    assert finding.severity == engine.FAIL
    assert "rev-issue-999" in finding.data["misplaced"]


def test_worktree_inside_the_pool_passes(engine, origin_and_clone):
    _, clone = origin_and_clone
    run_git(clone, "worktree", "add", "-q", "--detach", str(clone / ".worktrees" / "task"))

    trees = engine.list_worktrees(clone)
    assert engine.check_worktree_location(clone, trees).severity == engine.OK


# ---------------------------------------------------------------------------- other checks


def test_nested_clone_is_detected_but_a_linked_worktree_is_not(engine, origin_and_clone):
    """A stray clone has a .git *directory*; a linked worktree has a .git *file*.
    Conflating the two would make this check fire on every legitimate worktree."""
    _, clone = origin_and_clone
    run_git(clone, "worktree", "add", "-q", "--detach", str(clone / ".worktrees" / "legit"))
    trees = engine.list_worktrees(clone)
    assert engine.check_nested_clones(clone, trees).severity == engine.OK

    stray = clone / "vendored"
    stray.mkdir()
    run_git(stray, "init", "-q", "-b", "main")
    finding = engine.check_nested_clones(clone, trees)
    assert finding.severity == engine.FAIL
    assert "vendored" in finding.data["clones"]


def test_dirty_tree_warns_but_never_blocks(engine, origin_and_clone):
    """Uncommitted work is a smell, not a reason to refuse a write."""
    _, clone = origin_and_clone
    for i in range(engine.DIRTY_WARN + 2):
        (clone / f"dirty{i}.txt").write_text("x\n")
    finding = engine.check_dirty(clone)
    assert finding.severity == engine.WARN
    assert "DIRTY_TREE" not in engine.BLOCKING_CHECKS


def test_blocking_checks_are_a_subset_of_emitted_checks(engine, origin_and_clone):
    """A typo in BLOCKING_CHECKS would silently disarm the gate."""
    _, clone = origin_and_clone
    emitted = {f.check for f in engine.run_checks(clone)}
    assert engine.BLOCKING_CHECKS <= emitted


# ------------------------------------------------------------------------------- the hook


def test_engine_imports_cleanly_the_way_the_hook_imports_it():
    """Regression: importing via spec_from_file_location without registering the module in
    sys.modules made @dataclass raise, which the hook's fail-open handler swallowed."""
    module = load_module(ENGINE_PATH, "checkout_preflight_import_probe")
    assert hasattr(module, "run_checks")
    assert hasattr(module, "BLOCKING_CHECKS")


def invoke_hook(cwd: Path, file_path: Path, env_extra: dict | None = None):
    payload = json.dumps(
        {
            "tool_name": "Edit",
            "cwd": str(cwd),
            "tool_input": {"file_path": str(file_path)},
        }
    )
    import os

    env = {**os.environ, "TMPDIR": str(cwd.parent / "hookcache")}
    (cwd.parent / "hookcache").mkdir(exist_ok=True)
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
    )


def test_hook_blocks_on_a_failing_checkout(origin_and_clone):
    """The end-to-end assertion that the gate can actually say no."""
    _, clone = origin_and_clone
    (clone / "agent-runtime" / "scripts" / "git").mkdir(parents=True)
    (clone / "agent-runtime" / "scripts" / "git" / "checkout_preflight.py").write_text(
        ENGINE_PATH.read_text()
    )
    run_git(clone, "worktree", "add", "-q", "--detach", str(clone / "rev-issue-999"))

    result = invoke_hook(clone, clone / "README.md")
    assert result.returncode == 2, f"gate allowed a write it should have blocked: {result.stderr}"
    assert "WORKTREE_LOCATION" in result.stderr
    assert "JULI_SKIP_CHECKOUT_PREFLIGHT" in result.stderr, "must document its own override"


def test_hook_allows_when_the_escape_hatch_is_set(origin_and_clone):
    _, clone = origin_and_clone
    (clone / "agent-runtime" / "scripts" / "git").mkdir(parents=True)
    (clone / "agent-runtime" / "scripts" / "git" / "checkout_preflight.py").write_text(
        ENGINE_PATH.read_text()
    )
    run_git(clone, "worktree", "add", "-q", "--detach", str(clone / "rev-issue-999"))

    result = invoke_hook(clone, clone / "README.md", {"JULI_SKIP_CHECKOUT_PREFLIGHT": "1"})
    assert result.returncode == 0


def test_hook_allows_a_healthy_checkout(origin_and_clone):
    _, clone = origin_and_clone
    (clone / "agent-runtime" / "scripts" / "git").mkdir(parents=True)
    (clone / "agent-runtime" / "scripts" / "git" / "checkout_preflight.py").write_text(
        ENGINE_PATH.read_text()
    )
    result = invoke_hook(clone, clone / "README.md")
    assert result.returncode == 0, result.stderr


def test_hook_fails_open_when_the_engine_is_missing(origin_and_clone):
    """A partial checkout or an old branch must not become unwritable."""
    _, clone = origin_and_clone
    result = invoke_hook(clone, clone / "README.md")
    assert result.returncode == 0


def test_hook_ignores_edits_outside_the_repo(origin_and_clone, tmp_path):
    _, clone = origin_and_clone
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x")
    assert invoke_hook(clone, outside).returncode == 0
