# Repository Audit — Phase 0

**Date:** 2026-07-10  
**Status:** Investigation complete — no code changes in this phase  
**Gates:** Frontend consolidation (Phase 3), agent-runtime consolidation (proposed Phase 7)

This report resolves ambiguity around `web/` vs `apps/`, inventories scattered
folders, documents production deploy paths, and maps the agent optimization loop
so a later phase can consolidate it into one tree.

---

## 1. `web/` — what it actually is

| Property | Finding |
|----------|---------|
| **Package name** | `juli-web` (`web/package.json`) |
| **Framework** | Next.js 14, React 18, Tailwind, shadcn |
| **Scripts** | `dev`, `build`, `build:review` (`NEXT_PUBLIC_UI_ONLY=1`), `start`, `lint`, `type-check`, `test` (Jest) |
| **Routes** | Seller dashboard only — `home`, `decisions`, `orders`, `products`, `creators`, `recommendations`, `ai-chat`, `operation`, `login`, `mode-select`, `trends`, plus legacy routes (`alerts`, `inventory`, `livestreams`) still present in tree |
| **Marketing site?** | **No.** No landing/marketing pages. `apps/landing/README.md` confirms `app-juli.com` temporarily hosts this dashboard until a future landing app exists. |
| **MODULE.md** | `web/MODULE.md` documents the full seller UI surface (8k+ chars). |

**Verdict:** `web/` is the **only real, deployed frontend**. It is a single Next.js
seller dashboard — not a monorepo of dashboard + marketing.

### Production deploy path (today)

| Surface | Path / command |
|---------|----------------|
| **CI** (`.github/workflows/pr.yml` `frontend` job) | `working-directory: web`; `npm ci`; lint / type-check / test / build |
| **CD** (`release.yml` → `infra/scripts/deploy-release.sh`) | Copies `/etc/juli/web.env` → `web/.env.production`; `npm run build` in `web/` |
| **systemd** (`infra/systemd/juli-web.service`) | `WorkingDirectory=/root/releases/current/web`; `npm run start -- --port 3000` |
| **Nginx** (`infra/nginx/app-juli.com.conf`) | Proxies `app-juli.com` → `127.0.0.1:3000` (upstream `juli_web`) |

Nginx comments still say "legacy web/" — accurate; this is the App Review / production
frontend on the single VPS.

---

## 2. `apps/` — scaffold inventory

| Subfolder | Contents | Runtime code? |
|-----------|----------|---------------|
| `apps/dashboard` | `README.md` + `package.json` (`@juli/app-dashboard`, version `0.0.0`) | **No** — README says "Scaffold only — runtime code currently in `web/`" |
| `apps/landing` | `README.md` + `package.json` | **No** — future marketing site for `app-juli.com` |
| `apps/demo` | `README.md` + `package.json` | **No** |
| `apps/mobile` | `README.md` + `package.json` | **No** — duplicates native `ios/` (out of restructure scope) |

`apps/README.md` exists at parent level.

**Verdict:** `apps/*` is **scaffolding only**. No `src/`, no build output, no deploy
references. All four subfolders are placeholders for a future multi-app layout that
was never populated.

---

## 3. `packages/` — shared JS scaffolds

Seven workspace packages under `packages/` (`api-client`, `icons`, `illustrations`,
`theme`, `types`, `ui`, `utils`). Each contains only `README.md` + `package.json`
(2 files each). **Not imported by `web/`** in any meaningful way today.

Root declares pnpm workspaces (`pnpm-workspace.yaml` lists `web`, `apps/*`,
`packages/*`) and `turbo.json`, but CI, systemd, and deploy all use **npm inside
`web/`** with `web/package-lock.json`.

---

## 4. Frontend recommendation (gates Phase 3)

**Recommendation: Option A — `web/` is the real app; move it under `apps/`.**

| Action | Detail |
|--------|--------|
| Move | `git mv web apps/dashboard` (replace the empty scaffold) |
| Delete | `apps/demo`, `apps/landing` scaffolds **unless** you want to keep landing as a named placeholder for Phase 3 product work |
| Delete | `apps/mobile` (duplicates `ios/`) |
| Delete | empty `packages/*` scaffolds when decommissioning pnpm (locked decision) |
| Decommission | `pnpm-workspace.yaml`, `pnpm-lock.yaml`, `turbo.json`, root pnpm `packageManager` field |
| Keep | npm in `apps/dashboard` with its `package-lock.json` |

**Do not split** `web/` into dashboard + landing — it contains only dashboard routes.
A future marketing site should be a **new** `apps/landing` implementation, not a split
of the current tree.

**Naming note:** `apps/dashboard/README.md` targets `dashboard.app-juli.com`, but
production Nginx today serves `app-juli.com`. That domain mismatch is a product/deploy
decision outside this restructure; the folder name `dashboard` still matches the app's
actual content.

---

## 5. Duplicate `node_modules` and build artifacts

| Path | Size (local) | In git? | Depends on path? |
|------|--------------|---------|------------------|
| `node_modules/` (root) | ~537 MB | No (`.gitignore`) | Root `package.json` — Playwright + turbo only |
| `web/node_modules/` | ~40 KB (likely hoisted/partial) | No | `web/package.json` — real frontend deps |
| `web/.next/` | varies | No | Next build output |
| `web/coverage/` | present locally | No | Jest coverage |
| `coverage/` (root) | absent | No | — |
| `web/tsconfig.tsbuildinfo` | 136 KB | **Yes (tracked)** | TypeScript incremental — consider gitignoring |

After Phase 3, root `node_modules/` shrinks to Playwright-only (no turbo/pnpm).

---

## 6. `artifacts/`, `screenshots/`, `coverage/`

### `artifacts/` (agent runtime — 338 tracked files)

| Subdir | Tracked files | Purpose |
|--------|---------------|---------|
| `reviews/` | 83 | Review Agent output; CI gate (`pr.yml`) |
| `validation/` | 44 | Validate output; CI gate |
| `implementations/` | 52 | Executor output |
| `optimization/` | 152 | Meta Agent harness tuning proposals |
| `benchmarks/` | 6 | Benchmark run reports |
| `releases/` | 1 | Ship / release metadata |
| `runtime/raw/`, `runtime/logs/` | gitignored | Verbose session telemetry |

**Commit policy:** Intentionally versioned per ADR-003 and `artifacts/README.md`.
CI and Meta Agent read these across sessions. **Do not blanket-gitignore.**

### `screenshots/` (39 tracked files)

UI reference captures under `screenshots/dashboard/` (desktop/tablet/mobile variants).
Used by design/QA workflows (`scripts/capture-ui-screenshots.mjs`). **Intentionally
tracked** — do not gitignore without an explicit decision.

### `coverage/`

Not tracked. Safe to add to `.gitignore` in Phase 6.

---

## 7. `infra/` inventory

```
infra/
  README.md
  ci/README.md              # pointer doc only
  deploy/
    README.md, *-runbook.md (7 runbooks)
    *.sh (9 deploy/provision/smoke scripts)
    aws/iam-policy-secrets-reader.json   # secrets reader policy only — not compute IaC
    env/api.env.example, web.env.example
    nginx/app-juli.com.conf, api.app-juli.com.conf
    systemd/juli-{api,web,secrets-refresh}.{service,timer}
```

**CD exists today** (contrary to "no CD" assumption): `release.yml` SSH-deploys via
`deploy-release.sh`; `rollback.yml` calls `rollback-release.sh`. Phase 4 reorg must
update these paths.

**No Docker, Terraform, or K8s** in this tree. Postgres/Redis images appear only
as **CI service containers** in `pr.yml` — not production deploy.

---

## 8. `docs/` inventory (top level)

| Path | Role |
|------|------|
| `architecture/` | System + agent-runtime architecture (incl. this audit) |
| `benchmarks/agent-runtime/` | Benchmark task fixtures (types A–D) |
| `ci/` | CI implementation guide, troubleshooting |
| `data-models/` | Canonical entities |
| `decisions/` | ADRs (→ `adr/` in Phase 5) |
| `design/`, `visual_layer.md` | Product/design |
| `features/` | Legacy feature specs (mostly archived to `handoffs/archive/`) |
| `handoffs/` | Active + archived session handoffs |
| `ml_layer.md`, `phases/` | ML + phase tracking |
| `schemas/agent-runtime/` | JSON Schema for runtime artifacts |
| `templates/` | Handoff templates |
| `tiktok_api/`, `tiktok_platform/` | Integration docs |
| `execution_layer.md`, `system-design.md` | Canonical system docs |

Phase 5 reorg maps these into the target eight-category tree. Agent-runtime-specific
docs are candidates to move under a consolidated `agent-runtime/` folder (see §10).

---

## 9. Backend packaging note (gates Phase 1)

| Property | Current state |
|----------|---------------|
| Layout | Flat: `backend/{api,ai,database,workers,integrations}/` + `backend/runtime.py` |
| Import style | `from backend.<pkg>...` (**143** `.py` files); not `from api...` |
| Packaging | Root `requirements.txt` only; **no** `pyproject.toml` or `uv.lock` |
| Alembic | Root `alembic.ini` → `backend/database/migrations/`; `env.py` imports `backend.database.*` |
| Prod entry | `uvicorn backend.api.api.main:app` (systemd); deploy does `pip install -r requirements.txt` only |
| Tests | `pytest tests/` with `--cov=backend` |

Phase 1 must add `pip install -e .` to deploy and rewrite the systemd module path when
moving to `backend/src/juli_backend/`.

**Name collision warning:** `backend/ai/artifacts/` is **ML model artifact code**
(publish, schema, promotion) — not agent runtime. Do not consolidate it with the
agent optimization loop.

---

## 10. Agent optimization loop — scatter map

### What the loop does

The Agent Runtime implements a closed feedback cycle:

```
Executor → implementation-artifact
        → Review Agent → review-artifact
        → Validate → validation-artifact
        → Meta Agent (Focus) → harness-optimization-artifact
        → harness_config.py / agent-runtime.config.yml (auto-apply eligible fields)
        → benchmark reruns → benchmarks/*.json
```

Canonical architecture: `docs/architecture/agent-runtime.md`. Policy: ADR-003.

### Files by location today

| Location | Files | Role |
|----------|-------|------|
| **Root config** | `agent-runtime.config.yml`, `harness-editable.yml`, `harness-safelist.yml` | Harness behavior, editable-field allowlist, write denylist |
| **`done.md`** (root) | 1 ephemeral per-issue file | Validate gate input (`check_done_md.py`) — working file, not loop infrastructure |
| **`scripts/`** | `build_runtime.py`, `harness_config.py`, `harness_optimizer.py` | Build effective runtime; safe config R/W; consume artifacts → propose/apply optimizations |
| **`scripts/ci/`** | 11 files (`common.py`, 4× `generate_*`, `normalize_review_artifacts.py`, 4× `audit_*`, `ml_thresholds.py`) | Artifact generators, path constants (`REVIEWS_DIR`, etc.), nightly audits |
| **`scripts/validate/`** | 13 `check_*.py` gates | Deterministic validate phase (`pr.yml` runs all on issue branches) |
| **`artifacts/`** | 338 tracked JSON (+ README) | Persistent memory: reviews, validation, implementations, optimization, benchmarks, releases |
| **`docs/architecture/`** | 4× `agent-runtime*.md` | Architecture, artifacts, benchmarks, migration |
| **`docs/benchmarks/agent-runtime/`** | 5 task specs (types A–D) | Benchmark fixtures |
| **`docs/schemas/agent-runtime/`** | 6 JSON Schema files | Artifact + config schemas |
| **`docs/handoffs/context-plan-template.md`** | 1 | Harness-editable target (context budget section) |
| **`tests/unit/`** | `test_harness_config.py`, `test_harness_runtime.py`, `test_implementation_artifact.py` | Unit tests for harness tooling |
| **Consumers (stay outside)** | `.cursor/skills/{focus,validate,ship}/`, `.github/workflows/{pr,release,architecture-audit}.yml`, `docs/ci/implementation-guide.md`, ADR-003 | Reference artifact paths; updated in consolidation phase |

**Total loop-adjacent tracked files:** ~390 (338 artifacts + ~52 config/scripts/docs/tests).

### Scatter problem

The loop's **config, scripts, artifacts, docs, and schemas** live in five separate
root-level trees. Any path change requires grep across CI workflows, 13 validate
scripts, 3 harness scripts, `common.py` constants, skills, and 338 committed JSON
files. This is the highest reference-churn surface in the repo after backend import
rewrites.

### Recommendation: consolidate under `agent-runtime/`

Create a single top-level folder. **Do not** fold in `backend/ai/artifacts/` (ML domain).

```
agent-runtime/
  README.md                         # merge artifacts/README.md + entry-point doc
  config/
    agent-runtime.config.yml        # ← root
    harness-editable.yml            # ← root
    harness-safelist.yml            # ← root
  artifacts/                        # ← root artifacts/ (entire tree)
    reviews/
    validation/
    implementations/
    optimization/
    benchmarks/
    releases/
  scripts/
    build_runtime.py                # ← scripts/
    harness_config.py
    harness_optimizer.py
    ci/                             # ← scripts/ci/
    validate/                       # ← scripts/validate/
  docs/
    agent-runtime.md                # ← docs/architecture/agent-runtime.md
    agent-runtime-artifacts.md
    agent-runtime-benchmarks.md
    agent-runtime-migration.md
    benchmarks/                     # ← docs/benchmarks/agent-runtime/
    schemas/                        # ← docs/schemas/agent-runtime/
  templates/
    context-plan-template.md        # ← docs/handoffs/ (harness-editable target)
```

**Keep outside `agent-runtime/` (consumers, not loop machinery):**

| Path | Reason |
|------|--------|
| `.cursor/skills/` | Skills governance — referenced by loop, not part of it |
| `.github/workflows/` | CI/CD entry points — update paths, don't move |
| `docs/decisions/003-*.md` | ADR stays in `adr/` after Phase 5 |
| `docs/ci/implementation-guide.md` | General CI docs — update cross-links |
| `done.md` | Ephemeral per-issue working file at repo root during active work |
| `backend/ai/artifacts/` | ML model artifacts — different domain |

### Reference-update blast radius (Phase 7 checklist)

- [ ] `scripts/ci/common.py` — `REVIEWS_DIR`, `VALIDATION_DIR`, `IMPLEMENTATIONS_DIR`, `OPTIMIZATION_DIR`, `RELEASES_DIR`, `DONE_MD`
- [ ] `harness_optimizer.py`, `harness_config.py`, `build_runtime.py` — `DEFAULT_CONFIG`, `REPO_ROOT` relatives
- [ ] `harness-editable.yml` — `file:` paths for config + template + benchmarks doc
- [ ] `harness-safelist.yml` — `path_patterns` for `docs/architecture/**` exception
- [ ] `.github/workflows/pr.yml` — `artifacts/validation/...` upload path; validate script invocations
- [ ] `.github/workflows/architecture-audit.yml` — audit output paths
- [ ] `.github/workflows/release.yml` — release artifact path
- [ ] All 338 committed artifact JSON files — **only if** paths are embedded inside JSON (grep `artifacts/` in JSON values)
- [ ] `.cursor/skills/standalone/focus/SKILL.md` — artifact path table
- [ ] `.cursor/skills/standalone/validate/`, `ship/` — artifact paths
- [ ] `docs/ci/implementation-guide.md`, `docs/architecture/map.md` cross-links
- [ ] `tests/unit/test_harness_*.py`, `test_implementation_artifact.py`
- [ ] `agent-runtime.config.yml` — `routing.domain_mappings` paths (currently `web`, `backend/...`)

### Suggested phase placement

**Phase 7 — Agent runtime consolidation** (`refactor/agent-runtime-consolidation`).

Run after Phase 6 (root cleanup) or in parallel with Phase 5 (docs overlap). Do **not**
combine with Phase 1 (backend import churn) or Phase 3 (frontend path churn) — three
simultaneous path rewrites is too much for one maintainer.

**Gate:** full pytest including `test_harness_*`; run `python scripts/harness_optimizer.py propose --issue <n>` against a fixture issue; `pr.yml` validate-artifacts job green on a test branch.

---

## 11. Open questions (do not guess)

| # | Question | Blocks |
|---|----------|--------|
| 1 | Delete `apps/landing` scaffold or keep as named placeholder for future marketing app? | Phase 3 | **Delete** (locked) |
| 2 | Delete `apps/mobile` scaffold (duplicates `ios/`)? | Phase 3 | **Delete** (locked) |
| 3 | Move `done.md` into `agent-runtime/templates/` or keep at root? | Phase 7 | **Recommend: keep at root** — ephemeral per-issue working file; validate gate reads it there today |
| 4 | Leave stub cross-links at old `artifacts/` path during Phase 7, or big-bang move? | Phase 7 | **Recommend: big-bang** — solo maintainer; one grep sweep beats maintaining stubs |
| 5 | `docs/ci/` — general CI docs vs fold agent-runtime sections into `agent-runtime/docs/`? | Phase 5 / 7 |

---

## 12. Phase 0 exit criteria

- [x] `web/` vs `apps/` resolved → move `web` to `apps/dashboard`
- [x] `packages/`, pnpm, turbo inventoried → decommission in Phase 3
- [x] `artifacts/`, `screenshots/`, `coverage/` inventoried → selective gitignore only
- [x] `infra/`, `docs/` inventoried
- [x] Agent optimization loop mapped → consolidate to `agent-runtime/` in Phase 7
- [x] No code changes made in Phase 0

**Next:** Phase 1 (`refactor/backend-src-layout`) per [`docs/handoffs/repo-restructure-plan.md`](../handoffs/repo-restructure-plan.md).
