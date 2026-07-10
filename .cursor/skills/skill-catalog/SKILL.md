---
name: skill-catalog
description: >-
  Index of Cursor marketplace plugins, MCP servers, and plugin skills available in
  this workspace. Use when routing external integrations (Supabase, Next.js/Vercel,
  Sentry, Figma, shadcn, library docs, browser/Playwright, Celery, Upstash) or when
  focus/agent phases need to name the right plugin skill to load.
catalog:
  updated: "2026-06-09"
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
    standalone:
      - api-docs
      - platform-docs
      - focus
      - review
      - ship
      - validate
      - qa
      - to-prd
      - to-issues
      - ui-ux-design
    domain:
      - ui-ux
      - backend
      - data-platform
      - machine-learning
      - python-patterns
      - python-testing
      - postgres-patterns
      - swift-patterns
  routing:
    readRules:
      - .cursor/rules/mcp-usage.mdc
      - .cursor/rules/core-orchestration.mdc
    tier1AlwaysOn:
      - .cursor/rules/core-safety.mdc
      - .cursor/rules/core-orchestration.mdc
      - .cursor/rules/mcp-usage.mdc
      - .cursor/rules/git-baseline.mdc
    lazyLoad:
      pluginSkills: true
      mcpToolSchemas: true
      tier2Rules: focus
    loadPluginSkillBeforeMcp:
      figma:
        - figma-use
      figmaDiagram:
        - figma-generate-diagram
---

# Skill catalog

Machine-readable index for **focus** and agent-phase routing. Plugin skills ship with Cursor marketplace plugins (user cache); this file records what is enabled for **Juli-AI-Next** and how to invoke them.

## How agents should use this

1. **Focus runs first** — [`.cursor/skills/standalone/focus/SKILL.md`](../standalone/focus/SKILL.md) selects capabilities; this catalog is the index, not a load-everything list.
2. **Task involves an external product** → find matching `catalog.mcpServers[].when`, then **read and follow** listed plugin `skills` before calling MCP tools.
3. **MCP server name** for `CallMcpTool` must match `serverName` from `~/.cursor/projects/<project>/mcps/<folder>/SERVER_METADATA.json`.
4. **Do not load every plugin skill** — Cursor may list all marketplace skills in UI; ignore unselected ones. Pick the smallest set (e.g. `sentry-python-sdk` only for FastAPI work).
5. **MCP tool schemas** — read from `mcps/<folder>/tools/` only after Focus lists that server in the Context Plan.
6. **Project skills** under `.cursor/skills/` are in `catalog.projectSkills`; load per Focus agent phase, not at startup.

## Lazy-load contract

| Surface | Default at startup | Load when |
|---------|-------------------|-----------|
| Tier 1 rules | Always (4 files) | — |
| Tier 2 rules | No | Focus `RULE_TRIGGERS` |
| Repo agent skills | No | Focus agent phase |
| Domain pattern files | No | Language/stack detected |
| Plugin skills | No | skill-catalog `when` + Focus |
| MCP tool JSON | No | Focus selects server |

## Quick routing (Juli stack)

| Task signal | MCP server | Plugin skill(s) |
|-------------|------------|-----------------|
| Alembic, RLS, Supabase auth | `supabase` | `supabase`, `supabase-postgres-best-practices` |
| FastAPI / pytest change | — | `backend` executor, `.cursor/skills/domain/python-*` |
| `web/` Next.js, App Router | `plugin-vercel-vercel` (if deploy) | `nextjs`, `react-best-practices` |
| Add/refine UI component, page, form | `shadcn` (user-shadcn) if registry | `ui-ux` executor, `ui-ux-design`, `nextjs`, `react-best-practices`; `shadcn` when adding registry primitives |
| LLM / AI SDK in app | — | `ai-sdk`, `ai-gateway`; review `ai-integration` checklist |
| TikTok API / webhooks | — | `docs/integrations/tiktok_api/`, MODULE.md (no plugin) |
| New vendor API onboarding | `context7` | `api-docs` → `context7-mcp` |
| Seller/creator feature guide, policy, account health | — | `platform-docs` (WebFetch TikTok Shop University + `context7-mcp`) |
| Library “how do I …” | `context7` | `context7-mcp` |
| Production error / Sentry | `plugin-sentry-sentry` | `sentry-workflow` → platform SDK skill |
| Figma read/write | `figma` | `figma-use` (required before MCP) |
| E2E / browser verify | `playwright` or `cursor-ide-browser` | — (MCP + `.cursor/rules/mcp-usage.mdc`) |

## Maintaining this catalog

When the team adds or removes a Cursor marketplace plugin:

1. Update `catalog.mcpServers` in this file (frontmatter).
2. Align `.cursor/rules/mcp-usage.mdc` principles if routing behavior changes.
3. Add a row to `focus/routing-rules.md` if new detection patterns are needed.

Plugin skills are **not** copied into this repo; they remain in the plugin install path. This catalog only documents names and routing so agents can invoke `/skill-name` when relevant.
