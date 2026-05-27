# Objective

TikTok Shop AI Operating System PRD (issue #2) broken into 24 independently-grabbable
vertical-slice GitHub issues, ready for implementation via `focus → tdd → review`.

# Completed

- 24 vertical-slice issues created (#24–#47)
- Old duplicate issues (#3–#23) closed with superseded comment
- All slices validated: ≤3 modules, ≤5 ACs, mapped to PRD user stories
- Dependency graph filed in each issue's "Blocked by" field
- **14 issues implemented** (#24, #25, #26, #27, #28, #29, #30, #31, #33, #34, #37, #41, #42, #45) — see Status column below

# Issue Registry

| # | Slice | Modules | Blocked by | Type | Status |
|---|-------|---------|------------|------|--------|
| 24 | Data: Auth/shop core schema + repos | `data` | None | AFK | **Done** |
| 25 | Integrations/TikTok: Creator, livestream, settlement resources | `integrations/tiktok` | None | AFK | **Done** |
| 26 | Services: Rename workers → polling | `services/polling` | None | AFK | **Done** |
| 27 | Services/Webhook: New event types | `services/webhook` | None | AFK | **Done** |
| 28 | Data: Commerce + analytics tables + repos | `data` | ~~#24~~ | AFK | **Done** |
| 29 | Auth: Phone-OTP login + JWT middleware | `auth`, `data` | ~~#24~~ | AFK | **Done** |
| 30 | Auth: TikTok OAuth + shop provisioning | `auth`, `integrations/tiktok`, `data` | ~~#29~~ | AFK | **Done** |
| 31 | Services/Polling: Extend sync (creators, livestreams, settlements) | `services/polling`, `integrations/tiktok`, `data` | ~~#28~~, ~~#25~~, ~~#26~~ | AFK | **Done** |
| 32 | ETL: Kafka consumer + dedup + DLQ | `etl`, `data` | ~~#28~~, ~~#27~~ | AFK | **Unblocked** |
| 33 | API: Bootstrap + auth + shop endpoints | `api`, `auth`, `data` | ~~#29~~ | AFK | **Done** |
| 34 | Intelligence/Scoring: Livestream grade + anomaly detection | `intelligence/scoring`, `data` | ~~#28~~ | AFK | **Done** |
| 35 | Intelligence/Forecasting: Inventory depletion + velocity | `intelligence/forecasting`, `data` | ~~#28~~ | AFK | **Unblocked** |
| 36 | Alerts: Rule engine + channel abstraction + FCM | `alerts`, `data` | ~~#28~~ | AFK | **Unblocked** |
| 37 | API: Orders + products + inventory endpoints | `api`, `data` | ~~#33~~, ~~#28~~ | AFK | **Done** |
| 38 | API: Livestream + creator + settlement endpoints | `api`, `data` | ~~#33~~, ~~#28~~ | AFK | **Unblocked** |
| 39 | Recommendations: Rule-based product push + restock | `recommendations`, `intelligence/forecasting`, `data` | #35 | AFK | Blocked |
| 40 | Alerts: Zalo OA adapter | `alerts` | #36 | AFK | Blocked |
| 41 | Web: Auth + homepage + orders | `web` | ~~#33~~ | HITL | **Done** |
| 42 | iOS: Auth + daily value loop shell | `ios` | ~~#33~~ | HITL | **Done** |
| 43 | API: Alerts + recommendations + analytics endpoints | `api`, `alerts`, `recommendations` | ~~#37~~, #39, #36 | AFK | Blocked |
| 44 | Recommendations: LLM stream optimization + host matching | `recommendations`, `intelligence/scoring` | ~~#34~~, #39 | AFK | Blocked |
| 45 | Web: Products, inventory, livestreams, creators pages | `web` | ~~#41~~ | AFK | **Done** |
| 46 | iOS: Push notifications + live alerts | `ios` | ~~#42~~, #36 | AFK | Blocked |
| 47 | Web: Alerts config + recommendations feed | `web` | #43, ~~#41~~ | AFK | Blocked |

# Dependency Order (critical path)

```
#24 → #29 → #33 → #37 → #43 → #47
 ↓      ↓      ↓
#28    #30    #41 → #45
 ↓             #42 → #46
 ├→ #35 → #39 → #44
 ├→ #34 ─────────↗
 ├→ #36 → #40
 ├→ #32
 ├→ #37, #38

#25 ─┐
#26 ─┼→ #31
#28 ─┘

#27 → #32
```

Parallelism unlocked:
- ~~**Immediate starts (4 slices):** #24, #25, #26, #27~~ → all done
- ~~**After #24 merges:** #28, #29~~ → all done
- ~~**After #29 merges:** #30, #33~~ → all done
- ~~**After #33 merges:** #37, #38, #41, #42~~ → #37, #41, #42 done; #38 unblocked
- ~~**After #25+#26+#28 merge:** #31~~ → done
- **Now unblocked (4 slices):** #32, #35, #36, #38
- **After #35 merges:** #39 → unblocks #43 (partial), #44 (partial)
- **After #36 merges:** #40, #43 (partial), #46 (partial)
- **After #39+#36 merge:** #43 fully unblocked → #47

# Parallel Execution — Conflict Matrix

#38 may run in parallel with any non-`api` slice. Backend slices sharing
`data` must be sequenced — see conflict warnings below.

| Issue | Modules (Writer of) | Type  | Conflicts with               |
|-------|---------------------|-------|------------------------------|
| #32   | `etl`, `data`       | AFK   | #35, #36, #38 (shared `data`) |
| #35   | `intelligence/forecasting`, `data` | AFK | #32, #36, #38 (shared `data`) |
| #36   | `alerts`, `data`    | AFK   | #32, #35, #38 (shared `data`) |
| #38   | `api`, `data`       | AFK   | #32, #35, #36 (shared `data`) |

# Decisions

- Split #1 into #24 (auth core) + #28 (commerce) — parallelizes auth vs commerce paths
- Split #5 into #26 (rename) + #31 (feature) — isolates mechanical refactor blast radius
- #41 (Web) and #42 (iOS) start after #33 (API bootstrap), not after all backend — interleaved for earlier stakeholder demos
- #40 (Zalo OA) isolated from #36 (FCM) — decouples risky external dependency
- #3 (OAuth) marked AFK with verification note, not full HITL

# Modules

All modules across all slices:
- `data`, `auth`, `api`, `etl` (Core — created)
- `intelligence/forecasting`, `intelligence/scoring`, `recommendations`, `alerts` (Feature — created)
- `web`, `ios` (Interface — created)
- `integrations/tiktok`, `services/webhook`, `services/polling` (Existing — modified)

# Interfaces Changed

- N/A (planning phase — interfaces defined in PRD issue #2)

# Remaining Work

1. Per-issue implementation: `focus` → `tdd` → `review` → merge
2. **14 of 24 slices done** (58%) — 10 remaining
3. **4 slices now unblocked:** #32, #35, #36, #38
4. Recommended next: #35 (unblocks #39 → #43 → #47 critical path), #36 (unblocks #40, #43, #46), #38 (API tier 2)

# Risks

- #40 (Zalo OA) may be blocked by API approval — #36 (FCM) ships independently
- #30 (OAuth) requires TikTok sandbox credentials for e2e verification
- #35 (forecasting) is on the critical path for 4 downstream slices (#39, #43, #44, #47)
- #36 (alerts) is on the critical path for 4 downstream slices (#40, #43, #46, #47)

# Tests

- N/A (planning phase — each issue defines its own test mapping)
- TDD approach: RED (write failing test from AC) → GREEN → REFACTOR

# Required Context Next Session

- This handoff: `docs/handoffs/tiktok-mvp-issues-01.md`
- Next issues to implement: `gh issue view 35`, `gh issue view 36`, `gh issue view 38`, `gh issue view 32`
- Architecture map: `docs/architecture/map.md`
- MODULE.md for target module (created during implementation)

# Bootstrap Prompt

"Continue build-feature for TikTok Shop AI Operating System. Load handoff
docs/handoffs/tiktok-mvp-issues-01.md. Start with issue #35 (Intelligence/Forecasting).
Run focus → tdd → review."
