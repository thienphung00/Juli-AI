"""Optimize Product `Playbook` contract tests — issue #1036 (W2-A, ADR-072
decision 2).

Proves the concrete `OPTIMIZE_PRODUCT_PLAYBOOK` matches ADR-069 decision 1's
documented step order and policy column exactly, resolves against the real
tool registry, carries ADR-073's `TerminationPolicy` on the artifact itself,
pins `workflow_key` to the system-wide catalog key (not the prompt
directory name), and stays business-English / vendor-vocabulary-free
(note #1014).
"""

from __future__ import annotations

import dataclasses

import pytest

from juli_backend.services.agent.playbooks.base import Playbook, validate_playbook_tools
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    OPTIMIZE_PRODUCT_TERMINATION_POLICY,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.tools.product import register_product_read_tools
from juli_backend.services.agent.tools.product_write import register_product_write_tools
from juli_backend.services.agent.tools.registry import ToolClassification, ToolPolicy, ToolRegistry
from juli_backend.services.execution.tool_routing import WORKFLOW_TOOL_CATALOG

# ADR-069 decision 1's documented order and policy column, reproduced
# exactly here as this test's own independent pin (not read back off the
# playbook under test).
EXPECTED_STEP_ORDER: tuple[tuple[str, str, ToolPolicy], ...] = (
    ("1", "get_product_information", ToolPolicy.AUTO),
    ("2+3", "get_seo_keywords", ToolPolicy.AUTO),
    ("4, 4.5", "upload_product_image", ToolPolicy.AUTO),
    ("5", "update_product_listing", ToolPolicy.CONFIRM),
    ("6", "update_product_price", ToolPolicy.CONFIRM),
    ("6.5", "check_product_status", ToolPolicy.AUTO),
)

VENDOR_VOCABULARY_BANNED_SUBSTRINGS = (
    "products.get_details",
    "products.edit",
    "products.update_prices",
    "get_seo_words",
    "get_suggestions",
    "GuardedTikTokClient",
    "TikTokClient",
    "ProductionReadResources",
    "SandboxWriteResources",
    "ToolSpec",
    "ProductToolContext",
    "resources.products",
    "sku_ref",
)


def _build_full_registry() -> ToolRegistry:
    """The real current universe of registered agent capabilities (W1-A),
    built independently of `optimize_product.py`'s own internal
    `_build_registry` helper so this test does not merely trust that the
    production module validated itself correctly at import time."""
    registry = ToolRegistry()
    register_product_read_tools(registry)
    register_product_write_tools(registry)
    return registry


class TestPlaybookShape:
    def test_is_a_playbook_instance(self):
        assert isinstance(OPTIMIZE_PRODUCT_PLAYBOOK, Playbook)

    def test_workflow_key_and_version(self):
        assert OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key == WORKFLOW_KEY == "optimize_product_2"
        assert OPTIMIZE_PRODUCT_PLAYBOOK.version == 1

    def test_six_steps_in_adr069_order_with_exact_policy_column(self):
        actual = tuple(
            (step.step_id, step.tools, step.policy) for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps
        )
        expected = tuple(
            (step_id, (tool_name,), policy) for step_id, tool_name, policy in EXPECTED_STEP_ORDER
        )
        assert actual == expected

    def test_covers_all_six_registered_capabilities_exactly_once(self):
        all_tool_names = [
            tool_name for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps for tool_name in step.tools
        ]
        assert sorted(all_tool_names) == sorted(
            [
                "get_product_information",
                "get_seo_keywords",
                "check_product_status",
                "upload_product_image",
                "update_product_listing",
                "update_product_price",
            ]
        )
        assert len(all_tool_names) == len(set(all_tool_names))  # each tool exactly once


class TestWorkflowKeyMatchesCatalog:
    """The playbook's `workflow_key` is the system-wide key, not the prompt
    directory name — it must join against `WORKFLOW_TOOL_CATALOG` (#983's
    cross-validation and ADR-077 decision 5's outcome vocabulary both key
    off this same value). An earlier attempt at this slice set
    `workflow_key = "optimize_product"` (the prompt directory name from
    ADR-072 decision 2) instead of the catalog key — that was a bug this
    test class exists to catch, permanently.

    `WORKFLOW_TOOL_CATALOG` (`services/execution/tool_routing.py`) is
    imported read-only here — never modified, never used to construct or
    dispatch anything."""

    def test_workflow_key_is_a_real_catalog_key(self):
        assert OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key in WORKFLOW_TOOL_CATALOG

    def test_workflow_key_is_not_the_prompt_directory_name(self):
        """Guards against the exact regression this test class exists to
        catch: workflow_key silently reverting to the prompt-directory
        spelling, which is a different namespace (the prompt path stays
        `services/agent/prompts/optimize_product/v1.md` regardless of this
        key)."""
        assert OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key == "optimize_product_2"
        assert OPTIMIZE_PRODUCT_PLAYBOOK.workflow_key != "optimize_product"


class TestPlaybookToolsResolveAgainstRealRegistry:
    def test_validate_playbook_tools_does_not_raise(self):
        validate_playbook_tools(OPTIMIZE_PRODUCT_PLAYBOOK, _build_full_registry())

    def test_every_step_tool_is_gettable_from_registry(self):
        registry = _build_full_registry()
        for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
            for tool_name in step.tools:
                registry.get(tool_name)  # raises UnknownToolError if missing


class TestTerminationPolicyFromADR073:
    def test_carried_on_the_playbook_not_a_module_constant_reference(self):
        assert OPTIMIZE_PRODUCT_PLAYBOOK.termination_policy is OPTIMIZE_PRODUCT_TERMINATION_POLICY

    def test_values_match_adr073_decision_2(self):
        policy = OPTIMIZE_PRODUCT_PLAYBOOK.termination_policy
        assert policy.max_iterations == 6
        assert policy.max_extensions == 1
        assert policy.extension_iterations == 2
        assert policy.wall_clock_timeout_s == 300
        assert policy.approval_timeout_h == 4

    def test_required_steps_pinned_to_the_two_adr073_confirmed_writes(self):
        """ADR-073 decision 2: "did the job" is defined by the two
        seller-confirmed writes -- the listing content change and the price
        change. Pinned as an exact tuple (not just "contains" or
        "is a subset of") so a silent addition, removal, or reordering of
        required_steps fails here rather than passing under a weaker check."""
        assert OPTIMIZE_PRODUCT_PLAYBOOK.termination_policy.required_steps == (
            "update_product_listing",
            "update_product_price",
        )

    def test_required_steps_are_registered_write_capabilities(self):
        """Acceptance criterion: required_steps names the writes whose
        seller confirmation defines "did the job" -- not merely tool names
        that happen to resolve against the registry (a READ tool would
        resolve too). Asserts genuine WRITE classification on each entry,
        not just registry.get() succeeding."""
        registry = _build_full_registry()
        for tool_name in OPTIMIZE_PRODUCT_PLAYBOOK.termination_policy.required_steps:
            spec = registry.get(tool_name)
            assert spec.classification == ToolClassification.WRITE, (
                f"required_steps entry {tool_name!r} must be a WRITE-classified "
                f"tool, got {spec.classification!r}"
            )


class TestIntentIsBusinessEnglish:
    """Note #1014: model-facing text shipping internal vocabulary is an
    open defect — this playbook must not add to it."""

    def test_no_vendor_endpoint_or_internal_class_names_in_intent_text(self):
        for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
            for banned in VENDOR_VOCABULARY_BANNED_SUBSTRINGS:
                assert banned not in step.intent, (
                    f"step {step.step_id!r} intent leaks vendor/internal vocabulary "
                    f"{banned!r}: {step.intent!r}"
                )

    def test_intent_is_not_just_the_tool_name_restated(self):
        for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
            for tool_name in step.tools:
                assert step.intent.strip() != tool_name


class TestPlaybookIsFrozenAtConcreteLevel:
    def test_mutating_the_real_playbook_raises(self):
        with pytest.raises(dataclasses.FrozenInstanceError):
            OPTIMIZE_PRODUCT_PLAYBOOK.version = 2  # type: ignore[misc]
