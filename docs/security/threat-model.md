# Juli API Threat Model

Issue #1331 (W7-B/P-PROD-6) — a written model of the security trust boundaries the system enforces and the residual risks accepted at each. This document is maintained as a code artifact under CI control (see "Maintenance" section below).

## Executive summary

Juli's surface consists of three main trust boundaries, each with different threat profiles:

1. **Unauthenticated edge** — webhooks and public demo routes; attack surface is URL/signature validation and state injection.
2. **Authenticated API (`/v1/*`)** — user credential verification and per-shop authorization; attack surface is privilege escalation and cross-tenant access.
3. **Agent runtime** — three nested boundaries: inbound content (vendor text → prompt injection), tool execution (playbook allow-list enforcement), and credentials (TikTok token security).

This model assumes a threat actor with network access to the public API, ability to observe webhook deliveries (but not forge cryptographic signatures), and knowledge of system architecture from public sources (ADR-061).

---

## Trust boundaries

### Boundary 1: Unauthenticated edge (webhooks, health)

**What crosses this boundary:**
- Inbound webhook deliveries from TikTok Partner Center (`POST /webhooks/tiktok`)
- Public demo analytics reads (`GET /v1/demo/analytics`)
- OAuth redirect callbacks (`GET /v1/auth/tiktok/callback`, `GET /v1/auth/tiktok/business/callback`, `GET /v1/auth/tiktok/business/account-holder/callback`)

**What is trusted:**
- TikTok Partner Center webhook signatures (HMAC-SHA256 over request body)
- OAuth state parameter round-trip through browser session
- Request source IP (Cloudflare-proxied; attacker must compromise TikTok's egress or intercept at CDN level)

**Controls in force:**

| Control | File | Symbol | Notes |
|---------|------|--------|-------|
| Webhook request handling | `juli_backend/services/webhook/deployed.py` | `handle_tiktok_webhook_delivery()` | Signature validation and fail-closed JSON parsing before mutation |
| Demo analytics masking | `juli_backend/services/analytics_kpi_masking/mask.py` | `mask_public_analytics_envelope()` | Removes absolute metrics, returns only rate-of-change; reference shop ID server-bound |
| OAuth callback handling | `juli_backend/api/routes/auth_tiktok.py` | `tiktok_oauth_callback()` | State validation, code exchange server-side only; code never exposed to client |

**Residual risks:**

| Risk | Likelihood | Impact | Accepted because | Owner | Trigger for remediation |
|------|------------|--------|-------------------|-------|-------------------------|
| Webhook signature key compromise | Low | Critical — attacker injects fabricated shop events | Key is long-lived and not rotated in-band; rotation would require manual TikTok Partner Center re-registration | Backend | Signature verification fails on >10% of known-good webhook IPs in 1 hour |
| State parameter interception at CDN | Very low | High — attacker completes OAuth as victim | Assumes Cloudflare compromise; OTP tokens mitigate session hijacking | Backend | Evidence of Cloudflare security incident |
| Demo analytics inference attack | Medium | Medium — attacker re-constructs deleted shop state from rate changes | Masking hides absolute values but not trends; a time-series with public dates reveals structure | Analytics | No acceptance criteria; residual risk logged and deferred to ADR-086 |

---

### Boundary 2: Authenticated `/v1/*` API

**What crosses this boundary:**
- Every `/v1/*` route except OAuth callbacks and demo/analytics
- User credentials (JWT or session cookie)
- Per-shop authorization headers (`X-Shop-Id`)

**What is trusted:**
- Valid JWT signed by the same server that issued it (symmetric key)
- User ID embedded in JWT payload
- Shop ID in `X-Shop-Id` header matches a shop the authenticated user owns

**Controls in force:**

| Control | File | Symbol | Notes |
|---------|------|--------|-------|
| User authentication | `juli_backend/core/security/dependencies.py` | `get_current_user()` | Verifies JWT and looks up user by ID; missing user → 401 |
| Shop authorization | `juli_backend/api/dependencies.py` | `get_active_shop()` | Verifies `X-Shop-Id` header matches a shop in `User.shops`; mismatch → 403 |
| OAuth credential exchange | `juli_backend/api/routes/auth_tiktok.py` | `tiktok_oauth_callback()` | User identity verified via TikTok OAuth before JWT issued; code exchanged server-side only |

**Residual risks:**

| Risk | Likelihood | Impact | Accepted because | Owner | Trigger for remediation |
|------|------------|--------|-------------------|-------|-------------------------|
| JWT key disclosure | Very low | Critical — attacker forges tokens for any user | Key is environment-only, rotatable; compromise would require VPS intrusion | Backend | Evidence of VPS compromise |
| Cross-tenant access via header tampering | Medium | Critical — attacker reads/modifies another user's shop | Relationship to user verified on every request; admin cannot change user←→shop ownership mid-request | Backend | Failure in `get_active_shop()` auth check; audit log shows access denial |
| Privilege escalation via user lookup race | Low | High — attacker modifies their own user record mid-request | User record is immutable after sign-in except for shop membership (read-only during request); mutation requires logout+re-auth | Backend | User record read shows mutation; audit trail shows two different user states in same request |
| Token replay (CSRF) | Low | Medium — attacker tricks user into visiting attacker-controlled form | Tokens are bearer-only (no cookie); CORS headers restrict cross-origin requests; SameSite cookie policies enforced by browsers (if session cookies added) | Backend | CORS preflight fails on `/v1/` routes from non-origin |

---

### Boundary 3: Agent inbound content (vendor product text → prompt)

**What crosses this boundary:**
- Product titles, descriptions, images from TikTok Shop API
- User-supplied product context (shop ID, product ID)
- Prompt instructions (static, server-bound)

**What is trusted:**
- Vendor product data is from TikTok (authenticated via shop credentials)
- Product ID is valid per the shop's own catalog
- Prompt instructions are server-sourced, never user-controlled

**Controls in force:**

| Control | File | Symbol | Notes |
|---------|------|--------|-------|
| Vendor text sanitization | `juli_backend/services/agent/sanitize/chokepoints.py` | `guard_inbound_tool_result()` | Fail-closed boundary seam: regex rejects banned patterns (jargon only per #1304); forensics preserved |
| Output schema validation | `juli_backend/services/agent/tools/product.py` | `ProductToolContext` | Handler results validated against declared output schema before return to LLM; mismatch → error |
| Playbook allow-list | `juli_backend/services/agent/playbooks/optimize_product.py` | `OPTIMIZE_PRODUCT_PLAYBOOK` | Prompt defined in code, never user-constructed; only Optimize Product playbook can execute tools |

**Residual risks:**

| Risk | Likelihood | Impact | Accepted because | Owner | Trigger for remediation |
|------|------------|--------|-------------------|-------|-------------------------|
| Prompt injection via vendor text | Medium | High — attacker crafts product description that breaks prompt → unexpected LLM behavior | Sanitization catches known patterns; LLM may infer intent from context; requires manual red-team (gate #1339) | Backend + ML | Red-team pass finds novel injection pattern; no pattern-based detection possible |
| Evasion of sanitization regex | Medium | Medium — attacker bypasses banned-pattern filter | Regex is narrowed to jargon only (#1304); evolving patterns require code change; forensics preserved in logs | Backend | Forensics log shows rejected text that audit later identifies as harmful |
| Image dimension inference attack | Low | Low — attacker infers shop state from image count/sizes | Only aggregates are exposed (count, not list of sizes); dimensions are pixel-level resolution, not business-sensitive | Backend | No remediation unless image dimensions prove to encode merchant data |

---

### Boundary 4: Agent tool boundary (playbook allow-list → WRITE)

**What crosses this boundary:**
- LLM-selected tool invocations (name + input JSON)
- Tool results returned to LLM (output JSON)
- Confirmation decisions for CONFIRM-policy tools

**What is trusted:**
- Tool name is in the registered registry (ADR-069)
- Tool input matches the declared Pydantic schema (enforced by LLM)
- Tool result is validated against output schema before returning to LLM

**Controls in force:**

| Control | File | Symbol | Notes |
|---------|------|--------|-------|
| Tool registry enumeration | `juli_backend/services/agent/tools/registry.py` | `ToolRegistry` | Explicit registry; tools registered at startup via `build_product_tool_registry()` — no implicit registration |
| Tool lookup enforcement | `juli_backend/services/agent/composition.py` | `build_product_tool_registry()` | Unknown tool → error during dispatch; no fallback or dynamic registration |
| Playbook allow-list | `juli_backend/services/agent/playbooks/optimize_product.py` | `OPTIMIZE_PRODUCT_PLAYBOOK` | Only Optimize Product playbook permitted; new playbooks require explicit registration |
| Input/output schema binding | `juli_backend/services/agent/tools/product.py` | `ToolSpec` | Pydantic model validation; schema passed to LLM; mismatch on input/output → validation error |

**Residual risks:**

| Risk | Likelihood | Impact | Accepted because | Owner | Trigger for remediation |
|------|------------|--------|-------------------|-------|-------------------------|
| LLM hallucinates tool output | Low | Medium — attacker/LLM generates output the tool never returned | Output is validated against schema; invalid JSON → logged and re-prompted; cannot persist without matching schema | ML | Output parser fails on valid JSON that doesn't match declared model |
| WRITE tool approval bypass | Very low | Critical — attacker modifies product without confirmation | Confirmation decision persisted in ledger; approval UI enforces signature check (#1073); mismatch audited | Backend + UI | Ledger shows WRITE tool execution without corresponding approval record in 1 hour |
| Tool timeout DoS | Low | Medium — attacker crafts input that causes tool to hang, blocking run | Timeout enforced by wall-clock, not application logic; process killed after timeout; requires LLM to deliberately supply adversarial input | Backend | Run timeout on known-benign input; tool handler exception spike |

---

### Boundary 5: Credential boundary (TikTok tokens, JWT verification)

**What crosses this boundary:**
- TikTok access tokens (long-lived, refresh-capable)
- TikTok Shop product/order/seller credentials (per-shop)
- JWT signing key (server-held only, HS256)

**What is trusted:**
- Tokens issued by TikTok are valid and unexpired
- Tokens have the minimum scopes required (defined at credential provisioning time)
- JWT key is stored securely in environment and never exposed via logs

**Controls in force:**

| Control | File | Symbol | Notes |
|---------|------|--------|-------|
| Credential resolution | `juli_backend/core/security/credential_resolver.py` | `resolve_production_read_credential()` | Credential lookup enforces scope matching; missing scope → NotFound |
| Structured logging policy | `juli_backend/core/config/runtime.py` | `require_env()` | Audit logging captures auth decisions; tokens never logged |
| OAuth callback verification | `juli_backend/api/routes/auth_tiktok.py` | `tiktok_oauth_callback()` | State parameter validated, code exchanged server-side, bearer tokens issued |

**Residual risks:**

| Risk | Likelihood | Impact | Accepted because | Owner | Trigger for remediation |
|------|------------|--------|-------------------|-------|-------------------------|
| Token theft via log leakage | Low | Critical — attacker obtains token from logs | Logging is structured, tokens never rendered; requires log access (VPS intrusion or vendor compromise) | Backend | Secret detection tool finds token pattern in logs; audit trail shows export time |
| Refresh token handling | Low | Medium — refresh token used to re-issue access tokens; compromise extends attack window | Refresh tokens stored encrypted; no in-app refresh (requires manual credential re-provisioning); long-lived access tokens increase attack window | Backend | Refresh token used for >100 calls in 1 hour; token scope mismatch detected |
| Credential scope creep | Medium | Medium — credential provisioned with overly-broad scopes (e.g., WRITE on all products) | Scope is declared at credential provisioning time (manual process); no dynamic elevation; shop owns the scopes they grant | Backend | Credential scope read from DB differs from provisioning record; audit shows scope elevation |
| JWT key compromise | Very low | Critical — attacker forges tokens for any user | Key is environment-only, rotatable; requires VPS access or CI/CD compromise | Backend | JWT verification fails on signed tokens; system enters failure mode (no tokens valid) |

---

### Boundary 6: Data boundary (tenant isolation, PostgREST roles)

**What crosses this boundary:**
- Queries for user's shops, orders, products, action cards
- Mutations (updates) to product state
- Cross-shop read access requests

**What is trusted:**
- User ID from JWT is the authenticated owner
- Shop ID in header matches the user's own shop membership
- Database row-level security (RLS) enforces isolation in PostgreSQL

**Controls in force:**

| Control | File | Symbol | Notes |
|---------|------|--------|-------|
| User-shop ownership verification | `juli_backend/api/dependencies.py` | `get_active_shop()` | Every shop-scoped request verified against user's own shop membership |
| Shop-scoped query filtering | `juli_backend/repositories/repos.py` | `ShopsRepo` | Repository methods filter by shop_id parameter; isolation enforced at query layer |
| Transactional isolation | `juli_backend/database/database.py` | `get_session()` | AsyncSession enforces ACID; pessimistic isolation prevents dirty reads |

**Residual risks:**

| Risk | Likelihood | Impact | Accepted because | Owner | Trigger for remediation |
|------|------------|--------|-------------------|-------|-------------------------|
| Repository query bypass | Medium | Critical — attacker crafts raw SQL to read all shops | Repositories are the only query interface in application code; direct SQL use is not part of the API; attacker would need code injection or DB access | Backend | Query audit log shows query from unexpected codepath; codebase grep for raw SQL patterns |
| Shop membership escalation | Low | High — attacker adds themselves to another user's shop | Shop membership is user-managed via OAuth; no API mutation for membership; requires compromising the user record itself | Backend | Shop membership changes without corresponding OAuth re-auth event in ledger |
| Transactional race (lost update) | Low | Medium — attacker reads stale product state, writes based on old version | No optimistic locking on product mutations; concurrent updates may clobber each other; audit log captures all mutations but no conflict detection | Backend | Audit log shows two consecutive mutations by different users within <100ms |
| PostgREST RLS bypass | Very low | Critical — attacker bypasses RLS policies at DB layer | RLS is optional (not currently enforced); Python repositories are the primary isolation mechanism; RLS is a defense-in-depth layer | Backend | Database shows query execution outside of application context; unauthorized row access in audit log |

---

## How to run a red-team pass

A manual red-team pass is a gate in the release process (#1339). Use this section to scope and prioritize findings.

### Boundaries in priority order (severity decreases)

1. **Boundary 2: Authenticated API** — Highest risk. Covers 22/25 routes. Attack surface: cross-tenant access via header tampering, JWT compromise, user lookup races. Start here.
2. **Boundary 3: Agent inbound content** — Medium risk. Covers prompt injection, sanitization bypass, inference attacks on masked data. Requires manual LLM testing.
3. **Boundary 5: Credential boundary** — Medium risk. Covers token theft, scope creep, refresh token handling. Requires log inspection and scope audit.
4. **Boundary 4: Tool boundary** — Lower risk. Covers tool hallucination, approval bypass, timeout DoS. Requires running actual LLM with adversarial prompts.
5. **Boundary 1: Unauthenticated edge** — Lower risk. Covers webhook signature verification, state parameter validation. Requires cryptographic testing.
6. **Boundary 6: Data boundary** — Lower risk. Covers repository isolation, transactional races. Requires database audit and concurrent-mutation testing.

### Previous passes and findings

This is the first documented pass. See ADR-085 decision 5 for why it was deferred until W7.

### Where findings get filed

File findings as issues in the GitHub repository with the label `sec-finding` and tag the issue with the boundary number (e.g., `boundary-2-api`). Each finding should include:

1. Boundary number and control name
2. Attack scenario
3. Likelihood and impact assessment
4. Reproduction steps or proof-of-concept
5. Suggested remediation

---

## Maintenance

This threat model is a code artifact. The surface inventory (`docs/security/surface_inventory.json`) is machine-generated from the live route table and tool registry; the CI check in `tests/unit/test_threat_model_inventory.py` fails if the inventory goes stale.

**Inventory normalization (cross-version determinism):** To ensure byte-equality across FastAPI/Starlette versions (0.50 → 1.6 auto-method handling differs), the generator normalizes routes by excluding auto-generated HEAD and OPTIONS methods. Only developer-declared methods are recorded. Route paths are reconstructed to include router prefixes, and both routes and tools are stably sorted.

**To regenerate the surface inventory after adding a route or tool:**

The surface inventory is generated with PYTHONPATH pinned to ensure correct module resolution across environments:

```bash
PYTHONPATH=$PWD/backend/src python -c "
import sys
sys.path.insert(0, 'backend/src')
from tests.unit.test_threat_model_inventory import generate_surface_inventory
import json
from pathlib import Path
inv = generate_surface_inventory()
Path('docs/security/surface_inventory.json').write_text(json.dumps(inv, indent=2) + '\n')
"
```

Then run the byte-equality test to verify:

```bash
PYTHONPATH=$PWD/backend/src python -m pytest tests/unit/test_threat_model_inventory.py::TestSurfaceInventoryGeneration::test_surface_inventory_matches_committed_file -xvs
```

Then commit both the updated inventory and any threat-model.md changes together.

**Unauthenticated allowlist:**

The explicit allowlist of unauthenticated routes is checked in `test_unauthenticated_routes_on_allowlist()`. Routes must be added to the allowlist when they are intentionally public:

```python
UNAUTHENTICATED_ALLOWLIST = {
    "/v1/auth/tiktok/callback",
    "/v1/auth/tiktok/business/callback",
    "/v1/auth/tiktok/business/account-holder/callback",
    "/v1/demo/analytics",  # REPORTED FINDING: W6 is bringing demo surfaces under real auth (#1313); this allowlist entry may need to shrink when that lands
    # W6-owned routes may add more (e.g., /v1/demo/runs/{run_id}/events)
}
```

The check fails with the missing route name if a route is added without updating the allowlist.

---

## Reported Findings (for red-team pass #1339)

**Boundary 1 observation:** `/v1/demo/analytics` sits on the unauthenticated allowlist to serve public demo data. However, issue #1313 (W6-A) plans to bring demo surfaces under real seller authentication. The allowlist entry for `/v1/demo/analytics` should be flagged as a **scope change point** — when W6 lands, the red-team pass should confirm whether this route has been moved under auth and the allowlist correspondingly shrunk.
