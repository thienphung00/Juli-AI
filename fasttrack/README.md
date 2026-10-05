# fasttrack/ — how agents work on this branch

Branch: `fasttrack/optimize-product`. Cut from `main` at `0332c405` on 2026-10-05.
`main` is frozen until this branch merges back once (DECISIONS D2).

This folder replaces the PRD → issue → slice → Executor → Review loop and its
validators (D4). It is the spec, the acceptance criteria, the progress tracker
and the log, all in one place.

## Read order (every agent, every session, before touching code)

1. `README.md` (this file)
2. `SPEC.md` — what we are building. The source of truth.
3. `PROGRESS.md` — the current phase, what's done, what's next.
4. `ACCEPTANCE.md` — the ACs for the task you are picking up.
5. `DECISIONS.md` — only when something in SPEC seems ambiguous.
6. The last ~5 entries of `LOG.md`.

## Rules

- **Work only on tasks in `PROGRESS.md`.** If you need something that isn't
  there, add it as a new task with a one-line reason, then do it.
- **Tick an AC only with evidence**: a commit SHA, a test name, a query and its
  result, or a log line. Write the evidence next to the AC.
- **Append to `LOG.md` before you stop**: date, who (agent/model), what
  changed, what broke, what's next. Never rewrite old entries.
- **Every shortcut goes in `DEBT.md`**: a skipped gate, a test not written, a
  hardcoded value, a TODO. Debt is repaid before the merge into `main`.
- **A new decision goes in `DECISIONS.md`** with the next D-number. Decisions
  that change SPEC need the owner; note them as "PROPOSED" until confirmed.
- **Small commits**, conventional-commit style, on this branch. No PRs needed.
- **Never push to `main`. Never force-push.** Merging is the owner's.
- **Production safety rules still apply** (D8): anything touching the database,
  credentials, tenant isolation or TikTok writes needs a test.

## Running checks locally

```bash
fasttrack/check.sh            # what the deploy runs: backup-free local subset
```

In a git worktree, run pytest with `PYTHONPATH=backend/src` (or the
worktree's own venv). A bare `pytest` can import the main checkout's code
instead.
