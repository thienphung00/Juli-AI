"""Resolve parent/child linkage fields for workflow prompt cache gates."""

from __future__ import annotations

from workflow_cache_store import DEFAULT_ARTIFACTS_REL


def resolve_slice_id(parent_cache: dict, child_cache: dict) -> str | None:
    """Prefer child parentLinkage.sliceId — siblings under one parent may differ.

    Parent.sliceId remains the epic default (or last-written) and must not
    override a child's unique Focus slice for authority / load-profile gates.
    """
    linkage = child_cache.get("parentLinkage") or {}
    child_slice = linkage.get("sliceId")
    if isinstance(child_slice, str) and child_slice.strip():
        return child_slice.strip()
    parent_slice = parent_cache.get("sliceId")
    if isinstance(parent_slice, str) and parent_slice.strip():
        return parent_slice.strip()
    return None


def resolve_handoff_path(parent_cache: dict, child_cache: dict) -> str:
    handoff = parent_cache.get("handoffPath")
    if isinstance(handoff, str) and handoff.strip():
        return handoff.strip()
    linkage = child_cache.get("parentLinkage") or {}
    linkage_handoff = linkage.get("handoffPath")
    if isinstance(linkage_handoff, str) and linkage_handoff.strip():
        return linkage_handoff.strip()
    raise ValueError("handoffPath missing from parent and child workflow caches")


def resolve_scope_alignment_path(child_cache: dict, issue_id: int) -> str:
    scope_path = child_cache.get("scopeAlignmentPath")
    if isinstance(scope_path, str) and scope_path.strip():
        return scope_path.strip()
    return f"agent-runtime/artifacts/{DEFAULT_ARTIFACTS_REL.name}/scope-alignment-issue-{issue_id}.md"
