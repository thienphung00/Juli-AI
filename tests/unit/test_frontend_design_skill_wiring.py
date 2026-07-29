"""ADR-043 durable frontend design skill wiring (#581 / DVR-B1)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

OPEN_DESIGN_SKILL = REPO_ROOT / ".cursor/skills/standalone/open-design-system/SKILL.md"
SKILL_CATALOG = REPO_ROOT / ".cursor/skills/skill-catalog/SKILL.md"
FOCUS_SKILL = REPO_ROOT / ".cursor/skills/standalone/focus/SKILL.md"
ROUTING_RULES = REPO_ROOT / ".cursor/skills/standalone/focus/routing-rules.md"
SLICE_ROUTING = REPO_ROOT / "agent-runtime/config/slice-routing.yml"
META_PREPARE = REPO_ROOT / "agent-runtime/scripts/meta_prepare_executor.py"
AGENT_RUNTIME_CONFIG = REPO_ROOT / "agent-runtime/config/agent-runtime.config.yml"

UI_UX_SLICES = ("P2-6", "DEMO-ASSET-1", "DEMO-ASSET-3")
UPSTREAM_SKILL = ".cursor/skills/standalone/open-design-system/SKILL.md"
IMPLEMENTATION_SKILL = ".cursor/skills/standalone/ui-ux-design/SKILL.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file at {path}"
    return path.read_text(encoding="utf-8")


def _slice_block(yaml_text: str, slice_id: str) -> str:
    match = re.search(
        rf"^{re.escape(slice_id)}:\n(.*?)(?=^\S|\Z)",
        yaml_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match, f"slice {slice_id!r} missing from slice-routing.yml"
    return match.group(1)


@pytest.mark.parametrize("path", [OPEN_DESIGN_SKILL])
def test_open_design_skill_exists(path: Path) -> None:
    text = _read(path)
    assert "design-reference" in text.lower() or "design reference" in text.lower()
    assert "ui-ux-design" in text
    assert "Mobbin" in text or "mobbin" in text


def test_skill_catalog_registers_open_design_and_mobbin_mcps() -> None:
    catalog = _read(SKILL_CATALOG)
    assert "id: open-design" in catalog or "id: open_design" in catalog
    assert "folder: user-open-design" in catalog
    assert "serverName: open-design" in catalog
    assert "id: mobbin" in catalog.lower()
    assert "folder: user-Mobbin" in catalog
    assert "serverName: Mobbin" in catalog
    assert "open-design-system" in catalog


def test_focus_documents_upstream_design_reference_order() -> None:
    routing = _read(ROUTING_RULES)
    adr_section = routing.split("## Design-reference upstream stack (ADR-043)", 1)[-1]
    focus = _read(FOCUS_SKILL)
    assert "Open Design" in adr_section
    assert "Mobbin" in adr_section
    assert "ui-ux-design" in adr_section
    assert "ADR-028" in adr_section or "dictionary.md" in adr_section
    od_pos = adr_section.find("Open Design")
    mobbin_pos = adr_section.find("Mobbin")
    ui_ux_design_pos = adr_section.find("ui-ux-design")
    assert od_pos != -1 and mobbin_pos != -1 and ui_ux_design_pos != -1
    assert od_pos < ui_ux_design_pos
    assert mobbin_pos < ui_ux_design_pos
    assert "open-design-system" in focus
    assert "Mobbin" in focus


@pytest.mark.parametrize("slice_id", UI_UX_SLICES)
def test_ui_ux_slices_load_upstream_reference_skills_before_executor(slice_id: str) -> None:
    block = _slice_block(_read(SLICE_ROUTING), slice_id)
    assert "upstreamReferenceSkills:" in block
    assert UPSTREAM_SKILL in block
    assert IMPLEMENTATION_SKILL in block
    upstream_idx = block.index("upstreamReferenceSkills:")
    impl_idx = block.index(IMPLEMENTATION_SKILL)
    assert upstream_idx < impl_idx


def test_no_airtable_first_meta_pipeline_in_harness_config() -> None:
    meta_text = _read(META_PREPARE)
    config_text = _read(AGENT_RUNTIME_CONFIG)
    assert "airtable" not in meta_text.lower()
    assert "design_reference_pipeline" not in config_text.lower()
    assert "airtable-first" not in config_text.lower()
    # Deferral prose in parent scope blocks is allowed; no orchestration keys added.
    assert (
        "airtable"
        not in re.sub(
            r"parentScopeBlock:.*?(?=\n  [a-zA-Z]|\Z)",
            "",
            config_text,
            flags=re.DOTALL,
        ).lower()
    )


def test_dvr_b1_slice_includes_open_design_skill_module() -> None:
    block = _slice_block(_read(SLICE_ROUTING), "DVR-B1")
    assert UPSTREAM_SKILL in block
