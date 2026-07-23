# UI/UX reference

Curated patterns for the 80% path. For library API details and churn-prone behavior,
use the **Context7 CLI** at Executor time when Focus/Meta selects it (see **Sources /
live Context7 pointers**). Load on demand — not always injected in full.

---

## 1. App Router layout and client boundaries

- **File routes:** `apps/dashboard/src/app/` and `apps/demo/src/app/` — `layout.tsx`,
  `page.tsx`, nested segments (`decisions/`, `analytics/`, etc.).
- **Server by default:** layouts and static shells stay Server Components; add
  `'use client'` only for hooks, browser APIs, or local interaction state.
- **Composition:** Server layouts may import Client Components (search bars, toggles);
  keep data fetching in Server Components or route handlers when possible.
- **Loading UX:** wrap async layout segments in `<Suspense fallback={…}>`; pair with
  route-level `loading.tsx` where the issue specifies skeleton behavior.

---

## 2. Shared packages and imports

| Package | Role |
|---------|------|
| `packages/ui` | Shared shadcn-style primitives (`button`, `card`, `dialog`, …) |
| `packages/theme` | Design tokens consumed by apps |
| `packages/contracts` | Cross-app TypeScript contracts |
| `packages/utils` | Shared non-UI helpers |

Apps use `@/` → `src/` (dashboard Jest config). Promote cross-app components to
`packages/ui`; keep app-specific shells and routing in the app tree.

---

## 3. Design and copy context

| Resource | When |
|----------|------|
| [`dictionary.md`](../../../dictionary.md) | Product terminology, Vietnamese labels |
| [`docs/product/design/design.md`](../../../docs/product/design/design.md) | Visual system |
| [`docs/product/design/ux_principles.md`](../../../docs/product/design/ux_principles.md) | Interaction principles |
| [`docs/product/design/colors_and_type.css`](../../../docs/product/design/colors_and_type.css) | Token reference |
| `apps/*/src/app/globals.css` | App-level CSS variables |

Verify diacritics in user-visible copy; cover empty, loading, and error states per AC.

---

## 4. Component and route testing

**Dashboard (Jest + RTL)**

- Config: `apps/dashboard/jest.config.js` — `jsdom`, `@/` mapper, `setup.ts`
- Tests: `apps/dashboard/src/__tests__/**/*.test.{ts,tsx}`
- Prefer `screen.getByRole` over test IDs; use `user-event` for interactions

**Demo (Vitest + RTL)**

- Config: `apps/demo/vitest.config.ts`, `vitest.setup.ts`
- Colocated tests under `src/lib/**/__tests__/` and `src/__tests__/`

**a11y**

- Query by accessible name/role first (RTL guiding principle)
- Add `jest-axe` / axe-core integration when issue AC includes accessibility audit

**E2E**

- Playwright only when issue explicitly scopes full-browser flows (not default unit path)

**iOS**

- [`swift-patterns.md`](../testing-patterns/swift-patterns.md) — MVVM, `@Observable`, navigation
- Tests: `ios/Tests/`; `ios/MODULE.md` for Keychain/JWT invariants

---

## 5. Juli path cheat-sheet

| Surface | Path |
|---------|------|
| Live seller dashboard | `apps/dashboard/` |
| Workflow / landing demo | `apps/demo/` |
| Shared UI primitives | `packages/ui/src/` |
| iOS app | `ios/Sources/`, `ios/Tests/` |
| Legacy (removed) | `web/` → use `apps/dashboard/` |

Deployable map: [`apps/README.md`](../../../apps/README.md).

---

## 6. Context7 curated extracts

### Next.js — Server + Client composition (`/vercel/next.js`)

Server layouts may render Client Components for interactive islands:

```tsx
// layout.tsx — Server Component
import Search from './search' // Client Component

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <nav><Search /></nav>
      <main>{children}</main>
    </>
  )
}
```

### Next.js — Suspense loading (`/vercel/next.js`)

```tsx
import { Suspense } from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <Suspense fallback={<NavSkeleton />}><DashboardNav /></Suspense>
      <main>{children}</main>
    </>
  )
}
```

### React Testing Library — role queries (`/testing-library/react-testing-library`)

```jsx
import { render, screen } from '@testing-library/react'

render(<UserProfile user={{ name: 'Jane', email: 'jane@example.com' }} />)

const heading = screen.getByRole('heading', { name: 'Jane' })
const button = screen.getByRole('button', { name: /edit profile/i })
```

---

## 7. Sources / live Context7 pointers

This workspace uses the **Context7 CLI** (`npx ctx7@latest`), not Context7 MCP.
Resolve library IDs at Executor time; one concept per query (≤3 per family).

```bash
npx ctx7@latest library next.js "App Router server client components"
npx ctx7@latest docs /vercel/next.js "Suspense loading error states"
```

| Topic | Suggested CLI queries |
|-------|----------------------|
| App Router layouts | `library next.js` → `docs /vercel/next.js` — layouts, `use client`, Suspense |
| RTL queries / a11y | `docs /testing-library/react-testing-library` — `getByRole`, `user-event` |
| axe accessibility | `library axe-core` → `docs /dequelabs/axe-core` — rule integration |
| shadcn components | `library shadcn` → `docs <id>` — registry install patterns |

**Example library IDs** (resolve with `library` before use): `/vercel/next.js`,
`/websites/nextjs`, `/testing-library/react-testing-library`, `/dequelabs/axe-core`.

See [`.cursor/rules/context7-cli.mdc`](../../../rules/context7-cli.mdc).

**Repo authority:** `apps/<app>/MODULE.md`, `ios/MODULE.md`, [`apps/README.md`](../../../apps/README.md).
