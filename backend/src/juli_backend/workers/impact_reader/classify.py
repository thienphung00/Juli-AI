"""``ToolExecution`` -> ADR-077 ``MutationKind`` classification (#1044).

``services.impact.metric_map``'s ``MutationKind`` docstring deliberately
leaves this classification to a future caller: "the caller (the future daily
impact-reader beat task, #1044) is responsible for deciding which
``MutationKind`` value(s) a given ``ToolExecution`` maps to." This module is
that caller.

Only ``listing.optimize_product`` (workflow key ``optimize_product_2``)
produces measurable SEO/description/image/price mutations today —
``listing.create_hero_product`` creates a brand-new listing with no
pre-period baseline to measure against, so it is out of scope here (see
``queries.MEASURABLE_TOOL_NAMES``, the single source of truth for which tool
names this reader scans at all).

Classification reads the *request* payload (``ToolExecution.payload_json``),
not the outcome (``ToolExecution.outcome_json``): the caller's own declared
intent is the more stable, directly-controllable signal.
``run_optimize_product_chain`` (``services/execution/listing.py``) can
auto-fill ``title``/``description`` from catalog suggestions even when the
caller only asked for something else (see
``_build_edit_body_from_chain``), which would over-classify a run as
touching SEO/description if read from the outcome instead.
"""

from __future__ import annotations

from typing import Any

from juli_backend.services.impact import METRIC_MAP, MetricSpec, MutationKind

#: Deterministic classification order — a caller picking ``kinds[0]`` (e.g.
#: for a rollup metric, see :func:`rollup_metric_for`) gets a stable choice
#: across runs regardless of dict/JSON key ordering.
_CLASSIFICATION_ORDER: tuple[tuple[MutationKind, str], ...] = (
    (MutationKind.PRICE, "price_update"),
    (MutationKind.IMAGE, "image_uri"),
)


def classify_mutation_kinds(payload: dict[str, Any]) -> list[MutationKind]:
    """Which mutation kind(s) a ``listing.optimize_product`` request payload
    touches.

    Returns ``[]`` for a payload this heuristic cannot classify (e.g. a
    no-op call with none of the recognized fields) — the caller must skip
    that execution, never guess a mutation kind out of thin air.
    """
    edit_body = payload.get("edit_body")
    edit_body = edit_body if isinstance(edit_body, dict) else {}

    kinds: list[MutationKind] = []
    if payload.get("price_update"):
        kinds.append(MutationKind.PRICE)
    if payload.get("image_uri") or payload.get("image_content_base64"):
        kinds.append(MutationKind.IMAGE)
    if edit_body.get("title") or payload.get("title"):
        kinds.append(MutationKind.SEO_KEYWORDS_TITLE)
    if edit_body.get("description") or payload.get("description"):
        kinds.append(MutationKind.DESCRIPTION)
    return kinds


def rollup_metric_for(kinds: list[MutationKind]) -> MetricSpec:
    """The run-level rollup metric spec (ADR-077 decision 1's per-run
    rollup, keyed on the ActionCard's ``expected_impact.metric`` in the full
    design).

    Simplification, flagged in the PR body rather than silently worked
    around: resolving the *real* ``expected_impact.metric`` requires
    joining ``ToolExecution.approval_id`` back to an ``ActionCard`` row,
    which is out of this slice's scope and not required by any #1044
    acceptance criterion. This falls back to the primary metric of the
    first classified mutation kind — ``reading.py``'s own docstring notes
    "a single-mutation run's rollup is typically the same metric as that
    mutation's primary," which is the common case this approximates.
    """
    return METRIC_MAP[kinds[0]].primary
