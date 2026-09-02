"""Capture provider (#1443): did the commands the artifact cites actually run?

The committed mutant table in ``eval/results/gate_operator_scores.md`` scored all
29 gates against seven planted-defect operators. Two operators —
``narrowed_command_scope`` and ``environment_mismatch`` — are caught by *no*
gate. The reason is structural rather than accidental: 28 of the 29 gates only
read JSON, and the one that shells out (``check_differential_tdd``) re-runs the
tests itself and never looks at what the artifact *claimed* it ran. So a
fabricated ``redGreenRefactorEvidence.commands`` entry costs an agent nothing.

This provider closes that hole from the other side. It parses the session
transcripts' ``tool_use`` records for the commands that were *observed* to be
invoked, and diffs them against the commands the implementation artifact cites.
A cited command with no matching invocation fails the record.

Two design commitments, both learned the hard way:

**Match on exact identity, never on containment.** A cited ``python -m pytest``
backed only by an invoked ``python -m pytest tests/unit/test_one.py -q`` is
precisely the ``narrowed_command_scope`` defect. Substring matching would wave
it through, because the narrow run contains the broad claim as a prefix. So a
cited command matches only if it equals — after whitespace normalisation and
``cd``-prefix stripping — a whole invoked command or one leg of an invoked
``&&``/``||``/``;`` chain. Normalisation absorbs formatting, never specificity.

**A corpus we could not read is not a corpus with nothing in it.** #1456 found
1176 of 2457 dataset rows provenanced to one machine-local ``~/.claude/projects``
directory that is not backed up, not shareable, and does not exist in CI. If
this provider answered "0 unmatched" there, it would manufacture exactly the
vacuous pass this epic exists to end — an unverifiable claim rendered
indistinguishable from a verified one. When the transcript cache is absent the
block reports :data:`STATUS_MISSING_SOURCE` with ``unmatchedCommandCount: None``,
so "could not look" can never be misread as "looked and found nothing".

**Known coverage boundary: parent sessions only.** Measured on the local corpus,
71,359 transcript records carry an ``isSidechain`` flag and *every one of them is
``false``* — subagent (Task-tool) traffic is never written to
``~/.claude/projects``. Executors are subagents, so an executor's own invocations
are absent from the corpus at the moment its artifact is written, and this
provider will report a cited-but-unfound command for work that genuinely ran.
That is the scope #1443 states explicitly ("it works against parent transcripts,
which exist today; extending coverage to executors is a separate slice and is
**not** a prerequisite"). Read a ``FAIL`` on an executor-authored artifact as
"unverifiable from this corpus" until that slice lands; the verdict is only
load-bearing for commands a parent session was in a position to observe.

Stdlib only, by contract: the module is imported by path with no package context
and no repo on ``sys.path``, and CI installs nothing this file could rely on.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import CaptureContext

PROVIDER_NAME = "claimVsExecuted"

#: Every cited command was observed to be invoked.
STATUS_PASS = "PASS"
#: At least one cited command has no matching invocation.
STATUS_FAIL = "FAIL"
#: The transcripts or the artifact could not be read. Never a pass.
STATUS_MISSING_SOURCE = "MISSING_SOURCE"
#: The artifact cites no commands at all — zero evidence, not clean evidence.
STATUS_NO_CLAIMS = "NO_CLAIMS"

#: Override the transcript search path (CI, fixtures, a restored cache).
TRANSCRIPT_DIR_ENV = "JULI_TRANSCRIPT_DIR"
#: Claude Code's config root, if relocated from ``~/.claude``.
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"

#: Tool names whose ``input.command`` is a shell command that actually ran.
COMMAND_TOOL_NAMES = frozenset({"Bash", "BashOutput"})

#: Cap on named offenders so one bad artifact cannot bloat the committed record.
MAX_REPORTED_UNMATCHED = 20

_WHITESPACE = re.compile(r"\s+")
_CD_PREFIX = re.compile(r"^cd\s+[^&;|]+?\s*&&\s*")
_CHAIN_SEPARATOR = re.compile(r"\s*(?:&&|\|\||;)\s*")


# ---------------------------------------------------------------------------
# normalisation
# ---------------------------------------------------------------------------


def normalize_command(command: str) -> str:
    """Collapse formatting noise while preserving every scope-bearing token.

    Whitespace runs become single spaces and leading ``cd <path> &&`` hops are
    dropped, because neither changes *what* was executed. Flags, paths and test
    selectors are left exactly as written — they are the specificity that
    ``narrowed_command_scope`` attacks, and normalising them away would hand the
    defect the pass it is looking for.
    """
    if not isinstance(command, str):
        return ""
    text = _WHITESPACE.sub(" ", command.strip())
    while True:
        stripped = _CD_PREFIX.sub("", text, count=1)
        if stripped == text:
            return text
        text = stripped.strip()


def _chain_legs(command: str) -> Iterator[str]:
    """Yield the whole command plus each ``&&``/``||``/``;`` leg, normalised.

    A command genuinely run as one leg of a chain *did* run, so each leg is
    indexed on its own. This widens what counts as invoked, never what counts as
    a match for a broader claim.
    """
    normalized = normalize_command(command)
    if normalized:
        yield normalized
    for leg in _CHAIN_SEPARATOR.split(normalized):
        leg = normalize_command(leg)
        if leg and leg != normalized:
            yield leg


# ---------------------------------------------------------------------------
# claimed side — the implementation artifact
# ---------------------------------------------------------------------------


def _artifact_path(issue: int, artifact_dir: Path | str | None) -> Path:
    if artifact_dir is not None:
        return Path(artifact_dir) / f"implementation-issue-{issue}.json"
    repo_root = Path(__file__).resolve().parents[4]
    return (
        repo_root
        / "agent-runtime"
        / "artifacts"
        / "implementations"
        / f"implementation-issue-{issue}.json"
    )


def _load_artifact(issue: int, artifact_dir: Path | str | None) -> dict[str, Any] | None:
    path = _artifact_path(issue, artifact_dir)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cited_commands(artifact: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract every ``redGreenRefactorEvidence[].commands[]`` entry, in order."""
    cycles = artifact.get("redGreenRefactorEvidence")
    if not isinstance(cycles, list):
        return []
    cited: list[dict[str, Any]] = []
    for cycle in cycles:
        if not isinstance(cycle, dict):
            continue
        commands = cycle.get("commands")
        if not isinstance(commands, list):
            continue
        for entry in commands:
            if not isinstance(entry, dict):
                continue
            command = entry.get("command")
            if not isinstance(command, str) or not command.strip():
                continue
            cited.append(
                {
                    "command": command.strip(),
                    "cycle": cycle.get("cycle"),
                    "exitCode": entry.get("exitCode"),
                }
            )
    return cited


# ---------------------------------------------------------------------------
# executed side — the session transcripts
# ---------------------------------------------------------------------------


def default_transcript_dirs(project_root: Path | str | None = None) -> list[Path]:
    """Resolve where this machine's session transcripts live, if anywhere.

    Claude Code slugs a working directory into a project folder name by replacing
    ``/`` and ``.`` with ``-``. Worktrees therefore get their own sibling folders
    under the main repo's slug, so the main slug is used as a *prefix* glob: a
    command run by an executor inside ``.worktrees/w2-1443`` is still found.

    Returns an empty list when nothing exists. That emptiness is load-bearing —
    the caller turns it into :data:`STATUS_MISSING_SOURCE` rather than a pass.
    """
    override = os.environ.get(TRANSCRIPT_DIR_ENV)
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p and Path(p).is_dir()]

    config_dir = os.environ.get(CLAUDE_CONFIG_DIR_ENV)
    projects = (Path(config_dir) if config_dir else Path.home() / ".claude") / "projects"
    if not projects.is_dir():
        return []

    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[4]
    # A worktree's transcripts and the main checkout's transcripts are both this
    # repo's history; anchor the glob above `.worktrees` so neither is missed.
    if ".worktrees" in root.parts:
        root = Path(*root.parts[: root.parts.index(".worktrees")])

    slug = str(root).replace("/", "-").replace(".", "-")
    return sorted(p for p in projects.glob(f"{slug}*") if p.is_dir())


def _transcript_files(directories: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for directory in directories:
        directory = Path(directory)
        if not directory.is_dir():
            continue
        files.extend(sorted(p for p in directory.glob("*.jsonl") if p.is_file()))
    return files


def _commands_in_transcript(path: Path) -> Iterator[str]:
    """Stream one transcript, yielding every command a ``tool_use`` invoked.

    Line-by-line by construction: the local corpus is ~245 MB across 22 files and
    must never be materialised. The cheap ``in`` pre-filter skips the large
    majority of lines before paying for ``json.loads``.
    """
    try:
        handle = path.open("r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            if "tool_use" not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            message = record.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                if block.get("name") not in COMMAND_TOOL_NAMES:
                    continue
                payload = block.get("input")
                if not isinstance(payload, dict):
                    continue
                command = payload.get("command")
                if isinstance(command, str) and command.strip():
                    yield command


def build_invocation_index(files: Iterable[Path]) -> tuple[set[str], int]:
    """Index every observed invocation, returning ``(index, invocation_count)``.

    The index holds each whole command and each chain leg; the count is of whole
    invocations, so the record can show how much evidence a verdict rests on.
    """
    index: set[str] = set()
    invocations = 0
    for path in files:
        for command in _commands_in_transcript(path):
            invocations += 1
            index.update(_chain_legs(command))
    return index, invocations


# ---------------------------------------------------------------------------
# the block
# ---------------------------------------------------------------------------


def _missing_source(reason: str, **extra: Any) -> dict[str, Any]:
    """The fail-closed block. ``None``, never ``0``, for what was not measured."""
    block: dict[str, Any] = {
        "status": STATUS_MISSING_SOURCE,
        "verified": False,
        "recordPasses": False,
        "reason": reason,
        "citedCommandCount": None,
        "matchedCommandCount": None,
        "unmatchedCommandCount": None,
        "unmatchedCommands": [],
        "unmatchedCommandsTruncated": False,
        "invokedCommandCount": 0,
        "transcriptsScanned": 0,
        "transcriptSources": [],
    }
    block.update(extra)
    return block


def capture(
    context: CaptureContext,
    *,
    implementation_artifact: dict[str, Any] | None = None,
    artifact_dir: Path | str | None = None,
    transcript_dirs: Sequence[Path | str] | Path | str | None = None,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    """Diff the artifact's cited commands against the transcripts' invocations.

    The keyword arguments are the injectable seam: ``capture_run_block`` calls
    this with the context alone, while tests supply a fixture artifact and a
    fixture transcript directory. That is what makes the behaviour testable
    without mocking the filesystem, the home directory or the registry.
    """
    artifact = implementation_artifact
    if artifact is None:
        artifact = _load_artifact(context.issue, artifact_dir)
    if not isinstance(artifact, dict):
        return _missing_source(
            "implementation artifact for issue "
            f"{context.issue} could not be read at "
            f"{_artifact_path(context.issue, artifact_dir)}"
        )

    if transcript_dirs is None:
        directories = default_transcript_dirs(project_root)
    elif isinstance(transcript_dirs, (str, Path)):
        directories = [Path(transcript_dirs)]
    else:
        directories = [Path(d) for d in transcript_dirs]

    files = _transcript_files(directories)
    if not files:
        return _missing_source(
            "no session transcripts found; the transcript cache is machine-local "
            "and absent here, so cited commands could not be verified (#1456)",
            transcriptSources=[str(d) for d in directories],
        )

    cited = cited_commands(artifact)
    sources = [str(d) for d in directories]

    if not cited:
        return {
            "status": STATUS_NO_CLAIMS,
            "verified": True,
            "recordPasses": False,
            "reason": (
                "the implementation artifact cites no commands under "
                "redGreenRefactorEvidence[].commands; there is nothing to verify"
            ),
            "citedCommandCount": 0,
            "matchedCommandCount": 0,
            "unmatchedCommandCount": 0,
            "unmatchedCommands": [],
            "unmatchedCommandsTruncated": False,
            "invokedCommandCount": build_invocation_index(files)[1],
            "transcriptsScanned": len(files),
            "transcriptSources": sources,
        }

    index, invocations = build_invocation_index(files)

    unmatched: list[dict[str, Any]] = []
    matched = 0
    for entry in cited:
        if normalize_command(entry["command"]) in index:
            matched += 1
        else:
            unmatched.append(entry)

    failed = bool(unmatched)
    return {
        "status": STATUS_FAIL if failed else STATUS_PASS,
        "verified": True,
        "recordPasses": not failed,
        "reason": (
            f"{len(unmatched)} of {len(cited)} cited commands have no matching "
            "invocation in the session transcripts"
        )
        if failed
        else "",
        "citedCommandCount": len(cited),
        "matchedCommandCount": matched,
        "unmatchedCommandCount": len(unmatched),
        "unmatchedCommands": unmatched[:MAX_REPORTED_UNMATCHED],
        "unmatchedCommandsTruncated": len(unmatched) > MAX_REPORTED_UNMATCHED,
        "invokedCommandCount": invocations,
        "transcriptsScanned": len(files),
        "transcriptSources": sources,
    }
