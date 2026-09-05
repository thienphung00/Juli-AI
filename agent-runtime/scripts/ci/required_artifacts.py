#!/usr/bin/env python3
"""CI-computed required-artifact set for the phase-run correlation gate (#1439).

Why this module exists
----------------------
``check_phase_run_correlation`` used to read its ``required`` flags out of the
release-evidence plan — a file **the same agent loop writes**. 7 of 127 committed
plans were born with ``requiredArtifacts.intentReview: false``, so the gate's own
configuration sat inside the graded agent's write path and a missing artifact
resolved to ``"skipped"`` with a PASS verdict.

The required set is therefore computed here, from two inputs the loop does not
author: the **CI tier** (``classify-tier`` in ``.github/workflows/pr.yml``) and the
**head branch** (``resolve-issue``'s ``github.head_ref``). The plan is still read,
but only as evidence — it is recorded in the gate details and never consulted for
the verdict. See ADR-lock 6 of the #1434 epic: no gate may be satisfied by editing
gate configuration.

Rejected alternative (#1439): keep the plan and diff it against an expected set.
That detects tampering rather than preventing it, and the observed defect is plans
*born* pre-relaxed, which a diff against the loop's own prior state cannot catch.

Fail-closed
-----------
``compute_required_artifacts`` raises :class:`UnresolvableTierError` for any tier
it does not recognise, and ``resolve_tier_and_branch`` raises when a CI context is
present but does not classify, or when no branch can be determined at all. There is
no code path that returns a *permissive* set because it could not determine an
answer — the only non-raising outcomes are the full set or an explicitly narrowed
set carrying a stated reason.

Residual risk, stated rather than hidden: tier narrowing keys off the branch name,
so a ``docs/``-prefixed head branch narrows. That is deliberate (the fast-track lane
genuinely emits no review/validate artifacts) and is not reachable by editing a file
in the repository — it requires renaming the PR head branch, which is visible on the
PR itself and recorded in ``requiredArtifactSet.branch`` in every gate result.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Mapping

# The four phase artifacts the correlation gate walks, in ``_ARTIFACT_SPECS`` order.
ARTIFACT_KEYS: tuple[str, ...] = ("implementation", "intentReview", "review", "validation")

# Tiers emitted by ``classify-tier`` in .github/workflows/pr.yml.
KNOWN_TIERS: frozenset[str] = frozenset({"issue", "wave", "main"})

_WAVE_BRANCH_RE = re.compile(r"^feature/.*-wave$")
_ISSUE_BRANCH_RE = re.compile(r"issue-([0-9]+)")

_DOCS_REASON = (
    "docs-lane branch {branch!r}: the fast-track lane (CLAUDE.md two-lane policy) "
    "ships non-code changes without an Executor review or validate phase, so "
    "intentReview, review and validation are never emitted. The implementation "
    "artifact stays required as the phaseRunId anchor."
)
_HOTFIX_REASON = (
    "hotfix branch {branch!r}: the expedited lane defers intent-review and "
    "validation to a follow-up. review stays required — a hotfix is still reviewed."
)


class UnresolvableTierError(ValueError):
    """Raised when the CI tier cannot be determined. Always a gate failure."""


@dataclass(frozen=True)
class RequiredArtifactSet:
    """The artifacts CI requires, plus the provenance of every narrowing."""

    tier: str
    branch: str
    branch_class: str
    required: dict[str, bool]
    narrowed: tuple[str, ...]
    reason: str | None
    source: str = "ci-computed"

    def to_details(self) -> dict[str, Any]:
        """Serialisable form embedded in the gate's details payload."""
        return {
            "source": self.source,
            "tier": self.tier,
            "branch": self.branch,
            "branchClass": self.branch_class,
            "required": dict(self.required),
            "narrowed": list(self.narrowed),
            "reason": self.reason,
        }


def normalize_branch(branch: str | None) -> str:
    """Strip ref prefixes and surrounding whitespace. ``None`` becomes ``""``."""
    if not branch:
        return ""
    value = branch.strip()
    for prefix in ("refs/heads/", "refs/remotes/origin/"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value


def classify_branch(branch: str | None) -> str:
    """Classify a head branch into a lane: docs | hotfix | wave | issue | other."""
    value = normalize_branch(branch).lower()
    if not value:
        return "other"
    if value.startswith(("docs/", "doc/")):
        return "docs"
    if value.startswith("hotfix/"):
        return "hotfix"
    if _WAVE_BRANCH_RE.match(value):
        return "wave"
    if _ISSUE_BRANCH_RE.search(value):
        return "issue"
    return "other"


def compute_required_artifacts(tier: Any, branch: str | None) -> RequiredArtifactSet:
    """Return the required-artifact set for ``tier`` and ``branch``.

    Fail-closed: an unrecognised tier raises rather than defaulting to a
    permissive set. Narrowing happens only at the issue tier, only for the docs
    and hotfix lanes, and always carries a reason.
    """
    if not isinstance(tier, str) or tier not in KNOWN_TIERS:
        raise UnresolvableTierError(
            f"unrecognised CI tier {tier!r}; expected one of {sorted(KNOWN_TIERS)}. "
            "The required-artifact set is not narrowed on an unresolved tier — "
            "this gate fails closed."
        )

    normalized = normalize_branch(branch)
    branch_class = classify_branch(normalized)
    required = dict.fromkeys(ARTIFACT_KEYS, True)
    narrowed: tuple[str, ...] = ()
    reason: str | None = None

    # Aggregate tiers (wave, main) roll up many issues and never narrow.
    if tier == "issue":
        if branch_class == "docs":
            narrowed = ("intentReview", "review", "validation")
            reason = _DOCS_REASON.format(branch=normalized)
        elif branch_class == "hotfix":
            narrowed = ("intentReview", "validation")
            reason = _HOTFIX_REASON.format(branch=normalized)

    for key in narrowed:
        required[key] = False

    return RequiredArtifactSet(
        tier=tier,
        branch=normalized,
        branch_class=branch_class,
        required=required,
        narrowed=narrowed,
        reason=reason,
    )


def _git_current_branch() -> str | None:
    """Local-loop fallback: the branch of the checkout holding this script."""
    try:
        from common import git_current_branch
    except ImportError:  # pragma: no cover - common is always importable in-tree
        return None
    return git_current_branch()


def resolve_tier_and_branch(
    *,
    tier: str | None = None,
    branch: str | None = None,
    env: Mapping[str, str] | None = None,
    branch_resolver: Callable[[], str | None] | None = None,
) -> tuple[str, str]:
    """Resolve ``(tier, branch)`` from explicit args, then CI env, then git.

    Mirrors ``classify-tier`` and ``resolve-issue`` in ``.github/workflows/pr.yml``
    so CI and the local loop agree. An explicit ``tier`` is returned unvalidated —
    :func:`compute_required_artifacts` is the single place that rejects it, so an
    unknown value still fails closed one call later.
    """
    environ = os.environ if env is None else env
    resolver = _git_current_branch if branch_resolver is None else branch_resolver

    resolved_branch = normalize_branch(
        branch or environ.get("GITHUB_HEAD_REF") or environ.get("GITHUB_REF_NAME") or resolver()
    )

    if tier is not None:
        return tier, resolved_branch

    event = (environ.get("GITHUB_EVENT_NAME") or "").strip()
    base_ref = normalize_branch(environ.get("GITHUB_BASE_REF"))
    ref_name = normalize_branch(environ.get("GITHUB_REF_NAME"))

    if event:
        if event == "merge_group":
            return "main", resolved_branch
        if event == "push" and _WAVE_BRANCH_RE.match(ref_name):
            return "wave", resolved_branch
        if event == "pull_request" and _WAVE_BRANCH_RE.match(base_ref):
            return "issue", resolved_branch
        if event == "pull_request" and base_ref in {"main", "staging"}:
            return "main", resolved_branch
        # `release.yml` runs on push to main — the deploy pipeline, and the
        # post-merge state of a main-tier pull request. It was missing here,
        # so every merge to main raised UnresolvableTierError inside
        # `release.yml`'s own `pytest tests/` run and took the build down.
        # Three merges sat undeployed before it was noticed, including a
        # migration.
        #
        # This is the same shape as #1447: a change verified against `pr.yml`,
        # where the event is always `pull_request`, breaking `release.yml`,
        # where it is `push` to `main`. The two workflows exercise different
        # events, so a green `pr.yml` says nothing about this branch.
        if event == "push" and ref_name in {"main", "staging"}:
            return "main", resolved_branch
        raise UnresolvableTierError(
            f"unsupported CI flow: event={event!r} base={base_ref!r} ref={ref_name!r}; "
            "the required-artifact set is not narrowed on an unresolved tier."
        )

    # No CI context: the local agent loop. It only ever runs per-issue, so the
    # issue tier is the correct (and maximal) classification — but a branch must
    # exist for the lane to be knowable at all.
    if not resolved_branch:
        raise UnresolvableTierError(
            "no CI tier in the environment and no current git branch; the "
            "required-artifact set cannot be computed and this gate fails closed."
        )
    return "issue", resolved_branch


def resolve_required_artifacts(
    *,
    tier: str | None = None,
    branch: str | None = None,
    env: Mapping[str, str] | None = None,
    branch_resolver: Callable[[], str | None] | None = None,
) -> RequiredArtifactSet:
    """Convenience: resolve the tier/branch, then compute the required set."""
    resolved_tier, resolved_branch = resolve_tier_and_branch(
        tier=tier, branch=branch, env=env, branch_resolver=branch_resolver
    )
    return compute_required_artifacts(resolved_tier, resolved_branch)


def plan_narrowing_ignored(
    computed: RequiredArtifactSet, plan_required: Mapping[str, Any] | None
) -> list[str]:
    """Artifacts the plan tried to relax that CI still requires.

    Recorded as evidence in the gate details. The verdict never reads it — the
    point of #1439 is that the plan cannot narrow anything, only be observed
    disagreeing.
    """
    if not isinstance(plan_required, Mapping):
        return []
    return [
        key
        for key in ARTIFACT_KEYS
        if computed.required.get(key) is True and plan_required.get(key) is False
    ]
