# MVP 1.0 — Phase 1 Issue Queue

**Parent PRD:** Local [`PRD.md`](PRD.md) · GitHub parent issue: [#113](https://github.com/thienphung00/Juli-AI/issues/113)

Process issues top-to-bottom. **#119**, **#120**, and **#121** can run in parallel after **#118**.

> **GitHub sync:** `EXECUTION.md` still references older issue numbers (#102–#111). The
> authoritative Phase 1 issue set created in this repo is **#113–#123** below.

| Order | Issue | Title | Type | Blocked by | EXECUTION slice |
|-------|-------|-------|------|------------|-----------------|
| 0 | [#113](https://github.com/thienphung00/Juli-AI/issues/113) | PRD: MVP 1.0 — Phase 1 UI + Mock Data | AFK | — | (parent) |
| 1 | [#114](https://github.com/thienphung00/Juli-AI/issues/114) | Mock data schemas and seller personas | AFK | — | P1-1 |
| 2 | [#115](https://github.com/thienphung00/Juli-AI/issues/115) | Workspace mode — Seller dark / Affiliate out-of-scope | AFK | — | P1-0 |
| 3 | [#116](https://github.com/thienphung00/Juli-AI/issues/116) | Rules-based seller-stage router | AFK | #114 | P1-6 |
| 4 | [#117](https://github.com/thienphung00/Juli-AI/issues/117) | Shared task card + no-op executor | AFK | #115 | P1-5 |
| 5 | [#118](https://github.com/thienphung00/Juli-AI/issues/118) | Seller home shell — routing + persona switcher | AFK | #114, #115, #116 | — |
| 6 | [#119](https://github.com/thienphung00/Juli-AI/issues/119) | New Seller Copilot UI (mocked) | AFK | #114, #115, #117, #118 | P1-2 |
| 7 | [#120](https://github.com/thienphung00/Juli-AI/issues/120) | Revenue Leakage Detection UI (mocked) | AFK | #114, #115, #117, #118 | P1-3 |
| 8 | [#121](https://github.com/thienphung00/Juli-AI/issues/121) | Growth Copilot UI (mocked) | AFK | #114, #115, #117, #118 | P1-4 |
| 9 | [#122](https://github.com/thienphung00/Juli-AI/issues/122) | UX instrumentation | AFK | #117, #119–#121 | P1-7 |
| 10 | [#123](https://github.com/thienphung00/Juli-AI/issues/123) | Retire legacy creator-matching routes | AFK | #118–#121 | — |

## Workspace mode policy

- **Seller** = dark theme; owns all Phase 1 seller-money workflows.
- **Affiliate** = light theme; every route shows **Out of Scope** (no affiliate workflows in Phase 1).

## Parallelization

After **#118** lands, **#119**, **#120**, and **#121** are disjoint (separate workflow UIs) and may run in parallel per `issue-workflow.mdc`.

---

## Issue bodies (create in this order)

### #113 — PRD: MVP 1.0 — Phase 1 UI + Mock Data

## What to build

Parent tracking issue for Phase 1 (Weeks 1–6): mock-data-driven UI for all three seller-money workflows (New Seller Copilot, Revenue Leakage Detection, Growth Copilot), rules-based routing, no-op executor, and UX instrumentation. No real TikTok APIs, no ML.

Full PRD: `docs/features/mvp_1.0/PRD.md`

## Acceptance criteria

- Child issues #114–#123 created and linked
- Phase 1 exit gate criteria documented in PRD (100-seller UX test, engagement threshold)
- EXECUTION.md P1-0 through P1-7 slices traceable to child issues

## Blocked by

None — can start immediately

---

### #114 — Mock data schemas and seller personas

## Parent

#113

## What to build

End-to-end mock data layer: JSON schemas and typed fixtures for seller profiles, orders, returns, affiliate signals, ad campaigns, and task copy. At least three hardcoded Vietnamese personas (new seller, leakage-risk, growth) loadable without network I/O. Fixtures are volumetric enough to stress-test lists (10+ orders, multiple campaigns).

## Acceptance criteria

- JSON schemas exist for seller profile, task, order, return, affiliate event, and ad campaign
- Three persona fixtures (new, leakage, growth) with realistic Vietnamese shop names, products, and VND amounts
- Task copy (titles, bodies, CTAs) colocated with fixtures; `copy_source: "mock"` on tasks
- Schemas forbid buyer PII; only masked buyer identifiers where needed
- Unit tests validate each persona fixture against its schema
- Public loader: load persona by ID with no network calls

## Blocked by

None — can start immediately

**User stories:** 38–42

---

### #115 — Workspace mode — Seller dark / Affiliate out-of-scope

## Parent

#113

## What to build

Retain post-login Seller vs Affiliate workspace mode. Seller mode uses dark theme and is the only mode where Phase 1 workflows render. Affiliate mode uses light theme and shows a consistent Vietnamese "Out of Scope" state on every authenticated route. Mode switcher persists selection without losing auth.

## Acceptance criteria

- Seller mode applies dark theme; affiliate mode applies light theme
- Every route in affiliate mode renders a clear Out of Scope message (Vietnamese)
- Mode switcher toggles modes without logout
- Mode persists across refresh via existing storage convention
- Integration test: affiliate mode shows out-of-scope on at least home and one secondary route
- Integration test: seller mode does not show out-of-scope on workflow routes

## Blocked by

None — can start immediately

**User stories:** 53–58

---

### #116 — Rules-based seller-stage router

## Parent

#113

## What to build

Deterministic seller lifecycle classifier consuming mock profile metrics (shop age, order count, return rate, ad spend) and returning `new | leakage | growth`. Documented thresholds serve as the Phase 1.5 ML baseline. Include golden boundary fixtures for QA.

## Acceptance criteria

- Public `classifySellerStage(profile)` returns one of three stages
- Threshold constants documented inline or in module doc
- Unit tests cover all three personas plus edge cases at threshold boundaries
- Same input always yields same output (deterministic)
- No network or database dependencies

## Blocked by

Blocked by #114

**User stories:** 34–37

---

### #117 — Shared task card + no-op executor

## Parent

#113

## What to build

Reusable task card component and no-op executor used by all three workflows. Sellers approve or dismiss tasks; UI updates session state only (no backend side effects). Consistent interaction pattern with visual confirmation and demo-mode copy explaining that real TikTok actions are not triggered yet.

## Acceptance criteria

- Shared task card renders title, body, severity, CTA, and optional GMV impact
- Approve moves task to acknowledged/completed state; dismiss removes from active queue
- Visual confirmation on approve/dismiss (toast or inline)
- Demo tooltip or copy states Phase 1 is mock-only (no real execution)
- Session persistence: dismissals survive navigation within session
- Integration test: approve then dismiss on separate tasks updates queue correctly
- No API calls on approve/dismiss

## Blocked by

Blocked by #115

**User stories:** 28–33

---

### #118 — Seller home shell — routing + persona switcher

## Parent

#113

## What to build

Seller-mode home shell that routes to the correct workflow based on rules-based stage detection. Persona switcher lets test sellers demo all three workflows. Shows active workflow label/breadcrumb. Replaces creator-matching home as the primary seller entry (full legacy retirement in #123).

## Acceptance criteria

- Post-login seller lands in home shell (not legacy recommendation feed)
- Persona switcher loads mock personas from #114 and re-routes on change
- Stage router (#116) selects workflow; UI shows which workflow is active
- Vietnamese copy, VND formatting, responsive mobile layout
- Integration test: switching persona changes visible workflow/stage
- Integration test: new/leakage/growth personas route to expected workflow entry
- Phone-OTP auth flow unchanged

## Blocked by

Blocked by #114, #115, #116

**User stories:** 1–7, 36, 48–51

---

### #119 — New Seller Copilot UI (mocked)

## Parent

#113

## What to build

New Seller Copilot workflow UI: guided onboarding checklist toward first profitable sale, milestone progress, ranked mock tasks with justification, empty/completed states. Uses shared task card (#117) and mock persona data (#114).

## Acceptance criteria

- Checklist tasks render for new-seller persona (setup, list product, affiliate, first ad, etc.)
- Each task explains why it matters (Vietnamese copy from fixtures)
- First-sale milestone progress visible
- Approve/dismiss via shared executor; empty and completed states render without layout breaks
- Integration test: new-seller persona renders ≥3 tasks with Vietnamese titles
- Integration test: approve removes task from active queue
- No TikTok API calls

## Blocked by

Blocked by #114, #115, #117, #118

**User stories:** 8–14

---

### #120 — Revenue Leakage Detection UI (mocked)

## Parent

#113

## What to build

Revenue Leakage workflow UI: anomaly list (return spikes, refund clusters, suspicious affiliate patterns) with severity, estimated GMV impact in VND, recommended fixes, and evidence drill-down (masked IDs, no buyer PII). Positive empty state when no signals.

## Acceptance criteria

- Leakage persona renders ranked anomaly tasks with severity and VND impact
- Drill-down shows supporting mock evidence (order IDs, return reasons, affiliate IDs — masked)
- Recommended fix visible per anomaly
- Approve/dismiss via shared executor
- Empty state: "No leakage detected this week" (Vietnamese) for persona with no signals
- Integration test: leakage persona renders anomalies with severity labels
- Integration test: drill-down opens evidence without PII fields
- No TikTok API calls

## Blocked by

Blocked by #114, #115, #117, #118

**User stories:** 15–21

---

### #121 — Growth Copilot UI (mocked)

## Parent

#113

## What to build

Growth Copilot workflow UI: ad performance summary (spend, ROAS, CPC, conversions) and ranked scale/cut recommendations citing mock metrics. Multiple campaigns ordered by opportunity.

## Acceptance criteria

- Growth persona renders ad performance summary from mock fixtures
- Scale and pause/cut recommendations cite metric justification (e.g., ROAS vs account average)
- Campaigns ranked by opportunity
- Approve/dismiss via shared executor
- Integration test: growth persona renders ≥2 ad tasks with metric citations
- Integration test: dismiss removes campaign task from active queue
- No TikTok API calls

## Blocked by

Blocked by #114, #115, #117, #118

**User stories:** 22–27

---

### #122 — UX instrumentation

## Parent

#113

## What to build

Structured analytics events for Phase 1 UX validation: task clicks, approvals, dismissals. Events include workflow, task type, persona ID, and session ID. Calls fail silently without breaking UI. Document engagement threshold definition for exit gate.

## Acceptance criteria

- Events emitted: `task_clicked`, `task_approved`, `task_dismissed`
- Payload includes `workflow`, `task_type`, `persona_id`, `session_id`; no PII
- Instrumentation wired into shared task card and all three workflow pages
- Analytics failures do not break approve/dismiss or navigation
- Unit tests assert events fire on click, approve, dismiss
- Engagement threshold definition documented (e.g., % sellers completing ≥1 approval per workflow)

## Blocked by

Blocked by #117, #119, #120, #121

**User stories:** 43–47

---

### #123 — Retire legacy creator-matching routes

## Parent

#113

## What to build

Remove or redirect legacy creator-matching surfaces (`/recommendations`, `/creators`, etc.) so test sellers only see seller-money workflows. Auth and mode selection must remain functional. Seller home (#118) becomes the canonical entry.

## Acceptance criteria

- Legacy creator-matching routes redirect to seller home or return 301 to `/`
- Primary navigation no longer promotes creator-matching pages
- Existing auth and mode-select flows still work
- Integration test: `/recommendations` and `/creators` redirect without breaking session
- Integration test: seller home loads after redirect
- No removal of phone-OTP login

## Blocked by

Blocked by #118, #119, #120, #121

**User stories:** 52

---

## Handoff: to-issues → implementation

### Issue Queue (dependency order)

1. #114 — Mock data schemas and seller personas — AFK — blocked by: none
2. #115 — Workspace mode — Seller dark / Affiliate out-of-scope — AFK — blocked by: none
3. #116 — Rules-based seller-stage router — AFK — blocked by: #114
4. #117 — Shared task card + no-op executor — AFK — blocked by: #115
5. #118 — Seller home shell — routing + persona switcher — AFK — blocked by: #114, #115, #116
6. #119 — New Seller Copilot UI (mocked) — AFK — blocked by: #114, #115, #117, #118
7. #120 — Revenue Leakage Detection UI (mocked) — AFK — blocked by: #114, #115, #117, #118
8. #121 — Growth Copilot UI (mocked) — AFK — blocked by: #114, #115, #117, #118
9. #122 — UX instrumentation — AFK — blocked by: #117, #119–#121
10. #123 — Retire legacy creator-matching routes — AFK — blocked by: #118–#121

### Parent PRD

- Local: `docs/features/mvp_1.0/PRD.md`
- GitHub: #113

### Implementation Order

Process issues top-to-bottom. For each AFK issue: run **focus → tdd → review → ship**.

### GitHub creation blocked

`gh` token is invalid (`gh auth login -h github.com` required). Issue bodies above are ready to paste or batch-create once authenticated.
