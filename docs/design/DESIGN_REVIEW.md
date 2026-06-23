# Juli AI — Design Review Baseline

> Checklist for OpenDesign polish passes and pre-ship design QA. Derived from
> [ADR-007](../decisions/015-design-system-token-foundation.md),
> [ADR-007](../decisions/014-decision-copilot-app-structure-and-journey.md), `web/MODULE.md`, and the
> `ui-ux-design` skill verification contract.

## How to use this doc

1. Load [PRODUCT.md](./PRODUCT.md), [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md), and
   [UX_PRINCIPLES.md](./UX_PRINCIPLES.md) as context.
2. Walk each section below for the surfaces being polished.
3. Mark pass/fail per item; failures need a file reference and screenshot note.
4. Re-baseline `screenshots/` after visual changes land.

---

## 1. Product & IA integrity

| # | Check | Pass criteria |
|---|-------|---------------|
| 1.1 | Three tabs only | Bottom nav shows exactly Trang chủ, Quyết định, Juli — no fourth tab |
| 1.2 | Home is read-only | No approve, dismiss, or execute CTAs on `/` |
| 1.3 | Decisions is action hub | Full ranked list + approval on `/decisions` Recommended tab |
| 1.4 | Six workflows only | Cards map to ADR-007 catalog — no invented workflow types |
| 1.5 | Profile gating | NEW_SHOP vs MID_LARGE_SHOP workflows do not cross-contaminate |
| 1.6 | Decision object | Cards show title, impact, confidence, reasoning — not raw pipeline jargon |

---

## 2. Design tokens & theme

| # | Check | Pass criteria |
|---|-------|---------------|
| 2.1 | CSS variables | No hardcoded theme hex in components — `var(--*)` only |
| 2.2 | Seller white canvas | `--background`, `--header-background`, `--muted` = `#FFFFFF` on seller |
| 2.3 | Pink accent discipline | `#F86BA5` accent-only — not full-page wash |
| 2.4 | Semantic colors | Growth `#16A34A`, Loss `#E5484D`, Warning `#F59E0B`, Info `#2563EB` |
| 2.5 | Color + text | Status never conveyed by color alone — badge/icon/label paired |
| 2.6 | Dual theme | Seller light + affiliate dark both render without broken contrast |
| 2.7 | Inter only | No serif/monospace introduced |
| 2.8 | Radius | Cards/buttons use 16px (`--radius` / `rounded-2xl`) consistently |

---

## 3. Typography & copy

| # | Check | Pass criteria |
|---|-------|---------------|
| 3.1 | Vietnamese | All user-visible strings have proper diacritics |
| 3.2 | No English placeholders | Shipping UI has no lorem or English stubs |
| 3.3 | Home minimal copy | Metric tiles: chart + label + delta — not paragraph-heavy |
| 3.4 | Error messages | Problem + recovery path (LoginForm pattern) |
| 3.5 | Empty states | Why empty + what to do (CollectingDataEmpty pattern) |
| 3.6 | Money formatting | `formatVND` everywhere — no hand-formatted ₫ |
| 3.7 | Dates | ICT formatting via shared utilities |

---

## 4. Interactive states

Every button, tab, tile, and card action must implement:

| State | Verify |
|-------|--------|
| Default | Base styles at rest |
| Hover | Visible on desktop pointer devices |
| Active / pressed | `scale(0.98)` or darker fill on press |
| Focus-visible | 3px ring + offset — keyboard tab through flow |
| Disabled | Muted + `not-allowed` cursor |
| Loading | Spinner + disabled control, label preserved |
| Error | Inline message linked with `aria-describedby` |

---

## 5. Home dashboard

| # | Check | Pass criteria |
|---|-------|---------------|
| 5.1 | Layout stack | Shop info → Báo cáo hôm nay → Shop Health |
| 5.2 | No forbidden elements | No task preview, Tiến độ, persona copilot, RRAA labels |
| 5.3 | Domain tabs | Horizontal scroll tabs with `role="tablist"` |
| 5.4 | Charts | Recharts render; series use token colors |
| 5.5 | Juli suggestion | Tap tile → expand **Gợi ý từ Juli** with `--info` blue icon |
| 5.6 | Decisions link | Second action → `/decisions?highlight=` |
| 5.7 | Estimated bar | `RealEstimatedBar` glow on estimated segment; respects reduced motion |
| 5.8 | Shop Health bars | 5-segment pink ramp, threshold ticks readable |
| 5.9 | Desktop grid | `seller-home-grid` at ≥1024px — sidebar + main |
| 5.10 | Mobile stack | 375px usable without horizontal page scroll (tab scroll OK) |

---

## 6. Decisions & detail flow

| # | Check | Pass criteria |
|---|-------|---------------|
| 6.1 | Sub-tabs | Recommended / In Progress / Workflow Templates |
| 6.2 | ClarityCard hierarchy | Impact prominent; confidence visible; reasoning expandable |
| 6.3 | Highlight inbound | `?highlight=` scrolls + rings correct card (~2s) |
| 6.4 | Home return link | Anticipation shows **Xem trên Trang chủ →** when anchor exists |
| 6.5 | Detail steps | 5 steps with clear `DecisionDetailStepIndicator` |
| 6.6 | Approve path | Last step routes to executor modal or no-op per workflow |
| 6.7 | Dismiss path | `TaskDismissModal` with reason capture |
| 6.8 | Templates demoted | Workflow Templates sub-tab — not default landing |

---

## 7. RRAA journey loop

| # | Check | Pass criteria |
|---|-------|---------------|
| 7.1 | Home → Decisions | Metric CTA lands on correct highlighted card |
| 7.2 | Decisions → Home | Return link opens correct domain tab + metric pulse |
| 7.3 | No stage labels | Reward/Reason/Action/Anticipation never shown as UI text |
| 7.4 | Reduced motion | Pulse/glow disabled when `prefers-reduced-motion` |

---

## 8. Juli AI Chat

| # | Check | Pass criteria |
|---|-------|---------------|
| 8.1 | Sticky input | `ChatInput` fixed above bottom nav, not obscured |
| 8.2 | Suggested prompts | Visible chips; mode-aware |
| 8.3 | No purple AI slop | Blue info reserved for suggestions on Home — chat uses brand tokens |
| 8.4 | Contextual | Prompts reference decisions/metrics where applicable |

---

## 9. Accessibility

| # | Check | Pass criteria |
|---|-------|---------------|
| 9.1 | Text contrast | WCAG AA 4.5:1 on body text |
| 9.2 | Touch targets | ≥ 44×44px on nav, CTAs, metric tiles |
| 9.3 | Keyboard | All interactive charts/tiles reachable; `aria-expanded` on accordions |
| 9.4 | Modals | Focus trap, `aria-modal`, labelled title |
| 9.5 | Icons alone | `aria-label` on icon-only buttons |
| 9.6 | Live regions | Async feedback uses `aria-live` where needed |
| 9.7 | Semantic HTML | Headings, `main`, `role="banner"` on header |

---

## 10. Motion & performance

| # | Check | Pass criteria |
|---|-------|---------------|
| 10.1 | Reduced motion | `@media (prefers-reduced-motion: reduce)` disables non-essential animation |
| 10.2 | Skeleton loading | Home/Decisions show skeletons — not layout jump |
| 10.3 | Page load | Target <2s on representative mobile profile |
| 10.4 | Card entry | Staggered fade+scale acceptable; off when reduced motion |
| 10.5 | No bounce badges | Risk-badge bounce not shipped (deferred) |

---

## 11. Security & data display

| # | Check | Pass criteria |
|---|-------|---------------|
| 11.1 | No PII in tooltips/copy leaks | Financial fields formatted for display only |
| 11.2 | Evidence masking | `EvidenceDrawer` masks sensitive drill-down where designed |
| 11.3 | Auth boundary | Login through API — no browser Supabase secrets |

---

## 12. Regression test anchors

Run or verify these tests after polish:

```bash
cd web && npm test -- --testPathPattern="issue193|issue194|issue221|issue229|issue231|issue233|home_read_only|todays_report|rraa|responsive"
```

| Area | Key test files |
|------|----------------|
| Home read-only | `test_issue193_home_read_only.test.tsx` |
| Báo cáo | `test_issue194_todays_report.test.tsx` |
| RRAA loop | `test_issue221_rraa_loop.test.tsx` |
| Juli suggestion | `test_issue229_juli_suggestion_accordion.test.tsx` |
| Desktop grid | `test_issue231_seller_home_grid.test.tsx` |
| Detail Home link | `test_issue233_decision_detail_home_link.test.tsx` |
| Responsive | `test_responsive_breakpoints.test.tsx` |

---

## 13. Anti-pattern audit

Flag and remove if found:

- [ ] Task-first Home layout
- [ ] RRAA stage labels in UI
- [ ] Generic purple/blue AI gradients unrelated to `--info`
- [ ] Hardcoded chart hex colors
- [ ] English UI strings
- [ ] Color-only status indicators
- [ ] Approval CTAs on Home
- [ ] Pink `#FEF5F6` as seller page background
- [ ] Silent click-only chart interactions (no keyboard path)
- [ ] Fourth navigation tab

---

## 14. OpenDesign deliverables

When polish is complete, produce:

| Deliverable | Description |
|-------------|-------------|
| Updated Figma / design file | Aligned to token doc — seller light + affiliate dark |
| Screenshot baseline | `screenshots/` updated for Home, Decisions, Detail, Chat, Login |
| Changelog | List of token, spacing, or IA deltas vs this baseline |
| Known gaps | ADR-007 preview-on-Home, visual_layer 6-domain target vs 3-domain shipped |

---

## Review sign-off template

```markdown
## Design review — [date] — [scope]

**Reviewer:**
**Surfaces:** Home / Decisions / Detail / Chat / Shell

### Summary
- [ ] Pass — ready for implementation merge
- [ ] Pass with notes — non-blocking issues logged
- [ ] Fail — blocking issues listed below

### Blocking issues
1.

### Non-blocking notes
1.

### Screenshots
- [ ] Seller light — Home
- [ ] Seller light — Decisions
- [ ] Seller light — Decision detail
- [ ] Affiliate dark — out-of-scope shell
```

---

## Canonical references

| Doc | Role |
|-----|------|
| [PRODUCT.md](./PRODUCT.md) | What we're building |
| [DESIGN_SYSTEM.md](./DESIGN_SYSTEM.md) | Tokens and primitives |
| [UX_PRINCIPLES.md](./UX_PRINCIPLES.md) | Interaction rules |
| [SCREENS.md](./SCREENS.md) | Route inventory |
| [COMPONENTS.md](./COMPONENTS.md) | Component map |
| [`docs/visual_layer.md`](../visual_layer.md) | Phase 2+ KPI visual target |
| [`web/MODULE.md`](../../web/MODULE.md) | Code authority |
