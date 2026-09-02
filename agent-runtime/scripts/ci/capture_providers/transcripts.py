"""Capture provider (#1446): the executor's transcript, by reference.

``run.transcripts`` answers one question the harness could not previously ask:
*what did the delegate actually do?* Every ``Agent`` tool result in the corpus
is launch metadata, so until a subagent transcript is persisted, executor
behaviour is inferred from artifacts and git and never observed. This block
attaches the persisted transcript's **locator** — never its body — plus the
commands observed in it, which is what lets the claim-vs-executed check (#1443)
extend from parent commands to executor commands.

Two properties are load-bearing.

**Absence is reported, never assumed.** Most historical runs have no persisted
transcript, and CI has neither ``$HOME`` nor a store. In that state the block is
``status: "not-persisted"`` with named gaps and ``coverage.complete: false`` —
it must never look like full coverage. Reporting completeness nobody verified is
the exact defect this epic exists to end, so the degraded path is the one with
the loudest shape.

**It never raises.** A raising provider aborts record generation outright
(``CaptureProviderError``), which is right for a broken provider and wrong for a
missing transcript: the latter is the common, expected state and is data, not
failure. Everything that can fail is contained here and surfaces as a gap.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# The helper lives one level up in agent-runtime/scripts/ci/. This module is
# loaded two ways — imported as ``capture_providers.transcripts`` and loaded by
# file path by ``discover_providers`` — and only a sys.path entry works for
# both, since the file-path loader gives the module no package to relate to.
_CI_DIR = Path(__file__).resolve().parent.parent
if str(_CI_DIR) not in sys.path:
    sys.path.insert(0, str(_CI_DIR))

import transcript_store  # noqa: E402

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import CaptureContext

PROVIDER_NAME = "transcripts"

#: Bump when the block shape changes in a way a reader must notice.
BLOCK_SCHEMA_VERSION = 1

#: Agent names treated as the orchestrator rather than a delegate.
PARENT_AGENTS = frozenset({"parent", "orchestrator", "main"})

#: Commands listed per tier in the record. The true counts are always exact;
#: only the listings are bounded, so one long session cannot bloat the single
#: artifact that survives to ``main``.
MAX_LISTED_COMMANDS = 100


def _is_executor(agent: str) -> bool:
    return agent.lower() not in PARENT_AGENTS


def _expected_from_review(review: dict[str, Any]) -> tuple[str, ...]:
    """Best-effort name for the delegate this issue claims to have used.

    The review body carries no executor domain field, so this is a hint, not a
    contract. When nothing is known the gap is still reported — under the
    honest placeholder ``"executor"`` rather than being dropped for want of a
    name.
    """
    for key in ("executorDomain", "executorAgent", "reviewedBy"):
        value = review.get(key)
        if isinstance(value, str) and value.strip():
            name = value.strip()
            return (name if name.startswith("executor") else f"executor-{name}",)
    return ("executor",)


def capture(
    context: CaptureContext,
    *,
    store_root: Path | str | None = None,
    environ: dict[str, str] | None = None,
    expected_agents: tuple[str, ...] | None = None,
    index_loader: Any = None,
) -> dict[str, Any]:
    """Return the ``run.transcripts`` block for ``context.issue``.

    Keyword-only seams (``store_root``, ``environ``, ``expected_agents``,
    ``index_loader``) exist so this is testable without a real store, a real
    ``$HOME`` or a real transcript on disk — the house shape for providers.
    """
    loader = index_loader or transcript_store.load_index
    try:
        entries = loader(context.issue, store_root=store_root, environ=environ)
    except Exception as exc:  # noqa: BLE001 — a broken store is a gap, not an abort
        entries = []
        load_error: str | None = f"{type(exc).__name__}: {exc}"
    else:
        load_error = None

    executors: list[dict[str, Any]] = []
    parent_commands: list[str] = []
    executor_commands: list[str] = []
    parent_count = 0

    for entry in entries:
        agent = str(entry.get("agent") or "unknown")
        commands = [c for c in (entry.get("commands") or []) if isinstance(c, str)]
        count = int(entry.get("commandCount") or len(commands))
        if _is_executor(agent):
            executors.append(
                {
                    "agent": agent,
                    "sessionId": entry.get("sessionId"),
                    # A locator. The body stays outside the repository by
                    # construction (transcript_store.resolve_store_root).
                    "transcriptRef": entry.get("transcriptRef"),
                    "sha256": entry.get("sha256"),
                    "bytes": entry.get("bytes"),
                    "commandCount": count,
                    "redactionCount": int(entry.get("redactionCount") or 0),
                    "persisted": True,
                }
            )
            executor_commands.extend(commands)
        else:
            parent_commands.extend(commands)
            parent_count += count

    executors.sort(key=lambda item: (str(item["agent"]), str(item["sessionId"])))
    persisted_agents = {item["agent"] for item in executors}

    expected = expected_agents
    if expected is None:
        expected = _expected_from_review(context.review) if not executors else ()

    gaps: list[dict[str, Any]] = [
        {"agent": agent, "reason": "no-transcript-persisted"}
        for agent in expected
        if agent not in persisted_agents
    ]
    if load_error is not None:
        gaps.append({"agent": "*", "reason": "transcript-store-unreadable", "detail": load_error})

    return {
        "schemaVersion": BLOCK_SCHEMA_VERSION,
        "status": "persisted" if executors else "not-persisted",
        "executors": executors,
        "executorCount": len(executors),
        # True whenever the only observable tier is the parent — the state the
        # whole corpus was in before this slice.
        "parentOnly": not executors,
        "commands": {
            "parent": parent_count,
            "executor": len(executor_commands),
            "parentCommands": parent_commands[:MAX_LISTED_COMMANDS],
            "executorCommands": executor_commands[:MAX_LISTED_COMMANDS],
            "includesExecutorCommands": bool(executor_commands),
        },
        "coverage": {
            "executorsPersisted": len(executors),
            "executorsExpected": len(expected) if expected else len(executors),
            # Never true on an empty store: absence of evidence is recorded as
            # absence, not as coverage.
            "complete": bool(executors) and not gaps,
            "gaps": gaps,
        },
    }
