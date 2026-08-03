# Claude Code Harness

**Status:** Published  
**Authority:** [`EXECUTION.md`](../../EXECUTION.md) > [`agent-runtime.md`](agent-runtime.md) > this file > skills and rules

> **Routing:** Open this file when the task touches the Claude Code surfaces — subagents,
> slash commands, skill pointers, the PreToolUse gate, or CLI/MCP selection. For the
> agent-phase model itself see [`agent-runtime.md`](agent-runtime.md).

---

## Purpose

This repository is driven by **both Cursor and Claude Code.** The rule and skill *bodies* live under `.cursor/` and are the single source of truth. Files under `.claude/` are thin Claude-native pointers — they carry Claude frontmatter and phase contracts, then defer to the `.cursor/` body. **Never fork a rule or skill body into `.claude/`.** Edit the `.cursor/` file; both tools pick the change up.

---

## Surface map

| Concern | Cursor | Claude Code | Source of truth |
|---------|--------|-------------|-----------------|
| Always-on rules | `.cursor/rules/*.mdc` with `alwaysApply: true` (4 Tier-1: core-safety, core-orchestration, mcp-usage, git-baseline) | [`CLAUDE.md`](../../CLAUDE.md) | `.cursor/` |
| Focus-selected rules | `.cursor/rules/*.mdc` with `alwaysApply: false` (12 Tier-2) | loaded on demand by the `focus` skill, same files | `.cursor/` |
| Skills | `.cursor/skills/{standalone,domain}/<name>/SKILL.md` (30 skills) | `.claude/skills/<name>/SKILL.md` pointers, flat namespace | `.cursor/` |
| Agent roles | prose in `.cursor/rules/core-orchestration.mdc` and [`agent-runtime.md`](agent-runtime.md) | `.claude/agents/*.md` subagents with enforced `model:` and `tools:` | shared |
| Phase entry points | Cursor chat + skill invocation | `.claude/commands/juli-*.md` slash commands | Claude-only |
| Executor cache gate | instruction in core-orchestration.mdc + CI | `.claude/hooks/executor_cache_gate.py` PreToolUse hook | shared contract in [`agent-runtime.config.yml`](../config/agent-runtime.config.yml) |
| Runtime scripts, artifacts, validators, CI | `agent-runtime/` | same, unchanged | `agent-runtime/` |

---

## Model routing

| Phase | Agent file | Model | Why |
|-------|-----------|-------|-----|
| Planning | `.claude/agents/architect.md` | Opus | design decisions compress into artifacts every downstream agent executes |
| Implementation routing + harness optimization | `.claude/agents/meta.md` | Sonnet | orchestration against decisions already made |
| Implementation | `.claude/agents/executor-{backend,ui-ux,data-platform,machine-learning,integrations}.md` | Haiku | design is mapped out and passed down; execute the cache, do not redesign |
| Review + testing | `.claude/agents/review.md` | Haiku | checklist execution against existing artifacts |

Claude Code enforces this through the `model:` frontmatter field, so routing does not depend on prompt discipline.

The two harnesses set subagent models independently and **do not need to agree**: Cursor
launches Task subagents with `composer-2.5-fast` per `core-orchestration.mdc`, capped at
three concurrent. Do not "align" one side to the other — they are different runtimes with
different subagent economics.

---

## Skill pointers

Each `.claude/skills/<name>/SKILL.md` carries Claude frontmatter (name + description copied from Cursor) plus a Phase line, a link to the authoritative `.cursor/` body, a list of bundled sibling resources, and an optional Contract section.

Regenerate them with:

```bash
python agent-runtime/scripts/sync_claude_skill_pointers.py
```

The script is re-runnable and idempotent. Re-run it whenever a Cursor skill's name or description changes or a skill is added. Per-skill Phase/Contract text is maintained in the `PHASE` dict inside the script.

**Flat namespace:** Claude skill names come from the Cursor `name:` field, so domain skills appear as `backend-executor`, `ui-ux-executor`, `data-platform-executor`, `machine-learning-executor`, `integrations-executor`.

---

## Tooling: CLI first

MCP tool schemas are always-on context cost for every agent on every request; a CLI costs nothing until invoked, is reproducible from a workflow cache, and can be gated by a single Bash matcher. Therefore MCP is reserved for surfaces with no CLI equivalent and scoped to Architect and Meta phases only.

| Need | Claude Code uses |
|------|------------------|
| GitHub | `gh` |
| Supabase | `npx --yes supabase@latest` |
| Library/framework docs | `npx ctx7@latest` |
| shadcn | `npx shadcn@latest` |
| E2E browser | `npx playwright` |
| Deploy/env vars | `vercel` |
| Layout/component extraction | **MCP** `open-design` (no CLI) |
| Screen/flow inspiration | **MCP** `Mobbin` (no CLI) |
| Figma read/write | **MCP** `figma` (no CLI; load `figma-use` skill first) |

Executor subagents are declared with an explicit `tools:` list containing no MCP tools. This is structural, not advisory, and matches ADR-043 (design references gathered upstream during Planning).

**Caveat:** `.mcp.json`'s `open-design` entry points at a locally installed macOS application path, so it will not resolve on another machine or in CI. The `figma` MCP requires OAuth authorization through claude.ai connector settings.

---

## Executor cache gate

A PreToolUse hook (`.claude/hooks/executor_cache_gate.py`) mirrors `workflow_prompt_cache.requireValidCacheBeforeExecutor` and is registered in `.claude/settings.json` on Edit/Write/MultiEdit/NotebookEdit.

Decision order:

1. Non-write tool → allow
2. Missing `file_path` → allow
3. Branch not matching `issue-<N>` → allow (mirrors `artifact_gates.quickCommitSkip` and CI behavior in `.github/workflows/pr.yml`)
4. Path outside guarded roots (`backend/`, `apps/`, `packages/`, `ios/`, `infra/`, `tests/`, `web/`) → allow
5. Otherwise: requires `agent-runtime/artifacts/workflow-cache/issue-context-cache-<N>.json` with `cacheStatus == "valid"`, blocks with exit code 2 if missing
6. Fails open on unexpected errors so a broken hook cannot block the edit loop
7. Issue-branch regex read from `agent-runtime/config/agent-runtime.config.yml` with fallback to `issue-<N>`

---

## Adding a skill or rule

1. Add the body under `.cursor/` (only with explicit user approval per the skills-governance rule in core-orchestration.mdc)
2. Add Phase/Contract text to the `PHASE` dict in the sync script if the skill needs it
3. Run the sync script
4. Commit the `.cursor/` body and the generated `.claude/` pointer in the same change so the harnesses never drift
