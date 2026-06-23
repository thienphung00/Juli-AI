# Context Plan (focus skill)

What to load / skip per implementation task type.

---

## Always load

- `docs/tiktok_api/README.md`
- `docs/architecture/data-sources.md`
- `docs/architecture/map.md`
- `EXECUTION.md` (phase gate check)
- Affected `MODULE.md`

---

## By task type

| Task | Load | Skip |
|------|------|------|
| OAuth / token refresh | `authentication.md`, `identity/.../tiktok_oauth.py` MODULE | `webhooks.md`, ads sections |
| New resource / endpoint | `endpoints.md`, `rate-limits.md`, resource `MODULE.md` | `phase-roadmap.md` |
| Webhook receiver | `webhooks.md`, `architecture.md`, ETL MODULE | Affiliate scope details |
| Polling worker | `architecture.md`, `rate-limits.md`, `multi-tenant.md` | `authentication.md` OAuth URL details |
| P2 Ads client (new) | `endpoints.md` Ads section, `risks.md`, Growth Copilot feature docs | Settlements, inventory |
| Review / PR | `risks.md`, `data-sources.md` Forbidden rows | `phase-roadmap.md` |
| Seller / creator policy / feature guide | `platform-docs` docs (when exist) | Raw endpoint schemas |

---

## Phase-aware loading

| Current phase | TikTok docs emphasis |
|---------------|---------------------|
| P1 | `phase-roadmap.md` only — enforce no live API |
| P1.5 | `architecture.md` data pipeline section |
| P2 | Full set + `tech-stack.md` env vars |
