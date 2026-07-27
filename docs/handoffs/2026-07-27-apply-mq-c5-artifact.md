# Apply: Merge Queue CI + Candidate 5 (2026-07-27)

**Worktree:** `.worktrees/agentic-v1-docs-lean`

## MQ / path-filtered CI (`pr.yml`)

Two-tier (grill settled):
- **`pull_request`:** path-filtered jobs + always-on secrets (gitleaks). Fast/skip unrelated packages.
- **`merge_group`:** **full** suite (ignore path skips — all product jobs required).

Implement:
1. `on.merge_group.branches: [main]` (+ staging if desired)
2. `dorny/paths-filter@v4` with checkout (required for merge_group)
3. Filters: `backend`, `dashboard`, `demo`, `agent_runtime`, `migrations` (subset of backend)
4. Job `if:`: run when `github.event_name == 'merge_group' || outputs.X == 'true'`
5. Always on PR: `gitleaks`; always on both: `changes` + `status-check`
6. `status-check`: skipped OK on PR when path-filtered; on `merge_group` require success (not skipped) for full suite jobs
7. Concurrency: do not cancel-in-progress on `merge_group`
8. `resolve-issue`: handle empty `head_ref` on merge_group (use `ref_name` / merge queue branch)

Do **not** enable Merge Queue in GitHub UI via API unless trivial — document that repo settings must enable Merge Queue + require `status-check`.

## Candidate 5 — `web/` → `apps/*`

Rewrite harness product UI paths to `apps/demo` + `apps/dashboard`. Keep `web/` only as **explicit legacy** (doNotLoad / App Review).

| Wave | Owns |
|------|------|
| C5a | `.cursor/skills/domain/ui-ux/`, `standalone/ui-ux-design/`, `.cursor/rules/ui-ux-design.mdc`, `skill-catalog/SKILL.md`, `focus/routing-rules.md` |
| C5b | `slice-routing.yml` (comments/legacy labels; product loads → apps), `agent-runtime.config.yml` doNotLoad notes, other standalone skills with web/ (validate, domain-modeling, ui-bug, extract-design, restructure, to-issues, ship/ci-examples, screenshot-annotate, grill-with-docs) |

Focus SKILL.md already updated in C2a — skip unless residual `web/`.
