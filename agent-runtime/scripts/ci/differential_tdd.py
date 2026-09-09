"""Mechanical red→green verification for implementation artifacts.

The predecessor gate (``check_implementation_tdd_evidence``) accepts an
``exitCode`` the Executor typed into the artifact by hand. Nothing re-runs the
command, so narration satisfies it — #1318 shipped with no ``failingTestEvidence``
key at all and still PASSed, and #1337 shipped prose with zero ``commands``.

This module measures the same property instead of reading a claim about it:

    red   — the probe tests fail against the *base* source
    green — the probe tests pass against the *head* source

A test that passes at base did not discriminate the change (``assert True`` is
the degenerate case), and is reported as such rather than counted as evidence.

The base tree is materialised with ``git archive`` into a temp directory, so no
worktree is registered and the caller's checkout is never mutated.

Canonical ``testsAdded``/``testsUpdated`` format
------------------------------------------------
Pytest **node ids** — ``tests/unit/test_x.py::test_y``. That is what the
Executor contract asks for and what real artifacts contain. A bare file path
remains valid; every reader of the field must accept both. ``implementation_tdd
.tests_added_or_updated`` only counts entries and so is format-agnostic
already; this module's :func:`select_probe_tests` resolves a node id to its
file via :func:`node_id_to_path`. Before #1498 it did not, dropped every node
id, and the gate reported "nothing to probe" instead of judging anything.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable

VERDICT_RED_GREEN = "red_green"
VERDICT_NO_DISCRIMINATION = "no_discrimination"
VERDICT_STILL_FAILING = "still_failing"
VERDICT_INCONCLUSIVE = "inconclusive"
# Distinct from every verdict above on purpose: nothing was executed, so there
# is no measurement to report. Conflating "we probed and found no
# discrimination" with "we never probed" is precisely how this gate hid — the
# second reads as "the gate had no opinion" and got waved through. Both fail.
VERDICT_NOTHING_TO_PROBE = "nothing_to_probe"

PASSING_VERDICTS = frozenset({VERDICT_RED_GREEN})

_PY_TEST_SUFFIXES = (".py",)
_JS_TEST_MARKERS = (".test.ts", ".test.tsx", ".test.js", ".spec.ts", ".spec.tsx", ".spec.js")


def _is_test_path(path: str) -> bool:
    """Whether a repo-relative path denotes a test file.

    Deliberately conservative: a source file mistakenly listed under
    ``testsAdded`` must not become a probe, or the gate would run production
    code as if it were a test and read the result as evidence.
    """
    normalised = path.replace("\\", "/")
    name = normalised.rsplit("/", 1)[-1]

    if any(name.endswith(marker) for marker in _JS_TEST_MARKERS):
        return True

    if name.endswith(_PY_TEST_SUFFIXES) and (name.startswith("test_") or name.endswith("_test.py")):
        return True

    return False


def node_id_to_path(entry: str) -> str:
    """Return the file part of a pytest node id; a bare path is returned as-is.

    ``tests/unit/test_x.py::test_y`` and ``tests/unit/test_x.py::test_y[a::b]``
    both yield ``tests/unit/test_x.py`` — split on the *first* separator so a
    parametrisation id containing ``::`` cannot truncate the path.

    Separators are normalised to ``/`` so this agrees with :func:`_is_test_path`,
    which already normalises. Without that they disagreed: a backslash entry was
    accepted as a probe and then could never be located on disk, so the gate
    failed with "no probe files exist at head" instead of naming the real cause.
    """
    return entry.split("::", 1)[0].strip().replace("\\", "/")


def is_repo_relative(path: str) -> bool:
    """Whether ``path`` stays inside the tree it is resolved against.

    The probe list comes from an artifact the graded agent writes, and every
    probe is both copied across trees by :func:`overlay_probes` and handed to
    pytest as an argument. An entry like ``../../OUTSIDE/test_evil.py`` clears
    :func:`_is_test_path` — the basename is ``test_evil.py`` — so without this
    guard the gate copies a file to, and then executes it from, a location
    outside both trees. Reject anything absolute, anchored, or containing a
    ``..`` segment; a probe must name a file in the repository under test.
    """
    if not path:
        return False
    normalised = path.replace("\\", "/")
    if normalised.startswith("/") or PurePosixPath(normalised).is_absolute():
        return False
    # A Windows drive or UNC anchor ("C:/x", "//host/share") is not repo-relative.
    if PureWindowsPath(path).anchor:
        return False
    return ".." not in normalised.split("/")


def declared_test_entries(artifact: Any) -> list[str]:
    """Every string entry the artifact lists under testsAdded/testsUpdated.

    Format-agnostic and unfiltered: this answers "did the Executor claim any
    tests at all", which is a different question from "which of those can we
    probe". The gate needs both to keep its two failure modes apart.
    """
    if not isinstance(artifact, dict):
        return []

    entries: list[str] = []
    for field in ("testsAdded", "testsUpdated"):
        value = artifact.get(field)
        if not isinstance(value, list):
            continue
        entries.extend(item for item in value if isinstance(item, str) and item.strip())
    return entries


def select_probe_tests(artifact: Any) -> list[str]:
    """Return the ordered, de-duplicated test files this change added or updated.

    **Canonical format.** ``testsAdded``/``testsUpdated`` hold pytest *node ids*
    (``tests/unit/test_x.py::test_y``) — that is what the Executor prompt and
    ``docs/benchmarks/task-type-b-bug-fix.md`` ask for, and what artifacts in
    the wild actually contain. A bare file path stays valid and is accepted
    unchanged, so both readers of the field agree. Before #1498 this selector
    required the *whole* entry to end in ``.py``, so every node id was dropped
    and the gate reported "nothing to probe" for changes that had real
    discriminating tests — it passed by never looking.

    Added tests come first, then updated ones; de-duplication is on the
    resolved file, so two node ids in one file yield one probe. Non-test paths
    and malformed entries are dropped rather than raising — a bad artifact
    yields no probes, which the gate treats as nothing-to-probe and fails
    closed on, never as a pass.
    """
    if not isinstance(artifact, dict):
        return []

    probes: list[str] = []
    seen: set[str] = set()

    for field in ("testsAdded", "testsUpdated"):
        entries = artifact.get(field)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, str):
                continue
            path = node_id_to_path(entry)
            if not is_repo_relative(path) or not _is_test_path(path):
                continue
            if path in seen:
                continue
            seen.add(path)
            probes.append(path)

    return probes


def classify_probe(base_exit: int | None, head_exit: int | None) -> tuple[str, str]:
    """Classify one differential run into a verdict and a human-readable reason.

    ``base_exit`` is ``None`` when the base tree could not be materialised or the
    probe could not be executed there — that is inconclusive, never a pass.
    """
    if head_exit is None:
        return (
            VERDICT_INCONCLUSIVE,
            "probe could not be executed against head source",
        )

    if head_exit != 0:
        return (
            VERDICT_STILL_FAILING,
            f"probe fails against head source (exit {head_exit}) — the change does not make it pass",
        )

    if base_exit is None:
        return (
            VERDICT_INCONCLUSIVE,
            "probe could not be executed against base source — red step unproven",
        )

    if base_exit == 0:
        return (
            VERDICT_NO_DISCRIMINATION,
            "probe already passes against base source — it does not discriminate this change",
        )

    return (
        VERDICT_RED_GREEN,
        f"probe fails against base source (exit {base_exit}) and passes against head",
    )


# --- base-tree materialisation -----------------------------------------


def base_ref_name() -> str:
    """This run's integration base, as a short ref name (``BASE_REF``, default ``main``).

    Re-exports ``checkout_preflight.base_ref_name`` rather than re-deriving it --
    #1608 fixed this for the bootstrap anchor and #1731 for ``check_stale_base``;
    this is the third gate with the identical hardcoded-``origin/main`` defect
    (#1842), so it reuses the one helper instead of writing a fourth copy.
    Imported lazily so this module never pays a module-level ``sys.path``
    mutation, and every caller (including this one) resolves fresh per call.
    """
    git_scripts_dir = Path(__file__).resolve().parents[1] / "git"
    if str(git_scripts_dir) not in sys.path:
        sys.path.insert(0, str(git_scripts_dir))
    from checkout_preflight import base_ref_name as _base_ref_name

    return _base_ref_name()


def resolve_base_sha(repo_root: Path, upstream: str | None = None) -> str | None:
    """Return the merge-base of HEAD and ``upstream``, or None if unavailable.

    ``upstream`` defaults to ``origin/{base_ref_name()}`` -- this run's actual
    integration base, read from ``BASE_REF`` (``main`` when unset) -- rather
    than a hardcoded ``origin/main``. At issue tier the real base is a wave
    branch; resolving against a hardcoded ``main`` measures red/green against
    a tree that is not this PR's starting point (#1842, following #1608 and
    #1731's identical fix in the bootstrap anchor and ``check_stale_base``).
    Computed per call, not cached at import, so a caller that changes
    ``BASE_REF`` mid-process (as tests do) is honoured.
    """
    if upstream is None:
        upstream = f"origin/{base_ref_name()}"
    result = subprocess.run(
        ["git", "-C", str(repo_root), "merge-base", "HEAD", upstream],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None


def materialize_base_tree(repo_root: Path, base_sha: str, dest: Path) -> bool:
    """Extract ``base_sha`` into ``dest`` via git archive. Returns success.

    Uses git archive rather than ``git worktree add`` so nothing is registered in
    the worktree pool and the caller's checkout is never touched.
    """
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".tar", delete=False) as handle:
        archive_path = Path(handle.name)
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "archive",
                "--format=tar",
                "-o",
                str(archive_path),
                base_sha,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return False
        with tarfile.open(archive_path) as tar:
            tar.extractall(dest, filter="data")
        return True
    finally:
        archive_path.unlink(missing_ok=True)


def overlay_probes(head_root: Path, base_tree: Path, probes: Iterable[str]) -> list[str]:
    """Copy head's probe files over the base tree; return those copied.

    This is what makes the red step meaningful: the *new* tests are run against
    the *old* source. A probe that does not exist at head is skipped.
    """
    copied: list[str] = []
    head_resolved = head_root.resolve()
    base_resolved = base_tree.resolve()
    for probe in probes:
        # Defence in depth: select_probe_tests already rejects non-repo-relative
        # entries, but this function is public and the cost of being wrong here
        # is a write outside the temp tree. Re-check rather than assume.
        if not is_repo_relative(probe):
            continue
        source = head_root / probe
        if not source.is_file():
            continue
        if not source.resolve().is_relative_to(head_resolved):
            continue
        target = base_tree / probe
        if not target.resolve().parent.is_relative_to(base_resolved):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
        copied.append(probe)
    return copied


def run_python_probes(
    tree_root: Path, probes: Iterable[str], python_executable: str
) -> tuple[int | None, str]:
    """Run the python probes inside ``tree_root``; return (exit code, tail of output).

    PYTHONPATH is pinned to this tree's ``backend/src`` so the run cannot silently
    import the package from another checkout — an editable-install ``.pth`` in the
    ambient venv otherwise wins and the result describes the wrong source.
    """
    targets = [p for p in probes if p.endswith(".py")]
    if not targets:
        return None, "no python probes to run"

    env = dict(os.environ)
    env["PYTHONPATH"] = str(tree_root / "backend" / "src")
    env.pop("COV_CORE_SOURCE", None)

    result = subprocess.run(
        [
            python_executable,
            "-m",
            "pytest",
            *targets,
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(tree_root),
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output[-4000:]
