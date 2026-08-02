---
name: open-design-system
description: >-
  Upstream design-reference skill for gathering layout and component patterns via Open
  Design MCP before Next.js implementation. Use for design-reference tasks — extracting
  runnable artifacts, browsing OD projects, or commissioning layout runs — not for
  shipping product UI in apps/demo or apps/dashboard (use ui-ux-design + ui-ux).
---

# open-design-system

**Phase:** Planning / Meta — design reference

**Authoritative body:** [`.cursor/skills/standalone/open-design-system/SKILL.md`](../../../.cursor/skills/standalone/open-design-system/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

## Contract

Upstream of `ui-ux-design` per ADR-043. Uses the `open-design` MCP, reference-only. **Executor agents have no MCP tools** — design references are gathered before the Executor starts.
