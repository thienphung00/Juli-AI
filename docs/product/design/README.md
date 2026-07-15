# Juli Open Design System

Juli is a Vietnamese-language shop-operations app that turns shop data into
ranked, explainable recommendations while preserving seller control. This
package defines the product's design authority, structures, reusable
specifications, and supporting evidence.

## Authority and precedence

Resolve every conflict top-down in this exact order:

1. **Root authorities**
   - `context.md`
   - `design.md`
   - `flows.md`
   - `soul.md`
   - `ux_principles.md`
2. **Product structures**
   - `Screens/`
   - `Flows/`
3. **Reusable specifications**
   - `Components/`
   - `colors_and_type.css`
4. **Demonstrations and evidence**
   - `preview/`
   - `ui_kits/`
   - `source_examples/`
   - `context/`

Lower tiers apply higher-tier decisions; they do not redefine them. Generated
previews, UI kits, snapshots, and historical implementation examples never
override the five root authorities. When two files disagree, update the
lower-precedence file to match the higher-precedence file.

## Locked product model

- Exactly four primary destinations: **Home, Decisions, Analytics, Settings**.
- Juli is contextual assistance within those destinations, not a standalone
  tab or destination.
- Home is a sparse launchpad with exactly two prominent clickable cards:
  **Decisions** and **Analytics**.
- Analytics owns every metric, KPI, chart, comparison, forecast, and report.
- Settings owns workflow templates and thresholds.
- Decisions has exactly two sub-tabs:
  **Recommendations / Đề xuất** and **In Progress / Đang thực hiện**.
- Every recommendation preserves a human gate:
  **Approve / Phê duyệt**, **Reject / Từ chối**, and
  **Expand / Mở rộng**.
- Approve opens a prefilled/fillable workflow; Reject removes the active
  recommendation; Expand reveals reasoning and details.
- The current In Progress statuses—`needs_input`, `executing`, and
  `completed`—remain unchanged until their deferred redesign is decided.

## Package contents

```text
context.md                Vietnamese terminology, copy, and product context
design.md                 Visual tokens, layout, motion, and component schemas
flows.md                  Journey, destination ownership, and parity contracts
soul.md                   Brand personality and product character
ux_principles.md           Interaction and information-design rules
colors_and_type.css        Reusable visual tokens and component classes
Screens/                   Product-level screen specifications
Flows/                     Step-by-step journey and workflow specifications
Components/                Reusable component specifications
Assets/                    Brand asset inventory
preview/                   Focused demonstrations
ui_kits/                   Composed runnable demonstrations
source_examples/           Historical implementation examples
context/                   Intake notes, evidence, and source snapshots
```

The agent-facing usage skill lives at
`.cursor/skills/standalone/open-design-system/SKILL.md`.

## Product destinations

| Destination | Purpose |
|---|---|
| Home | Choose between Decisions and Analytics without dashboard clutter |
| Decisions | Review recommendations and track approved workflows |
| Analytics | Explore all shop metrics and reporting |
| Settings | Manage workflow templates and thresholds |

Juli assistance is grounded in the currently active destination, item, and
workflow state. It can explain or clarify, but it cannot authorize or execute
work for the seller.

## Source and implementation references

The live application is under `apps/dashboard/...`. Token evidence comes from:

- `apps/dashboard/src/app/globals.css`
- `apps/dashboard/tailwind.config.ts`

Supporting evidence is recorded in:

- `context/local-code/Juli-AI-v2.md`
- `context/local-code/globals.css.snapshot`
- `context/local-code/tailwind.config.ts.snapshot`
- `context/source-context.md`

No linked Figma authority exists for this package. Evidence describes what was
observed in source; it does not override canonical product decisions.

## Working with this package

1. Read the five root authorities in precedence order:
   `context.md` → `design.md` → `flows.md` → `soul.md` →
   `ux_principles.md`.
2. Read the relevant product structure in `Screens/`, then `Flows/`.
3. Apply reusable specifications from `Components/` and
   `colors_and_type.css`.
4. Consult `preview/` and `ui_kits/` only as demonstrations.
5. Consult `source_examples/` and `context/` only as historical evidence.
6. Use implementation paths under `apps/dashboard/...`.

## Governance

- Update a root authority before propagating a product decision downward.
- Keep user-visible terminology aligned with `context.md`.
- Keep destination ownership and approval behavior aligned with
  `ux_principles.md` and `flows.md`.
- Add reusable specifications without duplicating flow or screen authority.
- Mark unsupported or unresolved behavior explicitly; never infer a product
  contract from a preview or historical implementation.
- When implementation and the authority differ, treat the difference as work
  to reconcile rather than silently changing the authority to match old code.
