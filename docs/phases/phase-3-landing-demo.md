# Phase 3 — Landing Page + Interactive Demo

> **Tier 1 — public mock experience.** Read [`EXECUTION.md`](../../EXECUTION.md) first.  
> **Owns:** Landing + Demo product scope, demo IA, mock-data boundary.  
> **Does not own:** backend pipeline (`phase-2-mvp.md`), production dashboard (`phase-3.5`).

**Goal:** Collect qualitative user feedback with minimal friction.

---

## Products

| App | Domain | Purpose |
|-----|--------|---------|
| **Landing** | `app-juli.com` | Marketing website — why Juli exists |
| **Demo** | `demo.app-juli.com` | Interactive storytelling product — why Juli is different |

Both deploy from `apps/landing` and `apps/demo` respectively (scaffolded in Phase 2.5).

---

## Demo philosophy

The demo is **not** a miniature dashboard. It answers:

> "Why is Juli different?"

The user journey reinforces one continuous AI workflow:

```
Observe → Understand → Recommend → Approve → Execute → Measure
```

Charts support recommendations — they are not the primary focus.

---

## Demo information architecture

Two primary screens only:

### Home

Scrolls naturally as one story:

1. **AI Briefing** — what matters today
2. **Analytics** — supporting evidence (charts subordinate to narrative)
3. **Recommendations** — ranked suggestions with reasoning
4. **Approval** — explicit seller consent
5. **CTA into Actions** — continue the workflow

### Actions

Execution lifecycle in one place:

| Section | Content |
|---------|---------|
| Pending Approval | Awaiting seller decision |
| Scheduled | Approved, queued |
| In Progress | Executing now |
| Completed | Done |
| Results / Impact | Outcome measurement |

The transition Home → Actions must feel like continuing one workflow, not navigating
unrelated pages.

---

## Boundaries

| In scope | Out of scope |
|----------|--------------|
| Mock data only | Real TikTok connection |
| Hardcoded demo flows | Login / account creation |
| Mobile-first UX | Production ML inference |
| PostHog behavior analytics | Backend pipeline validation |

---

## Relationship to legacy `web/`

The current [`web/`](../../web/) app is a **pre-ecosystem seller dashboard** (3-tab IA:
Home / Decisions / Juli Chat per ADR-014). It is **not** the Phase 3 demo.

Phase 3 builds fresh apps under `apps/demo` and `apps/landing`. Patterns from `web/` may
be referenced but the demo IA (Home + Actions) is authoritative for Phase 3.

---

## Exit gate → Phase 3.5

- [ ] Users understand Juli within minutes
- [ ] Users complete the demo without assistance
- [ ] Engagement and messaging metrics collected via PostHog
