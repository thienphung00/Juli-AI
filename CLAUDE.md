# Juli AI — Claude Code harness

B2B SaaS analytics & automation copilot for TikTok Shop sellers. Python/FastAPI backend,
Next.js apps, SwiftUI iOS, Postgres.

**This repo is driven by both Cursor and Claude Code.** The rule and skill *bodies* live
under `.cursor/` and are the single source of truth. Files under `.claude/` are thin
Claude-native pointers — they carry Claude frontmatter and phase contracts, then defer to
the `.cursor/` body. **Never fork a rule or skill body into `.claude/`.** Edit the
`.cursor/` file; both tools pick the change up.

Authority chain: [`EXECUTION.md`](EXECUTION.md) > [`agent-runtime/docs/agent-runtime.md`](agent-runtime/docs/agent-runtime.md) > skills and rules.

---

## Tier 1 — always on

Four rules are always in force. Two are short enough to inline; read the other two when
routing or touching git.

### Safety (`.cursor/rules/core-safety.mdc`)

- Never commit secrets — env vars or a secrets manager; `.env` stays gitignored.
- Validate at boundaries — HTTP, webhooks, events, file inputs; server-side always.
- Parameterized data access — no string interpolation into SQL or shell.
- AuthZ at the service layer, not only the router. Least privilege for tokens.
- Safe logging — never log passwords, tokens, PII, or full card numbers.

### Git (`.cursor/rules/git-baseline.mdc`)

- Short-lived `feature/<short-desc>` cut from `main`. Never push to `main` directly.
- Conventional commits: `feat|fix|refactor|docs|test|chore|perf|ci: <description>`.
- **Two lanes** (pick by what the diff touches): **Standard** — any code, or mixed code+docs: branch/worktree → PR → land on green → close. **Fast-track** — non-code only (`*.md`/`*.mdc`/`*.txt`, `docs/**`, `.cursor/rules|skills/**`; zero code edits): short branch → PR → immediate `gh pr merge --squash --delete-branch --admin`. Any code file in the diff ⇒ standard lane. Both lanes go via a PR.
- Persistent helper slots only: `agent/runtime`, `scratch/debug`, `local/adhoc`.
- Close each task's worktree + branch on PR merge — `python agent-runtime/scripts/git/worktree_gc.py --close <task>` verifies merged (incl. squash) + clean and prunes. Auto-close only worktrees you created that are merged **and** clean; confirm before deleting dirty, unpushed, human-created, or closed-not-merged branches. Never `main` or the helper slots.
- Pre-commit required in every checkout: `pip install pre-commit && pre-commit install`.

### Routing and MCP

Read [`.cursor/rules/core-orchestration.mdc`](.cursor/rules/core-orchestration.mdc) and
[`.cursor/rules/mcp-usage.mdc`](.cursor/rules/mcp-usage.mdc) before routing work.
Tier-2 rules under `.cursor/rules/` load **only** when Focus selects them — never all at once.

---

## Focus is the router

For every non-trivial task, run the `focus` skill first and produce a **Context Plan**
(docs / rules / skills / MCPs, with an explicit *DO NOT load* list). Ad-hoc chat stops at
Focus — do not auto-enter review, validate, or ship pipelines unless asked.

## Agent phase model

| Phase | Agent | Model | Sequence |
|-------|-------|-------|----------|
| Planning | `architect` | Opus | `focus` → `grill-with-docs` → `to-prd` → `to-issues` |
| Implementation routing | `meta` | Sonnet | `focus` → `meta_prepare_executor.py` → assign one executor domain |
| Implementation | `executor-<domain>` | Haiku | domain skill + built-in TDD (red → green → refactor) |
| Review + testing | `review` | Haiku | `intent-review` → `guardrails` → `validate` → ship-ready |
| Harness optimization | `meta` | Sonnet | consumes implementation/review/validation artifacts |

Executor domains: `backend`, `ui-ux`, `data-platform`, `machine-learning`, `integrations`.
One primary domain per issue — never dual-load `backend` + `data-platform`.

**Hard gate.** Meta must run this before assigning any Executor, and must halt unless it
prints `readyForExecutor: true`:

```bash
python agent-runtime/scripts/meta_prepare_executor.py --issue <N>
```

Executors and Review must never open TikTok corpora catalogs (ADR-051), route context,
or ship. Meta must never implement features or bypass Review.

---

## Tooling policy — CLI first

MCP tool schemas are always-on context cost for every agent on every request. CLIs cost
nothing until invoked, are reproducible in a workflow cache, and are gateable by a single
Bash hook. So: **use the CLI whenever one exists.** MCP is reserved for surfaces with no
CLI equivalent, and is scoped to the Architect/Meta phases only.

| Need | Use | Notes |
|------|-----|-------|
| GitHub issues, PRs, checks, merge queue | `gh` | Never an MCP |
| Supabase schema, RLS, local DB | `npx --yes supabase@latest <cmd>` | Focus-selected; see `.cursor/rules/supabase-cli.mdc`. MCP is **not** used |
| Library / framework / SDK docs | `npx ctx7@latest library\|docs` | Focus-selected; see `.cursor/rules/context7-cli.mdc`. **Not an MCP here** |
| shadcn registry / components | `npx shadcn@latest` | |
| E2E browser flows | `npx playwright` | |
| Deploy, env vars | `vercel` | |
| Design reference: layout, component extraction | **MCP** `open-design` | Upstream of `ui-ux-design` (ADR-043), reference-only |
| Design reference: screen/flow inspiration | **MCP** `Mobbin` | Reference-only — **layout and flow only, never colour**; palette comes from `packages/theme` tokens and `docs/product/design` |
| Figma read/write | **MCP** `figma` | Load the `figma-use` skill before any `use_figma` call |

Executor subagents have no MCP tools by construction. If an executor believes it needs a
design reference, that is a signal the Meta routing was wrong — stop and report, don't
reach for a tool.

Never call an MCP tool speculatively. Prefer `Grep` / `Read` / `Bash` when they suffice.

---

## Commands

```bash
python agent-runtime/scripts/meta_prepare_executor.py --issue <N>   # Meta gate
pytest                                                              # backend tests
ruff check backend tests scripts && ruff format --check backend tests scripts
pnpm -w turbo run build                                             # JS workspaces
python agent-runtime/scripts/validate/check_handoff.py --help       # validation gates
```

Validation gates live in `agent-runtime/scripts/validate/`; the `validate` skill runs all
of them and emits `agent-runtime/artifacts/validation/validation-issue-<n>.json`.

## Artifacts (ADR-003, as amended by #670)

Issue branches matching `issue-<N>` must **emit** implementation, review, and validation
artifacts under `agent-runtime/artifacts/`. Work in `.worktrees/debug` on a branch without
an `issue-<N>` suffix skips artifact emit per `artifact_gates.quickCommitSkip` in
[`agent-runtime/config/agent-runtime.config.yml`](agent-runtime/config/agent-runtime.config.yml).
Never use that path for issue work, and never edit `pr.yml` or Tier-1 rules from that slot.

**Emit is not commit.** Five body directories are gitignored and must never be committed —
`reviews/`, `implementations/`, `intent-reviews/`, `validation/`, `optimization/`. Their
JSON bodies are written locally during the loop (the in-loop gates read them off the
filesystem, unaffected by gitignore) and uploaded to CI artifact retention on the
issue-tier run. **Do not `git add -f` them.** The committed merge-time source of truth is
the compact record at `agent-runtime/artifacts/status/issue-<N>.json`, generated by
[`generate_status_records.py`](agent-runtime/scripts/ci/generate_status_records.py) from a
review + validation pair. `tests/unit/test_status_record_gate.py` fails CI on any tracked
`*.json` under those five directories.

## Skills governance

Do **not** create skills under `.cursor/skills/` or `.claude/skills/` unless the user
explicitly asks in the conversation. For repeatable prompts use `docs/handoffs/*.md`; for
always-on behavior use a `.cursor/rules/*.mdc`. Adding a Cursor skill means adding its
`.claude/skills/` pointer in the same change, so the two harnesses stay in step.
