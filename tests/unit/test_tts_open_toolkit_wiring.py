"""TTS Open Toolkit CLI wiring is durable (Partner Center docv2 `hhw7w40d`).

The Toolkit's skills install at *user* scope (`~/.claude/skills/tts-*`), so nothing
about them is visible in this tree. These assertions are the only thing stopping the
repo-side routing from rotting silently once someone edits the catalog: they are
file-based on purpose and never shell out to `tts_open_toolkit`, which CI does not
have installed.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

TOOLKIT_RULE = REPO_ROOT / ".cursor/rules/tts-open-toolkit-cli.mdc"
SKILL_CATALOG = REPO_ROOT / ".cursor/skills/skill-catalog/SKILL.md"
CLAUDE_CATALOG = REPO_ROOT / ".claude/skills/skill-catalog/SKILL.md"
ROUTING_RULES = REPO_ROOT / ".cursor/skills/standalone/focus/routing-rules.md"
TIKTOK_API_README = REPO_ROOT / "docs/integrations/tiktok_api/README.md"
GITIGNORE = REPO_ROOT / ".gitignore"

RULE_PATH = ".cursor/rules/tts-open-toolkit-cli.mdc"

# The bundled skills the CLI installs for `--agent cc`, as of @tts-open-toolkit/cli 0.1.7.
BUNDLED_SKILLS = (
    "tts-openapi-guide",
    "tts-openapi-faq-index",
    "tts-openapi-sandbox-materials",
    "tts-developer-onboarding-guide",
    "tts-open-platform-glossary",
    "tts-open-toolkit",
    "tts-seller-university-basic-knowledge-index",
)


def _read(path: Path) -> str:
    assert path.is_file(), f"expected file at {path}"
    return path.read_text(encoding="utf-8")


def test_toolkit_rule_exists_and_is_focus_selected() -> None:
    """Tier-2, never always-on: the rule must not add startup context."""
    text = _read(TOOLKIT_RULE)
    assert "alwaysApply: false" in text
    assert "tts_open_toolkit" in text
    assert "Focus" in text


def test_toolkit_rule_states_cli_first_boundaries() -> None:
    """The two vendor commands that would violate repo policy stay named and refused."""
    text = _read(TOOLKIT_RULE)
    assert "tts_open_toolkit mcp" in text, "MCP registration must stay explicitly refused"
    assert "tts_open_toolkit setup" in text, "vendor hook installer must stay refused"
    assert "Keychain" in text, "credential storage boundary must stay stated"


def test_toolkit_rule_lists_every_bundled_skill() -> None:
    text = _read(TOOLKIT_RULE)
    for skill in BUNDLED_SKILLS:
        assert skill in text, f"{skill} missing from {RULE_PATH}"


def test_skill_catalog_registers_toolkit_as_cli_not_mcp() -> None:
    catalog = _read(SKILL_CATALOG)
    assert "id: tts-open-toolkit" in catalog
    assert "@tts-open-toolkit/cli" in catalog
    assert RULE_PATH in catalog
    cli_docs, _, mcp_servers = catalog.partition("  mcpServers:")
    assert "id: tts-open-toolkit" in cli_docs, "toolkit must live under catalog.cliDocs"
    assert "tts-open-toolkit" not in mcp_servers, "toolkit must never be an MCP server entry"


def test_claude_pointer_routes_tiktok_work_to_the_cli() -> None:
    """Claude Code's CLI-first deviation table is its only always-cheap discovery path."""
    pointer = _read(CLAUDE_CATALOG)
    assert "tts_open_toolkit" in pointer


def test_focus_routing_rules_name_the_toolkit_and_its_rule() -> None:
    routing = _read(ROUTING_RULES)
    assert RULE_PATH in routing
    assert "tts-openapi-guide" in routing
    assert "tts-openapi-sandbox-materials" in routing


def test_tiktok_api_docs_point_at_the_toolkit_rule() -> None:
    """Repo docs stay the first authority; the toolkit is the next hop, not a bypass."""
    readme = _read(TIKTOK_API_README)
    assert "tts_open_toolkit skill add --agent cc" in readme
    assert "tts-open-toolkit-cli.mdc" in readme
    assert "contract-collection.md" in readme


def test_toolkit_project_state_is_gitignored() -> None:
    """`<project>/.tts_open_toolkit/` holds machine-local config and prompt history."""
    assert ".tts_open_toolkit/" in _read(GITIGNORE)
