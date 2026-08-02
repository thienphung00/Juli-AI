---
description: Run the full implementation pipeline for a GitHub issue — Meta routing gate, domain Executor, then Review.
argument-hint: <issue-number>
---

Run the full Juli implementation pipeline for issue **#$1**.

Dispatch each phase as a subagent, in order, waiting for each to finish before starting the
next. Do not do any of this work yourself in the main session — the per-phase model routing
(Sonnet for Meta, Haiku for Executor and Review) is the point.

1. **Meta** — dispatch the `meta` subagent: "Prepare issue #$1 for implementation. Run
   `focus`, run the pre-executor gate, assign exactly one executor domain, and report the
   gate output verbatim."

   **If Meta does not report `readyForExecutor: true`, stop here.** Report the failure and
   what it would take to clear it. Do not proceed to the Executor.

2. **Executor** — dispatch the `executor-<domain>` subagent for the domain Meta assigned,
   passing the issue number, the cache path, and the acceptance criteria. Do not second-guess
   the domain assignment.

3. **Review** — dispatch the `review` subagent: "Review issue #$1: `intent-review` →
   `guardrails` → `validate` → ship-ready."

   If Review reports a failing gate, report it as failing. Do not loop back to the Executor
   automatically — surface the finding and let the user decide.

Then summarise: gate result, domain, files changed, test evidence, gate verdicts, artifact
paths, and ship-ready yes/no. Do not merge or deploy.
