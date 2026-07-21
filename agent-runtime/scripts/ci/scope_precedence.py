"""Scope precedence chain validation for issue context caches."""

from __future__ import annotations

import re
from typing import Any

EXECUTION_MD = "EXECUTION.md"
SLICE_IN_REASON_RE = re.compile(r"\b([A-Z0-9]+(?:-[A-Z0-9]+)+)\b")

RANK_EXECUTION = 1
RANK_PARENT = 2
RANK_CHILD = 3
RANK_HANDOFF = 4

RESOLUTION_BY_RANK: dict[int, str] = {
    RANK_EXECUTION: "refresh_epic_cache",
    RANK_PARENT: "refresh_epic_cache",
    RANK_CHILD: "refresh_issue_cache",
    RANK_HANDOFF: "refresh_epic_cache",
}


def parent_cache_source(parent_issue_id: int) -> str:
    return f"parent-cache-issue-{parent_issue_id}"


def child_issue_source(child_issue_id: int) -> str:
    return f"GitHub issue #{child_issue_id}"


def normalize_authority_source(source: str) -> str:
    return source.strip()


def slice_ids_in_reason(reason: str) -> set[str]:
    return set(SLICE_IN_REASON_RE.findall(reason))


def build_expected_authority_chain(
    *,
    parent_issue_id: int,
    child_issue_id: int,
    handoff_path: str,
    slice_id: str | None,
) -> list[dict[str, Any]]:
    execution_reason = (
        f"Phase/slice law — {slice_id}" if slice_id else "Phase/slice law"
    )
    return [
        {
            "rank": RANK_EXECUTION,
            "source": EXECUTION_MD,
            "reason": execution_reason,
            "sliceId": slice_id,
        },
        {
            "rank": RANK_PARENT,
            "source": parent_cache_source(parent_issue_id),
            "reason": "Epic constant",
            "sliceId": None,
        },
        {
            "rank": RANK_CHILD,
            "source": child_issue_source(child_issue_id),
            "reason": "Child acceptance criteria",
            "sliceId": None,
        },
        {
            "rank": RANK_HANDOFF,
            "source": handoff_path,
            "reason": "Epic handoff",
            "sliceId": None,
        },
    ]


def cached_chain_by_rank(cached_chain: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    indexed: dict[int, dict[str, Any]] = {}
    for entry in cached_chain:
        rank = entry.get("rank")
        if isinstance(rank, int):
            indexed[rank] = entry
    return indexed


def compare_authority_chains(
    cached_chain: list[dict[str, Any]],
    expected_chain: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return structural conflicts between cached and live authority chains."""
    conflicts: list[dict[str, Any]] = []
    cached_by_rank = cached_chain_by_rank(cached_chain)

    for expected in expected_chain:
        rank = expected["rank"]
        cached = cached_by_rank.get(rank)
        if cached is None:
            conflicts.append(
                {
                    "rank": rank,
                    "type": "missing_entry",
                    "expectedSource": expected["source"],
                    "message": (
                        f"Rank {rank} missing from cached authorityChain "
                        f"(expected {expected['source']})"
                    ),
                }
            )
            continue

        cached_source = normalize_authority_source(str(cached.get("source", "")))
        expected_source = normalize_authority_source(expected["source"])
        if cached_source != expected_source:
            conflicts.append(
                {
                    "rank": rank,
                    "type": "source_mismatch",
                    "expectedSource": expected_source,
                    "cachedSource": cached_source,
                    "message": (
                        f"Rank {rank} source mismatch: cached {cached_source!r}, "
                        f"live {expected_source!r}"
                    ),
                }
            )

        if rank == RANK_EXECUTION and expected.get("sliceId"):
            slice_id = str(expected["sliceId"])
            reason = str(cached.get("reason", ""))
            if slice_id not in slice_ids_in_reason(reason):
                conflicts.append(
                    {
                        "rank": rank,
                        "type": "slice_omitted",
                        "expectedSliceId": slice_id,
                        "cachedReason": reason,
                        "message": (
                            f"Cached EXECUTION.md authority omits live slice {slice_id}"
                        ),
                    }
                )

    return conflicts


def resolution_for_conflicts(conflicts: list[dict[str, Any]]) -> str:
    if not conflicts:
        return ""
    ranks = sorted({item["rank"] for item in conflicts})
    if len(ranks) == 1 and any(item["type"] == "ambiguous_tie" for item in conflicts):
        return "hitl_confirm"
    primary_rank = ranks[0]
    return RESOLUTION_BY_RANK.get(primary_rank, "refresh_epic_cache")


def validate_authority_chain(
    *,
    child_cache: dict[str, Any],
    parent_issue_id: int,
    child_issue_id: int,
    handoff_path: str,
    slice_id: str | None,
) -> tuple[bool, str, dict[str, Any]]:
    cached_chain = child_cache.get("authorityChain") or []
    expected_chain = build_expected_authority_chain(
        parent_issue_id=parent_issue_id,
        child_issue_id=child_issue_id,
        handoff_path=handoff_path,
        slice_id=slice_id,
    )
    conflicts = compare_authority_chains(cached_chain, expected_chain)

    details: dict[str, Any] = {
        "issueId": child_issue_id,
        "parentIssueId": parent_issue_id,
        "sliceId": slice_id,
        "expectedAuthorityChain": expected_chain,
        "cachedAuthorityChain": cached_chain,
        "conflicts": conflicts,
        "halt": bool(conflicts),
        "cacheStatus": "partial" if conflicts else child_cache.get("cacheStatus"),
        "resolution": resolution_for_conflicts(conflicts),
        "conflictingRank": conflicts[0]["rank"] if conflicts else None,
    }

    if not conflicts:
        return True, "Cached authorityChain matches live upstream sources", details

    primary = conflicts[0]
    resolution = details["resolution"]
    action = {
        "refresh_epic_cache": "Refresh epic scope (parent cache) for conflicting rank only.",
        "refresh_issue_cache": "Refresh issue scope (child cache) for conflicting rank only.",
        "hitl_confirm": "Ask one HITL confirm question, then write cache.",
    }.get(resolution, "Refresh conflicting authority rank.")
    message = (
        f"Authority chain conflict at rank {primary['rank']}: {primary['message']}. "
        f"Halt Executor; set cacheStatus: partial; resolution: {resolution}. "
        f"{action} Record outcome in resolvedDecisions[]."
    )
    return False, message, details
