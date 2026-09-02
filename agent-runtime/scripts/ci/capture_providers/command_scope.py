"""Capture provider (#1444): does the cited command actually reach CI's scope?

487 of 541 ``pytest`` invocations in the corpus are narrower than the
``pytest tests/`` CI runs; ``ruff`` reaches CI-equivalent scope in 78 of 162
runs and ``mypy`` in 44 of 66. That is not itself a defect — a narrow run during
the loop is the right thing to do, and stays allowed. **The defect is a narrow
run reported as full coverage.** ``pytest tests/unit`` never executes
``tests/integration``, which is where the model/migration parity guard lives, so
a green ``tests/unit`` presented as "tests pass" is exactly how the
``products.revenue`` (#943) and ``inventory_items.velocity`` (#948) schema drift
reached main behind a green tick.

This provider does not judge whether a narrow run was appropriate. It records
what was run against what CI runs, so the two can never again be silently
conflated.

The unit is the invocation, not the command
-------------------------------------------
76 commands in the corpus chain 2-5 ``pytest`` runs. A chain whose first run is
broad and second narrow cannot honestly be scored as one selector: counting
per-command, the broad head launders the narrow tail into a clean result. So a
cited command is split on its shell operators and **every invocation is scored
independently**. The block states ``unit: "invocation"`` and reports
``commandsCited`` beside ``invocationsScored`` so the two framings stay
reconcilable rather than one silently replacing the other.

CI's selectors are read, never assumed
--------------------------------------
The reference comes from parsing ``.github/workflows/pr.yml`` itself. A
hardcoded ``"tests/"`` would freeze CI's scope at the moment this file was
written; if someone narrows the PR-safe lane, this reference must move with it,
or the provider starts certifying against a CI that no longer exists.

Fail-closed (#1434 lock 2)
--------------------------
A command that cannot be tokenised, an absent or unrecognisable workflow, an
ambiguous reference lane: each raises. A silently skipped command would leave
the block reporting zero narrowings, making "nothing was narrow" indistinguishable
from "nothing was checked" — the precise failure the ``run{}`` envelope exists
to close.

Stdlib only, by construction: this module runs wherever ``generate_status_records.py``
runs, which is not guaranteed to have anything beyond ``./backend[dev]``.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import CaptureContext

PROVIDER_NAME = "commandScope"

_REPO_ROOT = Path(__file__).resolve().parents[4]

#: The workflow whose invocations define "CI scope". Patched in tests; never
#: inlined as a constant, so a change to CI's lanes moves this reference too.
CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "pr.yml"

#: Source of ``pytest``'s default paths when a run names none of its own.
PYTEST_INI_PATH = _REPO_ROOT / "pytest.ini"

#: Tools whose scope is comparable. Anything else in a cited command is left
#: unrecognised and counted, never scored against an unrelated reference.
_TOOLS = frozenset({"pytest", "ruff", "mypy"})

#: ``ruff check`` and ``ruff format`` are different gates over different
#: properties; comparing one against the other's CI lane would manufacture a
#: pass out of an unrelated run.
_RUFF_SUBCOMMANDS = frozenset({"check", "format"})

#: Tokens that may legitimately precede the tool name without changing what is
#: run. Anything else before the tool means the segment is some other program
#: that merely mentions it (``pip install pytest``).
_WRAPPER_TOKENS = frozenset(
    {
        "-B",
        "-I",
        "-O",
        "-W",
        "-X",
        "-m",
        "-u",
        "command",
        "env",
        "exec",
        "faulthandler",
        "nice",
        "npx",
        "poetry",
        "python",
        "python3",
        "run",
        "stdbuf",
        "time",
        "timeout",
        "uv",
        "uvx",
        "xargs",
    }
)

_ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_DURATION = re.compile(r"^\d+(\.\d+)?[smhd]?$")
_VERSIONED_PYTHON = re.compile(r"^python3(\.\d+)?$")

#: Shell operators that end one invocation and begin another.
_CHAIN_OPERATORS = frozenset({"&&", "||", ";", "|", "&", "\n"})

#: Options that consume the following token, so that token is an option value
#: and not a path selector.
_VALUE_OPTIONS = frozenset(
    {
        "--config",
        "--config-file",
        "--cov",
        "--cov-fail-under",
        "--cov-report",
        "--deselect",
        "--durations",
        "--ignore",
        "--junitxml",
        "--maxfail",
        "--rootdir",
        "--tb",
        "-W",
        "-c",
        "-k",
        "-m",
        "-n",
        "-o",
        "-p",
    }
)

_MARKER_TERM = re.compile(r"(?P<neg>\bnot\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)")
_MARKER_KEYWORDS = frozenset({"and", "or", "not"})

# Verdicts. ``narrower_than_CI`` is the string the acceptance criteria name.
VERDICT_SUBSUMES = "subsumes_CI"
VERDICT_NARROWER = "narrower_than_CI"
VERDICT_NO_REFERENCE = "no_ci_reference"


class UnparseableCommandError(ValueError):
    """The provider could not resolve an input, so it refuses to report on it.

    Covers every fail-closed path: a command that cannot be tokenised, a cited
    value that is not a non-empty string, an absent or unrecognisable
    ``pr.yml``, and an ambiguous CI reference lane. Deliberately one class —
    every one of these means "this block cannot be trusted", and the caller's
    only correct response is the same in each case: abort the record.
    """


class Selector:
    """The scope one tool invocation actually covers.

    Hand-written rather than a ``@dataclass`` on purpose. ``discover_providers``
    execs this file under a synthetic module name that it never inserts into
    ``sys.modules``, and ``dataclasses`` resolves a subscripted annotation such
    as ``tuple[str, ...]`` by looking its module up there — under
    ``from __future__ import annotations`` that lookup returns ``None`` and the
    provider fails to import. The seam is fixed and shared; this class bends.
    """

    __slots__ = (
        "tool",
        "paths",
        "deselected_markers",
        "selected_markers",
        "keyword",
        "node_ids",
        "deselect_options",
        "ignore_options",
        "paths_defaulted",
        "raw",
    )

    def __init__(
        self,
        tool,
        paths=(),
        deselected_markers=frozenset(),
        selected_markers=frozenset(),
        keyword=None,
        node_ids=(),
        deselect_options=(),
        ignore_options=(),
        paths_defaulted=False,
        raw="",
    ):
        self.tool = tool
        self.paths = tuple(paths)
        self.deselected_markers = frozenset(deselected_markers)
        self.selected_markers = frozenset(selected_markers)
        self.keyword = keyword
        self.node_ids = tuple(node_ids)
        self.deselect_options = tuple(deselect_options)
        self.ignore_options = tuple(ignore_options)
        self.paths_defaulted = bool(paths_defaulted)
        self.raw = raw

    def __repr__(self) -> str:
        return (
            f"Selector(tool={self.tool!r}, paths={self.paths!r}, "
            f"deselected_markers={sorted(self.deselected_markers)!r})"
        )

    @property
    def selector_text(self) -> str:
        """The path selector as a human reads it in a command line."""
        return " ".join(self.paths)

    @property
    def restricts_selection(self) -> bool:
        """Whether this invocation opts into a subset rather than a whole tree."""
        return bool(self.selected_markers or self.keyword or self.node_ids)


# --------------------------------------------------------------------------- #
# Command parsing
# --------------------------------------------------------------------------- #


def _tokenise(command: str) -> list[str]:
    """Shell-tokenise ``command``, refusing anything that will not parse."""
    if not isinstance(command, str):
        raise UnparseableCommandError(
            f"cited command is {type(command).__name__}, not a string: {command!r}"
        )
    if not command.strip():
        raise UnparseableCommandError("cited command is empty")
    try:
        return shlex.split(command)
    except ValueError as exc:
        raise UnparseableCommandError(f"cannot tokenise cited command {command!r}: {exc}") from exc


def _segments(tokens: Iterable[str]) -> Iterator[list[str]]:
    """Split a token stream into one list per shell invocation."""
    segment: list[str] = []
    for token in tokens:
        if token in _CHAIN_OPERATORS:
            if segment:
                yield segment
            segment = []
            continue
        segment.append(token)
    if segment:
        yield segment


def _is_wrapper(token: str) -> bool:
    return (
        token in _WRAPPER_TOKENS
        or bool(_ENV_ASSIGNMENT.match(token))
        or bool(_VERSIONED_PYTHON.match(token))
        or bool(_DURATION.match(token))
    )


def _find_tool(segment: list[str]) -> tuple[str, list[str]] | None:
    """Return ``(tool_key, args)`` for a segment that invokes a comparable tool.

    Returns ``None`` — not an error — when the segment runs something else. Only
    tokens that cannot change what is executed may precede the tool name, so
    ``pip install pytest`` is correctly not read as a pytest run.
    """
    for index, token in enumerate(segment):
        name = token.replace("\\", "/").rsplit("/", 1)[-1]
        if name not in _TOOLS:
            if _is_wrapper(token):
                continue
            return None
        args = segment[index + 1 :]
        if name == "ruff":
            subcommand = args[0] if args and args[0] in _RUFF_SUBCOMMANDS else None
            if subcommand is None:
                return None
            return f"ruff {subcommand}", args[1:]
        return name, args
    return None


def _parse_markers(expression: str) -> tuple[frozenset[str], frozenset[str]]:
    """Split a ``-m`` expression into (deselected, selected) marker names.

    Deliberately conservative: a term this simple reader cannot prove is negated
    (``not (live or demo)``) is read as a positive selection, which flags the
    invocation as narrow. Over-reporting narrowness is recoverable; under-
    reporting it is the defect.
    """
    deselected: set[str] = set()
    selected: set[str] = set()
    for match in _MARKER_TERM.finditer(expression):
        name = match.group("name")
        if name in _MARKER_KEYWORDS:
            continue
        if match.group("neg"):
            deselected.add(name)
        else:
            selected.add(name)
    return frozenset(deselected), frozenset(selected)


def _normalise_path(path: str) -> str:
    cleaned = path.replace("\\", "/").strip()
    while cleaned.startswith("./") and len(cleaned) > 2:
        cleaned = cleaned[2:]
    if len(cleaned) > 1:
        cleaned = cleaned.rstrip("/")
    return cleaned


def _build_selector(tool: str, args: list[str], raw: str) -> Selector:
    paths: list[str] = []
    node_ids: list[str] = []
    deselected: frozenset[str] = frozenset()
    selected: frozenset[str] = frozenset()
    keyword: str | None = None
    deselect_options: list[str] = []
    ignore_options: list[str] = []

    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith("--") and "=" in token:
            name, _, value = token.partition("=")
            if name == "--deselect":
                deselect_options.append(value)
            elif name == "--ignore":
                ignore_options.append(value)
            index += 1
            continue
        if token in _VALUE_OPTIONS:
            value = args[index + 1] if index + 1 < len(args) else ""
            if token == "-m":
                deselected, selected = _parse_markers(value)
            elif token == "-k":
                keyword = value
            elif token == "--deselect":
                deselect_options.append(value)
            elif token == "--ignore":
                ignore_options.append(value)
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        if "::" in token:
            node_ids.append(token)
            paths.append(_normalise_path(token.split("::", 1)[0]))
        else:
            paths.append(_normalise_path(token))
        index += 1

    paths_defaulted = False
    if not paths and tool == "pytest":
        default_paths = _pytest_default_paths()
        if default_paths:
            paths = list(default_paths)
            paths_defaulted = True

    return Selector(
        tool=tool,
        paths=tuple(paths),
        deselected_markers=deselected,
        selected_markers=selected,
        keyword=keyword,
        node_ids=tuple(node_ids),
        deselect_options=tuple(deselect_options),
        ignore_options=tuple(ignore_options),
        paths_defaulted=paths_defaulted,
        raw=raw,
    )


def parse_invocations(command: str) -> list[Selector]:
    """Return one :class:`Selector` per comparable tool invocation in ``command``.

    Raises :class:`UnparseableCommandError` when the command cannot be
    tokenised. Segments running some other program yield nothing — they are
    counted by the caller, never dropped without trace.
    """
    tokens = _tokenise(command)
    selectors: list[Selector] = []
    for segment in _segments(tokens):
        found = _find_tool(segment)
        if found is None:
            continue
        tool, args = found
        selectors.append(_build_selector(tool, args, shlex.join(segment)))
    return selectors


def _count_segments(command: str) -> int:
    return sum(1 for _ in _segments(_tokenise(command)))


# --------------------------------------------------------------------------- #
# CI's own selectors, read from pr.yml
# --------------------------------------------------------------------------- #

_RUN_KEY = re.compile(r"^(?P<lead>\s*(?:-\s+)?)run:(?P<rest>.*)$")
_BLOCK_INDICATOR = re.compile(r"^(?P<style>[|>])[+-]?(?P<digits>\d*)$")


def _run_blocks(text: str) -> list[str]:
    """Extract every ``run:`` shell body from a workflow, stdlib only.

    Handles the three shapes ``pr.yml`` uses: a plain inline scalar, a literal
    block (``|``) whose lines may end in a backslash continuation, and a folded
    block (``>-``) joined with spaces. Comment lines are dropped everywhere —
    ``pr.yml`` carries prose about pytest selectors that must not be mistaken
    for an invocation.

    Not a YAML parser and not trying to be. It reads one key, which is why it
    needs no third-party dependency to run wherever the record is generated.
    """
    blocks: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            index += 1
            continue

        match = _RUN_KEY.match(line)
        if match is None:
            index += 1
            continue

        key_column = len(match.group("lead"))
        rest = match.group("rest").strip()
        index += 1

        indicator = _BLOCK_INDICATOR.match(rest) if rest else None
        if indicator is None:
            if rest:
                blocks.append(rest)
            continue

        body: list[str] = []
        while index < len(lines):
            candidate = lines[index]
            if candidate.strip() and (len(candidate) - len(candidate.lstrip())) <= key_column:
                break
            if candidate.strip() and not candidate.strip().startswith("#"):
                body.append(candidate.strip())
            index += 1

        joined = ("\n" if indicator.group("style") == "|" else " ").join(body)
        blocks.append(joined.replace("\\\n", " ").replace("\\ ", " "))

    return blocks


def _pytest_default_paths() -> tuple[str, ...]:
    """``testpaths`` from ``pytest.ini`` — what a bare ``pytest`` actually runs.

    An unreadable ini yields no defaults, which makes a bare ``pytest`` unable to
    prove it covers anything and so reports as narrow. That is the fail-closed
    direction: never a silent claim of full coverage.
    """
    try:
        text = PYTEST_INI_PATH.read_text(encoding="utf-8")
    except OSError:
        return ()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("testpaths"):
            _, _, value = stripped.partition("=")
            return tuple(_normalise_path(p) for p in value.split() if p)
    return ()


def _covers(cited: tuple[str, ...], reference: tuple[str, ...]) -> bool:
    """Whether every reference path lies inside some cited path."""
    if not cited or not reference:
        return False
    for target in reference:
        if not any(
            candidate in (".", "") or target == candidate or target.startswith(candidate + "/")
            for candidate in cited
        ):
            return False
    return True


def _pick_reference(tool: str, candidates: list[Selector]) -> Selector:
    """The broadest CI lane for ``tool``: the one whose paths cover every other.

    Lanes that opt into a subset (``-m live``, ``-k ...``, a node id) are not
    candidates — they are deliberate slices of CI, not CI's scope. An ambiguous
    result raises rather than picking arbitrarily; a reference chosen by
    coin-flip would make the verdict non-reproducible.
    """
    broad = [c for c in candidates if not c.restricts_selection]
    if not broad:
        raise UnparseableCommandError(
            f"{CI_WORKFLOW_PATH} has no unrestricted {tool} lane to use as a scope reference"
        )

    covering = [c for c in broad if all(_covers(c.paths, other.paths) for other in broad)]
    if not covering:
        raise UnparseableCommandError(
            f"no single {tool} lane in {CI_WORKFLOW_PATH} covers the others; "
            "the CI scope reference is ambiguous"
        )
    fewest = min(len(c.deselected_markers) for c in covering)
    finalists = [c for c in covering if len(c.deselected_markers) == fewest]
    distinct = {(c.paths, c.deselected_markers) for c in finalists}
    if len(distinct) > 1:
        raise UnparseableCommandError(
            f"{len(distinct)} equally broad {tool} lanes in {CI_WORKFLOW_PATH}; "
            "the CI scope reference is ambiguous"
        )
    return finalists[0]


def ci_selectors() -> dict[str, Selector]:
    """The reference selector per tool, parsed from the live workflow."""
    try:
        text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise UnparseableCommandError(
            f"cannot read the CI workflow at {CI_WORKFLOW_PATH}: {exc}"
        ) from exc

    by_tool: dict[str, list[Selector]] = {}
    for block in _run_blocks(text):
        try:
            selectors = parse_invocations(block)
        except UnparseableCommandError:
            # One unquotable shell line must not blind the reference set. The
            # required-lane check below is what keeps this fail-closed.
            continue
        for selector in selectors:
            by_tool.setdefault(selector.tool, []).append(selector)

    if not by_tool:
        raise UnparseableCommandError(
            f"{CI_WORKFLOW_PATH} yielded no recognisable pytest/ruff/mypy lane; "
            "CI's scope is unknown and no comparison can be trusted"
        )

    return {tool: _pick_reference(tool, lanes) for tool, lanes in sorted(by_tool.items())}


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def compare(cited: Selector, reference: Selector | None) -> dict[str, Any]:
    """Score one cited invocation against CI's lane for the same tool."""
    entry: dict[str, Any] = {
        "tool": cited.tool,
        "citedCommand": cited.raw,
        "citedSelector": cited.selector_text,
        "citedDeselectedMarkers": sorted(cited.deselected_markers),
        "selectedMarkers": sorted(cited.selected_markers),
        "keywordFilter": cited.keyword,
        "nodeIds": list(cited.node_ids),
        "pathsFromTestpaths": cited.paths_defaulted,
    }

    if reference is None:
        entry.update(
            {
                "verdict": VERDICT_NO_REFERENCE,
                "ciSelector": None,
                "ciDeselectedMarkers": [],
                "extraDeselectedMarkers": [],
                "reasons": [],
            }
        )
        return entry

    extra = sorted(cited.deselected_markers - reference.deselected_markers)
    reasons: list[str] = []
    if not _covers(cited.paths, reference.paths):
        reasons.append("paths_not_subsuming")
    if extra:
        reasons.append("extra_deselected_markers")
    if cited.selected_markers:
        reasons.append("positive_marker_selection")
    if cited.keyword:
        reasons.append("keyword_filter")
    if cited.node_ids:
        reasons.append("node_id_selection")
    if cited.deselect_options:
        reasons.append("deselect_option")
    if cited.ignore_options:
        reasons.append("ignore_option")

    entry.update(
        {
            "verdict": VERDICT_NARROWER if reasons else VERDICT_SUBSUMES,
            "ciSelector": reference.selector_text,
            "ciCommand": reference.raw,
            "ciDeselectedMarkers": sorted(reference.deselected_markers),
            "extraDeselectedMarkers": extra,
            "reasons": sorted(reasons),
        }
    )
    return entry


# --------------------------------------------------------------------------- #
# Cited-command extraction
# --------------------------------------------------------------------------- #


def _walk_commands(node: Any) -> Iterator[Any]:
    """Yield every cited command value found anywhere in an artifact body.

    Both bodies are ``additionalProperties: true`` and commands surface in more
    than one shape (``redGreenRefactorEvidence[].commands[].command`` carried
    forward by Review, ``checks[].details.command`` written by a gate). Walking
    for the key rather than a fixed path means a command cited in a new place is
    scored rather than quietly ignored.

    Non-string values are yielded too — validating them is the caller's job, and
    dropping them here would be the silent skip this provider exists to prevent.
    """
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "command":
                yield value
            elif key == "commands" and isinstance(value, list):
                for item in value:
                    if not isinstance(item, dict):
                        yield item
            for child in _walk_commands(value):
                yield child
    elif isinstance(node, list):
        for item in node:
            for child in _walk_commands(item):
                yield child


def cited_commands(context: CaptureContext) -> list[Any]:
    """Every command the record's review and validation bodies cite, in order."""
    return list(_walk_commands(context.review)) + list(_walk_commands(context.validation))


# --------------------------------------------------------------------------- #
# Provider entry point
# --------------------------------------------------------------------------- #


def capture(context: CaptureContext) -> dict[str, Any]:
    """Record whether each cited invocation reaches the scope CI runs."""
    reference = ci_selectors()
    commands = cited_commands(context)

    invocations: list[dict[str, Any]] = []
    unrecognised = 0
    for command in commands:
        selectors = parse_invocations(command)
        unrecognised += _count_segments(command) - len(selectors)
        for selector in selectors:
            invocations.append(compare(selector, reference.get(selector.tool)))

    narrower = [entry for entry in invocations if entry["verdict"] == VERDICT_NARROWER]

    return {
        "unit": "invocation",
        "unitRationale": (
            "76 corpus commands chain 2-5 runs; scoring per command lets a broad "
            "first run launder a narrow second one, so each invocation is scored "
            "on its own selector."
        ),
        "ciWorkflow": str(CI_WORKFLOW_PATH.relative_to(_REPO_ROOT))
        if CI_WORKFLOW_PATH.is_relative_to(_REPO_ROOT)
        else str(CI_WORKFLOW_PATH),
        "ciSelectors": {
            tool: {
                "paths": list(selector.paths),
                "deselectedMarkers": sorted(selector.deselected_markers),
                "command": selector.raw,
            }
            for tool, selector in sorted(reference.items())
        },
        "commandsCited": len(commands),
        "invocationsScored": len(invocations),
        "invocationsUnrecognised": unrecognised,
        "narrowerCount": len(narrower),
        "narrowerThanCI": narrower,
        "invocations": invocations,
    }
