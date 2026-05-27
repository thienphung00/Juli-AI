# Objective

TikTok Shop AI Operating System PRD (issue #2) — 24 vertical-slice issues for
`focus → tdd → review`.

# Completed

- 24 issues (#24–#47); 15 shipped — see registry
- Dependencies in GitHub "Blocked by"

# Status

| Status | Meaning |
|--------|---------|
| `Done` | Merged |
| `Blocked` | Waiting on another issue |
| `Unblocked` | Ready; **Parallel**-safe (disjoint `Modules` vs other ready issues) |
| `Isolate` | Ready; **Isolate** only (overlapping `Modules` with another ready issue) |

**Workflow:** `Unblocked` → Parallel. `Isolate` → Isolate (one at a time).

Recompute after **each merge** (on `main`):

1. Mark shipped issue `Done`.
2. Unblock dependents → `Blocked` becomes `Unblocked` or `Isolate` when deps clear.
3. Among all non-`Done` issues with deps satisfied, set **`Isolate`** if `Modules` intersects any other such issue; else **`Unblocked`**.

# Issue Registry

| # | Slice | Modules | Blocked by | Type | Status |
|---|-------|---------|------------|------|--------|
| 24 | Data: Auth/shop core schema + repos | `data` | None | AFK | Done |
| 25 | Integrations/TikTok: Creator, livestream, settlement resources | `integrations/tiktok` | None | AFK | Done |
| 26 | Services: Rename workers → polling | `services/polling` | None | AFK | Done |
| 27 | Services/Webhook: New event types | `services/webhook` | None | AFK | Done |
| 28 | Data: Commerce + analytics tables + repos | `data` | ~~#24~~ | AFK | Done |
| 29 | Auth: Phone-OTP login + JWT middleware | `auth`, `data` | ~~#24~~ | AFK | Done |
| 30 | Auth: TikTok OAuth + shop provisioning | `auth`, `integrations/tiktok`, `data` | ~~#29~~ | AFK | Done |
| 31 | Services/Polling: Extend sync | `services/polling`, `integrations/tiktok`, `data` | ~~#28~~, ~~#25~~, ~~#26~~ | AFK | Done |
| 32 | ETL: Kafka consumer + dedup + DLQ | `etl`, `data` | ~~#28~~, ~~#27~~ | AFK | Isolate |
| 33 | API: Bootstrap + auth + shop endpoints | `api`, `auth`, `data` | ~~#29~~ | AFK | Done |
| 34 | Intelligence/Scoring: Livestream grade + anomaly | `intelligence/scoring`, `data` | ~~#28~~ | AFK | Done |
| 35 | Intelligence/Forecasting: Inventory depletion + velocity | `intelligence/forecasting`, `data` | ~~#28~~ | AFK | Done |
| 36 | Alerts: Rule engine + FCM | `alerts`, `data` | ~~#28~~ | AFK | Isolate |
| 37 | API: Orders + products + inventory | `api`, `data` | ~~#33~~, ~~#28~~ | AFK | Done |
| 38 | API: Livestream + creator + settlement | `api`, `data` | ~~#33~~, ~~#28~~ | AFK | Isolate |
| 39 | Recommendations: Rule-based push + restock | `recommendations`, `intelligence/forecasting`, `data` | ~~#35~~ | AFK | Isolate |
| 40 | Alerts: Zalo OA adapter | `alerts` | #36 | AFK | Blocked |
| 41 | Web: Auth + homepage + orders | `web` | ~~#33~~ | HITL | Done |
| 42 | iOS: Auth + daily value loop shell | `ios` | ~~#33~~ | HITL | Done |
| 43 | API: Alerts + recommendations + analytics | `api`, `alerts`, `recommendations` | ~~#37~~, #39, #36 | AFK | Blocked |
| 44 | Recommendations: LLM stream optimization | `recommendations`, `intelligence/scoring` | ~~#34~~, #39 | AFK | Blocked |
| 45 | Web: Products, inventory, livestreams, creators | `web` | ~~#41~~ | AFK | Done |
| 46 | iOS: Push notifications + live alerts | `ios` | ~~#42~~, #36 | AFK | Blocked |
| 47 | Web: Alerts config + recommendations feed | `web` | #43, ~~#41~~ | AFK | Blocked |

**Ready now (Isolate):** #32, #36, #38, #39 — run one at a time until merges shrink overlap.

# Dependency Order (critical path)

```
#24 → #29 → #33 → #37 → #43 → #47
#28 → #35 → #39 → #44
#28 → #36 → #40
#27 → #32
```

# Prompts

Protocol: `docs/handoffs/_bootstrap.md` · `.cursor/rules/issue-workflow.mdc`

## Parallel coordinator (only `Unblocked` issues)

```text
Parallel coordinator — do not implement product code.

1. docs/handoffs/tiktok-mvp-issues-01.md — pick issues with Status Unblocked only.
2. Confirm pairwise disjoint Modules.
3. On main: worktrees + rows in docs/handoffs/parallel-status.md per _bootstrap.md Parallel.
4. Reply with one Issue prompt per issue (workflow: Parallel).
```

## Issue prompt (template)

Replace `<N>`, `<slug>`, `<OWNER>`. Set `workflow` from Status: `Isolate` or `Parallel`.

```text
Implement GitHub issue #<N> (workflow: <Isolate|Parallel>).

1. docs/handoffs/tiktok-mvp-issues-01.md — confirm Status for #<N> matches workflow.
2. docs/handoffs/_bootstrap.md — Isolate or Parallel steps.
3. docs/handoffs/parallel-status.md — claim row on main before first edit.
4. git worktree add ../juli-ai-issue-<N> -b feat/issue-<N>-<slug> origin/main  (skip if exists)
5. cd ../juli-ai-issue-<N>
6. gh issue view <N>
7. focus → tdd → review → PR (update parallel-status phase each step)
8. After merge on main: mark #<N> Done; recompute Unblocked / Isolate for remaining issues.
```

**Examples (current):**

| Issue | workflow | slug |
|-------|----------|------|
| #39 | Isolate | `recommendations-rules` |
| #36 | Isolate | `alerts-fcm` |
| #32 | Isolate | `etl-kafka` |
| #38 | Isolate | `api-livestream` |

# Remaining Work

- 9 issues open; 4 ready (`Isolate`): #32, #36, #38, #39
- Suggested order: #39 → #36 → #38 → #32 (critical path first)

# Required Context

- `docs/architecture/map.md`
- `gh issue view <N>`
- Target `MODULE.md` under issue `Modules`
