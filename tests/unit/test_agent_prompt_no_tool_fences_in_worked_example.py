"""Regression test for #1367 — no fenced tool calls in a worked example.

DEFECT (#1367): The Optimize Product v2 prompt's Section 7 worked example
contained both seller-facing Vietnamese prose AND a ```python fenced code
block with the `update_product_listing` tool call. The model copied the
visible fence into its message, printing the tool call as text rather than
emitting it through the tool-call channel. No CONFIRM pause occurred and the
run terminated final_response.

This regression test pins the exact defect: no released prompt version's
worked example shall contain a fenced code block (```lang ... ```) that names
a registered tool from the playbook. This is the precise, cheapest guard
against silent reintroduction during future exemplar edits.

The test is non-vacuous by construction: v2 is carried as a strict xfail
because its Section 7 worked example (lines 177-192) contains exactly such a
fence with `update_product_listing`. See `RELEASED_PROMPT_VERSIONS` below for
why v2 is marked rather than excluded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = (
    REPO_ROOT
    / "backend"
    / "src"
    / "juli_backend"
    / "services"
    / "agent"
    / "prompts"
    / "optimize_product"
)

# All released versions of the prompt (v1, v2, v3, ...) that exist on disk.
# As new versions are added, add them here to include them in the regression
# test. This is deliberately explicit, not a glob — we want to know exactly
# which versions we're testing, and a new version must be a conscious entry.
#
# v2 is the known-bad version: its Section 7 worked example IS defect #1367.
# ADR-072 d.4 makes a released prompt immutable, and v2 has already executed
# in production with a recorded `prompt_sha256` on `workflow_runs`, so it can
# never be cleaned up in place and this invariant can never hold for it.
#
# It is marked strict-xfail rather than dropped from the parameter list, so
# the assertion still runs against v2 and the defect stays documented in
# executable form. `strict=True` matters: if v2 ever STOPS containing the
# fence, the xfail turns into a suite failure — which is exactly the alarm we
# want, because the only way that happens is someone editing an immutable
# released prompt.
RELEASED_PROMPT_VERSIONS = (
    1,
    pytest.param(
        2,
        marks=pytest.mark.xfail(
            strict=True,
            reason=(
                "v2 Section 7 is defect #1367 itself; released and immutable "
                "under ADR-072 d.4, so it cannot be fixed in place"
            ),
        ),
    ),
    3,
)


@pytest.fixture(scope="module")
def tool_names_in_playbook() -> set[str]:
    """The set of all tool names declared in the Optimize Product playbook.
    These are the names we must NOT find inside fenced code blocks in worked
    examples.
    """
    tools = set()
    for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
        tools.update(step.tools)
    return tools


def _extract_worked_example(prompt_text: str) -> str:
    """Extract the worked example section from a prompt file.

    The worked example runs from the "Worked example" marker in Section 7
    until Section 8's heading.
    """
    try:
        start_idx = prompt_text.index("**Worked example", prompt_text.index("## 7."))
        end_idx = prompt_text.index("## 8. Prohibited Behaviors")
        return prompt_text[start_idx:end_idx]
    except ValueError:
        # If the marker or section is missing, return empty string
        return ""


def _extract_fenced_blocks(text: str) -> list[str]:
    """Extract all fenced code blocks from the text.

    Returns a list of the content inside each fenced block (language tag and
    content, but not the delimiters).
    """
    # Match ``` optionally followed by a language tag, then content, then ```
    pattern = r"```[\w]*\n(.*?)\n```"
    matches = re.findall(pattern, text, re.DOTALL)
    return matches


@pytest.mark.parametrize("version", RELEASED_PROMPT_VERSIONS)
def test_no_tool_names_in_fenced_blocks_of_worked_example(
    version: int, tool_names_in_playbook: set[str]
):
    """For each released prompt version, assert that no fenced code block
    in the worked example contains any tool name from the playbook.

    v2 is expected to fail (strict xfail) — its worked example contains a
    ```python block with `update_product_listing(...)`, which is the defect
    this guard exists to prevent recurring.
    """
    prompt_path = PROMPTS_DIR / f"v{version}.md"
    if not prompt_path.is_file():
        pytest.skip(f"prompt version {version} does not exist at {prompt_path}")

    prompt_text = prompt_path.read_text(encoding="utf-8")
    worked_example = _extract_worked_example(prompt_text)

    # If no worked example marker is found, skip (shouldn't happen, but be defensive)
    if not worked_example.strip():
        pytest.skip(f"v{version} has no worked example section")

    # Extract all fenced blocks from the worked example
    fenced_blocks = _extract_fenced_blocks(worked_example)

    # Check each fenced block: it must not contain any tool name
    for block_idx, block_content in enumerate(fenced_blocks):
        block_lower = block_content.lower()
        for tool_name in tool_names_in_playbook:
            # Case-insensitive check: the tool name must not appear in the
            # fenced block. This catches both explicit function calls
            # (update_product_listing(...)) and any reference to the tool.
            if tool_name.lower() in block_lower:
                pytest.fail(
                    f"v{version} worked example fenced block #{block_idx} "
                    f"contains tool name {tool_name!r}:\n{block_content}\n\n"
                    f"Fenced code blocks in worked examples must never show "
                    f"tool calls or tool names — the tool call is emitted "
                    f"through the tool-call channel, not printed as text."
                )
