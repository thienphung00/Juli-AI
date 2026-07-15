# Components / navigation.md

> Historical reference: `source_examples/NavBar.tsx`. Current IA comes from
> the root design authorities and the matching `Screens/` and `Flows/` specs.

## Primary navigation (four destinations)

| Label | Route | Question |
|---|---|---|
| Trang chủ | `/` | What is happening? |
| Quyết định | `/decisions` | What should I do? |
| Phân tích | `/analytics` | How is the shop performing? |
| Cài đặt | `/settings` | How should workflows behave? |

- Fixed to viewport bottom, `pb-24` clearance on the scrollable content above it.
- The active destination uses the restrained brand-pink indicator plus
  font-weight/icon change; no destination receives an elevated ornamental tab.
- **Locked at four destinations.** Juli is contextual assistance inside the active
  destination, never a fifth primary destination.
- Minimum 44×44px touch target per tab, active state via `isNavTabActive`.

## Desktop navigation

- The same four destinations may render as a side rail at desktop widths; labels,
  order, and route ownership do not change.
- Home remains a sparse two-card launcher. A desktop layout must not turn it into
  a KPI dashboard or add shop-health/report modules.

## Header

- Sticky `PageHeader` — shop name/status when available (`ShopInfoHeader`), page
  title otherwise.
- Glass blur backdrop (`--glass-bg`, `--glass-border`) when scrolled content sits
  beneath it.
- Contextual Juli help may appear as a header or in-content affordance tied to the
  current screen. It does not compete with primary navigation.

## ModeSwitcher

- Seller ⇄ Affiliate workspace toggle. Switching persists `juli_workspace_mode` to
  `localStorage` and toggles the `dark` class on `<html>` (affiliate = dark theme).
- Lives in Cài đặt or a settings/header surface, not
  competing with the primary navigation model.

## Rules

- Active tab state is never conveyed by color alone — combine fill/weight change
  with the active indicator.
- Route labels are always Vietnamese; implementation paths use
  `apps/dashboard/...` and route paths stay English.

## Anti-patterns

- A standalone assistant, chat, Orders, or other fifth primary destination.
- KPI cards, reports, or shop-health modules embedded into Home navigation.
- Workflow templates or thresholds placed under Decisions; they belong to Settings.
