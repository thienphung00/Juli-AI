"""Playbook consistency gate — issue #1039 (W2-A/P12-4, ADR-072 decision 6,
gate 3 of 4).

ADR-069 decision 3's two-way cross-validation and `playbooks/base.py`'s
`validate_playbook_tools` already prove every `Playbook.steps[*].tools` entry
resolves against the real `ToolRegistry` (playbook -> registry). #1038's
`test_rendered_playbook_contains_every_tool_name_from_the_artifact` already
proves every `Playbook` tool name appears somewhere in the *rendered*
`{playbook}` slot (playbook -> composed prompt).

This gate closes the one direction neither of those proves: every tool-name-
shaped token that appears **anywhere in the composed prompt** -- not just
inside the rendered playbook table -- must actually be a real step tool in
the `Playbook`. That is the gap ADR-072 d.6 names: "closing the gap where
prose and allowlist could drift" -- e.g. a future prose edit that mentions a
tool by name in running text (a typo, a leftover reference to a renamed
tool, a tool a future prompt author assumes exists) would pass every
existing check and still mislead the model about what it may call.

## How a "tool name" is identified mechanically

A tool-name-shaped token is a backtick-quoted, all-lowercase identifier
containing at least one underscore -- e.g. `` `get_product_information` ``.
Every real tool name in this repo's registry is exactly this shape
(`services/agent/tools/registry.py`'s `ToolSpec.name` docstring: "business-
semantic English snake_case"). Checked directly against the real,
already-composed `v1.md` prose (verified below by
`test_no_other_backtick_underscored_tokens_exist_outside_tool_names_in_the_static_prose`),
no other backtick-quoted token in this prompt's static prose (section
markers like `` `intent` ``/`` `policy` ``/`` `tools` ``, source roles like
`` `juli` ``/`` `vendor` ``/`` `seller` ``, or dotted `dictionary.md` keys
like `` `decisions.recommendation` ``) matches this shape, so the extraction
below has no realistic false-positive surface today.

Driven with **synthetic** input (`TestSyntheticDriftDetection` below), per
issue #1039's acceptance criterion -- this gate must fail naming a tool
present in prose but absent from the `Playbook` even if the real pair never
actually drifts, so it cannot pass "by accident of the real pair agreeing".
"""

from __future__ import annotations

import re

import pytest

from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.prompts.composer import compose

#: Backtick-quoted, all-lowercase-with-underscore identifiers -- the shape
#: every real tool name in this repo's `ToolRegistry` takes (see module
#: docstring). Deliberately requires an underscore so it never matches the
#: single-word backtick tokens this prompt's static prose legitimately uses
#: for other purposes (`` `juli` ``, `` `policy` ``, `` `tools` ``, ...), and
#: deliberately excludes any character outside `[a-z0-9_]` so it never
#: matches dotted `dictionary.md` keys like `` `decisions.recommendation` ``.
_TOOL_NAME_SHAPED_TOKEN_PATTERN = re.compile(r"`([a-z][a-z0-9_]*)`")


def _tool_name_shaped_tokens(text: str) -> set[str]:
    return {token for token in _TOOL_NAME_SHAPED_TOKEN_PATTERN.findall(text) if "_" in token}


def _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
    text: str, known_tool_names: frozenset[str]
) -> None:
    """The gate's actual check: every tool-name-shaped token found in `text`
    must be a member of `known_tool_names`. Raises `AssertionError` naming
    every offending token -- never just "a tool was wrong".
    """
    found = _tool_name_shaped_tokens(text)
    offenders = sorted(found - known_tool_names)
    assert offenders == [], (
        f"tool-name-shaped token(s) in composed prompt not present in the "
        f"Playbook's tool allowlist: {offenders}"
    )


def _real_playbook_tool_names() -> frozenset[str]:
    return frozenset(
        tool_name for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps for tool_name in step.tools
    )


# ---------------------------------------------------------------------------
# The real gate: every tool-name-shaped token in the real composed prompt is
# a real Playbook tool.
# ---------------------------------------------------------------------------


def test_every_tool_name_shaped_token_in_the_real_composed_prompt_is_in_the_playbook():
    composed = compose(WORKFLOW_KEY, 1)
    _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
        composed, _real_playbook_tool_names()
    )


def test_the_real_composed_prompt_actually_contains_tool_name_shaped_tokens():
    """Sanity check the extraction isn't vacuously finding zero tokens --
    the gate above only means something if it is actually exercised by real
    tokens from the rendered playbook table.
    """
    composed = compose(WORKFLOW_KEY, 1)
    found = _tool_name_shaped_tokens(composed)
    assert found == _real_playbook_tool_names()


def test_no_other_backtick_underscored_tokens_exist_outside_tool_names_in_the_static_prose():
    """Documents, mechanically, the "no realistic false-positive surface"
    claim in the module docstring: every backtick-quoted token found in the
    real composed prompt that both starts with a lowercase letter and
    contains an underscore is either a real playbook tool name, a dotted
    `dictionary.md` key (e.g. `` `decisions.estimated_impact` ``), or the
    mini-glossary's own `` `_Avoid_` `` marker -- there is no fourth,
    unaccounted-for category the extraction regex could be silently
    misclassifying as a tool name.

    Broader than `_tool_name_shaped_tokens` on purpose (it also inspects
    tokens containing "." and mixed-case tokens) precisely so this test can
    prove the *production* extraction pattern's narrower shape
    (`_TOOL_NAME_SHAPED_TOKEN_PATTERN`, `[a-z][a-z0-9_]*` only) isn't
    quietly missing some other token shape that also deserves scrutiny.
    """
    composed = compose(WORKFLOW_KEY, 1)
    all_backtick_tokens = set(re.findall(r"`([a-zA-Z0-9_.]+)`", composed))
    underscored_lowercase_start_tokens = {
        token
        for token in all_backtick_tokens
        if "_" in token and token[0].islower() and token not in _real_playbook_tool_names()
    }
    # Every remaining token is a dotted dictionary.md key -- the only other
    # backtick-quoted, lowercase-starting, underscore-containing shape this
    # prompt's static prose legitimately uses.
    assert all("." in token for token in underscored_lowercase_start_tokens), (
        underscored_lowercase_start_tokens
    )


# ---------------------------------------------------------------------------
# Synthetic drift detection -- do not rely on the real pair happening to
# agree (issue #1039 acceptance criterion).
# ---------------------------------------------------------------------------


class TestSyntheticDriftDetection:
    def test_a_tool_name_in_prose_but_absent_from_the_playbook_fails_naming_it(self):
        synthetic_composed = (
            "## 5. Playbook\n\n"
            "| Step | Intent | Tools | Policy |\n"
            "|------|--------|-------|--------|\n"
            "| 1 | Read the product. | `get_product_information` | AUTO |\n\n"
            "## 6. Recommend Within Scope\n\n"
            "If you need to look up a competing listing, call "
            "`search_marketplace_products` for comparison data.\n"
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

    def test_multiple_offenders_are_all_named_together(self):
        synthetic_composed = "Use `list_all_orders` first, then `delete_product_listing` if needed."
        known_tool_names = frozenset({"get_product_information"})

        offenders_pattern = (
            r"delete_product_listing.*list_all_orders|list_all_orders.*delete_product_listing"
        )
        with pytest.raises(AssertionError, match=offenders_pattern):
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

    def test_prose_with_no_tool_name_shaped_tokens_at_all_does_not_fail(self):
        synthetic_composed = "This prose mentions `juli`, `vendor`, and `seller` only."
        known_tool_names = frozenset({"get_product_information"})
        # Must not raise -- no tool-name-shaped tokens present at all.
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
