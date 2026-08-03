---
name: ship
description: >-
  Covers CI/CD, git workflow, infrastructure, deployment, incident response, and rollback
  — prepares, validates, and plans without directly deploying. Use when preparing
  deployment artifacts, validating release readiness, generating rollout plans,
  configuring CI pipelines, or handling incidents.
---

# ship

**Phase:** Review — ship-ready

**Authoritative body:** [`.cursor/skills/standalone/ship/SKILL.md`](../../../.cursor/skills/standalone/ship/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`ci-examples.md`](../../../.cursor/skills/standalone/ship/ci-examples.md)

## Contract

Prepares and validates; never deploys directly. Merge Queue is primary, sync-before-merge is the fallback only.
