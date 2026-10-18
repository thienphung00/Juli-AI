---
name: ui-ux-executor
description: >-
  Executor Agent domain skill for web and iOS UI work. Use when implementing
  GitHub issues that touch apps/demo, apps/landing, ios/, shared packages,
  components, pages, forms, or visual interaction behavior.
---

# UI/UX Executor

Interface work for Juli web apps and iOS. TDD + artifact handoff:
[`agent-runtime/docs/agent-runtime.md`](../../../agent-runtime/docs/agent-runtime.md).

## When to load

| Signal | Also load |
|--------|-----------|
| `apps/demo` / `apps/landing` route or component | `ui-ux-design`, `nextjs`, `react-best-practices` |
| shadcn registry primitive | `shadcn` (registry adds only) |
| Copy / visual language | `dictionary.md`, `docs/product/design/` |
| `ios/` SwiftUI | [`swift-patterns`](../testing-patterns/swift-patterns.md), `ios/MODULE.md` |

## Owns / Does not own

**Owns:** App Router pages/layouts, client/server boundaries, component composition,
loading/empty/error states, a11y, Vietnamese copy with diacritics, SwiftUI views.

**Does not own:** **`backend`** — `/v1/*` routes, scoring, auth; **`integrations`** —
vendor clients/webhooks/backfill; **`data-platform`** — schema, migrations, ETL.

Primary apps: `apps/demo` (demo + ops), `apps/landing` (public site). Legacy `web/` and `apps/dashboard` removed.
Shared: `packages/ui`, `packages/theme`, `packages/contracts`. iOS: `ios/`.

## Required context

- `apps/<app>/MODULE.md` or `ios/MODULE.md`; issue acceptance criteria
- `dictionary.md` + `docs/product/design/` for any visually-facing change (not just copy)
- [`REFERENCE.md`](REFERENCE.md) on demand

## Juli recipes

**Landing** — `apps/landing/src/app/` file routes; Server Components default;
`'use client'` for interactivity.

**Demo** — `apps/demo/src/app/` workflow slices; Vitest + RTL in `src/__tests__/` and
colocated `__tests__/`.

**Packages** — reusable primitives → `packages/ui`; tokens → `packages/theme`; shared
types → `packages/contracts`.

**Design** — `dictionary.md` for terms; `docs/product/design/` for tone/tokens.

**iOS** — `ios/Sources/` + `ios/Tests/`; [`swift-patterns`](../testing-patterns/swift-patterns.md);
Keychain/JWT rules in `ios/MODULE.md`.

## Domain test surfaces

- Landing: Vitest + RTL — `apps/landing/src/**/__tests__/*`
- Demo: Vitest + RTL — `apps/demo/src/**/__tests__/*`
- a11y: `getByRole` first; jest-axe when AC requires it
- E2E: Playwright only when issue scopes browser E2E
- iOS: `ios/Tests/` XCTest

Vertical RED→GREEN; one AC per cycle. Process details in agent-runtime doc above.

## Implementation artifact

```bash
python agent-runtime/scripts/ci/generate_implementation_artifact.py --issue <n> --executor-domain ui-ux
```

`agent-runtime/artifacts/implementations/implementation-issue-<n>.json` before Review Agent.
Schema: [`implementation-artifact.schema.json`](../../../agent-runtime/docs/schemas/implementation-artifact.schema.json).

## Validation & must not

`pnpm check:demo` / `pnpm check:landing` (lint, type-check, test, build). Map AC → named test. For visually-facing changes, capture rendered
screenshots per `ui-ux-design` § Visual check and reference their paths in the
implementation artifact. No vendor clients, backend `/v1` routes, schema/ETL
changes, or ship/validate — hand off to Review Agent.
