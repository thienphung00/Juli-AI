# ADR 023: Four-destination information architecture and Analytics ownership

## Status
Accepted

**Supersedes:** [ADR-014](014-decision-copilot-app-structure-and-journey.md)
for application tabs, Home composition, RRAA navigation, and placement of
workflow configuration.

**Retains from ADR-014:** the Decision object, explicit approval gate, and
five-step decision-detail flow.

## Context

ADR-014 placed shop health, reports, metric charts, recommendation previews,
and a standalone Juli chat destination in a three-tab workspace. That structure
conflicts with the current product model: Home is a sparse launchpad, reporting
needs one clear owner, workflow configuration belongs in Settings, and Juli is
contextual assistance rather than a destination.

The visual layer also marks one representative KPI as `(main)` in each of its
six categories. A canonical term is needed for that set.

## Decision

1. Juli has exactly four primary destinations:
   **Home, Decisions, Analytics, and Settings**.
2. Home contains exactly two prominent destination cards—Decisions and
   Analytics—and no KPI, chart, health summary, recommendation action, or
   workflow configuration.
3. Analytics exclusively owns all metrics, KPIs, charts, comparisons,
   forecasts, provenance, and reporting.
4. Decisions owns recommendation review and approved work. It has exactly two
   sub-tabs: Recommendations and In Progress.
5. Settings owns workflow templates and thresholds.
6. Juli assistance appears in the active destination and is never a standalone
   navigation item.
7. **Main KPI** is the canonical name for the representative KPI marked
   `(main)` in each visual-layer category: SPS, Net Revenue, ROAS, Inventory
   Turnover, Fulfillment Accuracy Rate, and CSAT.
8. Analytics presents one selected Main KPI as a detailed hero and the other
   five as selector cards. Availability remains honest; missing sources never
   produce fabricated values.

## Rationale

Clear destination ownership reduces duplication and gives sellers a stable
mental model: orient on Home, decide in Decisions, inspect evidence in
Analytics, and configure future behavior in Settings. The Main KPI set provides
a compact entry into the broader visual-layer catalog without redefining the
underlying KPI contracts.

## Consequences

- Existing Home KPI and report language must move to Analytics.
- Existing three-tab and standalone-chat references are historical.
- Deep links use `/analytics/[metricKey]`; Analytics may link to a related
  Decision but cannot expose approval or execution.
- Product documentation and demonstrations must preserve unavailable states,
  source provenance, keyboard access, and platform parity.
