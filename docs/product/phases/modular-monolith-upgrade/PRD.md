# PRD: Modular Monolith Upgrade

> **Canonical docs:** [`MODULES.md`](../../../architecture/MODULES.md) ·
> [`map.md`](../../../architecture/map.md) ·
> boundary audit [`modular-monolith-boundary-audit.html`](../../../handoffs/modular-monolith-boundary-audit.html) ·
> runtime ownership data [`modular-monolith-audit-data.json`](../../../handoffs/modular-monolith-audit-data.json).
>
> **Parent issue:** [#550](https://github.com/thienphung00/Juli-AI/issues/550) — filed via
> `to-prd` from architecture boundary audit (2026-07-28).
> Child slices via `to-issues` after parent acceptance.

## Assumptions

- Static-import audit + runtime ownership map in the handoff artifacts are authoritative for current as-built debt.
- Goal is a **hard-shell modular monolith** (~9/10), **not** microservices.
- Work proceeds without blocking active Phase 2.10 / 2.11 product slices; upgrade issues can land in parallel when path-disjoint.
- Default tests cover import-linter contracts, ownership registry drift, and cycle absence — not live TikTok/Supabase calls.
- Proposed deep modules below match Architect intent unless rejected at parent acceptance.

## Problem Statement

Engineers and agents cannot trust module boundaries. Documentation says “modular
monolith,” but runtime reality is softer: API routes reach into service and TikTok
internals, all tables live in one shared models bag, Redis has only a single
`ratelimit:*` convention with no registry, Celery wiring creates import cycles with
domain packages, and nothing fails a PR when a forbidden dependency appears.
That slows parallel work, hides ownership of tables/tasks/keys/integrations, and
makes every refactor a guess. We need an enforceable upgrade path to deep modules
with clear runtime ownership — without splitting into microservices.

## Solution

Ship a **Modular Monolith Upgrade**: define and enforce ownership for each
database table, Celery task, Redis key namespace, and external integration; harden
public module facades; break import cycles; split god models/repos by domain; make
API routes thin adapters; and add PR-blocking boundary CI (import contract +
ownership registry). Keep a single deployable backend. Target architecture score
~9/10 as a modular monolith.

## User Stories

Roles use the closed `to-prd` vocabulary (Architect, Backend Engineer, Platform
Engineer, QA Engineer, Product Manager, Meta/Executor/Review Agent).

1. As an Architect, I want every database table to name one owning module, so that schema changes have a clear steward.
2. As a Backend Engineer, I want only the owning module to write a table (others read via published contracts), so that write contention and surprise mutations stop.
3. As a Backend Engineer, I want dual-writer tables (`shops`, `tiktok_credentials`) collapsed to one OAuth/auth owner, so that token/shop provisioning is not forked.
4. As a Meta Agent, I want a machine-readable ownership registry, so that implementation plans do not invent stewards.
5. As a Backend Engineer, I want each Celery task’s logical owner to be the domain module (not the workers package), so that task semantics stay with the business capability.
6. As a Backend Engineer, I want Celery entrypoints to remain thin wrappers, so that HTTP never runs scoring or tools inline.
7. As a Backend Engineer, I want domain modules to depend on a dispatcher port — not import `workers.tasks` — so that action_cards/execution ↔ workers cycles disappear.
8. As a Platform Engineer, I want every Redis key pattern registered to a module namespace, so that new caches cannot collide with `ratelimit:*` or Celery keys.
9. As a Backend Engineer, I want a documented `juli:<module>:` key prefix convention, so that future KPI/precompute caches have a home.
10. As a Backend Engineer, I want TikTok HTTP client ownership isolated in the TikTok integration module, so that signing/rate-limit internals stay leaf-only.
11. As a Backend Engineer, I want Supabase JWT verification owned only by Auth & Security, so that identity checks are not reimplemented in routes.
12. As a Backend Engineer, I want Supabase Postgres session/migration ownership in the Database module, so that connection and Alembic policy stay centralized while table schemas are domain-owned.
13. As a Backend Engineer, I want package-root public APIs for every business module, so that deep submodule imports are forbidden by CI.
14. As a Backend Engineer, I want the TikTok integration module to expose a real package facade (not docs-only), so that callers stop importing leaf internals directly.
15. As a Backend Engineer, I want each router to call one owning application service, so that webhook/auth routes stop assembling ETL + TikTok + DB internals inline.
16. As a Backend Engineer, I want models and repositories split by domain ownership, so that the god models/repos files stop being everyone’s dependency.
17. As a Review Agent, I want import-linter (or equivalent) failing on PR, so that forbidden edges cannot merge.
18. As a Meta Agent, I want nightly architecture audits to become PR gates for cycles and ownership drift, so that debt does not only show up after merge.
19. As a Product Manager, I want upgrade slices to be path-disjoint from Phase 2.10 delivery when possible, so that Demo/API shipping is not blocked.
20. As a Platform Engineer, I want a published map of who owns TikTok, Supabase, Redis, and Celery at runtime, so that incidents route to the right module owner.
21. As an Architect, I want Billing reserved as its own future module slot (no premature package dump into shared bags), so that payments do not land inside unrelated modules.
22. As a QA Engineer, I want contract tests that prove a non-owner cannot write a protected table in unit scope, so that ownership is behaviorally real.
23. As a Platform Engineer, I want the upgrade to keep one backend deployable, so that we do not adopt microservices ops cost.
24. As an Architect, I want the post-upgrade score rationale documented against the boundary audit, so that “9/10 modular monolith” is falsifiable.
25. As a Backend Engineer, I want MODULE.md public surfaces to match the enforced facade, so that docs and CI do not diverge.
26. As an Executor Agent, I want clear “do not import” lists per module in the registry, so that TDD implementations stay inside the shell.
27. As a Backend Engineer, I want ETL to remain the sole writer for commerce ingest tables, so that polling and webhooks only hand off records.
28. As a Backend Engineer, I want action_cards/scoring to own decision persistence, so that recommendations and action_cards write paths stop competing.
29. As a Backend Engineer, I want operations to consume execution outcomes via a one-way contract, so that execution↔operations cycles are removed.
30. As a Backend Engineer, I want token encryption and credential resolution to stay in Auth/Database shared primitives, so that secrets handling is not copied into feature modules.
31. As a Review Agent, I want every PR to answer “does it work / belong / create forbidden deps / stay extractable?”, so that merge criteria match modular-monolith intent.
32. As a Platform Engineer, I want PR checks to gate architecture (imports, cycles, ownership) not only compile+tests, so that green builds cannot silently erode boundaries.
33. As a QA Engineer, I want unit tests to stay inside one module’s public surface, so that unit suites do not depend on other modules’ internals.
34. As a QA Engineer, I want integration tests to exercise only public interfaces between modules, so that collaboration is proven without coupling to private files.
35. As a QA Engineer, I want E2E tests to validate complete user workflows from the outside, so that module collaboration is verified without caring about internal layout.

## Implementation Decisions

### Deep modules (by responsibility)

1. **Ownership Registry** — Single machine-readable registry of table owners, Celery
   task owners, Redis key namespaces, and external integration owners; CI fails on
   drift vs code.
2. **Boundary Contract (import-linter)** — Allowed dependency matrix for business
   modules; ban deep submodule imports across packages; PR-blocking.
3. **Module Facades** — Every business module exposes a stable public surface;
   TikTok integration gains a real package facade; API becomes adapters only.
4. **Domain Persistence Split** — Split shared models/repos into domain-owned
   persistence packages (or clearly owned submodules) while keeping one Postgres
   database and shared session factory.
5. **Async Ports** — Dispatcher ports for Celery inside Action Cards and Execution;
   workers package only binds Celery implementations (breaks cycles).
6. **Runtime Namespace Policy** — Redis key prefix standard `juli:<module>:…`;
   register `ratelimit:*` under TikTok Integration; document Celery broker key space.
7. **Integration Ownership Map** — TikTok (client vs OAuth/webhook services),
   Supabase Postgres (Database), Supabase Auth JWT (Auth), Redis (shared infra +
   named consumers), Observability vendors (DOCP when landed).

### Technical clarifications

- No microservices, no new deployables, no polyglot DB split in this PRD.
- Prefer incremental strangler moves (facade + linter first; file splits next).
- Dual writers on `shops` / `tiktok_credentials` resolve to **Auth & TikTok OAuth
  services** as one stewarded capability (collapse `core/security` OAuth
  orchestration vs `services/tiktok` stores behind one facade).
- `recommendations` vs `action_cards` write paths: Action Cards / Scoring owns
  decision persistence going forward; legacy recommendation create-via-API is
  deprecated or routed through the same owner.
- Workers package owns Celery app wiring only; task names remain
  `juli_backend.*` but logical owners are domain modules.
- Billing remains out of scope to implement; registry may reserve a placeholder.

### Testing Decisions

- Good tests assert external behavior: forbidden import edges fail; non-owner write
  helpers are not part of public facades; dispatcher ports accept fakes; ownership
  registry validates completeness for all `__tablename__`s and `@task` names.
- Prior art: `agent-runtime/scripts/ci/audit_cycles.py`, `audit_module_drift.py`,
  unit tests under `tests/unit/` for dispatchers and TikTok rate limiter;
  existing two-tier CI in `.github/workflows/pr.yml` (fast PR + full merge_group).
- Modules under test: Ownership Registry, Boundary Contract, Module Facades,
  Async Ports, Domain Persistence Split (smoke that apps still boot and key
  repos resolve).
- **Unit tests** verify one module in isolation and must not import other modules’
  internals (only public facades / fakes).
- **Integration tests** verify modules work together through public interfaces only.
- **E2E tests** validate complete user workflows from the outside (module
  collaboration without asserting internal file layout).

### CI & PR handling (architecture-aware)

Moving to a modular monolith changes CI focus from only “Does it work?” to also
“Does it respect the architecture?”

#### Check matrix

| Check | Purpose | Cross-module relation |
|-------|---------|------------------------|
| Formatting (ruff format, prettier) | Consistent code style | None |
| Linting (ruff, eslint) | Catch code quality issues | Indirect |
| Type checking (mypy, tsc) | Ensure interfaces match | Detects broken module contracts |
| Unit tests | Verify one module in isolation | Must not depend on other modules’ internals |
| Integration tests | Verify modules work together | Tests public interfaces between modules |
| Import boundary check (import-linter) | Prevent forbidden imports | **Core architectural check** |
| Dependency cycle check | Prevent circular module dependencies | Ensures clean dependency graph |
| Architecture rules | Verify ownership (routes, models, services, tables, tasks, Redis keys, integrations) | Prevents coupling |
| Build | Ensure application compiles/packages | None |
| End-to-end tests | Validate complete user workflows | Verifies module collaboration from the outside |

#### CI mindset

Previously:

```
Code → Compiles? → Tests pass? → Merge
```

Now:

```
Code
  → Compiles?
  → Tests pass?
  → No forbidden imports?
  → No dependency cycles?
  → Module boundaries / ownership respected?
  → Merge
```

Wire this into the existing two-tier model:

- **PR (fast):** formatting/lint/type as today, plus **required** import-linter +
  cycle check + ownership-registry drift on backend-touching PRs (fail the PR,
  not `continue-on-error`).
- **Merge Queue (full):** keep full unit/integration (and E2E where already
  required); re-run architecture gates; do not treat nightly
  `architecture-audit.yml` alone as sufficient.

#### PR review — four questions

Every PR (human or agent) must answer:

1. **Does it work?** — Tests (unit / integration / E2E as applicable).
2. **Does it belong in this module?** — Ownership (routes, models, services,
   tables, tasks, Redis keys, integrations).
3. **Did it create forbidden dependencies?** — Import-linter + cycle check.
4. **Can this module still be extracted later?** — Architecture (deep module /
   facade discipline; no new god-file or cross-module internal reach-through).

A green “tests only” PR that fails any of questions 2–4 is not merge-ready.

## Out of Scope

- Extracting microservices or separate databases per module.
- Implementing Billing/payments.
- Rewriting frontend apps or iOS clients.
- Replacing Supabase or Celery.
- Full Observability DOCP build (owned by Phase 2.11 PRD).
- Kafka/event-bus introduction beyond existing handoff contracts.
- Large product feature work (Demo 2.10, Landing/Sign-in) except where boundary
  fixes are required for those slices.

## Further Notes

- Risks: large mechanical moves can conflict with parallel feature PRs — sequence
  facade/linter before file moves; use path-disjoint issues.
- Rollout: (1) registry + linter warn→error on PR, (2) facades + API thinning,
  (3) break Celery cycles, (4) split models/repos, (5) Redis namespace policy for
  new keys, (6) dual-writer consolidation, (7) promote architecture gates from
  nightly soft audit to required `pr.yml` / merge_group checks.
- Observability: emit a CI artifact summarizing boundary violations (reuse
  architecture-audit artifact paths); surface the four PR-review questions in
  PR template / agent review checklist.
- Follow-up: `to-issues` tracer-bullet slices after parent acceptance; update
  MODULES.md / map.md when ownership becomes as-built; update `pr.yml` status
  checks so Merge Queue requires architecture jobs.
- Score target: move from audit **5.5/10** toward **~9/10** modular monolith by
  making ownership and import contracts enforceable.
