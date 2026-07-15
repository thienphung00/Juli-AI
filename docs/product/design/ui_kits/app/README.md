# ui_kits/app/ — Applied interface kit

A runnable, browser-only demonstration of the current Juli seller model:
four destinations, a two-card Home launcher, contextual Juli assistance,
a six-Main-KPI Analytics selector, and one complete
recommendation-to-execution workflow.

## Structure

```
ui_kits/app/
  index.html                       Entry point — loads React/ReactDOM/Babel + colors_and_type.css,
                                    loads every component below, mounts <App />
  components/
    NavBar.jsx                     Four destinations: Home/Decisions/Analytics/Settings
    HomeAiRecommendationCard.jsx   Recommendation actions: Phê duyệt/Từ chối/Mở rộng
    ReportMetricChart.jsx          Main KPI hero, selectors, chart previews, unavailable popover
    InProgressDecisionCard.jsx     Prefilled input → executing → completed workflow card
    App.jsx                        Composes the four destinations and contextual Juli help
```

## How to use

Open `index.html` directly in a browser (no build step — React, ReactDOM,
and Babel Standalone load from unpkg and JSX is transpiled in-browser). Tap
the bottom nav to switch between **Trang chủ**, **Quyết định**,
**Phân tích**, and **Cài đặt**. Home contains exactly two launcher cards.
Decisions contains exactly **Đề xuất** and **Đang thực hiện** sub-tabs.

To try Analytics:

1. Open **Phân tích**. Net Revenue is selected with `30 ngày`.
2. Change the global range; the hero and all available previews update.
3. Select Inventory Turnover or Fulfillment Accuracy Rate. It swaps into the
   hero, the previous KPI takes its card position, and browser history records
   `/analytics/[metricKey]` (as a hash when opened from `file://`).
4. Toggle `So sánh kỳ trước`; comparison appears only in the hero.
5. Open the info control on SPS, ROAS, or CSAT to inspect the missing source and
   activation requirement. These cards cannot become the hero.

To run the complete workflow example:

1. Open Quyết định → Đề xuất and use **Mở rộng** to inspect reasoning.
2. Choose **Phê duyệt**; the example opens Đang thực hiện with prefilled input.
3. Start execution, then complete the simulated final step to see the outcome.

**Từ chối** removes the recommendation. Juli help stays contextual within each
destination and never becomes primary navigation.

To reuse a component in another project: copy the relevant `.jsx` file, keep
`colors_and_type.css` linked, and replace the demo data at the top of `App.jsx`
(`MAIN_KPIS`, `MOCK_RECOMMENDATION`) with real data.

## Design notes

- Every color/spacing/radius value comes from `colors_and_type.css` — no
  new hex values were introduced while adapting the components.
- KPI and chart evidence is owned by Analytics; Home is not a dashboard.
- Analytics always shows one hero and five selector cards. Available selection
  is a literal swap; the global range updates all available charts.
- SPS, ROAS, and CSAT deliberately use neutral unavailable states rather than
  fabricated values.
- Selector previews are low contrast and `aria-hidden`; card text is the data
  equivalent. Unavailable explanations support keyboard focus and Escape.
- Settings owns workflow templates and thresholds.
- `InProgressDecisionCard.jsx` demonstrates prefilled input, execution progress,
  and a completed outcome without claiming autonomous action.
- Next.js-specific pieces (`next/link`, `next/navigation`, module aliases,
  data hooks like `resolveMetricWorkflowId`) were replaced with plain props
  and local `React.useState` so the kit runs with zero build tooling. The
  original, unmodified source (with those imports intact) lives in
  `../../source_examples/` as non-authoritative historical evidence.

## Source basis

Visual primitives were adapted from `apps/dashboard/src/components/**` in
`/Users/macos/Juli-AI-v2`. The current composition follows the design authority
hierarchy; `../../context/local-code/Juli-AI-v2.md` and
`../../source_examples/README.md` are provenance only and cannot override it.
