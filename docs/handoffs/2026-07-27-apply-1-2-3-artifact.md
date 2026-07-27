# Apply artifact: Candidates 1+2+3 (2026-07-27)

**Status:** APPLY NOW · **Worktree:** `.worktrees/agentic-v1-docs-lean` on `feature/agentic-v1-docs-lean` (cut from `origin/main`)  
**Do not** edit the demo-deploy primary checkout.

## Settled decisions (do not re-grill)

- Product phases (EXECUTION) ≠ Agentic **versions** (migration doc + MODULES §11)
- Agentic Version 1 = ex Agent Runtime Phase 6 (optimization loop); no ADR for naming
- Merge Queue primary land path; sync-before-merge = cutover fallback only
- Two-tier CI: fast path-filtered PR; full suite on `merge_group`
- Light pre-commit + conventional commits; auto-deploy on `main` after queue
- Human approval: shared-core / auth / prod-config / public-release only

## Shared caches (load these)

| Cache | Path |
|-------|------|
| Parent apply plan | this file |
| C1 thin-out plan | `docs/handoffs/caches/apply-c1-context-thin.json` |
| C2 Focus/MODULES | `docs/handoffs/caches/apply-c2-focus-modules.json` |
| C3 Merge Queue | `docs/handoffs/caches/apply-c3-merge-queue.json` |
| Grill handoff | `docs/handoffs/2026-07-27-agentic-phase-1-grill.md` |
| Architecture HTML | temp `architecture-review-20260727-115107.html` (optional) |

## Seeded into worktree (from grill branch)

- `CONTEXT.md` (687-line grilled version — C1 thins this)
- `docs/architecture/MODULES.md` + `docs/adr/036-modules-tier1-planning-sot.md` (needed for C2; not yet on main)

## Path ownership (strict)

| Agent | Owns (write) | Must not touch |
|-------|--------------|----------------|
| C1 | `CONTEXT.md` only | rules, skills, config, other docs |
| C2a | `.cursor/skills/standalone/focus/SKILL.md`, `.cursor/skills/standalone/improve-codebase-architecture/SKILL.md`, `.cursor/skills/standalone/focus/routing-rules.md` if present | CONTEXT, git rules |
| C2b | `agent-runtime/config/agent-runtime.config.yml`, `agent-runtime/config/slice-routing.yml` | CONTEXT, Focus skill |
| C2c | Path-drift docs only: `docs/architecture/system-design.md` (`decisions/`→`adr/`), `docs/ml/ml_layer.md`, `agent-runtime/templates/context-plan-template.md`, `docs/templates/handoffs/validation-meta.md`, `docs/deployment/implementation-guide.md`, `docs/deployment/quick-reference.md`, `docs/adr/003-ai-native-cicd-policy.md` (href fix only) | CONTEXT, Focus, issue-workflow |
| C3a | `.cursor/rules/issue-workflow.mdc`, `.cursor/rules/git-baseline.mdc` | CONTEXT, Focus |
| C3b | `docs/handoffs/worktree-branch-topology.md`, `.cursor/skills/standalone/validate/SKILL.md`, `docs/handoffs/parallel-status.md` (pipeline lines only) | CONTEXT, Focus, config |

## Done criteria

- C1: CONTEXT ≤ ~320 lines; no Merge Queue mega-entry; Agentic Version 1 gates moved out; Doc SoT pointers; Copy dictionary deduped
- C2: Focus Step 3 loads MODULES; config `cross_layer_hints` include MODULES; no broken `docs/architecture/agent-runtime.md` links in owned files; `decisions/` ADR hrefs fixed in owned files
- C3: issue-workflow + topology + validate say Merge Queue primary; sync-before-merge labeled fallback

## Out of scope this apply

- Agentic Version 1 measured loop (Candidate 4)
- Full `web/`→`apps/*` sweep beyond Focus (Candidate 5 partial only if already in C2a Focus)
- Filing GitHub PRDs / CI `merge_group` workflow YAML (can note TODO)
- Committing unless parent asks
