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
import tarfile
import tempfile
from pathlib import Path
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
    """
    return entry.split("::", 1)[0].strip()


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
            if not path or not _is_test_path(path):
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


def resolve_base_sha(repo_root: Path, upstream: str = "origin/main") -> str | None:
    """Return the merge-base of HEAD and ``upstream``, or None if unavailable."""
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
    for probe in probes:
        source = head_root / probe
        if not source.is_file():
            continue
        target = base_tree / probe
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
