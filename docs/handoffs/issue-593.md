# Handoff: focus → implementation — Issue #593

## Issue
- **#593** — Wire TikTok document corpora for Architect/Meta catalog retrieval
- **EXECUTION slice:** CORPORA-1
- **Parent:** #593 (single large slice) · **Blocked by:** none
- **Executor domain:** backend (catalog builder scripts + harness/docs routing)

## Branch
- Prefer `feature/issue-593-tiktok-corpora` (or current Meta checkout with ADR-051 + PRD present)

## phaseRunId
- 593-20260729-corpora — use across all runtime artifacts for this run

## Implementation artifact (end of Executor phase)
- `artifacts/implementations/implementation-issue-593.json`

## Acceptance criteria
- Three corpora at shared local root (move/symlink); playbook docs path + `JULI_TIKTOK_CORPORA_ROOT`
- Regen script → three catalog JSON files (ADR-051 fields; no bodies; skip Partner `_raw/`)
- Catalogs + README under `docs/integrations/tiktok_corpora/`
- Focus: Architect/Meta may load; Executor/Review DO NOT Load corpora
- Crawler output root updated or documented → shared local root
- Fixture unit tests: front-matter → entry; `_raw` skip; no body leakage
- Smoke: Grep catalog → Read body; missing body fail soft

## Context loaded
| Area | Files |
|------|-------|
| Decision | docs/adr/051-tiktok-corpora-catalog-retrieval.md, CONTEXT.md |
| PRD | docs/product/phases/tiktok-corpora-catalog/PRD.md |
| Focus | .cursor/skills/standalone/focus/SKILL.md, routing-rules.md |
| Curated SoT | docs/integrations/tiktok_api/, tiktok_platform/ (reference only; do not rewrite) |

## Standards applied
- reliability (fail soft for missing bodies)
- code-quality (script + tests)
- core-orchestration (Executor/Review never open corpus bodies)

## Plugin skills & MCP
- none (local markdown corpora; no TikTok MCP)

## Implementation approach
**Dependency order:** residency bootstrap (Meta) → catalog builder TDD → generate catalogs → Focus/playbook routing → review

### Parallel sub-agent slices (Meta)
1. **Catalog TDD** — `scripts/tiktok_corpora_catalog/` + `tests/unit/test_tiktok_corpora_catalog*.py` + emit catalogs
2. **Focus + playbook** — `docs/integrations/tiktok_corpora/README.md` + Focus routing only (no catalog JSON writes)
3. **Review** — after 1+2: intent-review fidelity to ADR-051 / #593 AC

**Slice B (playbook + Focus):** Playbook documents shared local root, crawler retarget to
`JULI_TIKTOK_CORPORA_ROOT`, and ADR-051 phase gate. Crawler code under `local/adhoc` is
unchanged in this slice — output root is specified in the playbook README.

### DO NOT touch
- `backend/src/juli_backend/` product code
- `apps/demo`, `apps/dashboard`, `ios/`
- Committing corpus markdown bodies
- Embedding RAG / new Cursor skill
- Executor domain skills claiming corpus Read access
