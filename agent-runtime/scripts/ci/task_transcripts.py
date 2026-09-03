#!/usr/bin/env python3
"""Read the persisted subagent task transcripts (#1441).

Why this exists
---------------
Three executors independently reported that ``tokenUsage`` and
``executionDurationMs`` are unobtainable from an executor process, and the
slice they were working was set aside on their word. They were wrong, and the
wrongness is specific: subagent transcripts *are* persisted, at
``<session-temp>/tasks/<agentId>.output`` — the one location
``default_transcript_dirs()`` never looks in. Measured 2026-09-02 on one
session: 56 ``.output`` files, 37 of them JSONL transcripts, 5,089 records,
every one carrying ``isSidechain: true``, 1,577 ``Bash`` ``tool_use`` blocks.

That location is the whole point. A metric an agent types about itself is a
claim; a metric read out of a file the agent cannot write is a measurement.

Three counting rules are load-bearing
-------------------------------------
**Usage is per message, not per row.** The transcript writes one row per
content block, and *every* row of a message repeats that message's whole
``usage`` object. Summing rows overcounts: on a real transcript, 201 usage rows
for 91 distinct message ids turn 10,588,988 real tokens into 22,563,409. Usage
is therefore accumulated once per ``message.id``.

**Tool calls are per ``tool_use`` id.** Deduping tool calls by message id would
lose calls, since a message can issue several. Deduping by the invocation's own
id survives both layouts — verified against the real corpus, where per-row and
per-unique-id counting agree exactly (110 = 110).

**Not every ``.output`` file is a transcript.** The same directory holds raw
tool output as plain text. A file with no parseable JSON object is not an empty
transcript, it is not a transcript; treating it as one would invent an agent
with a measured-looking zero.

Attribution is by the worktree the agent actually touched, and by nothing else.

``gitBranch`` looks like the obvious key and is a trap (#1508). It is a
*session-wide* field, not the agent's: it reports whatever branch the session
is on, so every concurrent agent carries the same value and it changes for all
of them at once. Both failure directions were measured on the live store while
this module was under review.

*False negative* — six concurrent executors, each in its own worktree, all
recording ``main``. Attributing on the branch finds none of them.

*False positive*, the dangerous one — once any tree in the session moved onto
``feature/issue-1441-…``, all five agents then running recorded that branch.
Attributing on it swept in a peer reviewer and three unrelated executors and
reported 34,200,395 tokens against 10,134,878 real: a 3.3x fabrication that
grew in real time as the neighbours worked. A number that large and that wrong
is worse than no number, which is the whole thesis of this epic.

So the branch is recorded as context and never attributes. The signal that
works is the worktree named in the agent's ``tool_use`` **inputs** — the tree
it actually operated on. Tool inputs rather than transcript text because prose
is not evidence of work: a neighbour that greps for ``1441`` mentions the
number without ever touching that tree.

That signal is not perfect either — an agent that merely *reads* another's tree
picks up its name — so more than one attributed agent is reported as ambiguous
rather than summed. See :func:`agents_for_issue`.

Attribution says which *tree*; role says which *job* (#1512)
------------------------------------------------------------
The tree an agent worked in cannot tell an executor from the reviewer that
read the same tree, and on a normal issue both are there. Left role-blind, a
settled reviewer beside an in-flight executor read as the run: measured, with
the reviewer's 400,000 tokens as the headline and the executor's honest
9,000,000 filed as a 22x over-claim. Every figure real, the role wrong, so the
reading was wrong.

The role is read from the transcript's **first record** — the prompt the
orchestrator handed the agent before it ran a turn. Measured on the live store:
188 of 203 transcripts open with it. It is the harness stating the job, in a
record the measured agent cannot write, which is the same property that makes
the usage counts a measurement rather than a claim.

Two weaker signals were measured and rejected as the primary. *Which agent
wrote the implementation artifact* cannot classify an agent that has not
written one yet — and an in-flight executor is exactly the case the defect
turns on. *Write/Edit-to-Read ratio* is a proxy with no ground truth behind it.
The directive was cross-checked against the artifact-write signal over all 203
transcripts on the live store: zero contradictions — no directive-classified
executor wrote a review artifact without also writing an implementation one,
and no directive-classified reviewer wrote an implementation artifact. That
cross-check was a one-off offline measurement taken while choosing the signal.
It is **not** shipped: nothing below reads artifact writes, and no test asserts
the agreement. Re-run it by hand before trusting it again, and do not read the
paragraph above as a guard that is still running.

Only the **head** of the directive is read, and that bound is load-bearing. An
executor's brief routinely quotes the reviewer who filed the issue, and a
reviewer's brief routinely names the executor whose work it is reading, so a
whole-prompt keyword search flips both. See :func:`classify_role`.

Classification fails to ``unknown``, never to a guess: a directive this module
cannot read is not an executor, and a lone unclassifiable candidate keeps its
figures under ``agents[]`` while the headline goes unavailable.

Stdlib only, by policy: this module is imported during status-record generation
in CI, where the dependency set is ``./backend[dev] -c backend/constraints.txt``.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Points discovery at an explicit ``tasks`` directory (or a session root that
#: contains one), so a deployment can relocate the store without a code change.
STORE_ENV_VAR = "JULI_TASK_TRANSCRIPT_ROOT"

#: Session id to prefer when several are present, if the harness exports one.
SESSION_ENV_VAR = "CLAUDE_SESSION_ID"

#: Temp roots searched, in order, when no override is given. macOS puts the
#: session dir under ``/tmp`` rather than ``$TMPDIR``; both are checked because
#: neither is guaranteed and the cost of a miss is a silent unmeasured run.
DEFAULT_TEMP_BASES: tuple[str, ...] = ("/tmp", "/private/tmp", "/var/tmp")

#: Per-agent tool listings are bounded; the *counts* are always exact. Only the
#: listing is capped, so one long session cannot bloat the single artifact that
#: survives to ``main``.
MAX_LISTED_TOOLS = 40

#: Seconds a transcript must go untouched before its reading is treated as
#: final. A file still being appended to has no total yet, and reading one makes
#: status-record generation non-idempotent: two passes seconds apart disagree.
SETTLE_SECONDS = 300

_SLUG_RE = re.compile(r"[^A-Za-z0-9]")

#: Worktree directory names appearing in a tool input's paths. ``.worktrees/``
#: is the repo's mandated location for task checkouts (git-baseline), so a name
#: matched here is a tree the agent actually operated on.
_WORKTREE_RE = re.compile(r"\.worktrees/([A-Za-z0-9._-]+)")

ROLE_EXECUTOR = "executor"
ROLE_REVIEWER = "reviewer"
ROLE_META = "meta"
ROLE_PLANNER = "planner"
ROLE_UNKNOWN = "unknown"

#: Words in a spawn directive that name the *addressee's* job. Every pattern
#: here was fixed against the 203 transcripts on the live store rather than
#: guessed; anything unmatched stays :data:`ROLE_UNKNOWN`, which is a state and
#: not a fallback role.
_ROLE_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Meta first only in listing order — precedence is by position in the text,
    # which is what makes "Prepare issue #N for implementation" read as Meta
    # despite "implementation" sitting three words later.
    (ROLE_META, re.compile(r"\bprepare[sd]?\b", re.IGNORECASE)),
    (ROLE_PLANNER, re.compile(r"\bplan(?:s|ned|ning)?\b", re.IGNORECASE)),
    (
        ROLE_REVIEWER,
        re.compile(
            r"\b(?:re-?)?review(?:s|ed|ing|er|ers)?\b|\baudit(?:s|ed|ing|or|ors)?\b",
            re.IGNORECASE,
        ),
    ),
    (
        ROLE_EXECUTOR,
        re.compile(
            r"\bexecutor\b|\bimplement(?:s|ed|ing|ation)?\b|\bfix(?:es|ed|ing)?\b"
            r"|\bfinish(?:es|ed|ing)?\b|\btaking over\b|\brepair(?:s|ed|ing)?\b",
            re.IGNORECASE,
        ),
    ),
)

#: Words of the directive that carry the job. Every harness prompt opens either
#: with an imperative ("Implement issue #N", "Review issue #N") or with a
#: self-description ("You are the ui-ux Executor for ..."), and on the live
#: store the role word lands within eight tokens in every prompt this module
#: classifies — but only just: the deepest sits at token seven ("You are
#: performing an ADVERSARIAL correctness review of ...", "You are doing a
#: FINAL, TIGHT re-review of ..."), so the headroom is one token, not three.
#: Widen this only against a fresh measurement. Reading further is what lets a
#: quoted reviewer or a named executor deeper in the brief flip the answer.
DIRECTIVE_TOKENS = 8

#: Bounded so a full spawn prompt — which can be thousands of words of scope,
#: prohibitions and file paths — never travels into the committed record.
MAX_DIRECTIVE_CHARS = 160
#: The instant this process measures every settle decision against, latched on
#: first use and never advanced. ``None`` until the first read.
#:
#: A latch rather than a fresh sample, because ``settled`` is a *judgement about
#: a boundary*, and a boundary judged against a moving reference is not stable
#: under repetition. Sampling the wall clock inside each read made two
#: generations of one status record compare the same unchanged transcript
#: against two instants seconds apart; any transcript whose age fell in that gap
#: flipped, and the record's byte-idempotency promise flipped with it (#1515).
_settle_clock: float | None = None


def settle_clock(now: float | None = None) -> float:
    """The single instant every settle decision in this process is measured against.

    ``now`` is passed straight back when given: a caller that supplies an
    instant already holds a shared one, and substituting the latch for it would
    make the parameter a lie. Supplying one deliberately does *not* latch —
    a one-off read against a hypothetical instant must not pin every later read
    in the process to it.

    Otherwise the first call latches the wall clock and every later call returns
    that same reading. This is what makes repeated generation idempotent by
    construction rather than by luck: with the clock fixed and the file's mtime
    fixed, ``settled`` is a pure function of the store, so two generations over
    an unchanged store cannot disagree — there is no longer a quantity left that
    could differ between them.

    Latching for the process lifetime is safe for the way this module is used:
    it is imported by short-lived generation scripts. Long-lived callers (a test
    session) reset it explicitly.
    """
    global _settle_clock
    if now is not None:
        return float(now)
    if _settle_clock is None:
        _settle_clock = time.time()
    return _settle_clock


def reset_settle_clock() -> None:
    """Forget the latched instant; the next unpinned read latches a fresh one.

    Exists for tests, which run many generations in one process and must be able
    to place the clock rather than inherit whatever the first test in the file
    happened to latch.
    """
    global _settle_clock
    _settle_clock = None


def project_slug(path: Path | str) -> str:
    """The on-disk directory name a project path is stored under.

    Every character outside ``[A-Za-z0-9]`` becomes ``-``, so
    ``/Users/macos/Juli-AI-v2`` is ``-Users-macos-Juli-AI-v2`` and
    ``/Users/macos/Juli-AI-v2/.claude`` is ``-Users-macos-Juli-AI-v2--claude``.
    Fixed against the real corpus rather than guessed.
    """
    return _SLUG_RE.sub("-", str(path))


def slug_candidates(repo_root: Path | str) -> tuple[str, ...]:
    """Slugs a session for ``repo_root`` could plausibly live under.

    A worktree checkout is a child of the repository the session was opened in
    (``<repo>/.worktrees/<task>``), so the session landed under the *parent's*
    slug. Every ancestor is offered rather than special-casing ``.worktrees``,
    which keeps this correct for a session opened in any subdirectory.
    """
    resolved = Path(repo_root).resolve()
    return tuple(dict.fromkeys(project_slug(p) for p in (resolved, *resolved.parents)))


def spawn_directive(record: dict[str, Any]) -> str | None:
    """The prompt text of ``record``, if it is an agent's spawn record.

    A transcript's first ``user`` row is the brief the orchestrator handed the
    agent. Later ``user`` rows are tool results, whose content blocks carry no
    ``text``, so they yield nothing here and cannot be mistaken for a directive.
    """
    if record.get("type") != "user":
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            return None
    message = record.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        text = " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        return None
    text = text.strip()
    return text or None


def directive_head(directive: str | None) -> str:
    """The opening words of a directive, with markdown noise removed.

    Bounded to :data:`DIRECTIVE_TOKENS` words because the role is stated at the
    front and contradicted further in: a brief that opens "Implement issue #N"
    goes on to quote the reviewer who filed it, and one that opens "Round-2
    review of issue #N" names the executor whose fix round it follows.
    """
    if not directive:
        return ""
    cleaned = directive.replace("*", " ").replace("`", " ").replace("#", " ")
    return " ".join(cleaned.split()[:DIRECTIVE_TOKENS])


def classify_role(directive: str | None) -> tuple[str, str | None]:
    """The role a spawn directive names, and the word that named it.

    Precedence is by **position in the text**, not by rule order: the job is
    whatever the directive says first. That is what separates "Round-2 review
    of issue #N after the executor's fix round" (a reviewer) from "You are
    fixing a real defect the Review found" (an executor) without either
    keyword needing to outrank the other in the abstract.

    Returns ``(ROLE_UNKNOWN, None)`` for a directive naming no job, which is a
    real state on the live store — "Work in the existing worktree ..." is an
    executor brief this cannot read. Unknown must never be resolved into a
    role: a guessed executor is the same class of error as a reported reviewer.
    """
    head = directive_head(directive)
    if not head:
        return ROLE_UNKNOWN, None
    hits = []
    for role, pattern in _ROLE_MARKERS:
        match = pattern.search(head)
        if match is not None:
            hits.append((match.start(), role, match.group(0)))
    if not hits:
        return ROLE_UNKNOWN, None
    hits.sort()
    _, role, signal = hits[0]
    return role, signal


def _timestamp_ms(raw: Any) -> int | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def discover_task_dirs(
    *,
    repo_root: Path | str,
    environ: dict[str, str] | None = None,
    temp_bases: tuple[str, ...] | None = None,
) -> list[Path]:
    """Every ``tasks`` directory that could hold this checkout's transcripts.

    Newest first, by directory mtime. Returns an empty list rather than raising
    when nothing is found — CI has no session temp directory at all, and that
    absence is the common, expected state, not a failure.
    """
    env = os.environ if environ is None else environ

    override = (env.get(STORE_ENV_VAR) or "").strip()
    if override:
        candidate = Path(override)
        for path in (candidate, candidate / "tasks"):
            if path.is_dir():
                return [path]
        return []

    slugs = set(slug_candidates(repo_root))
    bases = DEFAULT_TEMP_BASES if temp_bases is None else temp_bases

    found: list[Path] = []
    seen: set[Path] = set()
    for base in bases:
        root = Path(base)
        if not root.is_dir():
            continue
        try:
            claude_dirs = sorted(root.glob("claude-*"))
        except OSError:
            continue
        for claude_dir in claude_dirs:
            for slug in slugs:
                project = claude_dir / slug
                if not project.is_dir():
                    continue
                try:
                    sessions = sorted(project.iterdir())
                except OSError:
                    continue
                for session in sessions:
                    tasks = session / "tasks"
                    resolved = tasks.resolve() if tasks.is_dir() else None
                    if resolved is None or resolved in seen:
                        continue
                    seen.add(resolved)
                    found.append(tasks)

    def _mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    found.sort(key=_mtime, reverse=True)
    return found


def _parse_records(path: Path) -> list[dict[str, Any]]:
    """JSON objects in ``path``, one per line. A non-transcript yields none."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def measure_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Token usage, tool calls and wall-clock for one agent's records.

    Applies the three counting rules in the module docstring. Every value here
    is read out of the file; nothing is inferred and nothing defaults to a
    number the caller could mistake for a reading.
    """
    seen_messages: set[str] = set()
    seen_tool_calls: set[str] = set()
    tokens = {"input": 0, "output": 0, "cacheCreation": 0, "cacheRead": 0}
    tools: dict[str, int] = {}
    stamps: list[int] = []
    branches: set[str] = set()
    workspaces: set[str] = set()
    agent_ids: list[str] = []
    session_ids: set[str] = set()
    sidechain = 0
    directive: str | None = None

    for index, record in enumerate(records):
        if directive is None:
            directive = spawn_directive(record)
        stamp = _timestamp_ms(record.get("timestamp"))
        if stamp is not None:
            stamps.append(stamp)
        if record.get("isSidechain"):
            sidechain += 1
        branch = record.get("gitBranch")
        if isinstance(branch, str) and branch:
            branches.add(branch)
        agent_id = record.get("agentId")
        if isinstance(agent_id, str) and agent_id and agent_id not in agent_ids:
            agent_ids.append(agent_id)
        session_id = record.get("sessionId")
        if isinstance(session_id, str) and session_id:
            session_ids.add(session_id)

        message = record.get("message")
        if not isinstance(message, dict):
            continue

        usage = message.get("usage")
        if isinstance(usage, dict):
            # Once per message. A message id is present in practice; the row
            # index is the fallback so a malformed record is counted rather
            # than collapsing every id-less row into one.
            message_id = message.get("id")
            key = message_id if isinstance(message_id, str) and message_id else f"row-{index}"
            if key not in seen_messages:
                seen_messages.add(key)
                tokens["input"] += _as_int(usage.get("input_tokens"))
                tokens["output"] += _as_int(usage.get("output_tokens"))
                tokens["cacheCreation"] += _as_int(usage.get("cache_creation_input_tokens"))
                tokens["cacheRead"] += _as_int(usage.get("cache_read_input_tokens"))

        content = message.get("content")
        if isinstance(content, list):
            for position, block in enumerate(content):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                block_id = block.get("id")
                key = (
                    block_id
                    if isinstance(block_id, str) and block_id
                    else f"row-{index}-block-{position}"
                )
                if key in seen_tool_calls:
                    continue
                seen_tool_calls.add(key)
                name = block.get("name")
                name = name if isinstance(name, str) and name else "unknown"
                tools[name] = tools.get(name, 0) + 1
                workspaces.update(_worktrees_in(block.get("input")))

    total = sum(tokens.values())
    duration = (max(stamps) - min(stamps)) if len(stamps) >= 2 else 0
    role, role_signal = classify_role(directive)

    return {
        "agentIds": agent_ids,
        "role": role,
        "roleSignal": role_signal,
        "spawnDirective": directive_head(directive)[:MAX_DIRECTIVE_CHARS] or None,
        "sessionIds": sorted(session_ids),
        "branches": sorted(branches),
        "workspaces": sorted(workspaces),
        "recordCount": len(records),
        "sidechainRecordCount": sidechain,
        "messageCount": len(seen_messages),
        "tokenUsage": {**tokens, "total": total},
        "toolInvocationCount": len(seen_tool_calls),
        "toolsUsed": _rank_tools(tools),
        "startedAtMs": min(stamps) if stamps else None,
        "completedAtMs": max(stamps) if stamps else None,
        "durationMs": duration,
    }


def _worktrees_in(tool_input: Any) -> set[str]:
    """Worktree names referenced by a tool call's arguments.

    Serialising the whole input rather than reading known keys keeps this
    correct across tools: a path can arrive as ``file_path``, inside a shell
    ``command``, or nested in a list, and a per-tool reader would silently miss
    whichever shape it was not written for.
    """
    if tool_input is None:
        return set()
    try:
        blob = json.dumps(tool_input)
    except (TypeError, ValueError):
        blob = str(tool_input)
    return set(_WORKTREE_RE.findall(blob))


def _as_int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _rank_tools(tools: dict[str, int]) -> list[dict[str, Any]]:
    ranked = sorted(tools.items(), key=lambda item: (-item[1], item[0]))
    return [{"toolName": name, "count": count} for name, count in ranked[:MAX_LISTED_TOOLS]]


def read_task_dir(
    tasks_dir: Path | str,
    *,
    now: float | None = None,
    settle_seconds: float = SETTLE_SECONDS,
) -> list[dict[str, Any]]:
    """Measure every agent transcript in ``tasks_dir``, sorted by agent id.

    Files that hold no JSON object are skipped outright: the directory also
    carries raw tool output, and a text file reported as an agent with zero
    tokens is precisely the measured-looking zero this module exists to end.

    Each agent carries ``settled``, false while its transcript is still being
    appended to. The reading is still returned — dropping it here would hide
    that the agent exists — but a caller must not treat an unsettled one as a
    measurement: it is a lower bound on a run still in progress, and reading it
    is what makes two status-record generations disagree.

    ``settled`` is judged against :func:`settle_clock`, one instant latched per
    process, not against a wall clock sampled inside each read. Two reads of an
    unchanged store therefore agree by construction: both the latched instant
    and the file's mtime are fixed, so nothing is left that could differ. An
    explicit ``now`` still wins, for a caller pinning the boundary itself.
    """
    clock = settle_clock(now)
    directory = Path(tasks_dir)
    try:
        entries = sorted(directory.glob("*.output"))
    except OSError:
        return []

    agents: list[dict[str, Any]] = []
    for path in entries:
        records = _parse_records(path)
        if not records:
            continue
        measured = measure_records(records)
        agent_id = measured["agentIds"][0] if measured["agentIds"] else path.stem
        try:
            target = str(path.resolve())
        except OSError:
            target = str(path)
        try:
            # follow_symlinks: the tasks entry is a link to the real transcript,
            # and it is the transcript that is being written.
            age = clock - path.stat().st_mtime
        except OSError:
            age = 0.0
        agents.append(
            {
                "agentId": agent_id,
                # A locator, never the body: the transcript stays outside the
                # repository and only its path travels into the record.
                "transcriptRef": str(path),
                "resolvedRef": target,
                "settled": age >= settle_seconds,
                **{k: v for k, v in measured.items() if k != "agentIds"},
            }
        )

    agents.sort(key=lambda agent: str(agent["agentId"]))
    return agents


def issue_branch_pattern(issue: int) -> re.Pattern[str]:
    """Match a branch naming ``issue`` without matching ``issue-14410``."""
    return re.compile(rf"issue-0*{int(issue)}(?!\d)")


def issue_workspace_pattern(issue: int) -> re.Pattern[str]:
    """Match a worktree name carrying ``issue`` as a whole number.

    ``w3-1441`` matches; ``w3-14410`` and ``w3-11441`` do not. A substring match
    here would quietly pull a neighbour's tree into this issue's totals.
    """
    return re.compile(rf"(?<!\d)0*{int(issue)}(?!\d)")


def attribution_for(agent: dict[str, Any], issue: int) -> str | None:
    """How ``agent`` is tied to ``issue``, or ``None`` if it is not.

    Returned rather than a bool so the record can state which signal fired,
    even though there is currently one. ``gitBranch`` is deliberately *not*
    consulted: it is session-wide, so it cannot distinguish concurrent agents
    and attributing on it fabricated a 3.3x total (see the module docstring).
    """
    workspace_pattern = issue_workspace_pattern(issue)
    for workspace in agent.get("workspaces", []):
        if workspace_pattern.search(workspace):
            return "worktreePath"
    return None


def agents_for_issue(agents: list[dict[str, Any]], issue: int) -> list[dict[str, Any]]:
    """Those agents tied to ``issue``, each tagged with the signal that tied it.

    May legitimately return more than one — an agent that only read another's
    tree is indistinguishable here from one that worked in it, and on a normal
    issue the *reviewer* worked in it too. Every entry carries the ``role`` its
    spawn directive named, so a caller can select rather than conflate, but
    this function stays a filter: it neither ranks the result nor drops a
    non-executor, since both would be selection decisions made where the record
    cannot show them. Callers must not sum across the result;
    ``run_metrics.capture`` selects the one executor or reports ambiguous.
    """
    attributed: list[dict[str, Any]] = []
    for agent in agents:
        signal = attribution_for(agent, issue)
        if signal is not None:
            attributed.append({**agent, "attributedBy": signal})
    return attributed


__all__ = [
    "DEFAULT_TEMP_BASES",
    "DIRECTIVE_TOKENS",
    "MAX_DIRECTIVE_CHARS",
    "MAX_LISTED_TOOLS",
    "ROLE_EXECUTOR",
    "ROLE_META",
    "ROLE_PLANNER",
    "ROLE_REVIEWER",
    "ROLE_UNKNOWN",
    "SESSION_ENV_VAR",
    "SETTLE_SECONDS",
    "STORE_ENV_VAR",
    "agents_for_issue",
    "attribution_for",
    "classify_role",
    "directive_head",
    "discover_task_dirs",
    "issue_branch_pattern",
    "issue_workspace_pattern",
    "measure_records",
    "project_slug",
    "read_task_dir",
    "reset_settle_clock",
    "settle_clock",
    "slug_candidates",
    "spawn_directive",
]
