# Intent review — smell baseline & convention sources

Paste the **Smell baseline** section in full into the Standards sub-agent prompt.

## Convention source candidates (light citations only)

Load for **convention/pattern** citations — not Guardrails domain checklists:

| Path | Covers |
|------|--------|
| `.cursor/rules/patterns.mdc` | Repository interfaces, API envelopes |
| `.cursor/rules/code-quality.mdc` | Layout/naming conventions (cite lightly; do not turn into full Maintainability re-audit inside Guardrails) |
| Affected `MODULE.md` | Module boundaries |
| Domain skill under `.cursor/skills/domain/` | Domain conventions for touched layer |

**Do not** treat `.cursor/skills/standalone/guardrails/SKILL.md` domain tables as
intent-review input — those belong only to Guardrails.

Repo-documented conventions **override** the smell baseline when they conflict.

## Smell baseline (Fowler, *Refactoring* ch.3)

Each smell reads **what it is** → **how to fix**. Label as heuristics ("possible Feature Envy").
Skip anything tooling already enforces. **Only intent-review may block merge on these.**

| Smell | What it is → how to fix |
|-------|-------------------------|
| **Mysterious Name** | A function, variable, or type whose name doesn't reveal what it does or holds. → Rename it; if no honest name comes, the design's murky. |
| **Duplicated Code** | The same logic shape appears in more than one hunk or file in the change. → Extract the shared shape, call it from both. |
| **Feature Envy** | A method that reaches into another object's data more than its own. → Move the method onto the data it envies. |
| **Data Clumps** | The same few fields or params keep travelling together (a type wanting to be born). → Bundle them into one type, pass that. |
| **Primitive Obsession** | A primitive or string standing in for a domain concept that deserves its own type. → Give the concept its own small type. |
| **Repeated Switches** | The same switch/if-cascade on the same type recurs across the change. → Replace with polymorphism, or one map both sites share. |
| **Shotgun Surgery** | One logical change forces scattered edits across many files in the diff. → Gather what changes together into one module. |
| **Divergent Change** | One file or module is edited for several unrelated reasons. → Split so each module changes for one reason. |
| **Speculative Generality** | Abstraction, parameters, or hooks added for needs the Intent source doesn't have. → Delete it; inline back until a real need shows. |
| **Message Chains** | Long `a.b().c().d()` navigation the caller shouldn't depend on. → Hide the walk behind one method on the first object. |
| **Middle Man** | A class or function that mostly just delegates onward. → Cut it, call the real target direct. |
| **Refused Bequest** | A subclass or implementer that ignores or overrides most of what it inherits. → Drop the inheritance, use composition. |

### Binding rules

1. **The repo overrides.** Documented convention wins; suppress baseline smells the repo endorses.
2. **Judgement only at detection.** Smells are heuristics; merge-blocking authority for structure still sits with intent-review (not Executor).
3. **Skip tooling.** Do not re-report what ruff, mypy, eslint, CI, or formatters already enforce.
