"""Contract tests for the deterministic prompt composer -- issue #1038
(W2-A/P12-3, ADR-072 decisions 2 and 4, interface I4).

`compose(workflow_key, version)` joins the typed `Playbook` artifact (#1036)
into the version-addressed prose file (#1037). This file proves the
acceptance criteria in #1038 against the real production module:

- deterministic output, byte-identical across separate processes;
- every playbook tool name appears in the rendered `{playbook}` slot, in
  the artifact's step order;
- no template slot survives composition;
- `prompt_version`/`prompt_sha256` are exposed and stable, and the hash
  changes iff the composed bytes change (both directions);
- the production version pin is a code constant -- no environment variable
  can redirect which version composes;
- an unknown workflow_key, and an unreleased version, both raise loudly,
  naming the offending value -- never a silent fallback.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

import juli_backend.services.agent.prompts.composer as compose_module
from juli_backend.services.agent.playbooks.optimize_product import (
    OPTIMIZE_PRODUCT_PLAYBOOK,
    WORKFLOW_KEY,
)
from juli_backend.services.agent.prompts.composer import (
    ComposeIntegrityError,
    UnknownWorkflowKeyError,
    UnreleasedPromptVersionError,
    compose,
    production_version,
    prompt_sha256,
    prompt_version,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
COMPOSE_MODULE_PATH = (
    BACKEND_SRC / "juli_backend" / "services" / "agent" / "prompts" / "composer.py"
)


# ---------------------------------------------------------------------------
# compose() returns the composed prompt, deterministically
# ---------------------------------------------------------------------------


def test_compose_returns_a_string_containing_the_static_prose():
    composed = compose(WORKFLOW_KEY, 1)
    assert isinstance(composed, str)
    assert "## 1. Role" in composed
    assert "## 5. Playbook" in composed


def test_compose_same_process_twice_is_byte_identical():
    first = compose(WORKFLOW_KEY, 1)
    second = compose(WORKFLOW_KEY, 1)
    assert first == second


def test_compose_is_byte_identical_across_separate_processes():
    """Assert determinism across processes, not just twice in one process."""
    script = (
        "import sys; "
        f"sys.path.insert(0, {str(BACKEND_SRC)!r}); "
        "from juli_backend.services.agent.prompts.composer import compose; "
        f"sys.stdout.write(compose({WORKFLOW_KEY!r}, 1))"
    )
    proc_a = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    proc_b = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True
    )
    assert proc_a.stdout == proc_b.stdout
    assert proc_a.stdout != ""
    # And the cross-process output matches the same-process output too.
    assert proc_a.stdout == compose(WORKFLOW_KEY, 1)


# ---------------------------------------------------------------------------
# The rendered {playbook} slot: every tool name present, in artifact order
# ---------------------------------------------------------------------------


def test_rendered_playbook_contains_every_tool_name_from_the_artifact():
    composed = compose(WORKFLOW_KEY, 1)
    for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
        for tool_name in step.tools:
            assert tool_name in composed, tool_name


def test_rendered_playbook_step_order_matches_the_artifact():
    composed = compose(WORKFLOW_KEY, 1)
    tool_names_in_order = [
        tool_name for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps for tool_name in step.tools
    ]
    positions = [composed.index(name) for name in tool_names_in_order]
    assert positions == sorted(positions), (tool_names_in_order, positions)


def test_rendered_playbook_carries_the_policy_for_each_step():
    composed = compose(WORKFLOW_KEY, 1)
    section_start = composed.index("## 5. Playbook")
    section_end = composed.index("## 6. Recommend Within Scope")
    section = composed[section_start:section_end]
    for step in OPTIMIZE_PRODUCT_PLAYBOOK.steps:
        assert step.policy.value.upper() in section


# ---------------------------------------------------------------------------
# No template slot survives composition
# ---------------------------------------------------------------------------


def test_no_template_slot_survives_in_the_composed_output():
    composed = compose(WORKFLOW_KEY, 1)
    slot_pattern = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")
    assert slot_pattern.findall(composed) == []


# ---------------------------------------------------------------------------
# prompt_version / prompt_sha256 exposure and stability
# ---------------------------------------------------------------------------


def test_prompt_version_follows_the_prompt_directory_namespace():
    assert prompt_version(WORKFLOW_KEY, 1) == "optimize_product.v1"
    # Deliberately not the workflow_key namespace (ADR-072 decision 2).
    assert prompt_version(WORKFLOW_KEY, 1) != "optimize_product_2.v1"


def test_prompt_sha256_matches_direct_hash_of_composed_output():
    composed = compose(WORKFLOW_KEY, 1)
    expected = hashlib.sha256(composed.encode("utf-8")).hexdigest()
    assert prompt_sha256(WORKFLOW_KEY, 1) == expected


def test_prompt_sha256_is_stable_across_repeated_calls():
    assert prompt_sha256(WORKFLOW_KEY, 1) == prompt_sha256(WORKFLOW_KEY, 1)


def test_prompt_sha256_changes_when_composed_bytes_change(monkeypatch):
    """Reverse direction of the hash-changes-iff-bytes-change contract:
    swap in a `Playbook` that renders differently (same prose file, one
    fewer step) via the same explicit binding surface `compose()` reads,
    and confirm the hash moves."""
    baseline_hash = prompt_sha256(WORKFLOW_KEY, 1)

    shorter_playbook = dataclasses.replace(
        OPTIMIZE_PRODUCT_PLAYBOOK, steps=OPTIMIZE_PRODUCT_PLAYBOOK.steps[:-1]
    )
    monkeypatch.setitem(
        compose_module._WORKFLOW_BINDINGS,
        WORKFLOW_KEY,
        compose_module._WorkflowPromptBinding(
            prompt_dir="optimize_product", playbook=shorter_playbook
        ),
    )

    changed_hash = prompt_sha256(WORKFLOW_KEY, 1)
    assert changed_hash != baseline_hash


# ---------------------------------------------------------------------------
# The production pin is a code constant -- no environment variable can
# redirect which version composes.
# ---------------------------------------------------------------------------


class TestNoEnvironmentConfiguration:
    def test_module_source_never_reads_the_environment(self):
        # AST-based, not a raw substring search over the file text -- this
        # module's own docstrings legitimately discuss "the environment" in
        # English prose, which a naive `"environ" not in source` check would
        # false-positive on. What actually matters is whether any *code*
        # node references `os`, `os.environ`, or `os.getenv`.
        source = COMPOSE_MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_modules: set[str] = set()
        referenced_names: set[str] = set()
        referenced_attrs: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)
            elif isinstance(node, ast.Name):
                referenced_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_attrs.add(node.attr)
        assert "os" not in imported_modules
        assert "os" not in referenced_names
        assert "environ" not in referenced_attrs
        assert "getenv" not in referenced_attrs
        assert "getenv" not in referenced_names

    def test_setting_an_arbitrary_env_var_does_not_change_compose_output(self, monkeypatch):
        baseline = compose(WORKFLOW_KEY, 1)
        baseline_version = production_version(WORKFLOW_KEY)

        for var in (
            "OPTIMIZE_PRODUCT_PROMPT_VERSION",
            "JULI_PROMPT_VERSION",
            "PROMPT_VERSION",
            "AGENT_PROMPT_VERSION_PIN",
        ):
            monkeypatch.setenv(var, "99")

        assert compose(WORKFLOW_KEY, 1) == baseline
        assert production_version(WORKFLOW_KEY) == baseline_version

    def test_production_prompt_version_is_a_plain_module_level_dict(self):
        assert isinstance(compose_module.PRODUCTION_PROMPT_VERSION, dict)
        assert compose_module.PRODUCTION_PROMPT_VERSION[WORKFLOW_KEY] == 2

    def test_production_version_helper_returns_the_pinned_constant(self):
        assert production_version(WORKFLOW_KEY) == 2


# ---------------------------------------------------------------------------
# workflow_key -> prompt directory mapping is explicit and visible
# ---------------------------------------------------------------------------


class TestWorkflowKeyToPromptDirectoryMapping:
    def test_real_workflow_key_maps_to_the_optimize_product_prompt_directory(self):
        binding = compose_module._binding_for(WORKFLOW_KEY)
        assert binding.prompt_dir == "optimize_product"
        assert binding.playbook is OPTIMIZE_PRODUCT_PLAYBOOK

    def test_prompt_directory_name_differs_from_the_workflow_key(self):
        """Pins the exact namespace split ADR-072 decision 2 calls out:
        `workflow_key` ("optimize_product_2") is not the prompt directory
        name ("optimize_product")."""
        binding = compose_module._binding_for(WORKFLOW_KEY)
        assert WORKFLOW_KEY == "optimize_product_2"
        assert binding.prompt_dir == "optimize_product"
        assert binding.prompt_dir != WORKFLOW_KEY

    def test_unknown_workflow_key_raises_loudly_naming_it(self):
        with pytest.raises(UnknownWorkflowKeyError, match="bogus_workflow_key"):
            compose("bogus_workflow_key", 1)

    def test_unknown_workflow_key_never_silently_falls_back_to_the_default_directory(self):
        with pytest.raises(UnknownWorkflowKeyError):
            compose("optimize_product", 1)  # the *directory* name, not the workflow_key

    def test_unknown_workflow_key_also_raises_from_prompt_version_and_production_version(self):
        with pytest.raises(UnknownWorkflowKeyError, match="nonexistent_workflow"):
            prompt_version("nonexistent_workflow", 1)
        with pytest.raises(UnknownWorkflowKeyError, match="nonexistent_workflow"):
            production_version("nonexistent_workflow")


# ---------------------------------------------------------------------------
# Requesting an unreleased version raises loudly, naming the version
# ---------------------------------------------------------------------------


class TestUnreleasedVersionRaisesLoudly:
    def test_unreleased_version_raises_naming_the_version(self):
        with pytest.raises(UnreleasedPromptVersionError, match="999"):
            compose(WORKFLOW_KEY, 999)

    def test_unreleased_version_never_silently_falls_back_to_production_version(self):
        with pytest.raises(UnreleasedPromptVersionError):
            compose(WORKFLOW_KEY, 3)

    def test_invalid_version_type_or_value_raises(self):
        with pytest.raises(ValueError):
            compose(WORKFLOW_KEY, 0)
        with pytest.raises(ValueError):
            compose(WORKFLOW_KEY, -1)


# ---------------------------------------------------------------------------
# Composition integrity: a prose file whose {playbook} slot count is wrong
# ---------------------------------------------------------------------------


class TestComposeIntegrityGuards:
    def test_missing_or_duplicated_slot_raises_compose_integrity_error(self, tmp_path, monkeypatch):
        prompt_dir = tmp_path / "fake_workflow"
        prompt_dir.mkdir()
        (prompt_dir / "v1.md").write_text("no slot here at all", encoding="utf-8")

        monkeypatch.setattr(compose_module, "_PROMPTS_ROOT", tmp_path)
        monkeypatch.setitem(
            compose_module._WORKFLOW_BINDINGS,
            "fake_workflow_key",
            compose_module._WorkflowPromptBinding(
                prompt_dir="fake_workflow", playbook=OPTIMIZE_PRODUCT_PLAYBOOK
            ),
        )

        with pytest.raises(ComposeIntegrityError):
            compose("fake_workflow_key", 1)

    def test_real_v1_prose_file_has_exactly_one_playbook_slot(self):
        # Sanity pin against the real released file this module reads --
        # not a hand-copied count.
        path = COMPOSE_MODULE_PATH.parent / "optimize_product" / "v1.md"
        text = path.read_text(encoding="utf-8")
        assert text.count("{playbook}") == 1


# ---------------------------------------------------------------------------
# No I/O beyond reading the prose file: pure stdlib, no marketplace imports
# ---------------------------------------------------------------------------


class TestNoMarketplaceOrNetworkImports:
    def test_compose_module_imports_no_marketplace_or_network_symbols(self):
        tree = ast.parse(COMPOSE_MODULE_PATH.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module)

        forbidden_substrings = ("tiktok", "marketplace", "integrations", "requests", "httpx")
        offending = {
            module
            for module in imported_modules
            if any(bad in module.lower() for bad in forbidden_substrings)
        }
        assert not offending, f"compose.py must not import marketplace/network modules: {offending}"


# ---------------------------------------------------------------------------
# Composed-prompt token measurement (issue #1038 task description): report
# the real number against ADR-072 d.6's 3,000-token ceiling. This is a
# measurement/report test, not a gate -- the gate itself is #1039's scope.
# ---------------------------------------------------------------------------


def test_composed_prompt_token_estimate_is_reported_and_under_the_adr_ceiling():
    from juli_backend.services.agent.sanitize import estimate_tokens

    composed = compose(WORKFLOW_KEY, 1)
    estimate = estimate_tokens(composed)
    # ADR-072 decision 6's 3,000-token ceiling. Not a budget gate (#1039's
    # job) -- this only proves the measured number is available and, today,
    # under the ceiling reported by the architect.
    assert estimate <= 3000, (
        f"composed prompt estimates to {estimate} proxy tokens, over the "
        "3,000-token ADR-072 d.6 ceiling -- stop and report, do not trim v1.md"
    )
