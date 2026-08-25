"""LLM-facing input-schema description hygiene — issue #1014.

`ToolSpec.render_input_schema()` (`services/agent/tools/registry.py`) returns
`input_model.model_json_schema()` verbatim to the LLM every turn. Pydantic
puts a model's docstring straight into that schema's `"description"` key
(and, for any nested model referenced via `$ref`, into
`schema["$defs"][ModelName]["description"]`) — so an input-model docstring
written for a human maintainer (implementation rationale, ADR citations,
internal class names, internal identifier field names) ships into the
model's context on every turn, right alongside the genuinely model-facing
"what does this tool need" text.

This module drives the check from the **real, live registry**
(`register_product_read_tools` + `register_product_write_tools`), iterating
every currently-registered tool's rendered input schema — not a hardcoded
list of the six known tool names — so a future tool with a leaky docstring
fails this test without anyone remembering to add a case for it.

## Design decision: why this test does not reuse `banned_patterns.py`

Considered and rejected: extending `services/agent/sanitize/banned_patterns`
(the shared `packages/contracts/seller-copy-banned-patterns.json` list) to
also guard inbound schema text. Read closely, that list is calibrated for a
different surface than this one: **Vietnamese seller-facing copy** generated
*from* tool results (ADR-070 decision 6). Its entries include ordinary
English words with no internal-leak meaning on an operator-facing English
schema — `confirm`, `ship`, `split`, `activity`, `parity` — plus
Vietnamese-only phrases. Loading that list against English tool-schema
descriptions would either reject legitimate operating vocabulary (a
`policy=confirm` tool's schema describing a "confirm" step) or need per-surface
carve-outs bolted onto a list whose contract (`test_agent_banned_patterns_contract.py`)
is "every entry compiles under both JS and Python regex for seller-copy
purposes" — a different contract than "safe vocabulary for a schema shown to
a nano-class model." Schema text needs its own narrow marker list, which is
what this module hardcodes and asserts against the live registry, not a
detour through the seller-copy source.
"""

from __future__ import annotations

import re
from typing import Any

from juli_backend.services.agent.sanitize.banned_patterns import (
    compile_python_patterns,
    load_banned_pattern_entries,
)
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry

# --- Internal markers a model-facing schema description must never carry ---
#
# At minimum (per issue #1014): an ADR citation, the slice-local internal
# context class name, and internal `_id`-style identifier tokens (the raw
# vendor/internal field names the model never sees or supplies — ADR-070
# decision 1's whole point is that these never reach the LLM).

_ADR_CITATION = re.compile(r"ADR-\d")
_INTERNAL_CONTEXT_CLASS = re.compile(r"\bProductToolContext\b")
_INTERNAL_ID_IDENTIFIER = re.compile(r"\b[a-zA-Z][a-zA-Z0-9]*_id\b")


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _iter_schema_descriptions(schema: dict[str, Any]) -> dict[str, str]:
    """Every `"description"` string in a rendered input schema: the
    top-level model description plus every nested `$defs` entry's
    description (nested models reachable via `$ref`, e.g.
    `UpdateProductPriceInput` -> `ProductSkuPrice`)."""
    descriptions: dict[str, str] = {}
    top_level_description = schema.get("description")
    if isinstance(top_level_description, str):
        descriptions[schema.get("title", "<top-level>")] = top_level_description
    for def_name, def_schema in (schema.get("$defs") or {}).items():
        nested_description = def_schema.get("description")
        if isinstance(nested_description, str):
            descriptions[def_name] = nested_description
    return descriptions


def test_no_registered_tool_input_schema_description_leaks_internal_markers():
    registry = _build_registry()
    tools = registry.list_all()
    assert tools, "the real registry must have at least one registered tool"

    violations: list[str] = []
    for spec in tools:
        schema = spec.render_input_schema()
        for model_name, description in _iter_schema_descriptions(schema).items():
            hits = []
            if _ADR_CITATION.search(description):
                hits.append("ADR- citation")
            if _INTERNAL_CONTEXT_CLASS.search(description):
                hits.append("ProductToolContext")
            id_hit = _INTERNAL_ID_IDENTIFIER.search(description)
            if id_hit:
                hits.append(f"internal _id-style identifier ({id_hit.group(0)!r})")
            if hits:
                violations.append(
                    f"tool {spec.name!r}, schema model {model_name!r}: {', '.join(hits)}\n"
                    f"    description: {description!r}"
                )

    assert not violations, (
        "LLM-facing input-schema description(s) leak internal implementation "
        "markers that must never reach the model:\n" + "\n".join(violations)
    )


def test_every_registered_tool_input_schema_description_is_nonempty():
    """A hygiene fix must not regress to no description at all — every
    top-level input-model schema still documents what to pass, even for the
    zero-field models."""
    registry = _build_registry()
    for spec in registry.list_all():
        schema = spec.render_input_schema()
        description = schema.get("description")
        assert isinstance(description, str) and description.strip(), (
            f"tool {spec.name!r} has no model-facing input-schema description"
        )


# --- Decision record: the seller-copy banned-pattern list is NOT wired here ---


def _banned_pattern_hits(text: str) -> list[str]:
    entries = load_banned_pattern_entries()
    compiled = compile_python_patterns(entries)
    return [
        entry.id for entry, pattern in zip(entries, compiled, strict=True) if pattern.search(text)
    ]


class TestBannedPatternListDeliberatelyNotWiredToSchemaText:
    """Decision record (issue #1014, item 3).

    The shared seller-copy banned-pattern list
    (`packages/contracts/seller-copy-banned-patterns.json`, loaded by
    `services/agent/sanitize/banned_patterns.py`, ADR-070 decision 6) governs
    Vietnamese seller-facing copy generated *from* tool results — the
    outbound direction. It is deliberately **not** wired as a runtime or
    test gate on the English, operator-facing tool `description` / input
    -schema text that goes the other direction, into the model.

    Reasoning: read closely, several entries ban ordinary English operating
    words for a jargon-leaking-into-Vietnamese-translation reason that has
    no analog on an English schema whose only reader is the model itself —
    `confirm` (this repo's own CONFIRM policy vocabulary, unavoidable in a
    CONFIRM-tool's description), `ship`/`split` (routine English verbs),
    `activity`, `parity`, `endpoint`. Wiring the list here would force
    contorted rewrites of legitimate tool vocabulary for zero
    injection-safety benefit, since the model is not the audience that list
    protects. What guards *this* surface instead is the narrow,
    purpose-built internal-marker check above
    (`test_no_registered_tool_input_schema_description_leaks_internal_markers`)
    — calibrated for schema hygiene, not borrowed from a differently-scoped
    guard.

    The one concrete, non-coincidental leak the issue's own investigation
    found (`check_product_status`'s description naming the internal
    "webhook" delivery mechanism) was fixed directly in
    `services/agent/tools/product.py`, on its own hygiene merits — that is a
    real internal-implementation-detail leak, independent of whether the
    seller-copy list applies here.

    This test pins the *remaining* known false positive as a canary:
    `update_product_listing` / `update_product_price` trip `listing\\.`
    purely because their descriptions end a sentence with the word
    "listing" — legitimate vocabulary for a tool literally named
    `update_product_listing`, not an internal leak. If this set ever
    shrinks to empty, that's worth a second look (not a required action);
    if it grows, a new tool description may have picked up real leaking
    vocabulary and deserves a look regardless of this decision.
    """

    def test_known_false_positive_trips_match_the_documented_set(self):
        # Issue #1304 narrowed `listing_dot` to `listing\.(?=[A-Za-z_])`,
        # which was exactly the "second look" the class docstring invited:
        # sentence-final "listing." in the update_product_listing /
        # update_product_price descriptions no longer trips, so the
        # documented false-positive set is now empty. Any entry appearing
        # here again means a tool description picked up real jargon-shaped
        # vocabulary (e.g. `listing.title`) and deserves a look.
        registry = _build_registry()
        trips: dict[str, list[str]] = {}
        for spec in registry.list_all():
            hits = _banned_pattern_hits(spec.description)
            if hits:
                trips[spec.name] = hits
        assert trips == {}

    def test_check_product_status_no_longer_leaks_the_webhook_mechanism(self):
        registry = _build_registry()
        spec = registry.get("check_product_status")
        assert not _banned_pattern_hits(spec.description), (
            "check_product_status description should no longer trip any banned "
            f"pattern; got hits: {_banned_pattern_hits(spec.description)}"
        )
