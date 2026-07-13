---
name: improve-codebase-architecture
description: >-
  Scan for deepening opportunities, present a visual HTML report, grill through a pick,
  then execute safe refactors for a leaner maintainable codebase. Use when the user says
  "architecture review", "deepen modules", "improve codebase architecture", "restructure",
  "leaner codebase", or "find structural friction".
disable-model-invocation: true
---

# Improve codebase architecture

Surface architectural friction and propose **deepening opportunities** — refactors that
turn shallow modules into deep ones. Then **execute safe refactors** that preserve all
existing behaviour while optimizing for a leaner, easier-to-maintain codebase.

The invariant for execution: **the same tests pass before and after every change.**

Built on [`codebase-design`](../codebase-design/SKILL.md) vocabulary (module, interface,
depth, seam, adapter, leverage, locality) and [`CONTEXT.md`](../../../../CONTEXT.md)
domain language. ADRs in `docs/adr/` record decisions this command must not re-litigate.

## Process

### 1. Explore

1. Read `CONTEXT.md` and relevant ADRs in `docs/adr/` for the area under review.
2. Load [`codebase-design`](../codebase-design/SKILL.md) — use its terms exactly.
3. Launch **Task** with `subagent_type=explore` to walk the codebase organically.
   Do not follow rigid heuristics — note where you experience friction:

| Signal | What to look for |
|--------|------------------|
| Low locality | Understanding one concept requires bouncing between many small modules |
| Shallow modules | Interface nearly as complex as the implementation |
| Misplaced seams | Pure functions extracted for testability, but real bugs hide in call-site wiring |
| Leaky coupling | Tightly-coupled modules bleed across their seams |
| Untestable surfaces | Hard to test through the current interface |

Apply the **deletion test** to suspected shallow modules: would deleting it concentrate
complexity, or just move it? "Yes, concentrates" is the signal you want.

**Juli surfaces:** `backend/` (pytest), `apps/dashboard/` (npm test), `ios/` (xcodebuild).
Consult `docs/architecture/map.md` and affected `MODULE.md` files.

### 2. Present candidates as an HTML report

Write a **self-contained HTML file** to the OS temp directory — nothing lands in the repo.

```bash
# Resolve temp dir (macOS/Linux)
TMPDIR="${TMPDIR:-/tmp}"
OUT="$TMPDIR/architecture-review-$(date +%Y%m%d-%H%M%S).html"
# Windows: use %TEMP% and `start` instead of `open`
```

Open for the user:

| OS | Command |
|----|---------|
| macOS | `open "$OUT"` |
| Linux | `xdg-open "$OUT"` |
| Windows | `start "$OUT"` |

Tell the user the **absolute path** to the file.

Follow [HTML-REPORT.md](HTML-REPORT.md) for scaffold, diagram patterns, and styling.
Tailwind + Mermaid via CDN. Each candidate gets a before/after visualisation.

**Per candidate card:**

- **Files** — involved modules/files
- **Problem** — why the current architecture causes friction
- **Solution** — plain English deepening change
- **Benefits** — locality, leverage, and how tests improve
- **Before / After diagram** — side-by-side (Mermaid for graphs; hand-built CSS/SVG for editorial visuals)
- **Recommendation strength** — badge: `Strong` | `Worth exploring` | `Speculative`

End with a **Top recommendation** section: which candidate to tackle first and why.

Use **CONTEXT.md** vocabulary for domain terms and **codebase-design** vocabulary for
architecture. Do not propose interfaces yet.

**ADR conflicts:** if a candidate contradicts an existing ADR, surface it only when friction
warrants revisiting. Mark clearly (e.g. warning callout: "contradicts ADR-0007 — but worth
reopening because…"). Do not list every theoretical refactor an ADR forbids.

After the file is written and opened, ask:

> Which of these would you like to explore?

### 3. Grilling loop

Once the user picks a candidate, run [`grill-with-docs`](../grill-with-docs/SKILL.md) to
walk the design tree — constraints, dependencies, shape of the deepened module, what sits
behind the seam, what tests survive.

**Inline side effects** as decisions crystallize:

| Trigger | Action |
|---------|--------|
| New module name not in CONTEXT.md | Add term via [`domain-modeling`](../domain-modeling/SKILL.md); create `CONTEXT.md` lazily |
| Sharpening a fuzzy term | Update `CONTEXT.md` inline |
| User rejects with load-bearing reason | Offer ADR: "Want me to record this as an ADR so future architecture reviews don't re-suggest it?" Only when a future explorer needs it — skip ephemeral ("not now") or self-evident reasons |
| Alternative interfaces for the deepened module | Run [`codebase-design`](../codebase-design/SKILL.md) **design-it-twice** parallel sub-agents |

### 4. Execute safe refactors

After grilling settles the target structure, execute the structural change safely.
Goal: a **leaner codebase** — fewer shallow modules, clearer seams, less bounce-around —
that still passes the same tests and is easier to maintain.

#### Entry (before any code)

1. Confirm from the grilling session: **what must be preserved?** **what is allowed to change?**
   If either is unclear, resume [`grill-with-docs`](../grill-with-docs/SKILL.md) — do not write code yet.
2. Re-read `CONTEXT.md` and relevant `docs/adr/` — the execution plan must not contradict them.

#### Issue creation (when work spans multiple PRs)

- Each refactor issue states: **current structure**, **target structure**, and the **test(s) that gate it**.
- Issues that would require new tests are escalated to Implementation (Executor Agent). Flag them; do not silently convert.

#### Per-change loop

1. Run the full test suite for affected surfaces. **Record the result.**
2. Make **only** the structural change described in the plan or issue. No opportunistic improvements.
3. Run the full test suite again. Compare to the before result.
4. If any previously-passing test now fails: **stop**, surface the failure, **do not patch the test**.
   The test is the source of truth, not the refactor plan.

Prefer small, atomic changes — one logical structural move per commit/PR when possible.

#### Surfaces and test commands

| Surface | Path | Command |
|---------|------|---------|
| Backend | `backend/` | `pytest tests/` |
| Dashboard | `apps/dashboard/` | `npm run lint && npm run type-check && npm run test && npm run build` |
| iOS | `ios/` | `xcodebuild test -scheme [scheme] -destination 'platform=iOS Simulator,...'` |

After file moves, grep repo-wide for old paths. Prefer `git mv`.

#### Handoff

When execution completes (or pauses), write a handoff via [`handoff`](../handoff/SKILL.md):
what structural changes were completed, test baseline/results, and which issues remain open.
