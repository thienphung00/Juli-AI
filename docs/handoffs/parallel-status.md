# Parallel status — TikTok Business OAuth (#489)

**Started:** 2026-07-23 · **Parent PRD:** [#489](https://github.com/thienphung00/Juli-AI/issues/489) · Meta prepares; Executor → Review → Ship

## Locked decisions

| # | Decision |
|---|----------|
| 1 | **Parallel** #490 + #491 — path-disjoint vertical slices |
| 2 | Shared-core ADR-034 + CONTEXT land first (`feature/adr-032-tiktok-business-oauth-redirects` → renumbered ADR-034) |
| 3 | Open individual PRs; CI green; **sync-before-merge** onto current `origin/main` |
| 4 | Hard failure: retry ×2, then stop |
| 5 | No Marketing API campaign CRUD, Ads ETL, or Connect Ads UI in this wave |
| 6 | Do **not** edit Shop `auth_tiktok.py` behavior (read-only prior art) |
| 7 | Prefer existing `tiktok_credentials.capability` over new DDL unless proven necessary |
| 8 | Ops lock: Meta for sequential ship |

## Current run

| Issue | Title | Modules (exclusive) | Status | Branch | Worktree | GitHub ops |
|-------|-------|---------------------|--------|--------|----------|------------|
| shared-core | ADR-034 + epic #489 registry | `docs/adr/034-*`, CONTEXT, epicRegistry | **Shipping** | `feature/adr-032-tiktok-business-oauth-redirects` | primary | pending PR |
| #490 | Advertiser OAuth callback | advertiser route + auth client + tests | **Ship-ready** | `feature/issue-490-business-advertiser-oauth` | `.worktrees/issue-490` | pending PR |
| #491 | Account-holder OAuth callback | account-holder route + auth client + tests | **Ship-ready** | `feature/issue-491-business-account-holder-oauth` | `.worktrees/issue-491` | pending PR |
| #492 | Ops docs + smoke for Business OAuth | runbooks, api.env.example, smoke-test.sh | **Ship-ready** | `feature/issue-492-business-oauth-ops-docs` | `.worktrees/issue-492` | pending PR |

## Module ownership

| Path family | Owner |
|-------------|-------|
| `api/routes/auth_tiktok_business_advertiser.py` (+ router wire in `api/app.py` advertiser only) | #490 |
| `integrations/tiktok/business_advertiser_auth.py` (+ MODULE.md notes for advertiser) | #490 |
| `services/tiktok/*advertiser*` persistence helpers | #490 |
| `tests/unit/test_tiktok_business_advertiser_*.py` | #490 |
| `api/routes/auth_tiktok_business_account_holder.py` (+ router wire in `api/app.py` account-holder only) | #491 |
| `integrations/tiktok/business_account_holder_auth.py` | #491 |
| `services/tiktok/*account_holder*` persistence helpers | #491 |
| `tests/unit/test_tiktok_business_account_holder_*.py` | #491 |
| Shop `auth_tiktok.py`, Shop OAuth tests | **Read-only** |

## GitHub ops

| Field | Value |
|-------|-------|
| **Owner** | Meta (sequential ship) |
| **PR** | Individual — ADR-034 → #490 → #491 |
| **Merge** | sync-before-merge onto current `origin/main` |
| **AFK** | Yes — mocked TikTok HTTP |

### Remote op log

| Time (UTC) | Agent | Command | Issue |
|------------|-------|---------|-------|
| 2026-07-23T14:01Z | Meta | worktrees + meta_prepare | #489/#490/#491 |
| 2026-07-23T14:30Z | Meta | rebase ADR→034; sequential PR/CI | shared-core |

## References

- Topology: [`worktree-branch-topology.md`](worktree-branch-topology.md)
- ADR: [`docs/adr/034-tiktok-business-oauth-redirect-urls.md`](../adr/034-tiktok-business-oauth-redirect-urls.md)
- PRD: [#489](https://github.com/thienphung00/Juli-AI/issues/489)
