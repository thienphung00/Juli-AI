---
name: open-design-system
description: >-
  Upstream design-reference skill for gathering layout and component patterns via
  Open Design MCP before Next.js implementation. Use for design-reference tasks —
  extracting runnable artifacts, browsing OD projects, or commissioning layout runs —
  not for shipping product UI in apps/demo or apps/dashboard (use ui-ux-design + ui-ux).
catalog:
  pluginIndex: skill-catalog
  mcpServer: open-design
  loadWhen:
    - design reference layout component pattern before implementation
    - open design extract materialize artifact runnable preview
    - problem-section layout inspiration upstream of ui-ux-design
  notWhen:
    - implementing Next.js pages in apps/demo or apps/dashboard (use ui-ux-design)
    - copy authority or Vietnamese strings (dictionary.md + design-context.md per ADR-028)
    - binding IA changes (ADR-023 four destinations)
  upstreamOf:
    - ui-ux-design
    - ui-ux
  companionMcps:
    - Mobbin
---

# Open Design System (upstream reference)

**ADR-043:** Open Design sits **above** `ui-ux-design`; it does **not** replace it.
Gather references first; implement in Juli product apps with `ui-ux` executor +
`ui-ux-design` + ADR-028 copy authorities.

## When to invoke

| Signal | Action |
|--------|--------|
| Design-reference / layout exploration before coding | Load this skill + **Mobbin** MCP (problem-section screen inspiration) |
| Extract or extend OD artifacts (HTML/JSX/CSS) | Open Design MCP: `get_artifact`, `get_file`, `search_files` |
| Commission new layout/component exploration | Open Design MCP: `start_run` (poll 30–60s; do not substitute `write_file`) |
| Implement or polish Demo/Dashboard UI | **Stop** — hand off to `ui-ux-design` → `ui-ux` executor |
| Seller-facing copy | **Never** from OD output — `dictionary.md` + `docs/product/design/design-context.md` |

**Reference-only:** OD layouts and Mobbin screens are inspiration adapted to
[ADR-015](../../../../docs/adr/015-design-system-token-foundation.md) tokens and
`docs/product/design/` — not 1:1 binding specs.

## Upstream stack (load order)

1. **Open Design** (this skill + `open-design` MCP) — components, layouts, runnable artifacts
2. **Mobbin** (`Mobbin` MCP) — screen/flow/section search for problem areas
3. **`ui-ux-design`** — Next.js implementation executor for `apps/demo` / `apps/dashboard`
4. **`ui-ux` domain executor** — Meta assignment for frontend implementation slices
5. **ADR-028 copy** — `dictionary.md`, `design-context.md` loaded for implementation

`shadcn` is **atoms only** — refine registry primitives, fold into `@juli/ui`; not page composition.

## Juli design authority (after references)

When moving from reference to implementation, load repo authorities in order
(see [`docs/product/design/README.md`](../../../../docs/product/design/README.md)):

1. `design-context.md` → `design.md` → `flows.md` → `soul.md` → `ux_principles.md`
2. Repo-root `dictionary.md` (EN→VI terminology)
3. `Screens/` → `Flows/` → `Components/` → `colors_and_type.css`

OD/Mobbin text never overrides these.

## Open Design MCP workflow

**Server:** `open-design` (`user-open-design` folder). Read tool schemas from
`mcps/user-open-design/tools/` after Focus selects this server.

| Goal | Prefer |
|------|--------|
| Full design bundle | `get_artifact()` — entry + referenced siblings in one call |
| Single file | `get_file(path)` — page with offset if truncated |
| Find component/class/copy | `search_files(query)` |
| Generate/refine design | `start_run` → poll `get_run` → `get_artifact` on success |

**Active context:** omit `project` when the user has a design open in OD; confirm via
`usedActiveContext` in the response.

**Generation patience:** OD runs take 5–30 minutes. Poll every 30–60s; do not cancel
and hand-write substitutes unless the user explicitly aborts.

## Mobbin (companion reference)

Load **Mobbin** MCP for problem-section screen inspiration:

- `search_screens`, `search_flows`, `search_sections`
- Adapt patterns to Juli tokens — never pixel-perfect clones
- Mobbin copy is **not** authoritative (ADR-028)

## Out of scope

- Permanent Airtable-first Meta pipeline (ephemeral DVR-A0 only)
- Replacing `ui-ux-design` or wholesale Demo → shadcn migration
- Copy or IA authority from reference tools

## Related

- [ADR-041](../../../../docs/adr/041-frontend-design-skill-wiring.md)
- [ui-ux-design](../ui-ux-design/SKILL.md)
- [ui-ux domain skill](../../domain/ui-ux/SKILL.md)
- [skill-catalog](../../skill-catalog/SKILL.md)
