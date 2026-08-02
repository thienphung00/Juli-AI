---
description: Run the Review phase for an issue or the current branch — intent-review, guardrails, validate, ship-ready.
argument-hint: [issue-number]
---

Dispatch the `review` subagent for **$ARGUMENTS** (if no issue number was given, review the
current branch's diff against `main`).

Task it with the canonical sequence, in order: `intent-review` → `guardrails` → `validate` →
ship-ready. It must actually run every `agent-runtime/scripts/validate/*.py` gate and paste
the real output — no summarising a gate it did not run, no marking a red gate green.

Report the verdict per step, every failing gate with its actual output, the artifact paths
written, and an explicit ship-ready yes/no. Do not merge or deploy.
