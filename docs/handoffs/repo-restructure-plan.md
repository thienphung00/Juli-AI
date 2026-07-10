# Repo Restructure — Implementation Plan (Meta Agent handoff)

> **Status:** planned, not started. Owner: solo maintainer.
> **Nature:** read/refactor only — no behavior changes, **except** two explicitly-flagged
> deploy-script/systemd edits in Phase 1 that are required for the `src/` layout to run in
> production. No Docker / Terraform / K8s / cloud IaC introduced anywhere.
> **Invariant (per `restructure` skill):** the same tests pass before and after every phase.

## How to use this doc
One phase = one branch = one PR. Do not combine phases. Before each phase, capture the
baseline; after each phase, re-run and diff. Any new failure blocks the PR. Every file move
is followed by a repo-wide grep for the old path. Prefer `git mv`. If a phase becomes
ambiguous or contradicts the findings below, stop and flag rather than guess.

## Locked decisions
1. Backend package renamed to **`juli_backend`** (current imports are `backend.*` across 143 files).
2. Frontend stays on **npm**; **pnpm/turbo monorepo scaffolding is decommissioned** (see Phase 3/6).
3. This plan is the source of truth; execute phase-by-phase from a fresh `git pull`.

---

## Baseline capture (run before Phase 1, re-run per phase)

```bash
# Backend
pip install -r requirements.txt pytest-cov
pytest tests/ -q --cov=backend --cov-fail-under=80        # record pass/fail + coverage %

# Frontend
cd web && npm ci && npm run lint && npm run type-check && npm run test && npm run build
```
Record the numbers at the top of each phase PR description.

---

## Critical findings (reality vs. original prompt assumptions)

| # | Assumed | Reality | Consequence |
|---|---|---|---|
| 1 | imports `from api...` | `from backend.<pkg>...`; `backend/__init__.py` makes `backend` a top-level package; **143/171** py files import `backend.` | Phase 1 rename is `backend.*` → `juli_backend.*` |
| 2 | — | `systemd/juli-api.service` runs `.venv/bin/uvicorn backend.api.api.main:app`; `deploy-release.sh` only does `pip install -r requirements.txt` (works because `backend/` is on cwd `sys.path`) | `src/` layout **breaks prod import** unless Phase 1 also rewrites the systemd module path **and** adds `pip install -e .` to `deploy-release.sh` — flagged deploy change |
| 3 | keep `requirements.txt` "if CI reads it" | root `requirements.txt` read by CI `lint`, `test`, `migration-check` **and** `deploy-release.sh` | Phase 1 **must** keep emitting root `requirements.txt` from `pyproject.toml` |
| 4 | update Alembic `env.py` | `alembic.ini`: `script_location=%(here)s/backend/database/migrations`, `prepend_sys_path=.`; `env.py` imports `backend.database.*`, `backend.runtime` | Phase 1 updates `alembic.ini` + `env.py`; `migration-check` job gates it |
| 5 | Phase 3 "evaluate pnpm" | Split-brain: root declares pnpm workspaces, but CI/systemd/deploy all use **npm** in `web/` | Decision: keep npm, **remove pnpm scaffolding** |
| 6 | create turbo/pnpm/packages "only if adopted" | `turbo.json`, `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `packages/*` (7 empty), `apps/*` (4 empty) **already exist unused** | Phase 3/6 reconciles/removes existing scaffolds, does not introduce tooling |
| 7 | "No CD pipeline yet" | CD exists: `release.yml` (auto-deploy on push to `main`), `rollback.yml`, `deploy-release.sh`, `rollback-release.sh` | Not building CD, but every path move must update these or deploys break |
| 8 | Phase 6 ignore `artifacts/ screenshots/ coverage/` | `artifacts/` = 339 tracked files **intentionally versioned (ADR-003)**; `screenshots/` = 39 tracked; `coverage/` = not tracked | Ignore **only** `coverage/`; leave `artifacts/`+`screenshots/` unless you decide otherwise |

**Phase 2 note:** backend currently uses a DDD layout (`integrations/catalog/domain/…`,
`identity/infrastructure/auth/…`, `ordering/{api,use_cases}/…`; models+repos in `database/`)
and a double-nested `backend/api/api/`. The prompt's flat Phase 2 target is a semantic
re-architecture, not a mechanical move — treat as highest risk and inventory per-file first.

---

## Sequencing & branch map

| Order | Phase | Branch | Depends on | Risk |
|---|---|---|---|---|
| 1 | P0 audit report | `chore/repo-audit` | — | none |
| 2 | P1 Python packaging | `refactor/backend-src-layout` | P0 | high |
| 3 | P5 docs reorg (parallel with P1) | `docs/reorg` | P0 | low |
| 4 | P6a gitignore `coverage/` (parallel) | `chore/gitignore-coverage` | P0 | low |
| 5 | P2 backend domain reorg | `refactor/backend-domains` | P1 merged+green | highest |
| 6 | P3 frontend consolidation + pnpm removal | `refactor/frontend-apps` | P0 rec | high |
| 7 | P4 infra reorg | `refactor/infra-layout` | P3 | medium |
| 8 | P6b final layout + README | `chore/root-cleanup` | all | low |
| 9 | P7 agent-runtime consolidation | `refactor/agent-runtime-consolidation` | P6 (or parallel P5) | high |

---

## Phase 7 — Agent runtime consolidation (new)

**Goal:** Move the agent optimization loop from five scattered root trees into one
`agent-runtime/` folder. See [`docs/architecture/repo-audit.md`](../architecture/repo-audit.md) §10.

**Target layout:**
```
agent-runtime/
  README.md
  config/          # agent-runtime.config.yml, harness-editable.yml, harness-safelist.yml
  artifacts/       # entire root artifacts/ tree (reviews, validation, implementations, optimization, benchmarks, releases)
  scripts/         # build_runtime.py, harness_config.py, harness_optimizer.py, ci/, validate/
  docs/            # agent-runtime*.md, benchmarks/, schemas/
  templates/       # context-plan-template.md (from docs/handoffs/)
```

**Do NOT move:** `backend/ai/artifacts/` (ML model code — different domain).

**Reference-update checklist:** `scripts/ci/common.py` path constants; harness scripts;
`harness-editable.yml` + `harness-safelist.yml`; `.github/workflows/{pr,release,architecture-audit}.yml`;
`.cursor/skills/{focus,validate,ship}`; `docs/ci/implementation-guide.md`; harness unit tests;
grep `artifacts/` inside committed JSON if paths are embedded.

**Gate:** `pytest tests/unit/test_harness_*.py tests/unit/test_implementation_artifact.py`;
`harness_optimizer.py propose` dry-run against a fixture issue; `pr.yml` validate-artifacts green.

**Open:** keep `done.md` at root vs `agent-runtime/templates/`; big-bang vs stub re-exports at old paths.

---

## Phase 0 — Investigation report (docs only)
**Output:** `docs/architecture/repo-audit.md` recording findings #1–#8 and the frontend recommendation. **No code changes; stop after the report.**

Pre-established evidence to write up:
- `web/` (`name: juli-web`, Next.js 14, full `src/app` dashboard) **is the real deployed frontend** (served by `systemd/juli-web`, built by CI `frontend` job + `deploy-release.sh`).
- `apps/{dashboard,demo,landing,mobile}` and `packages/*` are empty scaffolds (README + trivial `package.json`).
- **Recommendation:** `git mv web apps/dashboard`; delete the scaffold `apps/dashboard` it replaces; delete `apps/demo`, `apps/landing` unless a marketing split is wanted (confirm); `apps/mobile` duplicates `ios/` → flag for deletion.
- Inventory: duplicate `node_modules` (root + `web/`), tracked `artifacts/`/`screenshots/`, untracked `coverage/`, current `infra/` + `docs/` trees.

## Phase 1 — Backend `src/` layout + `pyproject.toml`
**Moves (`git mv`):**

| From | To |
|---|---|
| `backend/{api,ai,database,workers,integrations}` | `backend/src/juli_backend/{api,ai,database,workers,integrations}` |
| `backend/runtime.py`, `backend/__init__.py` | `backend/src/juli_backend/{runtime.py,__init__.py}` |

**Create** `backend/pyproject.toml` (PEP 621 + **Hatchling** — no `uv.lock` present). Centralize Ruff, MyPy, Pytest, coverage, build backend, and deps. Emit a root `requirements.txt` (CI/deploy read it directly).

**Reference-update checklist (grep each old token):**
- [ ] `backend.` → `juli_backend.` across ~143 `.py` files (imports + string refs)
- [ ] `alembic.ini`: `script_location` → `backend/src/juli_backend/database/migrations`; verify `prepend_sys_path`
- [ ] `backend/.../database/migrations/env.py`: imports `backend.database.*`, `backend.runtime`
- [ ] `.github/workflows/pr.yml`: `mypy backend/`, `bandit -r backend/`, `--cov=backend`, `pip install -r requirements.txt`
- [ ] `.github/workflows/release.yml`: `mypy backend/`
- [ ] **`infra/systemd/juli-api.service`**: `uvicorn backend.api.api.main:app` → `juli_backend.api.api.main:app`
- [ ] **`infra/scripts/deploy-release.sh`**: add `pip install -e .` (or `-e backend`) after venv create — *flagged deploy change*
- [ ] any other `backend/` path refs in scripts/docs

**Gate:** clean venv `pip install -e ".[dev]"` succeeds; `pytest` == baseline; alembic up/down/up green.
**Flag in PR:** the systemd + deploy-release.sh edits are required for prod import under `src/` layout.

## Phase 2 — Backend domain reorg (highest risk)
Target (prompt): `api/{routes,middleware,dependencies}`, `services/`, `repositories/`, `models/`, `schemas/`, `integrations/{tiktok,openai,claude,invoice}`, `ai/{forecasting,ranking,recommendations}`, `workers/`, `core/{config,security,logging}`, `database/`.

- **Produce a per-file from→to inventory and review it before moving anything** (target conflicts with current DDD layout).
- Flatten `backend/src/juli_backend/api/api/` → `api/`.
- Do **not** split route/DB-mixed files into service/repo layers as drive-by work — move to nearest home, flag follow-ups.
- Do **not** scaffold empty `integrations/{openai,claude,invoice}` if no code exists yet.
- Add `__init__.py` re-exports to preserve call sites.
- **Gate:** `pytest` == baseline.

## Phase 3 — Frontend consolidation + pnpm decommission
- `git mv web apps/dashboard`; delete the scaffold `apps/dashboard` it replaces (+ `apps/demo`, `apps/landing`, `apps/mobile` per P0 confirmation).
- **Decommission pnpm/turbo (keep npm):** remove `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `turbo.json`, `packageManager: pnpm@9.15.4` + `turbo` devDep + `workspace:baseline` script from root `package.json`, pnpm-specific `.npmrc` keys; remove empty `packages/*` scaffolds (unless one becomes real). Keep root `package.json` for `playwright`/`screenshots` scripts under plain npm.

**Reference-update checklist:**
- [ ] CI `frontend` job: `working-directory: web` → `apps/dashboard`; `cache-dependency-path: web/package-lock.json`
- [ ] `infra/systemd/juli-web.service`: `WorkingDirectory=/root/releases/current/web` → `.../apps/dashboard`
- [ ] `infra/scripts/deploy-release.sh`: `web/.env.production` + build/copy paths
- [ ] `infra/nginx/*.conf`: verify upstream still `127.0.0.1:3000` (unchanged, confirm)
- [ ] root `package.json` scripts referencing `juli-web`/turbo
- [ ] `web/MODULE.md`, docs referencing `web/`

**Gate:** local `npm run build` from `apps/dashboard` succeeds; CI frontend job green.

## Phase 4 — Infra reorg (VPS-native only)

| From | To |
|---|---|
| `infra/nginx/` | `infra/nginx/` |
| `infra/systemd/` | `infra/systemd/` |
| `infra/deploy/*.sh` | `infra/scripts/` |
| `infra/scripts/aws/iam-policy-secrets-reader.json` | `infra/scripts/aws/` (secrets-only, not an IaC tree) |
| `infra/scripts/env/` | `infra/scripts/env/` (or keep adjacent to scripts that read it — confirm) |

Do **not** create `infra/docker/`, `infra/terraform/`, `infra/aws/` IaC.
**Reference-update checklist:** systemd `ExecStartPre=/root/Juli-AI-v2/infra/scripts/fetch-secrets.sh`, `EnvironmentFile` notes; `release.yml`/`rollback.yml` script paths; runbooks referencing `infra/deploy/…`.

## Phase 5 — Docs reorg
Into `docs/{architecture,api,deployment,runbooks,adr,product,ml,integrations}`.
Suggested mapping: `docs/decisions/` → `adr/`; `docs/tiktok_api/` → `integrations/`; `docs/ci/` + `*-runbook.md` → `deployment/` + `runbooks/`; `docs/phases/` + `docs/features/` → `product/`; `docs/ml_layer.md` etc. → `ml/`. **Ask** on anything that doesn't cleanly fit. Update internal cross-links after moves.

## Phase 6 — Root cleanup
- `.gitignore`: add **`coverage/`** and **`web/coverage/`** only. Do **not** ignore `artifacts/` (ADR-003) or `screenshots/` without an explicit decision.
- Confirm final root layout; ensure pnpm/turbo scaffolds removed (Phase 3).
- Update root `README.md`: backend `python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`; frontend `cd apps/dashboard && npm ci && npm run dev`.

---

## Per-phase reporting template
```
### Phase N report
- Moves (from → to): <table>
- Tests before: <pass/fail/cov>   after: <pass/fail/cov>   diff: <none/new failures>
- References updated: <files + what changed>
- Flagged / deferred: <ambiguities not guessed at>
```

## Open items to confirm during execution
- P0: keep or delete `apps/demo` / `apps/landing` (marketing split?) and `apps/mobile` (dup of `ios/`).
- P2: destination of `database/models.py` + `repos.py` (`models/`+`repositories/` vs stay); confirm re-export surface.
- P4: whether `infra/scripts/env/` moves under `scripts/` or stays adjacent.
- P5: any doc that resists the 8 categories.
