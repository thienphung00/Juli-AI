# Context Plan (focus skill)

What to load / skip per TikTok integration task. Aligns with Focus routing:
**Planning** → EXECUTION + Tier 1 + ADR; **Implementation** → Issue + PRD + ADR.

---

## Always load (implementation)

- `docs/tiktok_api/README.md`
- `docs/architecture/data-sources.md`
- `docs/architecture/map.md`
- `EXECUTION.md` (phase gate check)
- Affected `MODULE.md`

---

## By task type

| Task | Load | Skip |
|------|------|------|
| OAuth / token refresh | `authentication.md`, identity OAuth MODULE | `webhooks.md`, ads sections |
| New resource / endpoint | `endpoints.md`, `rate-limits.md`, resource `MODULE.md` | Phase 3 rollout docs |
| Webhook receiver | `webhooks.md`, `architecture.md`, ETL MODULE | Affiliate scope details |
| Polling worker | `architecture.md`, `rate-limits.md`, `multi-tenant.md` | OAuth URL details |
| P2 Ads client (new) | `endpoints.md` Ads section, `risks.md` | Settlements, inventory |
| Review / PR | `risks.md`, `data-sources.md` Forbidden rows | Historical MVP PRDs |
| Seller / creator policy | `platform-docs` docs (when exist) | Raw endpoint schemas |

---

## Phase-aware loading

| Current phase | TikTok docs emphasis |
|---------------|---------------------|
| P1 / pre-MVP | `data-sources.md` — enforce no live API |
| Phase 2 MVP Milestone A | `architecture.md` data pipeline section |
| P2 | Full set + `tech-stack.md` env vars |

Rollout alignment: [`EXECUTION.md`](../../EXECUTION.md) and [`phase-2-mvp.md`](../phases/phase-2-mvp.md).
