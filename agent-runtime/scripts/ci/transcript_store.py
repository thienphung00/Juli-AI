#!/usr/bin/env python3
"""Redact-at-capture persistence for subagent transcripts (#1446).

Why this exists
---------------
Every ``Agent`` tool result in the harness's transcript corpus (187 of them) is
launch metadata: the parent records that it *delegated*, never what the delegate
did. So every direct behavioural observation the harness owns is of the parent
orchestrator, executor behaviour is visible only through artifacts and git, and
questions like "do weaker executors bypass more?" are formally unanswerable at
the sample sizes available. Persisting the subagent's own transcript is the
missing input.

Two constraints shape the whole module.

**Redact at capture, not at read.** A transcript is a verbatim log of a shell
session; it can contain API keys, tokens, connection strings and PII. Redacting
on the way out would mean the unredacted bytes still exist on disk somewhere,
which is the same exposure with extra steps. :func:`persist_transcript` writes
only the redacted text, and the count of what it removed travels with the entry
so a reader can tell "clean" from "scrubbed".

**The body never enters the repository.** ``run{}`` gets a *locator*
(``file:/abs/path``) and a digest; the bytes stay in a store outside the git
working tree. :func:`resolve_store_root` refuses any root inside the repo — a
gitignore rule would be a convention, and conventions lose to ``git add -f``.

The store root is machine-local by default (``~/.juli/transcripts``), which is a
real limitation and is stated plainly rather than hidden: a peer slice found
1176 of 2457 dataset rows already depending on an unbacked ``~/.claude/projects``.
``JULI_TRANSCRIPT_STORE`` exists so a deployment can point the store at a
durable, shareable volume without touching this code.

Layout::

    <root>/issue-<N>/index.json                 # entries, sorted, no bodies
    <root>/issue-<N>/<agent>--<sessionId>.jsonl # redacted body

Stdlib only, by policy: this module is imported during status-record generation
in CI, where the dependency set is ``./backend[dev] -c backend/constraints.txt``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: Bump when the entry shape changes in a way a reader must notice.
ENTRY_SCHEMA_VERSION = 1

#: Env var pointing the store at a durable volume instead of ``~/.juli``.
STORE_ENV_VAR = "JULI_TRANSCRIPT_STORE"

#: Marker written in place of a redacted value. Also the idempotence guard —
#: a value already carrying it is never redacted (and never re-counted) twice.
REDACTION_PREFIX = "[REDACTED:"

#: Commands retained verbatim per entry. The true count is always reported;
#: only the listing is bounded, so a pathological session cannot inflate the
#: one artifact that survives to ``main``.
MAX_COMMANDS_PER_ENTRY = 200

_INDEX_NAME = "index.json"


class TranscriptStoreError(RuntimeError):
    """A transcript could not be persisted, or was asked to land unsafely."""


# --- redaction -----------------------------------------------------------

# (kind, pattern, group-to-replace). Specific shapes run before the generic
# ``key = value`` rule so a key is named by what it is, not by its assignment.
_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    (
        "privateKey",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
        0,
    ),
    ("anthropicKey", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), 0),
    ("openaiKey", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), 0),
    ("githubToken", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), 0),
    ("slackToken", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), 0),
    ("awsAccessKeyId", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{12,}"), 0),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{4,}"), 0),
    ("bearerToken", re.compile(r"(?i)\b(?:bearer|token)\s+([A-Za-z0-9._\-]{16,})"), 1),
    # user:password@host in any URL scheme.
    ("urlPassword", re.compile(r"(?i)\b[a-z][a-z0-9+.\-]*://[^\s/:@]+:([^\s/@]{3,})@"), 1),
    (
        "credential",
        re.compile(
            r"(?i)\b(?:password|passwd|pwd|secret|api[_\-]?key|access[_\-]?key|"
            r"auth[_\-]?token|client[_\-]?secret|[a-z0-9_\-]*token)\b"
            r"\s*(?:[:=]|=>)\s*[\"']?([^\s\"'&,}\\]{6,})"
        ),
        1,
    ),
)


def redact(text: str) -> tuple[str, dict[str, int]]:
    """Return ``text`` with credential-shaped values replaced, plus a tally.

    The tally is per pattern kind and is the record's honesty signal: a reader
    of ``run.transcripts`` can distinguish a transcript that had nothing to hide
    from one that was scrubbed, without ever seeing what was scrubbed.
    """
    counts: dict[str, int] = {}

    for kind, pattern, group in _PATTERNS:

        def _sub(match: re.Match[str], kind: str = kind, group: int = group) -> str:
            value = match.group(group)
            if value is None or REDACTION_PREFIX in value:
                return match.group(0)
            counts[kind] = counts.get(kind, 0) + 1
            whole = match.group(0)
            offset = match.start(0)
            start, end = match.start(group) - offset, match.end(group) - offset
            return f"{whole[:start]}{REDACTION_PREFIX}{kind}]{whole[end:]}"

        text = pattern.sub(_sub, text)

    return text, dict(sorted(counts.items()))


def sha256_text(text: str) -> str:
    """Digest of the *persisted* (redacted) text, so refs cannot drift."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- store location ------------------------------------------------------


def repository_root(start: Path | None = None) -> Path:
    """Nearest ancestor holding ``.git`` (a directory, or a worktree's file)."""
    current = (start or Path(__file__)).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current if current.is_dir() else current.parent


def default_store_root(environ: dict[str, str] | None = None) -> Path:
    """Where transcripts live when no root is passed.

    ``JULI_TRANSCRIPT_STORE`` first, then ``~/.juli/transcripts``. Machine-local
    by default and deliberately outside any repository — see the module
    docstring for why that trade is made in this direction.
    """
    env = os.environ if environ is None else environ
    configured = env.get(STORE_ENV_VAR)
    if configured:
        return Path(configured).expanduser().resolve()
    home = env.get("HOME") or os.path.expanduser("~")
    return (Path(home) / ".juli" / "transcripts").resolve()


def resolve_store_root(
    store_root: Path | str | None = None,
    *,
    environ: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Resolve and *vet* the store root.

    Raises :class:`TranscriptStoreError` when the root sits inside the git
    working tree. That is the enforcement of "no transcript body is ever
    committed": not a gitignore entry, which any ``-f`` defeats, but a path
    the writer refuses to write to.
    """
    root = Path(store_root).expanduser().resolve() if store_root else default_store_root(environ)
    repo = (repo_root or repository_root()).resolve()
    if root == repo or repo in root.parents:
        raise TranscriptStoreError(
            f"refusing to persist transcripts at {root}: it is inside the git working "
            f"tree at {repo}. Transcript bodies must never be committable — set "
            f"{STORE_ENV_VAR} to a path outside the repository."
        )
    return root


def issue_dir(issue: int, root: Path) -> Path:
    return root / f"issue-{int(issue)}"


# --- command extraction --------------------------------------------------


def _walk_tool_uses(node: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "tool_use" and isinstance(node.get("input"), dict):
            found.append(node)
        for value in node.values():
            found.extend(_walk_tool_uses(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_tool_uses(item))
    return found


def extract_commands(text: str) -> list[str]:
    """Shell commands invoked in a transcript, in order, duplicates kept.

    Tolerant by design: a transcript is an append-only log that may be
    truncated mid-write, and a half-written final line must degrade to "one
    command not seen" rather than to an exception that aborts record
    generation.
    """
    commands: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for tool_use in _walk_tool_uses(event):
            if tool_use.get("name") not in {"Bash", "bash"}:
                continue
            command = tool_use["input"].get("command")
            if isinstance(command, str) and command.strip():
                commands.append(command.strip())
    return commands


# --- persistence ---------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._\-]", "-", value.strip())
    return cleaned.strip("-") or "unknown"


def load_index(
    issue: int,
    *,
    store_root: Path | str | None = None,
    environ: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> list[dict[str, Any]]:
    """Entries persisted for ``issue``. Missing store or index -> ``[]``.

    A missing store is the normal state in CI (no ``$HOME``, shallow checkout),
    and it is a *gap*, not an error — the caller's job is to say so, which is
    exactly what the provider does rather than reporting coverage it lacks.
    """
    try:
        root = resolve_store_root(store_root, environ=environ, repo_root=repo_root)
    except TranscriptStoreError:
        return []
    index_path = issue_dir(issue, root) / _INDEX_NAME
    if not index_path.is_file():
        return []
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _write_index(issue: int, root: Path, entries: list[dict[str, Any]]) -> None:
    ordered = sorted(entries, key=lambda e: (str(e.get("agent")), str(e.get("sessionId"))))
    payload = {
        "schemaVersion": ENTRY_SCHEMA_VERSION,
        "issue": int(issue),
        "entries": ordered,
    }
    index_path = issue_dir(issue, root) / _INDEX_NAME
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def persist_transcript(
    *,
    issue: int,
    agent: str,
    text: str | None = None,
    source: Path | str | None = None,
    session_id: str | None = None,
    store_root: Path | str | None = None,
    environ: dict[str, str] | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Redact a transcript, write it outside the repo, and index the reference.

    Exactly one of ``text`` or ``source`` is required. Re-persisting the same
    ``(agent, sessionId)`` replaces its entry, so a re-run overwrites rather
    than accumulating half-truths.
    """
    if (text is None) == (source is None):
        raise TranscriptStoreError("persist_transcript needs exactly one of text= or source=")

    if source is not None:
        source_path = Path(source).expanduser()
        try:
            text = source_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise TranscriptStoreError(
                f"cannot read transcript source {source_path}: {exc}"
            ) from exc
        session_id = session_id or source_path.stem

    assert text is not None  # narrowed by the guard above
    root = resolve_store_root(store_root, environ=environ, repo_root=repo_root)
    redacted, redactions = redact(text)
    commands = extract_commands(redacted)
    session = _safe_component(session_id or sha256_text(redacted)[:12])
    agent_component = _safe_component(agent)

    target_dir = issue_dir(issue, root)
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{agent_component}--{session}.jsonl"
        target.write_text(redacted, encoding="utf-8")
    except OSError as exc:
        raise TranscriptStoreError(f"cannot write transcript under {target_dir}: {exc}") from exc

    entry: dict[str, Any] = {
        "schemaVersion": ENTRY_SCHEMA_VERSION,
        "issue": int(issue),
        "agent": agent,
        "sessionId": session,
        # A locator, never the body. The record cites this; the bytes stay here.
        "transcriptRef": f"file:{target}",
        "sha256": sha256_text(redacted),
        "bytes": len(redacted.encode("utf-8")),
        "redactions": redactions,
        "redactionCount": sum(redactions.values()),
        "commandCount": len(commands),
        "commands": commands[:MAX_COMMANDS_PER_ENTRY],
        "commandsTruncated": len(commands) > MAX_COMMANDS_PER_ENTRY,
        "persisted": True,
        "persistedAt": _utc_now_iso(),
    }

    existing = [
        item
        for item in load_index(issue, store_root=root, repo_root=repo_root)
        if not (item.get("agent") == agent and item.get("sessionId") == session)
    ]
    _write_index(issue, root, [*existing, entry])
    return entry


def executed_commands(
    issue: int,
    *,
    store_root: Path | str | None = None,
    environ: dict[str, str] | None = None,
    repo_root: Path | None = None,
    agents: tuple[str, ...] | None = None,
) -> list[str]:
    """Every command observed for ``issue``, parent and executors alike.

    This is the seam the claim-vs-executed check (#1443) reads: before it, a
    claim could only be matched against parent commands, so an executor's work
    was unmatchable by construction.
    """
    commands: list[str] = []
    for entry in load_index(issue, store_root=store_root, environ=environ, repo_root=repo_root):
        if agents is not None and entry.get("agent") not in agents:
            continue
        for command in entry.get("commands") or []:
            if isinstance(command, str):
                commands.append(command)
    return commands


# --- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persist a redacted subagent transcript.")
    parser.add_argument("--issue", type=int, required=True)
    parser.add_argument("--agent", required=True, help="e.g. executor-backend, review, parent")
    parser.add_argument("--source", required=True, help="path to the transcript .jsonl")
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--store-root", default=None)
    args = parser.parse_args(argv)

    try:
        entry = persist_transcript(
            issue=args.issue,
            agent=args.agent,
            source=args.source,
            session_id=args.session_id,
            store_root=args.store_root,
        )
    except TranscriptStoreError as exc:
        print(f"transcript-store: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(entry, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
