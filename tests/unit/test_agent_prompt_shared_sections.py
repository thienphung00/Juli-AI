"""Shared prompt sections -- issue #1705 (W9-A/P-SHARED-5, ADR-072 d.1's
extraction trigger).

ADR-072 d.1 shipped Optimize Product as one monolithic prose file and named
the condition under which that stops: "when a second workflow's prompt lands,
sections shared by both are extracted so that no behavior rule ever lives in
more than one file." This module is the test that the extraction is real
rather than cosmetic.

Two failure modes are worth naming, because a prompt refactor can pass every
existing gate while suffering either.

1. **The shared file is not actually in the composition.** Every gate still
   passes -- they compare composed bytes against goldens regenerated from the
   same broken composition. `TestASharedRuleLivesInExactlyOneFile` catches
   this by *editing* a shared section in a `tmp_path` copy of the real
   `prompts/` tree and asserting every registered workflow's composed prompt
   moved. If a shared file were not composed in, nothing would move.

2. **The gates pass in aggregate rather than per workflow.** A parametrised
   gate whose cases are dominated by one passing workflow is worse than three
   separate gates, because it reads as broader coverage than it has.
   `TestGatesFailPerWorkflow` registers a second workflow, breaks only that
   one, and asserts the real workflow's three gate checks still pass while the
   second one's fail.

Nothing here writes to the repository. Every mutation happens on a
`shutil.copytree` copy under `tmp_path`, and the final test of each mutating
class re-reads the real files to prove they never moved.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

import juli_backend.services.agent.playbooks as playbooks_module
import juli_backend.services.agent.prompts.composer as compose_module
from juli_backend.services.agent.playbooks.base import Playbook
from juli_backend.services.agent.playbooks.optimize_product import WORKFLOW_KEY
from juli_backend.services.agent.prompts.composer import (
    SHARED_SECTION_NAMES,
    SHARED_SECTIONS,
    ComposeIntegrityError,
    compose,
    production_version,
    registered_workflow_keys,
    shared_section_text,
    token_budget_ceiling,
)
from tests.support.workflow_registry import TEST_FIRST_TOOL, make_test_playbook

# The three gates, imported rather than reimplemented: this module asserts
# that a second workflow passes *the real gates*, so it must call the very
# helpers those gate modules call (#1705 acceptance criterion 3).
from tests.unit.test_agent_prompt_budget_gate import _assert_composed_prompt_within_budget
from tests.unit.test_agent_prompt_playbook_consistency_gate import (
    _assert_every_tool_name_shaped_token_is_a_real_playbook_tool,
    _playbook_tool_names,
)
from tests.unit.test_agent_prompt_snapshot_gate import _assert_matches_golden_snapshot

_REAL_PROMPTS_ROOT = compose_module._PROMPTS_ROOT

#: The second workflow's prompt directory and key. Not a plausible production
#: spelling, and registered only inside a contextmanager, so nothing it
#: composes can be mistaken for a released prompt.
SECOND_WORKFLOW_PROMPT_DIR = "test_only_workflow_1705"

#: The test-only workflow's own prose: two lines of workflow-specific text,
#: then the slots. Everything else it says -- role, mandate, source-role
#: rules, prohibitions -- arrives from the shared sections, which is exactly
#: the property under test.
_SECOND_WORKFLOW_OWN_PROSE = (
    "You are Juli's test-only workflow agent, for TikTok Shop sellers.\n"
    "Your job this run is to confirm one listing is still live, and nothing else.\n"
)


def _second_workflow_prose() -> str:
    slots = "\n\n".join(section.slot for section in SHARED_SECTIONS)
    return (
        f"## 1. Role\n\n{_SECOND_WORKFLOW_OWN_PROSE}\n{slots}\n\n## 5. Playbook\n\n{{playbook}}\n"
    )


@contextmanager
def _second_workflow_registered(tmp_path: Path, prose: str) -> Iterator[tuple[str, Path]]:
    """Register a real second workflow -- playbook, prompt binding and prose
    file -- against a `tmp_path` copy of the real `prompts/` tree.

    Yields `(workflow_key, prompts_root)`. The playbook goes through
    `playbooks.playbook_registered_for_test`, the same seam #1702 built and
    the same `_PLAYBOOK_REGISTRY` `approve_action_card` and the reaper read;
    the prompt binding goes into the real `_WORKFLOW_BINDINGS` dict
    `compose()` itself reads. Neither is a parallel dict built for this test
    -- a second workflow that resolved against its own map would prove
    nothing about the gates.
    """
    prompts_root = tmp_path / "prompts_copy"
    if not prompts_root.exists():
        shutil.copytree(_REAL_PROMPTS_ROOT, prompts_root)
    prompt_dir = prompts_root / SECOND_WORKFLOW_PROMPT_DIR
    prompt_dir.mkdir(exist_ok=True)
    (prompt_dir / "v1.md").write_text(prose, encoding="utf-8")

    playbook: Playbook = make_test_playbook(workflow_key=SECOND_WORKFLOW_PROMPT_DIR)
    key = playbook.workflow_key
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(compose_module, "_PROMPTS_ROOT", prompts_root)
        patch.setitem(
            compose_module._WORKFLOW_BINDINGS,
            key,
            compose_module._WorkflowPromptBinding(
                prompt_dir=SECOND_WORKFLOW_PROMPT_DIR, production_version=1
            ),
        )
        with playbooks_module.playbook_registered_for_test(playbook):
            yield key, prompts_root


def _pinned_prose_path(workflow_key: str) -> Path:
    binding = compose_module._binding_for(workflow_key)
    return compose_module._prose_path(binding.prompt_dir, binding.production_version)


# ---------------------------------------------------------------------------
# Acceptance criterion 1: a behaviour rule lives in exactly one file, and
# editing that file moves every registered workflow's composed prompt.
# ---------------------------------------------------------------------------


class TestASharedRuleLivesInExactlyOneFile:
    def test_shared_rule_appears_once_and_composes_into_every_workflow(self, tmp_path: Path):
        """The named acceptance criterion of #1705.

        Three claims, each asserted by execution:

        1. every registered workflow's composed prompt, at its pinned
           production version, contains every shared section verbatim;
        2. no pinned workflow prose file contains that text -- it carries the
           slot instead, so the rule is written down in exactly one place;
        3. editing the shared file moves every registered workflow's composed
           prompt, which is what makes (1) a fact about the composition
           rather than a coincidence of two files agreeing.
        """
        with _second_workflow_registered(tmp_path, _second_workflow_prose()) as (
            second_key,
            prompts_root,
        ):
            keys = registered_workflow_keys()
            assert len(keys) >= 2, "this criterion is vacuous with a single workflow"
            assert second_key in keys

            baseline = {key: compose(key, production_version(key)) for key in keys}

            # (1) every shared section's text is in every composed prompt.
            for section in SHARED_SECTIONS:
                text = shared_section_text(section.name, section.version)
                assert text, f"shared section {section.name!r} is empty"
                for key, composed in baseline.items():
                    assert text in composed, (
                        f"shared section {section.name!r} v{section.version} does not "
                        f"appear in {key!r}'s composed prompt"
                    )

                # (2) and it is not written out in any workflow's own prose.
                for key in keys:
                    prose = _pinned_prose_path(key).read_text(encoding="utf-8")
                    assert text not in prose, (
                        f"{key!r}'s pinned prose file restates shared section "
                        f"{section.name!r} instead of referencing its slot"
                    )
                    assert section.slot in prose

            # (3) editing the rule moves every workflow's composed prompt.
            edited = SHARED_SECTIONS[0]
            edited_path = prompts_root / edited.relative_path
            edited_path.write_text(
                edited_path.read_text(encoding="utf-8") + "\nOne further shared rule.\n",
                encoding="utf-8",
            )
            for key in keys:
                recomposed = compose(key, production_version(key))
                assert recomposed != baseline[key], (
                    f"editing shared section {edited.name!r} did not change {key!r}'s "
                    "composed prompt -- the shared file is not in the composition"
                )
                assert "One further shared rule." in recomposed

    def test_the_real_shared_section_files_are_untouched(self, tmp_path: Path):
        before = {
            section.name: (_REAL_PROMPTS_ROOT / section.relative_path).read_bytes()
            for section in SHARED_SECTIONS
        }
        with _second_workflow_registered(tmp_path, _second_workflow_prose()):
            pass
        after = {
            section.name: (_REAL_PROMPTS_ROOT / section.relative_path).read_bytes()
            for section in SHARED_SECTIONS
        }
        assert before == after

    def test_every_registered_shared_section_has_a_file_on_disk(self):
        for section in SHARED_SECTIONS:
            path = _REAL_PROMPTS_ROOT / section.relative_path
            assert path.is_file(), f"registered shared section has no file at {path}"
            assert path.read_text(encoding="utf-8").strip()

    def test_the_registered_sections_are_the_four_adr_072_d1_names(self):
        assert SHARED_SECTION_NAMES == ("role", "mandate", "source_roles", "prohibitions")


# ---------------------------------------------------------------------------
# Acceptance criterion 3: a second workflow with a two-line prompt composes
# the shared sections plus its own playbook block and passes all three gates.
# ---------------------------------------------------------------------------


class TestASecondWorkflowComposesAndPassesTheGates:
    def test_second_workflow_composes_and_passes_gates(self, tmp_path: Path):
        """The named acceptance criterion of #1705.

        The second workflow's own prose is two lines. Everything else it
        says arrives from the shared sections and from its own rendered
        playbook -- and it is put through the same three gate helpers the
        real workflow is, each against its own golden and its own ceiling.
        """
        with _second_workflow_registered(tmp_path, _second_workflow_prose()) as (key, _):
            composed = compose(key, production_version(key))

            # Its own two lines, and nothing of Optimize Product's.
            assert "test-only workflow agent" in composed
            assert "Optimize Product" not in composed

            # Every shared section, verbatim.
            for section in SHARED_SECTIONS:
                assert shared_section_text(section.name, section.version) in composed

            # Its own playbook block, rendered from the registered Playbook.
            assert "| 1 | " in composed
            assert f"`{TEST_FIRST_TOOL}`" in composed
            assert "{playbook}" not in composed

            # Gate 1 -- snapshot, against its own golden.
            golden = tmp_path / "second_workflow_v1_composed.golden.md"
            golden.write_bytes(composed.encode("utf-8"))
            _assert_matches_golden_snapshot(
                compose(key, production_version(key)), golden.read_bytes()
            )

            # Gate 2 -- budget, against its own registered ceiling.
            _assert_composed_prompt_within_budget(composed, ceiling=token_budget_ceiling(key))

            # Gate 3 -- playbook consistency, against its own allowlist.
            _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
                composed, _playbook_tool_names(playbooks_module.get_playbook(key))
            )

    def test_a_prompt_that_omits_a_shared_section_refuses_to_compose(self, tmp_path: Path):
        """A workflow cannot quietly opt out of a behaviour rule: a prose
        file that uses some shared sections but not all of them is a
        `ComposeIntegrityError` naming the ones it dropped."""
        dropped = SHARED_SECTIONS[-1]
        partial = _second_workflow_prose().replace(dropped.slot + "\n\n", "")
        assert dropped.slot not in partial

        with _second_workflow_registered(tmp_path, partial) as (key, _):
            with pytest.raises(ComposeIntegrityError, match=dropped.name):
                compose(key, production_version(key))

    def test_a_prompt_that_uses_no_shared_section_still_composes(self, tmp_path: Path):
        """The pre-extraction released versions (`optimize_product/v1.md`
        through `v3.md`) reference no shared section and must keep composing
        byte-identically -- ADR-072 d.4. Proven on the real files rather than
        on this synthetic one, but the rule is exercised here too."""
        no_shared = "## 1. Role\n\nA prompt from before the extraction.\n\n{playbook}\n"
        with _second_workflow_registered(tmp_path, no_shared) as (key, _):
            composed = compose(key, production_version(key))
        assert "before the extraction" in composed
        for section in SHARED_SECTIONS:
            assert shared_section_text(section.name, section.version) not in composed

    def test_an_unregistered_shared_slot_is_refused_by_name(self, tmp_path: Path):
        bogus = _second_workflow_prose().replace(
            SHARED_SECTIONS[0].slot, "{shared_not_a_real_section_v1}"
        )
        with _second_workflow_registered(tmp_path, bogus) as (key, _):
            with pytest.raises(ComposeIntegrityError, match="shared_not_a_real_section_v1"):
                compose(key, production_version(key))

    def test_a_repeated_shared_slot_is_refused_by_name(self, tmp_path: Path):
        repeated = _second_workflow_prose().replace(
            SHARED_SECTIONS[0].slot, SHARED_SECTIONS[0].slot + "\n\n" + SHARED_SECTIONS[0].slot
        )
        with _second_workflow_registered(tmp_path, repeated) as (key, _):
            with pytest.raises(ComposeIntegrityError, match=SHARED_SECTIONS[0].name):
                compose(key, production_version(key))


# ---------------------------------------------------------------------------
# Acceptance criterion 2: the gates run once per registered workflow, and a
# break in one workflow fails that workflow's case alone.
# ---------------------------------------------------------------------------


class TestGatesFailPerWorkflow:
    """A parametrised gate that passes because one case dominates is worse
    than three separate gates. These tests hold two workflows registered,
    break exactly one of them, and assert the asymmetry directly.
    """

    def test_a_broken_second_workflow_does_not_drag_down_the_real_one(self, tmp_path: Path):
        # A prose file that names a tool its own playbook never grants.
        broken = _second_workflow_prose().replace(
            "and nothing else.", "and nothing else. Never call `update_product_listing`."
        )
        with _second_workflow_registered(tmp_path, broken) as (second_key, _):
            second_composed = compose(second_key, production_version(second_key))
            with pytest.raises(AssertionError, match="update_product_listing"):
                _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
                    second_composed, _playbook_tool_names(playbooks_module.get_playbook(second_key))
                )

            # The real workflow's own case is untouched by the neighbour's break.
            real_composed = compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY))
            _assert_every_tool_name_shaped_token_is_a_real_playbook_tool(
                real_composed, _playbook_tool_names(playbooks_module.get_playbook(WORKFLOW_KEY))
            )

    def test_an_over_budget_second_workflow_does_not_drag_down_the_real_one(self, tmp_path: Path):
        padded = _second_workflow_prose().replace(
            "and nothing else.", "and nothing else. " + "padding " * 4000
        )
        with _second_workflow_registered(tmp_path, padded) as (second_key, _):
            second_composed = compose(second_key, production_version(second_key))
            with pytest.raises(AssertionError, match="over the 3000-token ceiling"):
                _assert_composed_prompt_within_budget(
                    second_composed, ceiling=token_budget_ceiling(second_key)
                )

            real_composed = compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY))
            _assert_composed_prompt_within_budget(
                real_composed, ceiling=token_budget_ceiling(WORKFLOW_KEY)
            )

    def test_the_snapshot_gate_distinguishes_the_two_workflows(self, tmp_path: Path):
        with _second_workflow_registered(tmp_path, _second_workflow_prose()) as (
            second_key,
            prompts_root,
        ):
            second_golden = compose(second_key, production_version(second_key)).encode("utf-8")
            real_golden = compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY)).encode("utf-8")

            # Break only the second workflow's prose file.
            second_prose = prompts_root / SECOND_WORKFLOW_PROMPT_DIR / "v1.md"
            second_prose.write_bytes(second_prose.read_bytes() + b".")

            with pytest.raises(AssertionError, match="no longer matches"):
                _assert_matches_golden_snapshot(
                    compose(second_key, production_version(second_key)), second_golden
                )

            # Must not raise: the real workflow's snapshot did not move.
            _assert_matches_golden_snapshot(
                compose(WORKFLOW_KEY, production_version(WORKFLOW_KEY)), real_golden
            )
