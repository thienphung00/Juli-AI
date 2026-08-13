"""Agent registry <-> legacy catalog cross-validation contract — issue #983 (W1-A).

AC1 → all six Optimize Product agent capabilities are registered
      (`TestSixOptimizeProductCapabilitiesRegistered`).
AC2 → the four known-unregistered legacy tool names are asserted as an explicit
      expected frozenset, checked in both directions against the computed set
      (`TestFourKnownUnregisteredLegacyTools`).
AC3 → adding a capability without a catalog relationship, or removing one, fails
      with a message naming the offending capability — proven by driving the
      validator with synthetic mismatched inputs, not just by trusting the real
      inputs happen to line up (`TestCrossValidationNamesTheOffendingCapability`).
AC4 → follows the `test_action_cards_contract.py` convention: module docstring
      mapping issue -> AC lines, `from __future__ import annotations`,
      class-grouped tests.
AC5 → the legacy execution registry (`services/execution/runner.py`) and its
      chains (`listing_handlers.py`, `leakage_handlers.py`) are read-only
      dependencies here — never imported for mutation, never edited
      (`TestLegacyRegistryUntouched` documents the read-only surface used).

## Design decision: what "cross-validation" means here (ADR-069 decision 4)

The agent registry's names are business-semantic capabilities
(`get_product_information`); `WORKFLOW_TOOL_CATALOG`'s names are legacy Celery
tool names (`listing.optimize_product`) keyed by workflow_key
(`optimize_product_2`). These are not the same namespace, so a naive
name-set comparison is meaningless — nothing here means to imply
`get_product_information == "listing.optimize_product"`.

Per ADR-069 decision 4, the agent's six Optimize Product capabilities
decompose the single `optimize_product_2` workflow (whose catalog entry
routes to the coarse legacy `listing.optimize_product` chain). So the pinned
contract is an **explicit, declared mapping** from each agent capability to
the catalog `workflow_key` it serves
(`AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY`), cross-checked in both
directions against the live registry and the live catalog:

- every registered capability must appear as a mapping key (nothing silently
  unmapped);
- every mapping key must still be a registered capability (nothing stale);
- every mapping value must be a real `WORKFLOW_TOOL_CATALOG` key (nothing
  pointing at a workflow that doesn't exist).

Per the issue's "Design authority" note, only the catalog direction is in
scope for this slice — the playbook direction (every playbook tool is
registered) arrives with ADR-072 in W2-A.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolRegistry
from juli_backend.services.execution.runner import is_tool_registered
from juli_backend.services.execution.tool_routing import WORKFLOW_TOOL_CATALOG

# --- The six Optimize Product agent capabilities (ADR-069 decision 1) ------------

EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES = frozenset(
    {
        "get_product_information",
        "get_seo_keywords",
        "check_product_status",
        "upload_product_image",
        "update_product_listing",
        "update_product_price",
    }
)

# --- Explicit capability -> catalog workflow_key mapping (ADR-069 decision 4) ----
#
# All six capabilities decompose the single `optimize_product_2` workflow,
# whose catalog entry routes to the coarse legacy `listing.optimize_product`
# chain. This mapping is the pinned contract: a future capability added to
# the agent registry without a line here, or a line here whose capability
# gets removed, fails loudly (see `TestCrossValidationNamesTheOffendingCapability`
# for proof of that failure mode, and the real-inputs tests below for the
# actual pin).

AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY: dict[str, str] = {
    "get_product_information": "optimize_product_2",
    "get_seo_keywords": "optimize_product_2",
    "check_product_status": "optimize_product_2",
    "upload_product_image": "optimize_product_2",
    "update_product_listing": "optimize_product_2",
    "update_product_price": "optimize_product_2",
}

# --- The four legacy tool names with no implementation yet (flag, do not fix) ----

EXPECTED_UNREGISTERED_LEGACY_TOOL_NAMES = frozenset(
    {
        "fulfillment.process_order",
        "returns.prevent_cancellation",
        "returns.prevent_return",
        "returns.prevent_refund",
    }
)


def _build_registry() -> ToolRegistry:
    """The full current universe of registered agent capabilities (W1-A)."""
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


def _registered_capability_names(registry: ToolRegistry) -> frozenset[str]:
    return frozenset(spec.name for spec in registry.list_all())


def _assert_capability_catalog_mapping_is_consistent(
    *,
    registered_capability_names: frozenset[str],
    mapping: Mapping[str, str],
    catalog_workflow_keys: frozenset[str],
) -> None:
    """The validator under test (AC3): both cross-validation directions, plus
    the catalog-key sanity check, each failing with a message naming the
    offending capability.

    This is the function both the real-inputs test (AC1/AC3 "the real thing
    stays green") and the synthetic-inputs tests (AC3 "the check actually
    bites") exercise — a single implementation, so the synthetic tests are
    real proof of the real test's failure behavior, not a parallel guess.
    """
    unmapped = registered_capability_names - mapping.keys()
    if unmapped:
        raise AssertionError(
            "Capability(ies) registered in the agent tool registry but missing "
            "from AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY: "
            f"{sorted(unmapped)}. Add a mapping entry (or explicitly mark the "
            "capability as catalog-exempt) — a capability must never be silently "
            "unmapped."
        )

    stale = set(mapping.keys()) - registered_capability_names
    if stale:
        raise AssertionError(
            "AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY references capability(ies) "
            f"no longer registered in the agent tool registry: {sorted(stale)}. "
            "Remove the stale mapping entry."
        )

    unknown_workflow_keys = {
        workflow_key
        for workflow_key in mapping.values()
        if workflow_key not in catalog_workflow_keys
    }
    if unknown_workflow_keys:
        offending_capabilities = sorted(
            name for name, workflow_key in mapping.items() if workflow_key in unknown_workflow_keys
        )
        raise AssertionError(
            f"Capability(ies) {offending_capabilities} map to workflow_key(s) "
            f"{sorted(unknown_workflow_keys)} that do not exist in "
            "WORKFLOW_TOOL_CATALOG."
        )


class TestSixOptimizeProductCapabilitiesRegistered:
    """AC1: an import-time assertion that all six Optimize Product capabilities
    are registered in the agent registry."""

    def test_all_six_expected_capabilities_are_registered(self):
        registry = _build_registry()
        for name in EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES:
            registry.get(name)  # raises UnknownToolError if missing

    def test_registry_contains_exactly_the_six_expected_capabilities(self):
        registry = _build_registry()
        assert _registered_capability_names(registry) == EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES


class TestFourKnownUnregisteredLegacyTools:
    """AC2: the four known-unregistered legacy tool names, asserted as an
    explicit expected frozenset in both directions — implementing one of them
    forces a deliberate edit here rather than silently passing."""

    def test_expected_set_has_exactly_four_names(self):
        assert len(EXPECTED_UNREGISTERED_LEGACY_TOOL_NAMES) == 4

    def test_computed_unregistered_catalog_tools_equals_expected_set(self):
        computed_unregistered = frozenset(
            entry.tool_name
            for entry in WORKFLOW_TOOL_CATALOG.values()
            if not is_tool_registered(entry.tool_name)
        )
        # Both directions: implementing one of the four (computed shrinks) or a
        # newly-added catalog entry going unregistered (computed grows) both
        # break this equality and force a deliberate edit to this test.
        assert computed_unregistered == EXPECTED_UNREGISTERED_LEGACY_TOOL_NAMES

    def test_every_other_catalog_tool_is_registered_in_the_legacy_runner(self):
        other_tool_names = (
            frozenset(entry.tool_name for entry in WORKFLOW_TOOL_CATALOG.values())
            - EXPECTED_UNREGISTERED_LEGACY_TOOL_NAMES
        )
        for tool_name in other_tool_names:
            assert is_tool_registered(tool_name), (
                f"{tool_name!r} was expected to be registered in the legacy runner "
                "(it is not one of the four known-missing tools)"
            )


class TestCapabilityCatalogMappingCoversTheRealRegistryAndCatalog:
    """AC3 (positive case): the real registry, the real mapping, and the real
    catalog are consistent right now — this is the actual import-time pin."""

    def test_real_inputs_pass_the_cross_validation(self):
        registry = _build_registry()
        _assert_capability_catalog_mapping_is_consistent(
            registered_capability_names=_registered_capability_names(registry),
            mapping=AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY,
            catalog_workflow_keys=frozenset(WORKFLOW_TOOL_CATALOG.keys()),
        )

    def test_mapping_keys_equal_the_six_expected_capabilities(self):
        assert set(AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY.keys()) == (
            EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES
        )

    def test_all_six_capabilities_map_to_the_optimize_product_workflow_key(self):
        # ADR-069 decision 4: all six decompose the single optimize_product_2
        # workflow, whose catalog entry routes to the coarse legacy
        # listing.optimize_product chain.
        assert set(AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY.values()) == {"optimize_product_2"}
        assert WORKFLOW_TOOL_CATALOG["optimize_product_2"].tool_name == "listing.optimize_product"


class TestCrossValidationNamesTheOffendingCapability:
    """AC3 (negative case): prove the validator actually fails, and that the
    failure message names the specific offending capability — driven with
    synthetic mismatched inputs so the assertion behavior is exercised
    directly rather than hoped for."""

    def test_capability_added_to_registry_without_a_mapping_entry_fails_naming_it(self):
        registered = EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES | {"new_unmapped_capability"}
        with pytest.raises(AssertionError, match="new_unmapped_capability"):
            _assert_capability_catalog_mapping_is_consistent(
                registered_capability_names=registered,
                mapping=AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY,
                catalog_workflow_keys=frozenset(WORKFLOW_TOOL_CATALOG.keys()),
            )

    def test_capability_removed_from_registry_leaves_a_stale_mapping_entry_fails_naming_it(
        self,
    ):
        registered = EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES - {"update_product_price"}
        with pytest.raises(AssertionError, match="update_product_price"):
            _assert_capability_catalog_mapping_is_consistent(
                registered_capability_names=registered,
                mapping=AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY,
                catalog_workflow_keys=frozenset(WORKFLOW_TOOL_CATALOG.keys()),
            )

    def test_mapping_entry_pointing_at_an_unknown_workflow_key_fails_naming_the_capability(
        self,
    ):
        mapping_with_bad_workflow_key = dict(AGENT_CAPABILITY_TO_CATALOG_WORKFLOW_KEY)
        mapping_with_bad_workflow_key["get_product_information"] = "no_such_workflow_key_999"
        with pytest.raises(AssertionError, match="get_product_information"):
            _assert_capability_catalog_mapping_is_consistent(
                registered_capability_names=EXPECTED_OPTIMIZE_PRODUCT_CAPABILITIES,
                mapping=mapping_with_bad_workflow_key,
                catalog_workflow_keys=frozenset(WORKFLOW_TOOL_CATALOG.keys()),
            )


class TestLegacyRegistryUntouched:
    """AC5: this test file only reads the legacy execution registry and
    catalog — `is_tool_registered` and `WORKFLOW_TOOL_CATALOG` — and never
    imports anything that would register, unregister, or mutate a chain."""

    def test_module_under_test_exposes_only_the_read_only_lookup(self):
        import inspect

        from juli_backend.services.execution import runner

        assert callable(is_tool_registered)
        assert inspect.signature(is_tool_registered).parameters.keys() == {"name"}
        # Sanity: the read-only lookup used here is backed by the same module
        # that owns registration — this test never calls register_tool /
        # register_async_tool itself.
        assert runner.is_tool_registered is is_tool_registered
