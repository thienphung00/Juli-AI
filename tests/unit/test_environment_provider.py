"""Tests for the ``environment`` capture provider (#1442, HE-B/P-EVAL-7).

Every test here plants a lie the harness has actually been told before and
asserts the provider catches it, because a happy-path fingerprint is worth
nothing: the defect class this slice exists to close is an environment fact
that *looked* fine in the record while the run was executing against the wrong
code.

The three lies, each drawn from a real session:

1. A base 17 commits behind ``origin/main`` (below ``checkout_preflight``'s
   >=50 threshold) broke ~61 tests through an Alembic ``ResolutionError`` that
   was read as a code defect. The fingerprint must publish the distance.
2. A shallow CI checkout makes ``git rev-list --count HEAD..origin/main``
   answer with a number that means nothing. The fingerprint must refuse to
   publish that number rather than record a confident zero.
3. One editable ``.pth`` decides where ``juli_backend`` resolves; a resolution
   into a *different* worktree reads downstream as an ordinary assertion
   failure. That one is fatal, not recorded.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "agent-runtime" / "scripts" / "ci"


def _load_seam():
    """Import the capture seam, which lives outside any importable package root.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    the module-level imports needs two ``# noqa: E402`` suppressions, and the
    repo's debt ratchet (#1462) counts suppression identities. Paying two units
    of tracked debt for import cosmetics is a bad trade.
    """
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    import capture_providers
    from capture_providers import environment

    return capture_providers, environment


capture_providers, env = _load_seam()


def _fake_git(answers: dict[tuple[str, ...], str]):
    """A git runner that answers only what it is told to, ``None`` otherwise.

    ``None`` is what the real runner returns for a failing command, so an
    unlisted invocation exercises the same branch a missing ``origin/main``
    would.
    """

    def run(*args: str) -> str | None:
        return answers.get(tuple(args))

    return run


def _plant_worktree(tmp_path: Path, name: str) -> tuple[Path, Path]:
    root = tmp_path / name
    package = root / "backend" / "src" / "juli_backend"
    package.mkdir(parents=True)
    module_file = package / "__init__.py"
    module_file.write_text("", encoding="utf-8")
    return root, module_file


def _context(issue: int = 1442) -> capture_providers.CaptureContext:
    return capture_providers.CaptureContext(
        issue=issue,
        review={"status": "PASS"},
        validation={"status": "PASS"},
        review_bytes=b"{}",
        validation_bytes=b"{}",
    )


# --- AC1 ------------------------------------------------------------------


def test_fingerprint_records_resolution_and_base_distance(tmp_path: Path) -> None:
    root, module_file = _plant_worktree(tmp_path, "w2-1442")

    # Lie 1: the base is 17 commits behind origin/main -- invisible to
    # checkout_preflight, and the record must say so out loud.
    behind = _fake_git(
        {
            ("rev-parse", "--is-shallow-repository"): "false",
            ("rev-parse", "HEAD"): "d" * 40,
            ("rev-parse", "--abbrev-ref", "HEAD"): "feature/issue-1442-env-fingerprint",
            ("rev-list", "--count", "HEAD..origin/main"): "17",
        }
    )

    fingerprint = env.fingerprint(
        repo_root=root,
        module_file=module_file,
        git=behind,
        constraints_text="alembic==1.19.1\n",
        installed_versions={"alembic": "1.19.1"},
        cwd=root,
    )

    assert fingerprint["moduleResolution"]["resolved"] == str(module_file)
    assert fingerprint["moduleResolution"]["insideRepo"] is True
    assert fingerprint["moduleResolution"]["expectedPrefix"] == str(
        root / "backend" / "src" / "juli_backend"
    )
    assert fingerprint["cwd"] == str(root)
    assert fingerprint["repoRoot"] == str(root)
    assert fingerprint["git"]["head"] == "d" * 40
    assert fingerprint["git"]["branch"] == "feature/issue-1442-env-fingerprint"
    assert fingerprint["git"]["shallow"] is False
    # The number itself, not a boolean "is it stale" -- 17 is the fact that was
    # missing from every one of those eight sessions.
    assert fingerprint["git"]["behindOriginMain"] == 17
    assert fingerprint["git"]["baseDistanceUnavailable"] is None
    assert fingerprint["python"] == sys.version.split()[0]

    # Lie 2: a shallow checkout, where the same rev-list happily answers "0".
    # Recording that 0 would assert a fresh base that was never observed.
    shallow = _fake_git(
        {
            ("rev-parse", "--is-shallow-repository"): "true",
            ("rev-parse", "HEAD"): "e" * 40,
            ("rev-parse", "--abbrev-ref", "HEAD"): "HEAD",
            ("rev-list", "--count", "HEAD..origin/main"): "0",
        }
    )
    shallow_fingerprint = env.fingerprint(
        repo_root=root,
        module_file=module_file,
        git=shallow,
        constraints_text="",
        installed_versions={},
        cwd=root,
    )
    assert shallow_fingerprint["git"]["shallow"] is True
    assert shallow_fingerprint["git"]["behindOriginMain"] is None
    assert shallow_fingerprint["git"]["baseDistanceUnavailable"] == "shallow-clone"

    # Lie 3: origin/main is simply absent (an unfetched remote). Same rule --
    # say why the number is missing instead of inventing one.
    no_remote = _fake_git(
        {
            ("rev-parse", "--is-shallow-repository"): "false",
            ("rev-parse", "HEAD"): "f" * 40,
            ("rev-parse", "--abbrev-ref", "HEAD"): "main",
        }
    )
    detached = env.fingerprint(
        repo_root=root,
        module_file=module_file,
        git=no_remote,
        constraints_text="",
        installed_versions={},
        cwd=root,
    )
    assert detached["git"]["behindOriginMain"] is None
    assert detached["git"]["baseDistanceUnavailable"] == "no-origin-main"


# --- AC2 ------------------------------------------------------------------


def test_module_resolved_outside_worktree_fails(tmp_path: Path) -> None:
    root, _ = _plant_worktree(tmp_path, "w2-1442")
    _, foreign_module = _plant_worktree(tmp_path, "w2-1445")

    git = _fake_git(
        {
            ("rev-parse", "--is-shallow-repository"): "false",
            ("rev-parse", "HEAD"): "a" * 40,
            ("rev-parse", "--abbrev-ref", "HEAD"): "feature/issue-1442-env-fingerprint",
            ("rev-list", "--count", "HEAD..origin/main"): "0",
        }
    )

    with pytest.raises(env.EnvironmentDriftError) as excinfo:
        env.fingerprint(
            repo_root=root,
            module_file=foreign_module,
            git=git,
            constraints_text="",
            installed_versions={},
            cwd=root,
        )

    message = str(excinfo.value)
    assert str(foreign_module) in message, "the resolved path must be named"
    assert str(root / "backend" / "src" / "juli_backend") in message, (
        "the expected path must be named alongside it"
    )


def test_module_resolved_outside_worktree_fails_through_the_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same lie, told through the seam the record generator actually uses."""
    root, _ = _plant_worktree(tmp_path, "w2-1442")
    _, foreign_module = _plant_worktree(tmp_path, "w2-1445")

    monkeypatch.setattr(env, "_repo_root", lambda: root)
    monkeypatch.setattr(env, "_resolve_module_file", lambda: foreign_module)

    with capture_providers.provider_sandbox():
        capture_providers.register_provider(env.PROVIDER_NAME, env.capture, replace=True)
        with pytest.raises(capture_providers.CaptureProviderError) as excinfo:
            capture_providers.capture_run_block(_context())

    assert excinfo.value.provider == "environment"
    assert str(foreign_module) in str(excinfo.value)


def test_unresolvable_module_is_recorded_with_its_error_not_silently_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The non-fatal branch, which is the one that could rot into a silent pass.

    A lookup that fails is deliberately *not* fatal, so that record generation
    works in an interpreter without the backend installed. The lie planted here
    is the one that failure mode would tell if it were sloppy: a record that
    simply omits the resolution and reads as "nothing to report".
    """
    root, _ = _plant_worktree(tmp_path, "w2-1442")

    def explode() -> Path | None:
        raise ImportError("No module named 'juli_backend'")

    monkeypatch.setattr(env, "_resolve_module_file", explode)

    fingerprint = env.fingerprint(
        repo_root=root,
        git=_fake_git({("rev-parse", "--is-shallow-repository"): "false"}),
        constraints_text="",
        installed_versions={},
        cwd=root,
    )

    resolution = fingerprint["moduleResolution"]
    assert resolution["resolved"] is None
    assert resolution["insideRepo"] is False
    # Absent must never be readable as fine: the reason is carried verbatim.
    assert resolution["error"] == "ImportError: No module named 'juli_backend'"
    assert resolution["expectedPrefix"] == str(root / "backend" / "src" / "juli_backend")


# --- AC3 ------------------------------------------------------------------


def test_dependency_drift_is_recorded(tmp_path: Path) -> None:
    root, module_file = _plant_worktree(tmp_path, "w2-1442")

    constraints_text = textwrap.dedent(
        """\
        # a comment line, and a pip-compile provenance continuation below
        alembic==1.19.1
            # via juli-backend (pyproject.toml)
        fastapi==0.128.0
            # via juli-backend (pyproject.toml)
        SQLAlchemy==2.0.43
        ghost-pkg==1.0.0
        """
    )
    # Lie: fastapi is the #921 drift exactly -- pinned 0.128.0, installed
    # 0.141.1, a pair that once made a security-invariant test pass vacuously.
    installed = {"alembic": "1.19.1", "fastapi": "0.141.1", "sqlalchemy": "2.0.43"}

    fingerprint = env.fingerprint(
        repo_root=root,
        module_file=module_file,
        git=_fake_git({("rev-parse", "--is-shallow-repository"): "false"}),
        constraints_text=constraints_text,
        installed_versions=installed,
        cwd=root,
    )
    dependencies = fingerprint["dependencies"]

    assert dependencies["pinned"] == 4
    # Both versions, not a boolean -- "drifted" without the pair is unactionable.
    assert dependencies["drift"] == [
        {"package": "fastapi", "pinned": "0.128.0", "installed": "0.141.1"}
    ]
    # `SQLAlchemy` pinned vs `sqlalchemy` installed is the same distribution;
    # manufacturing drift out of PEP 503 naming would train agents to ignore
    # this block entirely.
    assert dependencies["missing"] == ["ghost-pkg"]
    assert dependencies["matched"] == 2


def test_dependency_block_is_clean_when_nothing_drifted(tmp_path: Path) -> None:
    root, module_file = _plant_worktree(tmp_path, "w2-1442")

    fingerprint = env.fingerprint(
        repo_root=root,
        module_file=module_file,
        git=_fake_git({("rev-parse", "--is-shallow-repository"): "false"}),
        constraints_text="alembic==1.19.1\nfastapi==0.128.0\n",
        installed_versions={"alembic": "1.19.1", "fastapi": "0.128.0"},
        cwd=root,
    )

    assert fingerprint["dependencies"]["drift"] == []
    assert fingerprint["dependencies"]["missing"] == []
    assert fingerprint["dependencies"]["matched"] == 2


# --- the seam ------------------------------------------------------------


def test_provider_is_discovered_and_capturable_without_touching_the_generator() -> None:
    """DoD 3: dropping the module in the package is the whole registration."""
    with capture_providers.provider_sandbox():
        discovered = capture_providers.discover_providers()
        assert "environment" in discovered
        run = capture_providers.capture_run_block(_context())

    block = run["environment"]
    assert set(block) >= {"python", "cwd", "repoRoot", "moduleResolution", "git", "dependencies"}
    # Against the real repo, read live: the constraints file has real pins.
    assert block["dependencies"]["pinned"] > 0
    assert block["repoRoot"] == str(REPO_ROOT)
