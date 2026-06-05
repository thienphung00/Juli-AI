---
name: skill-catalog
description: >-
  Index of Cursor marketplace plugins, MCP servers, and plugin skills available in
  this workspace. Use when routing external integrations (Supabase, Next.js/Vercel,
  Sentry, Figma, shadcn, library docs, browser/Playwright, Celery, Upstash) or when
  focus/build-feature/fix-bug needs to name the right plugin skill to load.
catalog:
  updated: "2026-06-03"
  projectStack:
    - python-fastapi
    - nextjs-web
    - swiftui-ios
    - supabase-postgres
    - tiktok-shop-api
  mcpServers:
    - id: supabase
      folder: plugin-supabase-supabase
      serverName: supabase
      when:
        - database schema migrations alembic
        - rls policies auth jwt
        - supabase client edge functions
      skills:
        - name: supabase
          invoke: /supabase
        - name: supabase-postgres-best-practices
          invoke: /supabase-postgres-best-practices
    - id: context7
      folder: plugin-context7-plugin-context7
      serverName: context7
      when:
        - library framework api reference
        - migration guide version-specific docs
      skills:
        - name: context7-mcp
          invoke: /context7-mcp
    - id: sentry
      folder: plugin-sentry-sentry
      serverName: plugin-sentry-sentry
      when:
        - production errors exceptions monitoring
        - sentry sdk setup alerts otel
      skills:
        - name: sentry-sdk-setup
          invoke: /sentry-sdk-setup
        - name: sentry-python-sdk
          invoke: /sentry-python-sdk
          paths: ["src/**/*.py", "tests/**/*.py"]
        - name: sentry-nextjs-sdk
          invoke: /sentry-nextjs-sdk
          paths: ["web/**/*.ts", "web/**/*.tsx"]
        - name: sentry-workflow
          invoke: /sentry-workflow
        - name: sentry-feature-setup
          invoke: /sentry-feature-setup
    - id: figma
      folder: plugin-figma-figma
      serverName: figma
      when:
        - design to code code to design figma
        - design system variables components
      skills:
        - name: figma-use
          invoke: /figma-use
          note: Mandatory before every use_figma MCP call
        - name: figma-generate-design
          invoke: /figma-generate-design
        - name: figma-generate-diagram
          invoke: /figma-generate-diagram
        - name: figma-code-connect
          invoke: /figma-code-connect
    - id: vercel
      folder: plugin-vercel-vercel
      serverName: plugin-vercel-vercel
      when:
        - nextjs app router deployment vercel
        - ai sdk ai gateway chat sdk
      skills:
        - name: nextjs
          invoke: /nextjs
          paths: ["web/**"]
        - name: ai-sdk
          invoke: /ai-sdk
        - name: ai-gateway
          invoke: /ai-gateway
        - name: shadcn
          invoke: /shadcn
          note: Vercel plugin copy; prefer user-shadcn when both apply
        - name: react-best-practices
          invoke: /react-best-practices
          paths: ["web/**/*.tsx"]
        - name: deployments-cicd
          invoke: /deployments-cicd
        - name: verification
          invoke: /verification
        - name: env-vars
          invoke: /env-vars
    - id: shadcn-plugin
      folder: plugin-shadcn-shadcn
      serverName: shadcn
      when:
        - shadcn ui components registry components.json
      skills:
        - name: shadcn
          invoke: /shadcn
    - id: shadcn-user
      folder: user-shadcn
      serverName: shadcn
      when:
        - shadcn ui components registry components.json
      skills:
        - name: shadcn
          invoke: /shadcn
          note: Prefer over plugin-shadcn when working in web/
    - id: browser
      folder: cursor-ide-browser
      serverName: cursor-ide-browser
      when:
        - quick visual check in ide browser snapshot
      skills: []
    - id: playwright
      folder: user-playwright
      serverName: playwright
      when:
        - e2e browser automation test flows
      skills: []
    - id: celery
      folder: user-celery
      serverName: celery
      when:
        - celery worker flower task queue inspection
      skills: []
    - id: upstash
      folder: user-upstash
      serverName: upstash
      when:
        - redis upstash cache kv
      skills: []
  projectSkills:
    workflow:
      - build-feature
      - fix-bug
    standalone:
      - api-docs
      - platform-docs
      - discover
      - focus
      - tdd
      - review
      - ship
      - validate
      - qa
      - to-prd
      - to-issues
    domain:
      - python-patterns
      - python-testing
      - postgres-patterns
      - swift-patterns
  routing:
    readRules:
      - .cursor/rules/mcp-usage.mdc
    loadPluginSkillBeforeMcp:
      figma:
        - figma-use
      figmaDiagram:
        - figma-generate-diagram
---

# Skill catalog

Machine-readable index for **focus** and workflow skills. Plugin skills ship with Cursor marketplace plugins (user cache); this file records what is enabled for **Juli-AI-Next** and how to invoke them.

## How agents should use this

1. **Task involves an external product** (Supabase, Next.js deploy, Sentry, Figma, shadcn, library docs) → find the matching `catalog.mcpServers[].when` row, then **read and follow** the listed plugin `skills` before calling MCP tools.
2. **MCP server name** for `CallMcpTool` must match `serverName` from `~/.cursor/projects/<project>/mcps/<folder>/SERVER_METADATA.json`, not the folder id alone.
3. **Do not load every plugin skill** — pick the smallest set for the task (e.g. `sentry-python-sdk` only for FastAPI work).
4. **Project skills** under `.cursor/skills/` are listed in `catalog.projectSkills`; use those for delivery workflow, not marketplace plugins.

## Quick routing (Juli stack)

| Task signal | MCP server | Plugin skill(s) |
|-------------|------------|-----------------|
| Alembic, RLS, Supabase auth | `supabase` | `supabase`, `supabase-postgres-best-practices` |
| FastAPI / pytest change | — | `.cursor/skills/domain/python-*` |
| `web/` Next.js, App Router | `plugin-vercel-vercel` (if deploy) | `nextjs`, `react-best-practices` |
| Add UI component | `shadcn` (user-shadcn) | `shadcn` |
| LLM / AI SDK in app | — | `ai-sdk`, `ai-gateway`; review `ai-integration` checklist |
| TikTok API / webhooks | — | `docs/tiktok_api/`, MODULE.md (no plugin) |
| New vendor API onboarding | `context7` | `api-docs` → `context7-mcp` |
| Seller/creator feature guide, policy, account health | — | `platform-docs` (WebFetch TikTok Shop University + `context7-mcp`) |
| Library “how do I …” | `context7` | `context7-mcp` |
| Production error / Sentry | `plugin-sentry-sentry` | `sentry-workflow` → platform SDK skill |
| Figma read/write | `figma` | `figma-use` (required before MCP) |
| E2E / browser verify | `playwright` or `cursor-ide-browser` | — (MCP + `.cursor/rules/mcp-usage.mdc`) |

## Maintaining this catalog

When the team adds or removes a Cursor marketplace plugin:

1. Update `catalog.mcpServers` in this file (frontmatter).
2. Align `.cursor/rules/mcp-usage.mdc` server table.
3. Add a row to `focus/routing-rules.md` if new detection patterns are needed.

Plugin skills are **not** copied into this repo; they remain in the plugin install path. This catalog only documents names and routing so agents can invoke `/skill-name` when relevant.
