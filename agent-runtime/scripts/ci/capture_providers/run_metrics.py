"""Capture provider (#1441): run metrics, measured rather than typed.

``run.metrics`` carries token usage, tool-invocation count and wall-clock read
out of the executor's *persisted transcript*, plus the assigned executor
domain. The distinction from every prior source of these numbers is the whole
point: an agent cannot write the file it is measured from.

The premise was rejected three times before this slice. Three executors
independently reported ``tokenUsage`` and ``executionDurationMs`` unobtainable,
and that report was accepted — which is how ``assemble_evidence.py`` came to
record ``tokenUsage`` permanently unavailable and how a reviewer came to write
an annotated ``{0, 0, 0}`` into the corpus this epic exists to measure. The
transcripts were on disk the entire time, at ``<session-temp>/tasks/*.output``.

Three properties are load-bearing.

**Unavailable is not zero.** With no transcript the block records
``{"available": false, "reason": ...}`` with **no** ``value`` key — the shape
:func:`assemble_evidence.unavailable` established, so a consumer that skips the
``available`` check gets a ``KeyError`` rather than a plausible number. CI has
no session temp directory, so this is the *common* path, and it must never be
mistakable for a measured zero. A zero is exactly as unsourceable as 1,800,000
and is the more convincing of the two.

**Measured wins, and the disagreement is kept.** Where the implementation
artifact self-reports a figure that is also measured, the measurement is what
the record carries and the claim is preserved beside it in ``disagreements[]``.
That gap is not an error path — it is the eval label this epic exists to
produce, so it is recorded rather than resolved.

**It never raises.** A raising provider aborts record generation outright
(``CaptureProviderError``), which is right for a broken provider and wrong for
a missing transcript: the latter is expected and is data, not failure.
Everything that can fail is contained here and surfaces as a gap.

Attribution is by the worktree the agent operated on, never by the session's
``gitBranch`` and never by "the newest session" (#1508). A session commonly
holds several concurrent executors on different issues; crediting all of them
to whichever issue asked inflates this record with a neighbour's work, and did
— by 3.3x, measured. ``task_transcripts`` carries the evidence.

**A multi-agent match is ambiguous, not a sum.** Adding several agents together
asserts they were one run, which nothing on disk establishes: an agent that
merely read another's tree is indistinguishable from one that worked in it. A
sum would produce a total no process ever spent — a fabricated number, which is
strictly worse than an absent one. So the headline goes unavailable, and every
candidate keeps its own measured figures under ``agents[]`` where a reader can
see them.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

# The helper lives one level up in agent-runtime/scripts/ci/. This module is
# loaded two ways — imported as ``capture_providers.run_metrics`` and loaded by
# file path by ``discover_providers`` — and only a sys.path entry works for
# both, since the file-path loader gives the module no package to relate to.
_CI_DIR = Path(__file__).resolve().parent.parent


def _load_reader() -> Any:
    """Import the transcript reader, which lives outside any importable package.

    Done inside a function deliberately: hoisting the ``sys.path`` insert above
    the module-level imports needs a ``# noqa: E402`` suppression, and the
    repo's debt ratchet counts suppression identities rather than a total. One
    unit of tracked, permanent debt is a bad trade for import cosmetics.
    """
    if str(_CI_DIR) not in sys.path:
        sys.path.insert(0, str(_CI_DIR))
    import task_transcripts

    return task_transcripts


task_transcripts = _load_reader()

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import CaptureContext

PROVIDER_NAME = "metrics"

#: Bump when the block shape changes in a way a reader must notice.
BLOCK_SCHEMA_VERSION = 1

#: The one place these numbers may come from. Recorded on every reading so a
#: consumer can tell a measurement from a claim without knowing this module.
OBSERVED_FROM = "task-transcript"

#: Agents listed per record. Counts stay exact; only the listing is bounded, so
#: one long session cannot bloat the single artifact that survives to ``main``.
MAX_LISTED_AGENTS = 25

NO_TRANSCRIPT_REASON = (
    "no persisted task transcript was found for this issue; recorded unavailable "
    "rather than 0 so an unmeasured field cannot read as a measured zero"
)

AMBIGUOUS_REASON = (
    "ambiguous attribution: {count} agents were tied to this issue and nothing on "
    "disk establishes they were one run, so no headline is reported — summing them "
    "would invent a total no process ever spent. Per-agent readings are listed "
    "under agents[]"
)


def observed(value: Any) -> dict[str, Any]:
    """A measured value, with the source that measured it."""
    return {"available": True, "value": value, "observedFrom": OBSERVED_FROM}


def unavailable(reason: str) -> dict[str, Any]:
    """An unmeasured field. Deliberately carries no ``value`` key at all.

    Omitting the key rather than setting it to ``None`` or ``0`` means a
    consumer that forgets to check ``available`` gets a ``KeyError`` instead of
    a plausible number. Same shape as ``assemble_evidence.unavailable``.
    """
    return {"available": False, "reason": reason}


_MISSING = object()


def _default_claims_path(issue: int) -> Path:
    repo_root = _CI_DIR.parent.parent.parent
    return (
        repo_root
        / "agent-runtime"
        / "artifacts"
        / "implementations"
        / f"implementation-issue-{issue}.json"
    )


def _load_claims(issue: int, claims_path: Path | str | None) -> dict[str, Any] | None:
    """The implementation artifact, if one is on disk. Absence is not an error.

    Read only to be *contradicted*: nothing in the returned block is sourced
    from it except the assigned executor domain, which is a routing decision
    rather than a measurement.
    """
    import json

    path = Path(claims_path) if claims_path is not None else _default_claims_path(issue)
    try:
        loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _claimed(claims: dict[str, Any] | None, field: str) -> Any:
    """Look ``field`` up at the artifact's top level, then inside ``metrics``."""
    if not claims:
        return _MISSING
    if field in claims:
        return claims[field]
    metrics = claims.get("metrics")
    if isinstance(metrics, dict) and field in metrics:
        return metrics[field]
    return _MISSING


def _claimed_token_total(claims: dict[str, Any] | None) -> Any:
    usage = _claimed(claims, "tokenUsage")
    if not isinstance(usage, dict):
        return _MISSING
    # An unavailable claim is not a competing number; there is nothing to
    # disagree with, so it is not a disagreement.
    if usage.get("available") is False:
        return _MISSING
    return usage.get("total", _MISSING)


def _executor_domain(
    claims: dict[str, Any] | None, review: dict[str, Any]
) -> tuple[str | None, str]:
    """The assigned domain and where it was read from — never a guess.

    Its absence is recorded as ``None``/``"unknown"`` rather than filled in
    from the issue's shape, because a domain inferred by this module would be
    the same class of typed-not-measured value the block exists to displace.
    """
    for source, holder in (("implementation-artifact", claims), ("review", review)):
        if not isinstance(holder, dict):
            continue
        value = holder.get("executorDomain")
        if isinstance(value, str) and value.strip():
            return value.strip(), source
    return None, "unknown"


def _disagreements(
    claims: dict[str, Any] | None,
    measured: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Preserve each self-reported figure that the measurement contradicts.

    An agreeing claim produces no entry, so a non-empty list always means
    something. When nothing was measured, a claim is recorded as unobservable
    rather than silently dropped — including a claimed zero, which is a claim
    like any other.
    """
    comparisons: tuple[tuple[str, Any], ...] = (
        ("tokenUsage.total", _claimed_token_total(claims)),
        ("toolInvocationCount", _claimed(claims, "toolInvocationCount")),
        ("executionDurationMs", _claimed(claims, "executionDurationMs")),
    )

    entries: list[dict[str, Any]] = []
    for field, claimed in comparisons:
        if claimed is _MISSING:
            continue
        if measured is None:
            entries.append(
                {
                    "field": field,
                    "claimed": claimed,
                    "observed": None,
                    "observedFrom": "unavailable",
                    "reason": NO_TRANSCRIPT_REASON,
                    "resolution": "unobservable",
                }
            )
            continue
        observed_value = measured[field]
        if claimed == observed_value:
            continue
        entries.append(
            {
                "field": field,
                "claimed": claimed,
                "observed": observed_value,
                "observedFrom": OBSERVED_FROM,
                "resolution": "observed",
            }
        )
    return entries


def _merge(agents: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate the selected agents into one reading for the run."""
    tokens = {"input": 0, "output": 0, "cacheCreation": 0, "cacheRead": 0, "total": 0}
    tools: dict[str, int] = {}
    tool_calls = 0
    starts: list[int] = []
    ends: list[int] = []

    for agent in agents:
        for key in tokens:
            tokens[key] += int(agent["tokenUsage"].get(key, 0))
        tool_calls += int(agent["toolInvocationCount"])
        for entry in agent["toolsUsed"]:
            tools[entry["toolName"]] = tools.get(entry["toolName"], 0) + int(entry["count"])
        if agent["startedAtMs"] is not None:
            starts.append(int(agent["startedAtMs"]))
        if agent["completedAtMs"] is not None:
            ends.append(int(agent["completedAtMs"]))

    duration = (max(ends) - min(starts)) if starts and ends else 0
    ranked = sorted(tools.items(), key=lambda item: (-item[1], item[0]))
    return {
        "tokenUsage.total": tokens["total"],
        "tokenUsage": tokens,
        "toolInvocationCount": tool_calls,
        "toolsUsed": [{"toolName": name, "count": count} for name, count in ranked],
        "executionDurationMs": duration,
        "startedAtMs": min(starts) if starts else None,
        "completedAtMs": max(ends) if ends else None,
    }


def _strip(agent: dict[str, Any]) -> dict[str, Any]:
    """The per-agent detail worth committing: a locator and its counts."""
    return {
        "agentId": agent["agentId"],
        "transcriptRef": agent["transcriptRef"],
        "sessionIds": agent["sessionIds"],
        "settled": agent.get("settled", True),
        "branches": agent["branches"],
        "workspaces": agent["workspaces"],
        "attributedBy": agent.get("attributedBy"),
        "recordCount": agent["recordCount"],
        "sidechainRecordCount": agent["sidechainRecordCount"],
        "messageCount": agent["messageCount"],
        "tokenUsage": agent["tokenUsage"],
        "toolInvocationCount": agent["toolInvocationCount"],
        "toolsUsed": agent["toolsUsed"],
        "durationMs": agent["durationMs"],
    }


def capture(
    context: CaptureContext,
    *,
    repo_root: Path | str | None = None,
    environ: dict[str, str] | None = None,
    temp_bases: tuple[str, ...] | None = None,
    claims: dict[str, Any] | None = None,
    claims_path: Path | str | None = None,
) -> dict[str, Any]:
    """Return the ``run.metrics`` block for ``context.issue``.

    Keyword-only seams exist so this is testable without a real session temp
    directory, a real ``$HOME`` or a real transcript on disk — the house shape
    for providers, and the only way to exercise the CI-shaped absence path.
    """
    root = Path(repo_root) if repo_root is not None else _CI_DIR.parent.parent.parent
    if claims is None:
        claims = _load_claims(context.issue, claims_path)

    domain, domain_source = _executor_domain(claims, context.review)

    gaps: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    in_flight: list[str] = []
    task_dirs: list[Path] = []
    # A broken store is a gap, not an abort: this provider must never raise, so
    # the catch is deliberately blind. BLE001 is not in the selected rule set,
    # so no suppression comment is needed (one would be permanent ratcheted debt).
    try:
        task_dirs = task_transcripts.discover_task_dirs(
            repo_root=root, environ=environ, temp_bases=temp_bases
        )
    except Exception as exc:
        gaps.append({"reason": "task-store-unreadable", "detail": f"{type(exc).__name__}: {exc}"})

    scanned = 0
    for tasks_dir in task_dirs:
        try:
            found = task_transcripts.read_task_dir(tasks_dir)
        except Exception as exc:
            gaps.append(
                {
                    "reason": "task-dir-unreadable",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "path": str(tasks_dir),
                }
            )
            continue
        scanned += len(found)
        for agent in task_transcripts.agents_for_issue(found, context.issue):
            # A transcript still being appended to is a run in progress, not a
            # measurement — and reading one makes two generations of the same
            # record disagree, breaking capture_run_block's idempotency promise.
            if agent.get("settled", True):
                agents.append(agent)
            else:
                in_flight.append(str(agent["agentId"]))

    agents.sort(key=lambda agent: str(agent["agentId"]))
    if in_flight:
        gaps.append(
            {
                "reason": "in-flight-transcript",
                "detail": (
                    "attributed agents whose transcript is still being written; a "
                    "running agent has not yet spent what it will spend, so its "
                    "reading is a lower bound and is not reported as a measurement"
                ),
                "agents": sorted(in_flight),
            }
        )

    # Exactly one attributed agent is a reading. Zero is an absence. More than
    # one is an ambiguity, and all three are distinct states in the record —
    # collapsing the last two into "not measured" would hide that candidates
    # exist, and collapsing it into a sum would invent a number.
    measured = _merge(agents) if len(agents) == 1 else None
    tools_used: list[dict[str, Any]] = []

    if len(agents) > 1:
        status = "ambiguous"
        reason = AMBIGUOUS_REASON.format(count=len(agents))
        gaps.append(
            {
                "reason": "ambiguous-attribution",
                "detail": reason,
                "candidates": [str(agent["agentId"]) for agent in agents],
            }
        )
        readings = {
            "tokenUsage": unavailable(reason),
            "toolInvocationCount": unavailable(reason),
            "executionDurationMs": unavailable(reason),
        }
    elif measured is None:
        status = "not-measured"
        gaps.append(
            {
                "reason": "no-transcript-for-issue" if scanned else "no-persisted-task-transcripts",
                "detail": NO_TRANSCRIPT_REASON,
                "agentsScanned": scanned,
            }
        )
        readings = {
            "tokenUsage": unavailable(NO_TRANSCRIPT_REASON),
            "toolInvocationCount": unavailable(NO_TRANSCRIPT_REASON),
            "executionDurationMs": unavailable(NO_TRANSCRIPT_REASON),
        }
    else:
        status = "measured"
        readings = {
            "tokenUsage": observed(measured["tokenUsage"]),
            "toolInvocationCount": observed(measured["toolInvocationCount"]),
            "executionDurationMs": observed(measured["executionDurationMs"]),
        }
        tools_used = measured["toolsUsed"]

    if domain is None:
        gaps.append({"reason": "executor-domain-unknown", "detail": "no artifact named a domain"})

    return {
        "schemaVersion": BLOCK_SCHEMA_VERSION,
        "status": status,
        "executorDomain": domain,
        "executorDomainSource": domain_source,
        "source": {
            "kind": OBSERVED_FROM,
            "taskDirs": [str(path) for path in task_dirs[:MAX_LISTED_AGENTS]],
            "agentsScanned": scanned,
            "agentsAttributed": len(agents),
            "attributedBy": f".worktrees path naming issue-{context.issue}",
        },
        **readings,
        "toolsUsed": tools_used,
        "agents": [_strip(agent) for agent in agents[:MAX_LISTED_AGENTS]],
        "disagreements": _disagreements(claims, measured),
        "gaps": gaps,
    }
