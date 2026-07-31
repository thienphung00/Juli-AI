# Issue #600: Demo UI fix: CDP-honest Analytics cards and Decision automation UX
State: OPEN
Labels: PRD

# PRD: Demo UI fix — CDP-honest Analytics cards and Decision automation UX

> **Track B** — separate from Phase 3.5-A/B CDP spine ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)).
>
> **Canonical docs:** [`CONTEXT.md`](CONTEXT.md) · [ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md) · [ADR-046](docs/adr/046-cdp-medallion-physical-model.md) · [ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md) · [ADR-037](docs/adr/037-phase-2.10-demo-real-data-no-auth.md) · [ADR-038](docs/adr/038-phase-2.10-dual-layer-pipeline.md) · [ADR-023](docs/adr/023-four-destination-analytics-ownership.md) · [ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md).
>
> **Planning handoff:** [`docs/handoffs/demo-ui-fix-grill-summary.md`](docs/handoffs/demo-ui-fix-grill-summary.md) (2026-07-30 grill; no re-interview).
>
> **Related tracks (do not merge scope):**
> - [#598](https://github.com/thienphung00/Juli-AI/issues/598) — Phase 3.5-A: Continuous CDP Analytics spine + medallion physical model
> - [#599](https://github.com/thienphung00/Juli-AI/issues/599) — Phase 3.5-B: Continuous CDP Decisions on shared compute
> - [#580](https://github.com/thienphung00/Juli-AI/issues/580) — Demo visual & Decisions copy refinement (prior pass; this PRD supersedes KPI catalog + automation UX gaps)

## Assumptions

- Grill handoff (2026-07-30) and browser QA on `demo.app-juli.com` (2026-07-30) are authoritative; no re-interview.
- IA remains ADR-023 four destinations (Home, Decisions, Analytics, Settings); no greenfield rebuild.
- Mock mode + Fujiwa **`production_read`** only; Sign-in/OAuth stays disabled ([ADR-048](docs/adr/048-cdp-webhook-first-spine-dual-credential.md)).
- **`apps/dashboard`** authenticated Main KPI catalog stays ADR-023 until a future ADR; this PRD affects **`apps/demo` only**.
- Default hero KPI is **GMV (TikTok)**; default Analytics URL may remain GMV-keyed.
- **Demo Main KPI catalog locked at exactly five KPIs** ([ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md)): GMV, AOV, CTOR, LIVE hours, cancellation rate — **no sixth card**; **Bestselling (A-38/A-39) removed** (marketplace/platform metric ≠ merchant shop KPI).
- Serving gold envelope contract uses flexible **`payload.kpis`** map ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md) Q3) — UI consumes `metric_id` keys, not per-KPI Postgres columns.
- Negative/downtrend card emphasis is product intent; exact sort/weight algorithm is implementation detail.
- Decisions list load was OK in latest browser QA (no stuck **Đang tải…** reproduced); deep-link and In Progress paths still require verification before ship.

## Problem Statement

The public Interactive Demo (`demo.app-juli.com`) still behaves like Phase 2.6 mock IA in critical seller-facing places, even though Phase 2.10 wired CDP envelopes for the reference shop. Prospective sellers evaluating Juli see the wrong Analytics KPI catalog (ADR-023 placeholders like SPS, ROAS, and CSAT instead of CDP-backed metrics), GMV load failures, trust copy that exposes backend/fixture language, and a Decision automation flow that mis-sets expectations — silent prefills, visible confidence, you-vs-Juli execution checklists, webhook jargon, and broken In Progress / deep-link journeys.

Contextual Juli assistance (left bar) shows format errors on Decisions and Analytics and wrong Home copy on non-Home routes. Navigation labels overlap in EN/VN locales. Execution detail URLs 404. These defects undermine the Demo's purpose: proving webhook-first CDP intelligence and a safe dry-run Decision loop without OAuth or real Partner writes.

## Solution

**Track B — Demo UI fix:** Align `apps/demo` UX and seller-surface contracts with CDP reality and locked Decision automation patterns. Ship in parallel with Track A (CDP spine [#598](https://github.com/thienphung00/Juli-AI/issues/598)) under a clear data contract:

1. **Analytics — Demo Main KPI set (ADR-049 Option B′):** Replace ADR-023 selector with **exactly five** envelope-backed cards (GMV, AOV, CTOR, LIVE hours, cancellation rate). Apply **Analytics trust copy** on every card. Drop non-envelope ADR-023 metrics **and Bestselling (A-38/A-39)** from the Demo selector entirely.
2. **Decisions — automation UX:** Suggestion glow + **Gợi ý bởi Juli** (no silent prefill); editable inputs; **no confidence UI**; **Juli-handles-all confirm** with policy badge, cancel/rollback, and 5–10 min expectation; **In Progress** as ChatGPT-style progress cards with mode strip (confirm vs running).
3. **Must-fix shell & routing:** Assistance bar, nav label overlap, In Progress tab, Analytics deep link from five-stage review, execution URL 404s, GMV load (may depend on 3.5-A envelope keys — interim contract-shaped fixtures allowed).
4. **Browser-verified ship gate:** Real-browser QA on `demo.app-juli.com` before merge.

Track B consumes **serving gold** envelopes from Track A when available ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md) — `gold.kpi_envelopes.payload.kpis`); may ship interim **contract-shaped fixtures/mocks** matching ADR-049/ADR-046 shape until 3.5-A lands, then swap data source without a second IA redesign. **Do not block** on 3.5-B Decisions continuous scoring ([#599](https://github.com/thienphung00/Juli-AI/issues/599)). **Assistance/nav/Decision UX locks unchanged.**

## User Stories

### Analytics — Demo Main KPI set (ADR-049)

1. As a visitor, I want Demo Analytics to show **exactly five Main KPIs** (GMV, AOV, CTOR, LIVE hours, cancellation rate), so that I see what Juli can actually measure today.
2. As a visitor, I want SPS, ROAS, CSAT, inventory turnover, fulfillment accuracy, **and Bestselling (A-38/A-39)** **absent from the Demo selector**, so that I am not misled by empty ADR-023 placeholders or marketplace metrics.
3. As a visitor, I want GMV (TikTok) as the default hero KPI, so that the primary commerce metric loads first when I open Analytics.
4. As a visitor, I want GMV to load reliably (no P0 failure state), so that the Demo's headline evidence surface works.
5. As a visitor, I want AOV derived from GMV and orders when envelope fields exist, so that I understand average order value honestly.
6. As a visitor, I want CTOR shown as **CTOR (click→đơn)** in seller language, so that I understand click-to-order performance without API jargon.
7. As a visitor, I want LIVE hours from live session duration (not GMV LIVE, not avg watch duration), so that LIVE investment is represented accurately within Partner limits.
8. As a visitor, I want Cancellation rate when A-7 and webhook #11 data exist, so that I see post-sale risk honestly.
9. As a visitor, I want honest unavailable states when envelope fields are missing, so that Juli never fabricates dropped ADR-023 metrics.
10. As a visitor, I want the hero + four selector card layout preserved, so that ADR-023 compact selector IA stays familiar.
11. As a visitor, I want each Analytics card to show an insight chain (what changed → risk/opportunity → action), so that I know why the metric matters and what to do.
12. As a visitor, I want negative/downtrend cards emphasized in ordering or visual weight where rules allow, so that risks surface first.
13. As a visitor, I want seller-language provenance on every card (no API names, no "fixture" labels), so that I trust the copy.
14. As a visitor, I want relative sync freshness and a live indicator from envelope `computed_at`, so that I know how current the data is.
15. As a visitor, I want one consistent demo-data timestamp shared with Home, so that freshness is coherent across destinations.
16. As a visitor, I want Analytics deep links from the five-stage Decision review (Analytics step) to open the correct KPI, so that the review journey stays connected.

### Decisions — Recommendations & five-stage review

17. As a visitor, I want prefilled recommendation inputs to show a glow and **Gợi ý bởi Juli**, so that I know Juli suggested values without silent auto-fill.
18. As a visitor, I want to edit all inputs before approve, so that I stay in control of what Juli executes.
19. As a visitor, I want **no confidence scores or Độ tin cậy labels** on seller cards or approve surfaces, so that the Demo does not imply false precision.
20. As a visitor, I want the approve confirm screen to say **Juli handles all work** after I approve, so that I am not given a you-vs-Juli task checklist.
21. As a visitor, I want the **TikTok Shop policy checked** badge on confirm, so that I see policy compliance without executor jargon.
22. As a visitor, I want cancel/rollback always visible on confirm and execution surfaces, so that I feel safe trying dry-run actions.
23. As a visitor, I want expected duration shown as **5–10 phút**, so that I have realistic timing expectations.
24. As a visitor, I want the five-stage review flow (Why → Analytics → Inputs → Preview → Approve) in seller language, so that the journey reads coherently.
25. As a visitor, I want no webhook, endpoint, feature_id, tool name, or FBS/FBT badges in seller UI, so that backend internals stay hidden.
26. As a visitor, I want Decisions Recommendations list to load without hanging on **Đang tải…**, so that I can browse suggestions reliably.
27. As a visitor, I want highlight deep links on `/decisions` to scroll/focus the target card, so that shared links work in sales demos.

### Decisions — In Progress & execution

28. As a visitor, I want the In Progress sub-tab to work (not broken/empty when executions exist), so that I can follow running dry-runs.
29. As a visitor, I want In Progress shown as ChatGPT-style progress cards (not a status table), so that execution feels narrative and human.
30. As a visitor, I want a **mode strip** separating confirm vs running states, so that I know whether I am approving or watching progress.
31. As a visitor, I want execution detail pages to resolve (no 404 URLs), so that I can open a specific in-progress run.
32. As a visitor, I want Demo execution to remain dry-run only (local records, no Partner writes), so that the public Demo cannot mutate the reference shop.

### Shell, assistance & navigation

33. As a visitor, I want contextual Juli assistance (left bar) to render without format errors on Decisions and Analytics, so that help copy is trustworthy.
34. As a visitor, I want assistance bar copy to match the current destination (not Home copy on Decisions/Analytics), so that guidance is contextually relevant.
35. As a visitor, I want EN and VN navigation labels to not overlap, so that locale switching remains readable on desktop and mobile.
36. As a visitor, I want the four-destination shell (Home, Decisions, Analytics, Settings) unchanged, so that IA stability is preserved.
37. As a visitor, I want Mock/Sign-in mode toggle with Sign-in **disabled** (stub only), so that I am not prompted for OAuth this release.

### Home & cross-destination coherence

38. As a visitor, I want Home launchpad cards to reflect the same demo-data timestamp as Analytics, so that cross-destination freshness is consistent.
39. As a visitor, I want Home to remain a sparse two-card launchpad, so that ADR-023 IA is preserved.

### Settings & polish (P2/P3)

40. As a visitor, I want Settings tabs and disabled workflow placeholders to render with consistent spacing, so that the fourth destination does not feel broken.
41. As a visitor, I want mobile spacing and touch targets improved on touched surfaces, so that the Demo works on phone-width viewports.
42. As a visitor, I want insight/freshness polish on cards that already load data, so that secondary trust signals feel production-grade.

### Product / GTM / implementer

43. As product/GTM, I want the Demo to prove CDP-honest Analytics and Decision dry-run on real masked patterns, so that sales and Phase 2.10 exit evidence hold.
44. As an implementer, I want locked Demo Main KPI keys and copy rules aligned with `gold.kpi_envelopes.payload.kpis` → public Demo read API contracts ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)), so that Track B and Track A ([#598](https://github.com/thienphung00/Juli-AI/issues/598)) integrate without IA churn.
45. As an implementer, I want contract-shaped fixtures matching ADR-049/ADR-046 envelope shape when live envelopes are not yet ready, so that UI can ship before 3.5-A completes and swap sources later.
46. As QA, I want browser verification on live Demo before ship, so that P0/P1 defects from 2026-07-30 QA are closed.

## Implementation Decisions

### Deep modules (responsibility, not file paths)

| Module | Responsibility | Public interface (words) |
|--------|----------------|---------------------------|
| **Demo Analytics KPI catalog** | Demo-scoped Main KPI config separate from ADR-023 dashboard catalog | **Five** KPI keys; hero default GMV; honest unavailable per field |
| **Analytics envelope consumer** | Map public Demo read API envelopes (`payload.kpis`) to card view models | KPI value, trend, insight chain, freshness from `computed_at` |
| **Analytics trust copy renderer** | Seller-language insight chain + provenance + sync indicator | No API/fixture jargon; shared timestamp with Home |
| **Decision suggestion affordance** | Glow + **Gợi ý bởi Juli** on prefilled inputs | Visible suggestion; editable fields; no confidence |
| **Five-stage review presenter** | Why → Analytics → Inputs → Preview → Approve in seller language | Analytics deep link to correct KPI key |
| **Juli-handles-all confirm** | Post-approve messaging, policy badge, cancel/rollback, duration | No you-vs-Juli checklist; no webhook jargon |
| **In Progress progress cards** | ChatGPT-style cards + mode strip | Confirm vs running separation; not status table |
| **Demo dry-run execution router** | Resolve execution detail URLs; local records only | No Partner writes; no 404 on valid execution ids |
| **Contextual assistance panel** | Destination-aware Juli copy in left bar | Format-safe rendering on Decisions + Analytics |
| **Demo shell / nav i18n** | Four-destination chrome, EN/VN labels without overlap | Assistance bar context routing |
| **Interim fixture layer** (optional) | Contract-shaped mocks matching ADR-049/ADR-046 envelope shape | Swappable for live API when 3.5-A keys land |

### Parallelism with CDP Phase 3.5-A/B

**Yes, with a contract.** Demo UI Fix runs as **Parallel Isolate/Parallel** issue workflow — Demo UI worktree vs 3.5-A worktree ([`docs/handoffs/worktree-branch-topology.md`](docs/handoffs/worktree-branch-topology.md)).

| Coupling | Guidance |
|----------|----------|
| **Safe to parallel** | Decisions automation UX, shell/nav/assistance fixes, In Progress progress cards, Settings polish — fixture/dry-run backed |
| **Coupled to 3.5-A ([#598](https://github.com/thienphung00/Juli-AI/issues/598))** | Analytics live GMV + B′ five-KPI catalog need **3.5-A `payload.kpis` keys** OR Demo ships interim **contract-shaped fixtures/mocks** matching ADR-049/ADR-046 until 3.5-A lands, then swaps data source (no second IA redesign) |
| **Do not block on 3.5-B ([#599](https://github.com/thienphung00/Juli-AI/issues/599))** | Decision feed freshness from continuous scoring is Track A; UI ships UX contracts ahead of that wire |
| **Related issues** | [#598](https://github.com/thienphung00/Juli-AI/issues/598) (3.5-A), [#599](https://github.com/thienphung00/Juli-AI/issues/599) (3.5-B) — separate track, reference only |

### Technical clarifications

- **GMV P0 load failure:** Treat as ship blocker; root cause may be missing/stale envelope from Track A — Demo may use interim fixtures while 3.5-A completes; call out dependency in child issues.
- **Serving gold contract ([ADR-046](docs/adr/046-cdp-medallion-physical-model.md)):** Consume flexible `payload.kpis` map — KPI catalog changes are key additions/removals, not UI column coupling. Compat view during medallion cutover must preserve same payload shape.
- **Bestselling removed:** Not in Demo Main KPI set ([ADR-049](docs/adr/049-demo-analytics-main-kpi-override.md)); Track A may still stop wasted A-38/A-39 calls as ops hygiene — no UI card.
- **Authenticated dashboard:** No changes to ADR-023 catalog in this PRD.
- **Copy authority:** `dictionary.md` + design context ([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).
- **Design sync:** `docs/product/design/Screens/analytics.md` updates post-PRD to reflect Demo Main KPI set (five cards).

## Testing Decisions

- **Behavior over implementation:** Assert seller-visible outcomes (KPI set, copy guards, navigation, deep links, In Progress cards) — not internal fixture keys unless guarding contracts.
- **Modules under test (default):** Demo Analytics KPI catalog + envelope consumer; trust copy renderer; Decision suggestion + confirm surfaces; In Progress progress cards + mode strip; assistance panel destination routing; shell nav i18n overlap; execution URL resolution; five-stage Analytics deep link.
- **Prior art:** Existing `apps/demo` Vitest suites (analytics-dashboard, recommendation-review, in-progress, demo-shell, decisions-recommendations, workflow review/approve tests); Playwright exit-gate specs for decisions journey and accessibility.
- **Browser QA gate:** Manual or automated verification on `demo.app-juli.com` for P0 GMV load, P1 assistance/nav/In Progress/deep-link/execution paths before ship.
- **Copy guards:** Extend seller-surface tests to reject confidence labels, webhook jargon, fixture/API names, and silent prefill without **Gợi ý bởi Juli**.
- **Interim fixtures:** If used, tests assert ADR-049/ADR-046 `payload.kpis` shape so live swap does not require test rewrites beyond data source.

## Out of Scope

- TikTok OAuth, Sign-up, Sign-in implementation or enabling the Demo mode toggle.
- Real Partner write APIs from public Demo (dry-run / local execution records only).
- Landing (`app-juli.com`) deploy.
- Reintroducing SPS, ROAS, CSAT, inventory turnover, fulfillment accuracy, or **Bestselling (A-38/A-39)** in Demo selector without envelope backing + explicit ADR/catalog change.
- `avg_watch_duration` as LIVE hours proxy (Partner gap).
- Inventing confidence UI or **Độ tin cậy** on any seller surface.
- Full In Progress sub-tab redesign beyond progress-card + mode-strip contract (Five-stage review flow remains).
- **`apps/dashboard`** ADR-023 Main KPI catalog changes.
- Track A CDP spine implementation (webhook enqueue, medallion cutover, A-7, A-38/A-39 ops quota guard) — tracked in [#598](https://github.com/thienphung00/Juli-AI/issues/598).
- Continuous Decision scoring wire — tracked in [#599](https://github.com/thienphung00/Juli-AI/issues/599).

## Further Notes

### Browser QA baseline (2026-07-30, `demo.app-juli.com`)

| Priority | Finding | PRD coverage |
|----------|---------|--------------|
| **P0** | GMV load failure | User stories 4, 46; coupled to 3.5-A or interim fixtures |
| **P1** | Wrong KPI catalog (still ADR-023) | ADR-049 **five-card** set |
| **P1** | Assistance bar wrong Home copy | User stories 33–34 |
| **P1** | EN/VN nav label overlap | User story 35 |
| **P1** | In Progress tab broken | User stories 28–30 |
| **P1** | Analytics deep link from review broken | User stories 16, 24 |
| **P1** | Silent prefills without **Gợi ý bởi Juli** | User stories 17–18 |
| **P1** | Execution you-vs-Juli checklist + webhook jargon | User stories 20, 25 |
| **P1** | Execution URL 404s | User stories 31–32 |
| **P2/P3** | Insights/freshness, mobile spacing, settings tabs | User stories 40–42 |
| **Not reproduced** | Decisions list stuck **Đang tải…** | Still verify deep links (story 27) before ship |

### Rollout & risks

- **Data dependency risk:** Shipping Analytics before 3.5-A requires explicit interim fixture strategy and a follow-up swap issue — document in `to-issues` children.
- **Parallel merge conflicts:** Demo UI worktree should avoid shared-core envelope schema edits owned by 3.5-A; consume read API contracts only.
- **Regression vs #580:** This PRD supersedes KPI catalog and automation UX gaps left open after Demo visual refinement; coordinate so copy guard tests do not conflict.

### Follow-ups (post-PRD)

- Run **`to-issues`** to decompose into Parallel Track B child issues.
- Sync `docs/product/design/Screens/analytics.md` to Demo Main KPI set (five cards).
- Update Demo tests that still assert ADR-023 keys or six-card/Bestselling catalog on `apps/demo`.

### Acceptance themes (ship checklist)

1. Analytics selector shows **exactly five** Demo Main KPIs; dropped ADR-023 metrics **and Bestselling** absent.
2. Trust copy passes seller-language guardrails; insight chain + `computed_at` freshness; shared Home timestamp.
3. Recommendations → approve: suggestion glow, no confidence, editable inputs, Juli-handles-all confirm, policy badge, cancel/rollback, 5–10 min.
4. In Progress: progress cards + mode strip.
5. `/decisions` loads reliably; deep-link highlight works; browser-verified.
6. Contextual assistance renders without format errors on Decisions and Analytics.
7. Dry-run only; Sign-in disabled.



## Comment 1

**Superseding catalog / medallion locks (2026-07-30):** Issue body updated to match [ADR-049](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/049-demo-analytics-main-kpi-override.md) (**five** Demo Main KPIs; Bestselling user stories/assumptions removed) and [ADR-046](https://github.com/thienphung00/Juli-AI/blob/main/docs/adr/046-cdp-medallion-physical-model.md) (flexible `payload.kpis` serving envelope). Parallel contract with [#598](https://github.com/thienphung00/Juli-AI/issues/598) unchanged; assistance/nav/Decision UX locks unchanged.


## Comment 2

## PRD split update (ADR-047)

Analytics CDP **3.5-A** split into **A0 ([#598](https://github.com/thienphung00/Juli-AI/issues/598))**, **A1 Speed ([#601](https://github.com/thienphung00/Juli-AI/issues/601))**, **A2 Batch ([#602](https://github.com/thienphung00/Juli-AI/issues/602))** per [ADR-047](docs/adr/047-cdp-lambda-layers-prd-split.md).

### Track B unchanged — parallel OK

**This issue (#600) remains parallel** with Backend CDP work:

- **Contract-shaped fixtures/mocks** may ship until **A1** populates live `gold.kpi_envelopes.payload.kpis` (five Demo KPI keys per ADR-049/046).
- **Do not block** on A2 Batch (#602) or 3.5-B Decisions (#599).
- A0 (#598) establishes serving gold **shape**; A1 (#601) delivers live envelope data for B′ five KPIs.

```
A0 (#598) → A1 (#601) → live envelope swap for Analytics cards
#600 Track B  ∥  fixtures until A1 contract
```
