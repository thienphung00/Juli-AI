A/B Experiment Plan — KiotViet API Integration

Objective

Evaluate two different implementation strategies for integrating the KiotViet API into our system.

The experiment will:

1. Use the existing translated KiotViet API documentation in `/docs/kiotviet/`.
2. Use the existing skill sets in `.cursor/skills_A/` and `.cursor/skills_B/` — no new skills are created.
3. Run both implementations in parallel on separate git branches.
4. Compare architecture quality, maintainability, implementation speed, and output correctness.

Source Documentation

The KiotViet API docs have already been translated and normalized into `/docs/kiotviet/`:

- `authentication.md`
- `rate_limits.md`
- `products.md`
- `orders.md`
- `customers.md`
- `webhooks.md`
- `pagination.md`
- `error_handling.md`
- `api_examples.md`

Original sources:

- https://www.kiotviet.vn/huong-dan-su-dung-kiotviet/retail-ket-noi-api/public-api/
- https://www.kiotviet.vn/huong-dan-su-dung-kiotviet/retail-ket-noi-api/ket-noi-api/

Phase 1 — Documentation Translation (COMPLETED)

The Vietnamese KiotViet API docs have been translated into structured English engineering documentation in `/docs/kiotviet/`. This phase is done.

Phase 2 — Parallel Implementation Using Existing Skills

Goal

Run an A/B implementation experiment where each agent builds the KiotViet API Layer independently, guided by its own skill set and the shared docs.

Existing Skill Sets

Both skill folders contain the same five skills, but with different philosophies and naming:

`.cursor/skills_A/` — Approach A

| Skill | Internal Name | Role |
|-------|--------------|------|
| `discover/SKILL.md` | Solution Discovery | Turn ideas into implementable specs |
| `focus/SKILL.md` | Context Orchestrator | Manage what context gets loaded |
| `build-ai/SKILL.md` | AI Platform | Centralized AI engineering standards |
| `review/SKILL.md` | Engineering Standards | Validate code quality, suggest patches |
| `ship/SKILL.md` | Delivery Pipeline | CI/CD, git workflow, deployment planning |

`.cursor/skills_B/` — Approach B

| Skill | Internal Name | Role |
|-------|--------------|------|
| `discover/SKILL.md` | Blueprint | Turn ideas into implementable specs |
| `focus/SKILL.md` | Navigator | Route the right context to the right agent |
| `build-ai/SKILL.md` | AI Core | Centralized AI engineering standards |
| `review/SKILL.md` | Guardrails | Validate code quality, suggest patches |
| `ship/SKILL.md` | Launchpad | CI/CD, git workflow, deployment planning |

No new skills are created. Each agent uses only its assigned skill folder as-is.

Experimental Isolation Rule

Create a global rule:

```
create-rule: AB_Test
```

Rule Behavior

The rule MUST strictly isolate each agent's accessible skill set.

Agent A

- Can ONLY access: `.cursor/skills_A/`
- Cannot access: `.cursor/skills_B/`

Agent B

- Can ONLY access: `.cursor/skills_B/`
- Cannot access: `.cursor/skills_A/`

Shared Access

Both agents CAN access:

- `/docs/kiotviet/` (the translated KiotViet API documentation)
- `/docs/` (any other shared documentation)
- `/shared/` (shared utilities, if any)

Implementation-specific reasoning and code must remain isolated to each agent's branch.

Git Branch Strategy

Create two implementation branches from `main`:

- `feature/agent-a-implementation`
- `feature/agent-b-implementation`

Each agent works exclusively on its own branch. No cross-branch code sharing during the experiment.

Agent A Workflow

1. Check out `feature/agent-a-implementation`.
2. Read skills from `.cursor/skills_A/` (discover, focus, build-ai, review, ship).
3. Read API docs from `/docs/kiotviet/`.
4. Use `discover` to produce specs and architecture for the KiotViet API Layer.
5. Use `focus` to scope the right context for implementation.
6. Implement the API Layer following guidance from `build-ai` and `review`.
7. Use `ship` for git workflow, commit conventions, and CI readiness.

Agent B Workflow

1. Check out `feature/agent-b-implementation`.
2. Read skills from `.cursor/skills_B/` (discover, focus, build-ai, review, ship).
3. Read API docs from `/docs/kiotviet/`.
4. Use `discover` (Blueprint) to produce specs and architecture for the KiotViet API Layer.
5. Use `focus` (Navigator) to scope the right context for implementation.
6. Implement the API Layer following guidance from `build-ai` (AI Core) and `review` (Guardrails).
7. Use `ship` (Launchpad) for git workflow, commit conventions, and CI readiness.

Phase 3 — Required Implementation Scope

Both agents must independently implement:

Authentication Layer
- OAuth/token handling
- Refresh token handling
- Credential management

API Client
- Request wrapper
- Retry handling
- Pagination support
- Rate-limit handling
- Error normalization

Resource Modules
- Products
- Orders
- Customers
- Inventory

Testing
- Unit tests
- Integration tests
- Mock API tests

Each branch should produce:

```
/src/integrations/kiotviet/
/tests/
/docs/implementation-notes.md
```

Phase 4 — Evaluation

Compare both implementations based on:

Code Quality
- Readability
- Modularity
- Maintainability

Architecture
- Separation of concerns
- Extensibility
- Dependency management

Reliability
- Error handling
- Retry resilience
- Test coverage

Developer Experience
- Ease of debugging
- Ease of onboarding
- Clarity of abstractions

Performance
- API efficiency
- Retry overhead
- Concurrency handling

After implementation:

1. Run both implementations against the same test suite.
2. Compare pass/fail rate, performance, code complexity, and maintainability.
3. Produce a final evaluation report: `/docs/ab-test-results.md`

Orchestrator Prompt

Objective:
Run a parallel A/B implementation experiment for the KiotViet API integration using existing skills.

Step 1:
Verify that `/docs/kiotviet/` contains complete, translated API documentation.

Step 2:
Create rule `AB_Test` that strictly isolates agent skill access:

Agent A:
- Can ONLY access `.cursor/skills_A/`

Agent B:
- Can ONLY access `.cursor/skills_B/`

Both agents:
- Can access `/docs/kiotviet/` and `/shared/`

Step 3:
Create two git branches from `main`:
- `feature/agent-a-implementation`
- `feature/agent-b-implementation`

Step 4:
Each agent implements the KiotViet API Layer independently on its own branch:

- Agent A reads `.cursor/skills_A/` + `/docs/kiotviet/` → builds version A
- Agent B reads `.cursor/skills_B/` + `/docs/kiotviet/` → builds version B

Required implementation:
- Authentication (OAuth, token refresh, credential management)
- API client (request wrapper, retry, pagination, rate-limit, error normalization)
- Resource modules (Products, Orders, Customers, Inventory)
- Unit tests + Integration tests + Mock API tests

Step 5:
Compare both implementations using:
- Architecture quality
- Maintainability
- Reliability
- Test coverage
- Performance
- Developer experience

Generate:
- Implementation notes per branch
- Architecture analysis per branch
- Final A/B comparison report at `/docs/ab-test-results.md`
