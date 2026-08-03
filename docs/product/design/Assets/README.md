# Assets

Brand elements (logo, icon) are supplied by the designer and imported by the
developer — no markdown docs belong in this folder, only image files.

## Status

`logo.png` (Juli wordmark) and `icon.png` (Juli bird icon) are **not yet
available**. A search of the linked codebase (`/Users/macos/Juli-AI-v2`) found no
logo/icon asset files — only unrelated favicons in third-party package output
(`node_modules`, coverage reports). Per this design system's own governance rule
("never invent tokens outside these files"), no placeholder logo has been
generated here.

## When the real files arrive

Drop them in as:

- `logo.png` — Juli wordmark
- `icon.png` — Juli bird icon

Then update:
- `../design.md` if the real mark introduces any color not already in the
  palette (it shouldn't — the wordmark uses `--brand-gradient`, per
  `.brand-wordmark` in the codebase).
- `Screens/*.md` and `Components/navigation.md` wherever a header/wordmark
  placement is described, to reference the real file paths.

## UI iconography (not a brand-asset gap)

This section is about the brand mark only. Generic UI icons are **not**
bitmap assets pending a designer — `packages/ui/src/destination-icons.tsx`
already maps named roles to `lucide-react` components (e.g.
`DestinationIconName: "decisions" | "analytics"` → `ClipboardCheck` /
`BarChart3`). New icon roles from [ADR-053](../../adr/053-demo-home-activity-summary.md)
and the suggestion pattern ([PRD #600](https://github.com/thienphung00/Juli-AI/issues/600))
should extend that same map with existing `lucide-react` glyphs, not a new
asset pipeline. Suggested (confirm final pick at implementation time):

- **Done** (Home activity tile) — `CheckCircle2`, pairs with
  `Components/badges.md` Success.
- **Running** (Home activity tile) — reuses the existing `.badge-live` pulsing
  dot; only needs a static glyph (e.g. `Loader2` non-spinning) as the
  `prefers-reduced-motion` fallback.
- **Needs attention** (Home activity tile) — `AlertCircle` or `Bell`, never a
  generic red hazard-triangle icon (`soul.md` anti-clichés).
- **Gợi ý bởi Juli** (suggestion label, `Components/forms.md`) — `Sparkles` or
  `Wand2`, distinct from the bird wordmark.
