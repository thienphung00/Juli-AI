# Flows — Journeys and Platform Parity

> This root authority indexes `Flows/` and defines the interaction contracts
> that all individual flow specifications must follow.

## Platform parity

Web, mobile-web, and native use identical tokens, information architecture,
terminology, and approval behavior. Layout may simplify for a smaller viewport
or use native input affordances, but product behavior must not diverge.

| Layer | Parity rule |
|---|---|
| Tokens (`design.md`) | Identical semantic values |
| Terminology (`context.md`) | Identical Vietnamese product terms |
| Destinations | Home, Decisions, Analytics, Settings on every platform |
| Juli | Contextual assistance, never a standalone destination |
| Approval gate | Human approval required; no shortcut may skip reasoning or inputs |

All implementation references use `apps/dashboard/...`.

## Destination ownership

| Destination | Owns | Does not own |
|---|---|---|
| Home | Two-card launcher for Decisions and Analytics | Metrics, KPIs, recommendation actions, settings |
| Decisions | Recommendations and In Progress | Workflow templates and thresholds |
| Analytics | Metrics, KPIs, comparisons, forecasts, reports | Approval or workflow execution |
| Settings | Workflow templates and thresholds | Recommendation ranking or active execution |

Contextual Juli assistance may appear in each destination to explain the
current content. It cannot authorize, reject, or execute a workflow.

## Flow index

### `home/`

| File | Journey |
|---|---|
| `onboarding.md` | Shop connection, permissions, first useful state |
| `login.md` | Authentication, OTP, password recovery, session recovery |

After entry, Home presents exactly two prominent clickable cards:
**Decisions** and **Analytics**.

### `decisions/`

Decisions has exactly two sub-tabs:

- **Recommendations / Đề xuất**
- **In Progress / Đang thực hiện**

The nine workflow specifications describe recommendation eligibility and
execution. Workflow Templates is not a Decisions sub-tab; templates and
thresholds belong to Settings.

### `analytics/`

| File | Journey |
|---|---|
| `dashboard.md` | KPI drill-down, date range, time series, forecast, and period comparison |

Analytics owns all reporting formerly shown on Home.

### Settings

Settings owns workflow-template and threshold configuration. Lower-tier
screen and flow specifications must add or reference a Settings flow rather
than placing configuration in Decisions.

## Recommendation human gate

Every recommendation card exposes three seller choices:

1. **Approve / Phê duyệt** — starts the workflow with known values prefilled
   and missing or editable values fillable before execution.
2. **Reject / Từ chối** — removes the recommendation from the active list; it
   does not execute or silently defer it.
3. **Expand / Mở rộng** — reveals reasoning, evidence, expected impact,
   confidence, inputs, and relevant risks without authorizing action.

No default action fires without explicit approval.

## Recommendation-to-execution lifecycle

1. **Detect** — an eligible signal produces a draft recommendation.
2. **Rank** — open recommendations are ordered by expected value and urgency.
3. **Explain** — the card shows impact and confidence; Expand reveals details.
4. **Decide** — the seller Approves or Rejects.
5. **Prepare** — Approve opens a prefilled/fillable workflow before any action.
6. **Execute and track** — approved work appears in In Progress and follows
   the workflow's action, wait, outcome, recovery, and rollback states.

The current In Progress statuses are explicitly preserved:

- `needs_input`
- `executing`
- `completed`

Their redesign is deferred; lower-tier documentation must not rename or add
statuses as part of this authority change.

## Cross-destination behavior

- Home → Decisions opens the Recommendations sub-tab.
- Home → Analytics opens the reporting destination.
- Analytics may deep-link to a related recommendation in Decisions.
- Decisions may link to supporting evidence in Analytics.
- Settings changes future recommendation behavior; it does not bypass the
  human gate for an existing recommendation.
- Juli assistance receives the active destination and item as context but
  remains assistive.

## Governance

Individual files under `Flows/` specialize these contracts; they cannot
change destination ownership, tab count, approval behavior, or status names.
Unsupported execution behavior must be marked unresolved rather than invented.
