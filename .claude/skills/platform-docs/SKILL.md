---
name: platform-docs
description: >-
  Scans and generates platform documentation for Seller and Creator identities, covering
  Feature Guide and Policy Center sections, under docs/<vendor>_platform/. Use when
  onboarding marketplace feature knowledge (tools, programs, workflows), seller/creator
  policy rules (account health, limits, eligibility, compliance), or preparing decision
  context for Architect planning, api-docs, focus, to-prd, and review.
---

# platform-docs

**Phase:** Planning

**Authoritative body:** [`.cursor/skills/standalone/platform-docs/SKILL.md`](../../../.cursor/skills/standalone/platform-docs/SKILL.md)

Read that file now and follow it. This pointer exists so Claude Code can discover
and route the skill — the procedure itself is deliberately not restated here. The
`.cursor/` file is the single source of truth for both harnesses; edit it there, and
never fork a copy into `.claude/`.

**Bundled resources** in the same directory (load only when the body says to):

- [`REFERENCE.md`](../../../.cursor/skills/standalone/platform-docs/REFERENCE.md)

## Contract

Uses WebFetch against vendor University/policy pages. Context7 CLI only for partner SDK docs.
