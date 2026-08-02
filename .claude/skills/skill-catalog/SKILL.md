---
name: skill-catalog
description: >-
  Index of Cursor marketplace plugins, MCP servers, and plugin skills available in this
  workspace. Use when routing external integrations (Supabase, Next.js/Vercel, Sentry,
  Figma, shadcn, library docs, browser/Playwright, Celery, Upstash) or when focus/agent
  phases need to name the right plugin skill to load.
---

# skill-catalog

**Phase:** Architect / Meta — external tooling router

**Authoritative body:** [`.cursor/skills/skill-catalog/SKILL.md`](../../../.cursor/skills/skill-catalog/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

## Contract

The Cursor body is the authoritative index of marketplace plugins, MCP servers, and plugin
skills. **Claude Code deviates from it in one way: tooling is CLI-first.**

MCP tool schemas are always-on context cost for every agent on every request; a CLI costs
nothing until invoked, is reproducible from a workflow cache, and is gateable by a single
Bash hook. So in Claude Code, reach for MCP only where no CLI exists — and only during the
Architect/Meta phases.

| Need | Claude Code uses | Instead of |
|------|------------------|------------|
| GitHub issues, PRs, checks, merge queue | `gh` | (never an MCP) |
| Supabase schema, RLS, local DB | `npx --yes supabase@latest` | `supabase` MCP |
| Library / framework / SDK docs | `npx ctx7@latest` | `context7` MCP |
| shadcn registry / components | `npx shadcn@latest` | `shadcn` MCP |
| E2E browser flows | `npx playwright` | `playwright` MCP |
| Deploy, env vars | `vercel` | `plugin-vercel-vercel` MCP |
| Celery / Redis inspection | `celery` CLI, `redis-cli` | `celery`, `upstash` MCP |
| Layout / component extraction | **MCP** `open-design` | — no CLI exists |
| Screen / flow inspiration | **MCP** `Mobbin` | — no CLI exists |
| Figma read/write | **MCP** `figma` (load `figma-use` first) | — no CLI exists |

Executor subagents are configured with **no MCP tools at all**. If an Executor thinks it
needs a design reference, the Meta routing was wrong: stop and report rather than reaching
for a tool.

Cursor keeps using the MCP servers listed in the body — that is expected, and neither
harness should be changed to match the other here.
