---
description: Run the Meta routing gate for an issue — ensure the workflow cache, run the pre-executor gate, assign one executor domain.
argument-hint: <issue-number>
---

Dispatch the `meta` subagent for issue **#$1**.

Task it with: run `focus` and emit a Context Plan; run
`python agent-runtime/scripts/meta_prepare_executor.py --issue $1`; assign exactly one
executor domain; build the child cache injection in `injectionOrder`; report the gate output
verbatim along with the assigned domain, the cache path, what was injected, and what was
deliberately excluded.

Stop at the gate — do not dispatch an Executor from this command. If the gate is red, report
the cause and the fix.
