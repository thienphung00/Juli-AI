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

    for index, record in enumerate(records):
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

    return {
        "agentIds": agent_ids,
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
    """
    clock = time.time() if now is None else now
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
    tree is indistinguishable here from one that worked in it. Callers must not
    sum across the result without deciding what a multi-agent match means;
    ``run_metrics.capture`` reports it as ambiguous rather than adding them up.
    """
    attributed: list[dict[str, Any]] = []
    for agent in agents:
        signal = attribution_for(agent, issue)
        if signal is not None:
            attributed.append({**agent, "attributedBy": signal})
    return attributed


__all__ = [
    "DEFAULT_TEMP_BASES",
    "MAX_LISTED_TOOLS",
    "SESSION_ENV_VAR",
    "SETTLE_SECONDS",
    "STORE_ENV_VAR",
    "agents_for_issue",
    "attribution_for",
    "discover_task_dirs",
    "issue_branch_pattern",
    "issue_workspace_pattern",
    "measure_records",
    "project_slug",
    "read_task_dir",
    "slug_candidates",
]
