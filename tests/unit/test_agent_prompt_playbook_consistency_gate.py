"""Playbook consistency gate -- issue #1039 (W2-A/P12-4, ADR-072 decision 6
gate 3, ADR-069 decision 4's two-way cross-validation).

Two directions, both proven here.

## Direction 1: prose -> Playbook (composed prompt never grants a tool the

Playbook doesn't)

ADR-069 decision 3's two-way cross-validation and `playbooks/base.py`'s
`validate_playbook_tools` already prove every `Playbook.steps[*].tools`
entry resolves against the real `ToolRegistry` (playbook -> registry).
#1038's own contract test already proves every `Playbook` tool name appears
somewhere in the *rendered* `{playbook}` slot (playbook -> composed
prompt). What neither of those proves: every tool-name-shaped token that
appears **anywhere in the composed prompt** -- not just inside the
rendered playbook table -- is actually a real step tool in the `Playbook`.
That is the gap ADR-072 d.6 names: a future prose edit that mentions a
tool by name in running text (a typo, a leftover reference to a renamed
tool) would pass every existing check and still mislead the model about
what it may call.

A tool-name-shaped token is a backtick-quoted, all-lowercase identifier
containing at least one underscore -- e.g. `` `get_product_information` ``
(every real tool name in this repo's registry is exactly this shape --
`ToolSpec.name`'s docstring: "business-semantic English snake_case").

## Direction 2: registry -> playbooks (ADR-069 decision 4's other half --

the one that was vacuous)

"Allowlists live in playbooks, not on ToolSpecs. ... Import-time contract
tests cross-validate both directions: every playbook tool is registered;
every registered tool appears in at least one playbook or is explicitly
marked shared." (ADR-069 decision 4.) Direction 1 above, plus
`validate_playbook_tools`, together prove the first half. Nothing in this
repo proved the second half before this file: a tool landing in the
registry with no playbook step is never caught -- it is simply never
offered to the model, which looks identical to the model declining to use
it. Found during Review of #1036 (documented on issue #1039); vacuously
true today only because the registry holds exactly the tools the one
playbook grants.

**Built generically -- today's tools are never named in the check logic.**
The check walks two real, already-established production sources rather
than a hand-maintained list of "the current six":

- the full registered-tool universe: every domain module's
  `register_*_tools(registry)` function, called against a fresh
  `ToolRegistry()` -- the same construction every other test file in this
  suite already uses (`test_agent_tool_registry_contract.py`,
  `test_agent_tool_schema_description_hygiene.py`,
  `test_agent_playbooks_optimize_product.py`), not invented here;
- every currently-bound `Playbook`: `composer.py`'s own
  `_WORKFLOW_BINDINGS` dict -- the one explicit, visible `workflow_key` ->
  `(prompt_dir, Playbook)` mapping the composer itself reads. Every
  playbook a real workflow can compose from is reachable through this
  dict; when P13 adds a workflow, its `Playbook` is reachable the moment
  its binding is added to that dict, with **no edit to this gate file**.

`_SHARED_TOOL_NAMES` below is the "explicit shared / not-workflow-scoped
marker" ADR-069 decision 4 calls for. It is empty today (no tool is
shared/not-workflow-scoped yet -- all six real tools resolve through the
one real playbook), declared once as a named, documented set so a future
tool can be added to it explicitly rather than the reverse-direction check
being loosened ad hoc. The four unregistered legacy tools
(`fulfillment.process_order`, `returns.prevent_*`) are out of scope (issue
#1039 comment 2): they are not in the agent `ToolRegistry` at all, so they
never appear in `registered_tool_names` and this check has nothing to say
about them -- their disposition is #1072's Architect decision.

Driven with **synthetic** input for both directions (per issue #1039's
acceptance criteria) -- this gate must fail naming the offending tool even
if the real registry/playbook pair never actually drifts, so it cannot
pass "by accident of the real pair agreeing". `TestReverseDirectionDrift`
is the one proof this issue's own thread calls "most worth proving",
because it is the one that was vacuous.
"""

from __future__ import annotations

import re

import pytest
from pydantic import BaseModel

import juli_backend.services.agent.prompts.composer as compose_module
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.prompts.composer import compose, production_version
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import (
    ToolClassification,
    ToolPolicy,
    ToolRegistry,
    ToolSpec,
)

#: Backtick-quoted, all-lowercase-with-underscore identifiers -- the shape
#: every real tool name in this repo's `ToolRegistry` takes (see module
#: docstring). Requires an underscore so it never matches the single-word
#: backtick tokens this prompt's static prose legitimately uses for other
#: purposes (`` `juli` ``, `` `policy` ``, `` `tools` ``), and excludes any
#: character outside `[a-z0-9_]` so it never matches dotted `dictionary.md`
#: keys like `` `decisions.recommendation` ``.
_TOOL_NAME_SHAPED_TOKEN_PATTERN = re.compile(r"`([a-z][a-z0-9_]*)`")

#: ADR-069 decision 4's "explicitly marked shared" escape hatch -- empty
#: today (module docstring, Direction 2). A future tool that is genuinely
#: shared/not-workflow-scoped is added here explicitly, by name, in the
#: same reviewed commit that adds it to the registry -- never silently
#: inferred.
_SHARED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # #1208: Optimize Product's image step became `inspect_product_image`
        # (READ). `upload_product_image` stays REGISTERED but is granted by no
        # playbook: it uploads bytes staged in the run context, and nothing in any
        # current flow stages any -- which is exactly why the model could call it
        # and always fail. It is kept for the image-generation capability that will
        # stage bytes, and marked shared here rather than deleted so removing it is
        # a deliberate decision rather than a side effect of this fix.
        "upload_product_image",
    }
)


def _real_full_tool_registry() -> ToolRegistry:
    """Every tool this repo's agent runtime currently registers, built the
    same way every other contract test in this suite builds it (see module
    docstring) -- generic over which domain modules exist, not over which
    tool names they register.
    """
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _real_bound_playbooks() -> tuple:
    """Every `Playbook` reachable through the composer's own explicit
    `workflow_key` -> binding map -- the same source `compose()` itself
    reads, so this check and production code can never define "the current
    playbooks" two different ways.
    """
    return tuple(binding.playbook for binding in compose_module._WORKFLOW_BINDINGS.values())


def _tool_name_shaped_tokens(text: str) -> set[str]:
    return {token for token in _TOOL_NAME_SHAPED_TOKEN_PATTERN.findall(text) if "_" in token}


def _playbook_tool_names(playbook) -> frozenset[str]:
    return frozenset(tool_name for step in playbook.steps for tool_name in step.tools)


# ---------------------------------------------------------------------------
# Direction 1: every tool-name-shaped token in prose is a real Playbook tool
# ---------------------------------------------------------------------------


def _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
    text: str, known_tool_names: frozenset[str]
) -> None:
    found = _tool_name_shaped_tokens(text)
    offenders = sorted(found - known_tool_names)
    assert offenders == [], (
        "tool-name-shaped token(s) in composed prompt not present in the "
        f"Playbook's tool allowlist: {offenders}"
    )


def test_every_tool_name_shaped_token_in_the_real_composed_prompt_is_in_the_playbook():
    composed = compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY))
    _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
        composed, _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)
    )


def test_the_real_composed_prompt_actually_contains_tool_name_shaped_tokens():
    """Sanity check the extraction isn't vacuously finding zero tokens."""
    composed = compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY))
    found = _tool_name_shaped_tokens(composed)
    assert found == _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)


class TestForwardDirectionSyntheticDrift:
    def test_a_tool_name_in_prose_but_absent_from_the_playbook_fails_naming_it(self):
        synthetic_composed = (
            "## 5. Playbook\n\n"
            "| Step | Intent | Tools | Policy |\n"
            "|------|--------|-------|--------|\n"
            "| 1 | Read the product. | `get_product_information` | AUTO |\n\n"
            "## 6. Recommend Within Scope\n\n"
            "If you need a competing listing, call `search_marketplace_products`."
        )
        known_tool_names = frozenset({"get_product_information"})

        with pytest.raises(AssertionError, match="search_marketplace_products"):
            _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
                synthetic_composed, known_tool_names
            )

    def test_a_typo_of_a_real_tool_name_fails_naming_the_typo(self):
        synthetic_composed = "Call `update_product_lsiting` once the seller approves."
        known_tool_names = frozenset({"update_product_listing"})

        with pytest.raises(AssertionError, match="update_product_lsiting"):
            _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
                synthetic_composed, known_tool_names
            )

    def test_a_tool_name_present_in_prose_and_in_the_playbook_does_not_fail(self):
        synthetic_composed = "Call `get_product_information` first."
        known_tool_names = frozenset({"get_product_information", "get_seo_keywords"})
        # Must not raise.
        _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
            synthetic_composed, known_tool_names
        )

    def test_dotted_dictionary_keys_are_never_mistaken_for_tool_names(self):
        synthetic_composed = "Use the term `decisions.recommendation` from dictionary.md."
        known_tool_names = frozenset({"get_product_information"})
        # Must not raise -- a dotted key is never tool-name-shaped.
        _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
            synthetic_composed, known_tool_names
        )


# ---------------------------------------------------------------------------
# Direction 2 (ADR-069 decision 4's other half): every registered tool is
# granted by some playbook, or is explicitly marked shared.
# ---------------------------------------------------------------------------


def _assert_every_registered_tool_is_reachable(
    registered_tool_names: frozenset[str],
    granted_tool_names: frozenset[str],
    shared_tool_names: frozenset[str],
) -> None:
    """The reverse-direction gate's actual check. Raises `AssertionError`
    naming every offending tool and stating which of the two remedies is
    needed, per issue #1039's acceptance criterion -- never just "some tool
    is unreachable".
    """
    unaccounted = sorted(registered_tool_names - granted_tool_names - shared_tool_names)
    assert unaccounted == [], (
        "registered tool(s) granted by no playbook step and not marked "
        f"shared: {unaccounted}. Remedy: add each to a playbook step's "
        "`tools`, or add it to _SHARED_TOOL_NAMES if it is genuinely "
        "shared/not-workflow-scoped."
    )


def test_every_real_registered_tool_is_granted_by_a_playbook_or_marked_shared():
    registry = _real_full_tool_registry()
    registered_tool_names = frozenset(spec.name for spec in registry.list_all())

    granted_tool_names: set[str] = set()
    for playbook in _real_bound_playbooks():
        granted_tool_names |= _playbook_tool_names(playbook)

    _assert_every_registered_tool_is_reachable(
        registered_tool_names, frozenset(granted_tool_names), _SHARED_TOOL_NAMES
    )


def test_the_real_registry_is_non_empty_so_this_check_is_not_vacuous():
    registry = _real_full_tool_registry()
    assert len(registry.list_all()) > 0


def test_the_real_registry_and_the_one_real_playbook_agree_on_six_tools():
    """Confirms today's real state: every registered tool either traces to the
    one real playbook or is explicitly marked shared.

    #1208 changed this from "nothing rests on the shared marker" to one entry
    that does. `upload_product_image` stays registered for the future
    image-generation capability but is granted by no playbook, because nothing
    stages the bytes it needs. Asserting the shared set's exact contents keeps
    that a deliberate, reviewed exception rather than a growing dumping ground.
    """
    registry = _real_full_tool_registry()
    registered_tool_names = frozenset(spec.name for spec in registry.list_all())
    playbook_tool_names = _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)
    assert registered_tool_names - playbook_tool_names == _SHARED_TOOL_NAMES
    assert playbook_tool_names - registered_tool_names == frozenset()
    assert _SHARED_TOOL_NAMES == frozenset({"upload_product_image"})
    assert len(registered_tool_names) == 7


class TestReverseDirectionDrift:
    """Synthetic proof the reverse direction actually catches an
    unreferenced tool -- issue #1039's own thread names this "the one most
    worth proving", since it is the direction that was vacuous before this
    file. Every registry/playbook object here is constructed fresh,
    in-memory, and local to the test; nothing in `services/agent/tools/`
    or `services/agent/playbooks/` is imported for mutation, only for the
    real `ToolSpec`/`Playbook` shapes to build synthetic instances from.
    """

    def _seventh_tool_spec(self) -> ToolSpec:
        class _SeventhToolInput(BaseModel):
            note: str

        class _SeventhToolOutput(BaseModel):
            ok: bool

        return ToolSpec(
            name="archive_stale_listing",
            description="A seventh tool with no playbook step (test-only, never registered "
            "in production code).",
            input_model=_SeventhToolInput,
            output_model=_SeventhToolOutput,
            classification=ToolClassification.WRITE,
            policy=ToolPolicy.CONFIRM,
            timeout_seconds=10,
        )

    def test_a_seventh_registered_tool_with_no_playbook_step_fails_naming_it(self):
        registry = _real_full_tool_registry()
        registry.register(self._seventh_tool_spec())
        registered_tool_names = frozenset(spec.name for spec in registry.list_all())
        granted_tool_names = _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)

        with pytest.raises(AssertionError, match="archive_stale_listing"):
            _assert_every_registered_tool_is_reachable(
                registered_tool_names, granted_tool_names, _SHARED_TOOL_NAMES
            )

    def test_the_failure_message_names_both_remedies(self):
        registry = _real_full_tool_registry()
        registry.register(self._seventh_tool_spec())
        registered_tool_names = frozenset(spec.name for spec in registry.list_all())
        granted_tool_names = _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)

        with pytest.raises(AssertionError) as exc_info:
            _assert_every_registered_tool_is_reachable(
                registered_tool_names, granted_tool_names, _SHARED_TOOL_NAMES
            )
        message = str(exc_info.value)
        assert "playbook" in message.lower()
        assert "shared" in message.lower()

    def test_marking_the_seventh_tool_shared_makes_the_check_pass(self):
        """The other remedy: an explicit shared marker, not a playbook
        step, silences the same offender -- proves the escape hatch
        actually works, not just that the failure path does.
        """
        registry = _real_full_tool_registry()
        registry.register(self._seventh_tool_spec())
        registered_tool_names = frozenset(spec.name for spec in registry.list_all())
        granted_tool_names = _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)
        shared_with_seventh = _SHARED_TOOL_NAMES | {"archive_stale_listing"}

        # Must not raise.
        _assert_every_registered_tool_is_reachable(
            registered_tool_names, granted_tool_names, shared_with_seventh
        )

    def test_two_unreferenced_tools_are_both_named_together(self):
        registry = _real_full_tool_registry()
        registry.register(self._seventh_tool_spec())

        class _EighthToolInput(BaseModel):
            note: str

        class _EighthToolOutput(BaseModel):
            ok: bool

        registry.register(
            ToolSpec(
                name="merge_duplicate_listings",
                description="An eighth tool with no playbook step (test-only).",
                input_model=_EighthToolInput,
                output_model=_EighthToolOutput,
                classification=ToolClassification.WRITE,
                policy=ToolPolicy.CONFIRM,
                timeout_seconds=10,
            )
        )
        registered_tool_names = frozenset(spec.name for spec in registry.list_all())
        granted_tool_names = _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)

        offenders_pattern = (
            r"archive_stale_listing.*merge_duplicate_listings|"
            r"merge_duplicate_listings.*archive_stale_listing"
        )
        with pytest.raises(AssertionError, match=offenders_pattern):
            _assert_every_registered_tool_is_reachable(
                registered_tool_names, granted_tool_names, _SHARED_TOOL_NAMES
            )

    def test_a_registry_where_every_tool_is_granted_does_not_fail(self):
        # Must not raise -- the base case the drift proofs above are
        # contrasted against.
        registry = _real_full_tool_registry()
        registered_tool_names = frozenset(spec.name for spec in registry.list_all())
        granted_tool_names = _playbook_tool_names(OPTIMIZE_PRODUCT_PLAYBOOK)
        _assert_every_registered_tool_is_reachable(
            registered_tool_names, granted_tool_names, _SHARED_TOOL_NAMES
        )


# ---------------------------------------------------------------------------
# The four unregistered legacy tools stay structurally out of scope (issue
# #1039 comment 2) -- confirmed by fact, not asserted only in prose.
# ---------------------------------------------------------------------------


def test_legacy_fulfillment_and_returns_tools_are_not_in_the_agent_registry():
    """`fulfillment.process_order` and `returns.prevent_*` are legacy Celery
    tool-registry entries (`services/execution/runner.py`), never agent
    `ToolSpec`s -- confirms they cannot appear in `registered_tool_names`
    above, so this gate has structurally nothing to say about them."""
    registry = _real_full_tool_registry()
    registered_tool_names = {spec.name for spec in registry.list_all()}
    legacy_names = {
        "fulfillment.process_order",
        "returns.prevent_cancellation",
        "returns.prevent_return",
        "returns.prevent_refund",
    }
    assert registered_tool_names.isdisjoint(legacy_names)
