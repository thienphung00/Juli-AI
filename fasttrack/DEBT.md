# Debt — repay before merging into main

Every skipped gate or shortcut. Format: `- [ ] what — why skipped — how to repay`.

## Gates skipped by design (D4, D8)

- [ ] `pr.yml` does not run on this branch (typecheck, architecture/import-linter,
  bandit, nginx lints, demo/landing e2e, artifact gates, full regression,
  performance smoke) — speed — run the full `pr.yml` suite on the merge PR and
  fix what it finds.
- [ ] No Executor/Review artifacts, validators or ADRs — speed — write one ADR
  summarising DECISIONS.md D1–D19 before merge.
- [ ] `.claude` edit hooks and executor-cache pre-commit gate disabled —
  speed — restore `.claude/settings.json` hooks and `.pre-commit-config.yaml`
  entry from `main` in the merge PR.
- [ ] `fasttrack-deploy.yml` refuses SHAs that would redeploy `apps/demo`,
  `apps/landing`, `packages/` or `pnpm-lock.yaml` (those lanes need a
  `release.yml` build artifact) — fast-track frontend changes can't be deployed
  until merge, or until the workflow builds those artifacts itself.
- [ ] Deploy leaves the VPS clone `~/Juli-AI-v2` detached at the fast-track SHA
  — `release.yml`/`rollback.yml` re-checkout `main` first, but verify after the
  first fast-track deploy.
- [ ] Backup thresholds (≥1 MB, ≥10 TABLE DATA entries) are guesses — tune
  after the first real backup.
- [ ] `release.yml` release artifact / browser checks / GitHub release not
  produced for fasttrack deploys — speed — first deploy from `main` after merge
  runs the full release.

## P1 shortcuts and open risks

- [ ] A-33/A-31/A-36 returning daily intervals over a multi-day range is
  assumed, not verified against live TikTok — guarded (non-single-day rows are
  dropped and logged at ERROR) — verify on Fujiwa after first deploy.
- [ ] One `requests.Session` shared by 5 threads in parallel detail calls —
  works via urllib3's pool but not formally guaranteed — per-thread sessions if
  any flakiness shows.
- [ ] One Celery worker consumes all queues, so `ingest_priority` isn't truly
  ahead of `ingest_backfill` — add a dedicated worker if connects queue.
- [ ] Analytics list calls keep the 20-page incremental cap: catalogs > 1,000
  products are truncated with a warning.
- [ ] Partial ETL row rejections still advance the daily analytics cursor.
- [ ] First deploy bootstraps every already-connected shop (Fujiwa included):
  30-day fetch + history walk = a burst of vendor calls. Watch rate limits.
- [ ] Multi-day backfill windows carry no `conversion_rate` (list row only
  merged for single-day windows) — CVR history only from the daily pass;
  backfill it per day later if the model needs it.
- [ ] `fujiwa_poll_cycle` task still registered but unscheduled — delete
  after the fan-out is proven in production.

## P7-C UI (2026-10-08)

- [ ] Decision evidence field names are assumed (`apps/demo/src/lib/decision-evidence.ts`
  header) — P7-B not landed when P7-C ran — align the candidate key lists with
  P7-B's response and add one test on its real fixture.
- [ ] "Từ chối" on a signed-in card only hides it for the session (no reject
  route) — no backend endpoint — add `POST /v1/demo/decisions/{id}/reject` and
  call it; the on-screen copy says the choice is not saved.
- [ ] Anonymous Phân tích sample is a 100 KB bundled JSON
  (`lib/shop-analysis/sample-report.json`, generated from a synthetic snapshot
  via `tests/support/shop_diagnosis.py` + `build_report`; generator kept out of
  the repo) — speed — commit the generator script or shrink the sample.
- [ ] Inter font is named in the stack but not loaded (mock imports Google
  Fonts) — no network at build — add `next/font` if the owner wants Inter
  everywhere.
- [ ] Demo header keeps the old mode switcher / "Làm mới Demo" controls inside
  the kit header (mobile alignment of "Đăng nhập" is off, pre-existing) —
  out of scope — redesign the header actions with the owner.
- [ ] e2e (Playwright) specs only had the tab name updated; not run — no
  server lane in P7-C — run `pnpm --filter @juli/demo test:e2e` before merge
  (bottom nav at every width may move selectors that assumed the desktop rail).
- [ ] vitest needs Node 20 locally: under Node 26 jsdom's `localStorage` is
  shadowed (270 failures on untouched main) — env — pin `.nvmrc` to 20.
