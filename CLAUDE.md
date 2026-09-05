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

- **Preflight before you edit.** `python agent-runtime/scripts/git/checkout_preflight.py --fetch`
  must not print `FAIL`. Blocking conditions: base ≥50 commits / ≥7 days behind `origin/main`;
  the primary working directory off `main`; `main` held by a side worktree; a worktree outside
  `.worktrees/`; a stray `.git` directory in the tree. Enforced by
  `.claude/hooks/checkout_preflight_gate.py` on every write — override only with
  `JULI_SKIP_CHECKOUT_PREFLIGHT=1` and a stated reason.
- **The primary working directory stays on `main` and clean.** All task work happens in a
  worktree: `git worktree add .worktrees/<task> -b feature/<desc> origin/main`. One writer per
  tree. Sub-agents never `checkout`/`reset`/`stash` in the primary directory.
- Short-lived `feature/<short-desc>` cut from `main`. Never push to `main` directly.
- Conventional commits: `feat|fix|refactor|docs|test|chore|perf|ci: <description>`.
- **Two lanes** (pick by what the diff touches): **Standard** — any code, or mixed code+docs: branch/worktree → PR → land on green → close. **Fast-track** — non-code only (`*.md`/`*.mdc`/`*.txt`, `docs/**`, `.cursor/rules|skills/**`; zero code edits): short branch → PR → immediate `gh pr merge --squash --delete-branch --admin`, **with the bypass reason recorded on the merge** (`bypass: fast-track docs-only, <what changed>`; #1436). A **harness-path-only** PR (touching only `.cursor/skills/**` / `agent-runtime/docs/**`) is the second sanctioned `--admin` case — it cannot go green by construction, since `harness_bootstrap_pinned` compares the anchor against the working tree; record `bypass: harness sourcePath change, re-pin to follow` and **refresh the pin afterwards**, or every later PR on that branch inherits the red. Any code file in the diff ⇒ standard lane. `git commit --no-verify` is never sanctioned — fix the hook. Both lanes go via a PR.
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

## Code standard

Backend Python follows one explicit standard, demonstrated by exemplar modules already in
the tree. Before adding a repository, service, route, or test, open the exemplar for that
kind of change and match its shape. Do not invent a second shape.

| Adding a… | Copy |
|-----------|------|
| repository | `backend/src/juli_backend/repositories/_base.py`, then `backend/src/juli_backend/repositories/commerce.py` |
| service behind a route | `backend/src/juli_backend/services/agent_runs/` |
| route | `backend/src/juli_backend/api/routes/agent_runs.py` |
| infrastructure shared by two features | `backend/src/juli_backend/services/kpi_cache/` |
| test | `tests/unit/test_repositories_base.py`, `tests/unit/test_kpi_caches.py`, `tests/unit/test_agent_run_event_stream.py`; fixtures and doubles from `tests/support/` |

Rules: [`.cursor/rules/code-quality.mdc`](.cursor/rules/code-quality.mdc) (Focus loads it
for every code change). Long form with before/after excerpts:
[`docs/architecture/code-standard.md`](docs/architecture/code-standard.md). Tests:
[`python-testing.md`](.cursor/skills/domain/testing-patterns/python-testing.md).
`tests/unit/test_code_standard_exemplars.py` fails CI when a path these documents name
stops existing, so the pointers cannot rot silently.

## Agent phase model

| Phase | Agent | Model | Sequence |
|-------|-------|-------|----------|
| Planning | `architect` | Opus | `focus` → `grill-with-docs` → `to-prd` → `to-issues` |
| Implementation routing | `meta` | Sonnet | `focus` → `meta_prepare_executor.py` → assign one executor domain |
| Implementation | `executor-<domain>` | Haiku (`ui-ux`: Sonnet) | domain skill + built-in TDD (red → green → refactor) |
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

**Parallel orchestration.** One task, one worktree, one writer; disjoint write paths across
concurrent sub-agents; read-only agents get an explicit prohibition on `worktree remove`,
`branch -d`, `clean`, `commit`, `push`, `checkout` — the tool list alone does not convey it.
The parent runs the preflight before delegating and closes every worktree it opens
(`worktree_gc.py --close <task>`). Pin `PYTHONPATH` when running pytest in a worktree or the
green is fake. Full contract: [`.cursor/rules/core-orchestration.mdc`](.cursor/rules/core-orchestration.mdc).

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
filesystem, unaffected by gitignore). **Do not `git add -f` them.** Because they are
gitignored, they never reach the pushed branch, so no CI step ever checks them out or
uploads them — `pr.yml` has no `upload-artifact` step for these directories and cannot
have one (corrected 2026-08, #1064; the previous wording here claiming an issue-tier CI
upload described a mechanism that never existed — verified by grep across
`.github/workflows/`). The committed merge-time source of truth is the compact record at
`agent-runtime/artifacts/status/issue-<N>.json`, generated by
[`generate_status_records.py`](agent-runtime/scripts/ci/generate_status_records.py) from a
review + validation pair. `tests/unit/test_status_record_gate.py` fails CI on any tracked
`*.json` under those five directories.

**Artifact retention guard (#1064).** Beside the Meta gate above: an issue-tier PR whose
head branch resolves to issue `<N>` fails CI when `agent-runtime/artifacts/status/issue-<N>.json`
is absent, or present but not a `PASS` record — the one artifact CI can actually see,
since it is the only one of the six directories under `agent-runtime/artifacts/` that
stays tracked. Job `artifact-retention-guard` in `pr.yml` (existence + status check only,
via [`check_artifact_retention_guard.py`](agent-runtime/scripts/ci/check_artifact_retention_guard.py))
reuses `classify-tier`'s `tier == 'issue'` and `resolve-issue`'s branch parsing — it is
fail-closed (missing/malformed/unreadable/wrong-schema all fail, never a silent pass) and
red until the status record lands, by design: that is the earliest point a Wave-2-style
silent artifact loss (ADR-079) becomes visible instead of surfacing only at wave→main.
Not wired into required branch-protection checks — that is a repository-settings change
for the owner, not a code change.

## Skills governance

Do **not** create skills under `.cursor/skills/` or `.claude/skills/` unless the user
explicitly asks in the conversation. For repeatable prompts use `docs/handoffs/*.md`; for
always-on behavior use a `.cursor/rules/*.mdc`. Adding a Cursor skill means adding its
`.claude/skills/` pointer in the same change, so the two harnesses stay in step.
