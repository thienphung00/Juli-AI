# fasttrack/ — how agents work on this branch

Branch: `fasttrack/optimize-product`. Cut from `main` at `0332c405` on 2026-10-05.
`main` is frozen until this branch merges back once (DECISIONS D2).

This folder replaces the PRD → issue → slice → Executor → Review loop and its
validators (D4). It is the spec, the acceptance criteria, the progress tracker
and the log, all in one place.

## Read order (every agent, every session, before touching code)

1. `README.md` (this file)
2. `SPEC.md` — what we are building. The source of truth.
3. `PROGRESS.md` — the current phase, what's done, what's next.
4. `ACCEPTANCE.md` — the ACs for the task you are picking up.
5. `DECISIONS.md` — only when something in SPEC seems ambiguous.
6. The last ~5 entries of `LOG.md`.

## Rules

- **Work only on tasks in `PROGRESS.md`.** If you need something that isn't
  there, add it as a new task with a one-line reason, then do it.
- **Tick an AC only with evidence**: a commit SHA, a test name, a query and its
  result, or a log line. Write the evidence next to the AC.
- **Append to `LOG.md` before you stop**: date, who (agent/model), what
  changed, what broke, what's next. Never rewrite old entries.
- **Every shortcut goes in `DEBT.md`**: a skipped gate, a test not written, a
  hardcoded value, a TODO. Debt is repaid before the merge into `main`.
- **A new decision goes in `DECISIONS.md`** with the next D-number. Decisions
  that change SPEC need the owner; note them as "PROPOSED" until confirmed.
- **Small commits**, conventional-commit style, on this branch. No PRs needed.
- **Never push to `main`. Never force-push.** Merging is the owner's.
- **Production safety rules still apply** (D8): anything touching the database,
  credentials, tenant isolation or TikTok writes needs a test.

## Deploying to production

Owner only. Tag a commit that is already on `fasttrack/optimize-product` and
push the tag; `.github/workflows/fasttrack-deploy.yml` then runs `check.sh` and
deploys; a deploy that carries a migration is dumped once, inside `deploy.sh`,
right before `alembic upgrade` (abort on failure; P62-A, P62-C, D72.1). In parallel it
builds the demo artifact itself (`infra/scripts/build-release-artifact.sh`, the
`NEXT_PUBLIC_SUPABASE_*` repo secrets inlined at build, verified by
`verify-supabase-env-in-build.mjs`); if the demo lane changed, that tarball is
copied to the VPS and `deploy.sh` runs the demo lane after the API lane via
`DEMO_ARTIFACT_TARBALL`. The landing artifact is built and handed over the same
way (`LANDING_ARTIFACT_TARBALL`; DEBT repaid 2026-10-08):

```bash
git tag fasttrack-deploy-$(date -u +%Y%m%dT%H%MZ) <full-sha> && git push origin <that-tag>
```

Jobs (stable ids; `deploy` needs every one of them, P55 / D64):

| Job id | What it runs | Needs |
|---|---|---|
| `validate` | the SHA is a full commit on the fast-track branch | — |
| `plan` | reads production's `alembic current` on the VPS (one SELECT, no dump) and compares it with the SHA's alembic head (`infra/scripts/migration_heads.py`) for the log; outputs `backup=true` **only on force_backup** (P62-C) | validate |
| `check` | `fasttrack/check.sh` with a throwaway Postgres (migrations, isolation, gitleaks, ruff + pytest on changed files) | plan |
| `build` | demo + landing release tarballs | validate |
| `frontend` | demo + landing `eslint`, `tsc --noEmit`, `vitest` (what `pnpm check:demo` / `check:landing` run, minus `next build`); `packages/ui` and `utils` tests; Node from `.nvmrc` | validate |
| `backend-unit` | the full `pytest tests/unit -m "not live"` with no database (Postgres tests skip via `requires_postgres`), after fetching the negative dataset's archived evidence refs (D65) | validate |
| `static` | `mypy --config-file backend/pyproject.toml backend/src/juli_backend` + `bandit -r backend/src/juli_backend -ll` | validate |
| `backup` | **only when `plan` says `backup=true` and every gate passed**: verified `pg_dump` of production on the VPS (`infra/scripts/backup-database.sh`, copied from the SHA) | plan, check, build, frontend, backend-unit, static |
| `deploy` | `infra/scripts/deploy.sh <sha>` over SSH, then a public `/health` check. Runs when `backup` succeeded **or was skipped because none was asked for**; never after a failed backup | plan, backup, check, build, frontend, backend-unit, static |

`frontend`, `backend-unit` and `static` run beside `plan` → `check`, so they
add wall time only when one of them is slower than that branch (LOG P55 has the
measured times). The same commands locally:

```bash
pnpm install --frozen-lockfile
pnpm lint:demo && pnpm type-check:demo && pnpm test:demo
pnpm --filter @juli/ui test && pnpm --filter @juli/utils test
pnpm lint:landing && pnpm type-check:landing && pnpm test:landing
env -u DATABASE_URL python -m pytest tests/unit -m "not live" -q -p no:cacheprovider
mypy --config-file backend/pyproject.toml backend/src/juli_backend
bandit -r backend/src/juli_backend -ll
```

### Database dumps (P62-A, D72.1 — Supabase egress)

Every full dump is a full copy of production through Supabase egress, so dumps are
taken only where they protect something:

- **`safe-alembic-upgrade.sh`** (inside `deploy.sh`) — **the one dump of a migration
  deploy** (P62-C), taken right before `alembic upgrade` and only when `alembic` has
  pending revisions (an unreadable revision still dumps); otherwise it logs
  `no pending migration — pre-migrate dump skipped` and continues (privilege
  check, no-op upgrade, row counts and token decrypt still run).
- **Deploy `backup` job** — only on force_backup (below), and only after every gate
  passed, so a deploy that fails its tests never dumps. Until P62-C it also ran for
  every migration, which made each migration deploy two full dumps (measured
  2026-10-27: ~210 MB of pooler egress per dump, 803 MB that day for 3 dumps).
- **Both dumps leave out the rows of `public.processed_events`** (the webhook
  "already seen" ledger; schema kept). After a restore each record is re-compared
  once; nothing is lost.
- **Scheduled dump on the VPS** — `juli-db-backup.timer` fires daily at 19:30 UTC
  (02:30 Vietnam); `backup-database.sh` dumps only when the newest
  `~/backups/juli-pre-migrate-*.dump` is at least `BACKUP_MIN_INTERVAL_HOURS` old
  (72 = every 3 days; any dump, including a migration deploy's, resets the clock).
  Each dump logs `DUMP_SIZE label=… bytes=…` for measuring egress. Same rotation
  (14 days) and the weekly restore drill restores the newest dump.

**Force the workflow's `backup` job** (an extra verified dump, ~210 MB of egress) on
any deploy (any one of):

```bash
git tag fasttrack-deploy-$(date -u +%Y%m%dT%H%MZ)-force-backup <full-sha> && git push origin <that-tag>
gh workflow run fasttrack-deploy.yml --ref fasttrack/optimize-product -f sha=<full-sha> -f force_backup=true
gh variable set FASTTRACK_FORCE_BACKUP --body true   # every deploy until unset: gh variable delete FASTTRACK_FORCE_BACKUP
```

**Install the scheduled dump on the VPS** (once, as root, after a deploy that
ships these files — `deploy.sh` does not install timers, same as the restore drill):

```bash
cd ~/Juli-AI-v2
install -m 0644 infra/systemd/juli-db-backup.service infra/systemd/juli-db-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now juli-db-backup.timer
systemctl list-timers juli-db-backup.timer
systemctl start juli-db-backup.service && journalctl -u juli-db-backup.service -n 30 --no-pager   # first run: dumps if nothing < 72 h
# change the cadence: systemctl edit juli-db-backup.service -> [Service] Environment=BACKUP_MIN_INTERVAL_HOURS=48
```

## Rolling back production

Owner only. `infra/scripts/rollback-release.sh` (run by `.github/workflows/rollback.yml`)
moves API + Demo + Landing together to the state right after an earlier deploy
(default: the one before what is live), restarts the Celery worker + beat on it, and
prints a PASS/FAIL summary. No rebuild, and it never touches the database. Plan first:

```bash
git tag fasttrack-rollback-plan-$(date -u +%Y%m%dT%H%MZ) origin/fasttrack/optimize-product && git push origin <that-tag>
git tag fasttrack-rollback-$(date -u +%Y%m%dT%H%MZ)[-to-<sha>] origin/fasttrack/optimize-product && git push origin <that-tag>
# or: gh workflow run rollback.yml --ref fasttrack/optimize-product -f action=plan|rollback|verify [-f target_sha=<sha>]
```

Never dispatch `rollback.yml` with ref `main` (main's copy is the pre-P57 one). Topology,
failure handling, migrations and the one-time live drill:
[`docs/runbooks/rollback-runbook.md`](../docs/runbooks/rollback-runbook.md) (P57, D66).

## Running checks locally

```bash
fasttrack/check.sh            # what the deploy runs: backup-free local subset
```

In a git worktree, run pytest with `PYTHONPATH=backend/src` (or the
worktree's own venv). A bare `pytest` can import the main checkout's code
instead.
