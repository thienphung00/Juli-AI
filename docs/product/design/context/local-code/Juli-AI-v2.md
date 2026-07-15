# Local code evidence — /Users/macos/Juli-AI-v2

> **Non-authoritative historical evidence.** This note records what the local
> implementation looked like during intake. It does not define current IA,
> screen ownership, recommendation actions, or workflow behavior. Resolve any
> conflict in favor of the root design authorities, then `Screens/`, `Flows/`,
> and `Components/`.

> Manual evidence note. The bounded `local-design-context` connector command
> (`tools connectors local-design-context`) could not be invoked from this
> workspace shell — the Open Design daemon CLI requires the packaged Electron
> helper process, which fails to launch headless here (`Unable to find helper
> app` / GPU process crash). This note was produced by directly reading the
> linked folder instead of inventing tokens from the folder name, per the
> local-folder-intake runbook's fallback instruction ("stop and explain the
> local file access problem instead of inventing tokens from the folder
name").

## What was inspected

Repo root: `/Users/macos/Juli-AI-v2` (private monorepo, `juli-ai-monorepo`).

- `package.json` — root is a thin workspace shell (Playwright screenshot
  scripts only); the real product code lives in `apps/dashboard`.
- `apps/dashboard/src/app/globals.css` — canonical design tokens (`:root`,
  `html:not(.dark)`, `html.dark`), `@layer base/components/utilities`,
  keyframes. Read in full.
- `apps/dashboard/tailwind.config.ts` — font family, color scale extensions
  (`primary.50`–`900`), radius (`2xl`/`3xl`), animation keyframes. Read in
  full.
- `apps/dashboard/src/components/ui/button.tsx` — shared `Button` primitive
  (`cva` variants: default/outline/secondary/ghost/destructive/link; sizes
  xs–lg + icon). Read in full.
- `apps/dashboard/src/components/NavBar.tsx` — historical bottom-tab evidence
  with 44×44px touch targets. Its Juli-tab model is retired.
- `apps/dashboard/src/components/seller-home/SellerHomeShell.tsx` — historical
  Home shell + skeleton loading-state evidence, not the current two-card Home.
- `apps/dashboard/src/components/home/HomeAiRecommendationCard.tsx` — historical
  recommendation markup. Current cards use Phê duyệt/Từ chối/Mở rộng.
- `apps/dashboard/src/components/home/todays-report/ReportMetricChart.tsx` —
  expandable metric card with sparkline, Juli-suggestion accordion
  (`--info` blue, never purple), and a real/estimated progress bar link-out.
- `apps/dashboard/src/components/decisions/InProgressDecisionCard.tsx` —
  Đang thực hiện (in-progress) workflow card, per-status Vietnamese copy and
  CTA (resume input / executing copy / view outcome).
- `apps/dashboard/src/components/home/todays-report/MetricSparkline.tsx`,
  `apps/dashboard/src/components/decisions/DecisionsSubTabs.tsx` — referenced
  for tab and chart conventions, not fully reproduced below.

## What was NOT found (do not invent)

- **No logo/icon/wordmark image files anywhere in the repo** (`find` across
  `web/`, `apps/dashboard/`, and repo root for `.png`/`.svg`/`.ico`/`.jpg`
  outside of `node_modules`, `.next`, and unrelated Python venv packages
  turned up only unrelated `screenshots/*.png` UX captures, not brand marks).
  → `Assets/README.md`'s "pending from designer" note is confirmed still
  accurate. No `build/` runtime-icon evidence exists to preserve.
- **No local font files.** Typography loads Inter from Google Fonts via
  `@import url('https://fonts.googleapis.com/css2?family=Inter...')` in
  `globals.css` — there is nothing to bind with `@font-face`/`url(...)`.
- The retired `web/src/app/globals.css` path **no longer exists** — the product moved
  to `apps/dashboard/src/app/globals.css` at some point after this package
  was first drafted. All current references must use the corrected path.

## Snapshots preserved under `context/local-code/`

Full-file snapshots (verbatim, unmodified) copied alongside this note:

- `globals.css.snapshot` — `apps/dashboard/src/app/globals.css`
- `tailwind.config.ts.snapshot` — `apps/dashboard/tailwind.config.ts`

Representative component source was copied into `source_examples/` at the
package root (see that folder's own note) rather than duplicated here, to
match the Claude Design package convention of keeping original component
files alongside the package instead of nested under `context/`.
