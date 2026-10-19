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
push the tag; `.github/workflows/fasttrack-deploy.yml` then backs up the
production DB (abort on failure), runs `check.sh`, and deploys. In parallel it
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
| `backup` | verified `pg_dump` of production on the VPS | validate |
| `check` | `fasttrack/check.sh` with a throwaway Postgres (migrations, isolation, gitleaks, ruff + pytest on changed files) | backup |
| `build` | demo + landing release tarballs | validate |
| `frontend` | demo + landing `eslint`, `tsc --noEmit`, `vitest` (what `pnpm check:demo` / `check:landing` run, minus `next build`); `packages/ui` and `utils` tests; Node from `.nvmrc` | validate |
| `backend-unit` | the full `pytest tests/unit -m "not live"` with no database (Postgres tests skip via `requires_postgres`) | validate |
| `static` | `mypy --config-file backend/pyproject.toml backend/src/juli_backend` + `bandit -r backend/src/juli_backend -ll` | validate |
| `deploy` | `infra/scripts/deploy.sh <sha>` over SSH, then a public `/health` check | check, build, frontend, backend-unit, static |

`frontend`, `backend-unit` and `static` run beside `backup` → `check`, so they
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

## Running checks locally

```bash
fasttrack/check.sh            # what the deploy runs: backup-free local subset
```

In a git worktree, run pytest with `PYTHONPATH=backend/src` (or the
worktree's own venv). A bare `pytest` can import the main checkout's code
instead.
