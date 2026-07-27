# Apply artifact: Candidate 4 — Agentic Version 1 full optimization (2026-07-27)

**Worktree:** `.worktrees/agentic-v1-docs-lean` · branch `feature/agentic-v1-docs-lean`  
**Caches:** `docs/handoffs/caches/apply-c4-*.json`

## Goal

Close **Agentic Version 1** (ex Agent Runtime Phase 6): rename mapping + **one live** proposed → applied → measured harness loop on a real issue class.

## Critical safety

`harness_config.apply_change(..., confirm=True)` **rewrites the entire** `agent-runtime.config.yml` via `dump_simple_yaml` (strips comments, breaks quoted epic blocks). **Do NOT** use `harness_optimizer.py propose --apply` or `harness_config.py apply --confirm` for this proof.

**Allowed apply:** surgical edit only — `context.max_files: 25` → `20` (from issue **#513** auto-eligible proposal `context_overloaded`).

## Provenance (issue #513)

- Artifacts present: implementation + review + validation
- Dry-run propose already emitted: `context.max_files` 25→20, `autoApplyEligible: true`
- Root cause: `context_overloaded`

## Waves

| Wave | Owns | Must not touch |
|------|------|----------------|
| C4a | Rename docs: migration, agent-runtime.md, benchmarks, artifacts, schemas/README | CONFIG max_files, MODULES body goals (C4b), artifacts JSON |
| C4b | `docs/architecture/MODULES.md` §11 only — Version 1 / Phase 6 wording + quality snapshot | other MODULES sections unless Phase 6 string |
| C4c | Surgical max_files; optimization artifacts lifecycle; evaluate; proof note in migration | Focus skill, issue-workflow, CONTEXT |

## Measured protocol (C4c)

1. Confirm proposal artifact for #513 exists (or re-propose dry-run)
2. Set that artifact `appliedStatus: accepted` then copy to `-applied.json` with `applied`
3. Surgical StrReplace `max_files: 25` → `max_files: 20` in config
4. Build **after** metrics artifact (same validation PASS; token/context metrics ≤ baseline + thresholds) + `appliedStatus: measured`
5. `harness_optimizer.py evaluate --before <proposed> --after <measured-rerun>`
6. Write short proof section into migration doc Agentic Version 1 section
7. Leave `optimization.dry_run_default: true` (Version 2+ may change)

## Rename mapping (document once in migration.md)

| Legacy | New |
|--------|-----|
| Agent Runtime migration Phases 1–5 | Completed **bootstrap** (unchanged labels historically) |
| Agent Runtime Phase 6 | **Agentic Version 1** |
| Agentic Phase 1 | Rejected alias → Version 1 |

## Done criteria

- [ ] No pending “Phase 6: Optimization Loop” heading — Agentic Version 1 section with mapping + proof
- [ ] MODULES §11 says Agentic Version 1 / measured loop (not Phase 6 pending)
- [ ] `context.max_files == 20` in config
- [ ] Artifacts: proposed/accepted/applied + measured + evaluate report with no regression
- [ ] dry_run_default still true
