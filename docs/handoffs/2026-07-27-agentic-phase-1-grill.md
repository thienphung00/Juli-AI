# Handoff: Agentic Phase 1 grill (Product vs Agentic timelines)

**Date:** 2026-07-27  
**Audience:** Fresh agent window (Architect) — start here before any other file.  
**Skill sequence:** `focus` → **`grill-with-docs`** → (`to-prd` → `to-issues` if needed) → implement only after grill settles.

---

## Session summary

Prior session built the codebase mindmap, created Tier-1 [`docs/architecture/MODULES.md`](../architecture/MODULES.md) + [ADR-036](../adr/036-modules-tier1-planning-sot.md), evaluated the HITL Agent Runtime, and identified P0 quality gaps (Focus ↛ MODULES, path drift, Phase 6 not operational). User directed a **fresh context window** to grill and implement harness work under a **split timeline**: **Product phases** (`EXECUTION.md`) vs **Agentic phases** (harness maturity). Legacy “Agent Runtime Phase 6” is renamed **Agentic Phase 1**. P0 (Focus + MODULES wiring + path drift) is in scope for that Agentic Phase 1 grill/implementation track.

---

## Decisions made (do not re-ask)

| Decision | Choice |
|----------|--------|
| MODULES vs map | Split: MODULES = goals/features; map = as-built paths |
| EXECUTION vs MODULES | EXECUTION = multi-module **product** phase progression; MODULES = per-module refinement/features |
| MODULES entry schema | Status, Path, Purpose, Goals, Features (S/IP/P), Related slices, OOS, Links |
| MODULES granularity | Domain entries + selective nesting (14 domains) |
| Doc tier ladder | 0 EXECUTION → 1 MODULES/system-design/data-sources → 2 map/ADRs → 3 MODULE.md/AC |
| MODULES first draft | Seeded + ADR-036 + authority rewires |
| Sentry in mindmap | Omit |
| Phase 3 polyglot / hermes / doc crawlers | Keep on MODULES |
| Empty `identity/catalog/ordering` stubs | Omit from catalog |
| **Product vs Agentic timelines** | **Separate** — Agentic builds Product; do not number them as one sequence |
| **Rename** | Agent Runtime migration “Phase 6” → **Agentic Phase 1** |
| **P0 in Agentic Phase 1** | Focus + MODULES wiring + path drift included in this grill track |
| Fresh window | Implement/grill Agentic Phase 1 here — prior chat is handoff-only |

Glossary terms added: **Product phases**, **Agentic phases** in [`CONTEXT.md`](../../CONTEXT.md).

---

## Current state

- **Branch (prior session workspace):** `fix/demo-deploy-turbo-cache-and-systemd` (MODULES/ADR work may be uncommitted mixed with unrelated demo-deploy changes — **cut a clean `feature/` or `agent/runtime` worktree** before editing).
- **No GitHub issue yet** for Agentic Phase 1 — grill first, then `to-prd` / `to-issues` if scope warrants.
- **Agent Runtime migration doc:** Phases 1–5 complete; old “Phase 6” pending optimization loop.
- **MODULES §11:** status `partial`; quality snapshot + eval canvas exist.
- **Eval canvas:** `~/.cursor/projects/Users-macos-Juli-AI-v2/canvases/agentic-workflow-evaluation.canvas.tsx`
- **Mindmap canvas:** `.../canvases/codebase-component-mindmap.canvas.tsx`

### P0 problem statement (evidence)

1. **Focus does not load MODULES.md** — still Step-3 baseline `map.md` / system-design; ADR-036 authority not reflected in Focus or `agent-runtime.config.yml` `cross_layer_hints`.
2. **Path drift:** refs to `docs/architecture/agent-runtime.md` (moved to `agent-runtime/docs/`), `web/`, `docs/decisions/`.
3. **Optimization loop:** ~147 harness artifacts `proposed` vs 1 `measured`; `optimization.dry_run_default: true`; no CI for `harness_optimizer.py`.

---

## Next steps (ordered — new window)

1. **Read this handoff**, then `CONTEXT.md` (Product/Agentic terms), `MODULES.md` §11, `agent-runtime/docs/agent-runtime-migration.md`, ADR-036.
2. **Worktree:** prefer `.worktrees/agent-runtime` on `agent/runtime` or a new `feature/agentic-phase-1-*` cut from `main` — **do not** mix with demo-deploy branch.
3. **Run `grill-with-docs`** — one question at a time; start with **Q1 below**. Update CONTEXT/ADRs as answers land.
4. After grill settles: update migration doc (Agentic phase table), `agent-runtime.md`, Focus, config hints, stale path sweep; prove one Agentic Phase 1 loop if in scope.
5. If multi-issue: `to-prd` → `to-issues` (tracer bullets: Focus wiring / path drift / Phase-1 proof).

---

## Open questions (grill queue)

Ask **one at a time**. Recommended answers in italics.

### Q1 — Agentic phase numbering (start here)

How should the **Agentic** timeline be numbered relative to completed Agent Runtime migration Phases 1–5?

- **A (recommended):** Keep historical Agent Runtime migration Phases 1–5 as **completed bootstrap** (docs/skills/schemas/benchmarks). Start a **new** sequence: **Agentic Phase 1** = optimization loop (ex-Phase 6), then Agentic Phase 2+ for later harness maturity. Document the rename mapping once in migration.md.
- **B:** Renumber everything so Agentic Phase 1–5 = old 1–5 and Agentic Phase 6 stays (reject — user asked rename 6→1).
- **C:** Collapse bootstrap into “Agentic Phase 0” and Agentic Phase 1 = optimization only.

### Q2 — Where does Agentic timeline live?

- **A (recommended):** `agent-runtime/docs/agent-runtime-migration.md` (or rename to `agentic-phases.md`) + MODULES §11 Features; **not** rows in EXECUTION product phase table.
- **B:** Parallel section inside EXECUTION.md (“Agentic track”).
- **C:** MODULES §11 only.

### Q3 — Agentic Phase 1 exit gate

What must be true to call Agentic Phase 1 done?

- **A (recommended):** (1) Focus + config load MODULES for Architect/module planning; (2) path-drift sweep for agent-runtime/Focus; (3) **one live** proposed→applied→measured harness optimization on a real issue class (benchmark protocol OK if tied to production config change); (4) migration doc + MODULES §11 updated.
- **B:** Doc/wiring only — defer measured loop.
- **C:** Full CI automation of harness_optimizer every PR (likely over-scope).

### Q4 — P0 vs Agentic Phase 1 issue split

- **A (recommended):** Single PRD / epic “Agentic Phase 1” with slices: P0a Focus+MODULES, P0b path drift, P1c optimization proof.
- **B:** Three independent issues, no epic.
- **C:** P0 first (merge), then separate Agentic Phase 1 issue for the loop only.

### Q5 — ADR?

Does the Product vs Agentic dual-timeline + Phase 6→Agentic Phase 1 rename need ADR-037?

- **A (recommended):** Yes — hard to reverse naming, surprising without context, trade-off vs putting Agentic rows in EXECUTION.
- **B:** CONTEXT + migration doc only.

---

## Files changed (prior session — uncommitted / mixed branch)

```
CONTEXT.md
EXECUTION.md
docs/README.md
docs/adr/README.md
docs/adr/036-modules-tier1-planning-sot.md          (new)
docs/architecture/MODULES.md                       (new)
docs/architecture/data-sources.md
docs/architecture/map.md
docs/architecture/migration-plan.md
docs/architecture/system-design.md
docs/handoffs/2026-07-27-agentic-phase-1-grill.md  (this file)
```

IDE canvases (not in git): `codebase-component-mindmap.canvas.tsx`, `agentic-workflow-evaluation.canvas.tsx`.

---

## Paste into new agent window

```text
Read docs/handoffs/2026-07-27-agentic-phase-1-grill.md first, then CONTEXT.md
(Product phases / Agentic phases). Run focus → grill-with-docs. Start at Q1
(Agentic phase numbering). Do not re-ask settled MODULES/ADR-036 decisions.
Goal: grill then implement Agentic Phase 1 (ex Agent Runtime Phase 6) including
P0 Focus+MODULES wiring and path drift. Use a clean worktree off main / agent/runtime
— not the demo-deploy branch.
```
