# Log

Append-only. Newest at the bottom. Format: `## YYYY-MM-DD — who` then bullets.

## 2026-10-05 — orchestrator (Claude Opus)

- Grilling session completed: D1–D19 recorded in `DECISIONS.md`.
- #2079 merged by owner. Branch `fasttrack/optimize-product` cut at `0332c405`
  into worktree `/Users/macos/juli-fasttrack`.
- Wrote README, SPEC, ACCEPTANCE, PROGRESS, DECISIONS, LOG, DEBT.
- Next: disable hooks, P0 agent for check.sh + deploy workflow, P1-A and P1-B
  agents in parallel.
- Blocked by the Claude Code permission classifier, left for the owner:
  disabling `.claude` hooks / executor-cache pre-commit gate (AC-0.3);
  committing + pushing these `fasttrack/` docs (AC-0.1, AC-0.2);
  closing Dependabot PRs (AC-0.6).
- Started agents in separate worktrees: P0 deploy (`fasttrack/p0-deploy`),
  P1-A mapper (`fasttrack/p1a-mapper`), P1-B ingestion
  (`fasttrack/p1b-ingestion`). All branch from `0332c405`.
- With owner approval the orchestrator closed 19 Dependabot PRs (AC-0.6).
  Hook disabling + the docs commit/push stay with the owner (classifier blocks
  them even with chat approval).
- P1-A done (Sonnet), `fasttrack/p1a-mapper` @ 4010fece: A-33 impressions /
  clicks / ctr / traffic+sales breakdown per content type; A-34 →
  `conversion_rate`; `merge_product_analytics_rows` helper; products.price from
  `tax_exclusive_price`; category leaf from `category_chains`; migration
  `075_analytics_breakdown` (down 073). 15 new tests. Orchestrator verified: the
  `-k etl|transform|analytics|alembic|migration|mapping|tiktok|product|sync`
  selection fails the same 9 tests on P1-A and on the untouched base
  (pre-existing, missing node_modules) — no regressions.
- P0 done (Opus), `fasttrack/p0-deploy` @ 596f9d0b: `fasttrack/check.sh`
  (migration up/down/up on throwaway PG with prod-URL guard, two-tenant proof,
  gitleaks, ruff, pytest on changed files) and
  `.github/workflows/fasttrack-deploy.yml` (dispatch: validate → backup on VPS,
  verified pg_dump -Fc → check → deploy.sh <sha>). Local full run passed except
  the node_modules contract tests.
- OPEN (owner): the workflow is dispatch-only, and GitHub only dispatches
  workflows present on the default branch (`main`, frozen). Options: land the
  file on `main` once, or add a tag-push trigger (`fasttrack-deploy-*`). The
  orchestrator's attempt to add the tag trigger was blocked pending owner
  decision.

## 2026-10-05 — orchestrator (Claude Opus) — P1 integrated

- P1-B done (Opus) @ add4abd1..ea0142ee: `shop_ingestion_state` table (074),
  `bootstrap_shop` on `ingest_priority`, `shop_history_backfill` on
  `ingest_backfill`, beat `shop-poll-fanout` replaces `fujiwa-poll-cycle`,
  Redis per-shop lock, daily analytics ranges up to `latest_available_date`,
  bounded parallel detail calls, latency events. OAuth callback enqueues
  bootstrap after commit.
- Merged P0, P1-A, P1-B into `fasttrack/optimize-product` (merge 728f67d1).
  Re-chained migrations 073 → 074 → 075 → deferred phone cleanup.
- Found + fixed a latent test-isolation bug: `_isolated_migration_database`
  swapped only DATABASE_URL while alembic prefers DATABASE_DIRECT_URL.
- `fasttrack/check.sh` on a fresh throwaway PG16: all 5 steps PASS. Full
  unit+harness vs base: the only real new failure (MODULE.md allowlist) fixed;
  four others were flaky from running during concurrent edits and pass on
  rerun.
- All P0 + P1 ACs ticked. P2 waits on the FastMoss API trial.
- Deviations from SPEC (accepted): latest_available_date probed via one A-36
  call; bestseller/promotion calls dropped from the scheduled path; CVR lands
  only from single-day (daily incremental) windows, not multi-day backfill.

## 2026-10-05 — orchestrator (Claude Opus) — deploy trigger

- Owner decision: deploys trigger on pushing a `fasttrack-deploy-*` tag (push
  triggers use the workflow file from the tagged commit, so this works while
  `main` is frozen). Validate now accepts `refs/tags/fasttrack-deploy-*`; the
  existing ancestry check still refuses any commit not on the fast-track
  branch, and the VPS re-checks it. `workflow_dispatch` kept for after merge.
  actionlint clean. Not yet run.

## 2026-10-08 — orchestrator (Claude Opus) — D21, D22

- Synced main into the branch (7c31a0a4: ADR-106 amendments, ADR-108 shop
  diagnosis). D21 + P7 tasks recorded; P7-A..D running on fasttrack/p7*
  branches. P7-D done @ debb24d7 (not merged yet).
- Owner confirmed D22: three-tier recommendation (diagnosis → recoverable-GMV
  ranking → day-14 calibration); P3 = TikTok-only shop model for ranking;
  FastMoss (P2) optional. SPEC §4 P2/P3/P6 and PROGRESS updated.
