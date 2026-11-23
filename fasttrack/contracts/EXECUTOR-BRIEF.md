# Executor brief — template (copy per slice; fill every section; delete nothing)

`[ARM:SLICE]` goes at the start of the subagent description, e.g. `[B:b1-s2] Combo estimate`.

## 1. Slice
- Batch branch / worktree: `…` (absolute path). Start with `cd "<path>" || exit 1` and confirm `git rev-parse --show-toplevel`.
- Base: the batch branch at `<sha>`, which contains deploy tip `<sha>` (`state.py check` was OK at `<time>`).
- Owned paths (edit only these): `…`. Anything else is a routing error: stop and report it.
- Migration: none | `NNN_name`, claimed in state by `<session>`.

## 2. Goal
One paragraph, in the owner's words where possible.

## 2b. Restate before building (required first output, before any edit)
In 3–5 bullets: what each domain term in this brief means (check `fasttrack/GLOSSARY.md`) and what is in and out of scope. Then **stop**. The coordinator checks the bullets against the glossary and the acceptance table. A term that isn't in the glossary, or a scope doubt, goes to the owner (`state.py ask`). Don't start until the coordinator confirms.

## 3. Acceptance table (approved by the owner at grill close; the verifier checks every row)
| id | requirement | source (grill Q# / canvas board / standing rule / prompt) | verification (test id / Chrome walk on sample shop / SQL-API check) | evidence (executor fills) |
|---|---|---|---|---|
| A1 | | | | |
| R1… | apply each standing rule `fasttrack/bin/brief_rules.py <this brief>` prints (memory notes + `state.py decide` decisions) | standing rule (W47 M9) | verifier checks the diff against each note | |
| PLATFORM | (when brief_rules.py prints it) real page capture or sandbox probe + the doc it was checked against, **before the first edit** | standing rule (W47 M10) | capture/probe path + doc URL in `## Sources` | |
| LIB | (when brief_rules.py prints it) Context7 lookup for each library API touched | standing rule (W47 M8a) | lookup cited in `## Sources` | |
| LIVE | after deploy, the live numbers this slice touches are right | standing rule (deploy ≠ correct) | sample shop + 1 real shop (read-only): dashboard GMV, đơn, AOV, ads, profit, both margins vs a direct read-only SQL/API query, same window; every mismatch listed with its cause | |

Standing rules that always apply (from `fasttrack/UI-PRINCIPLES.md`, when the slice touches UI):
no explanatory captions or "ước tính" badges; Shop = all products (the default); the north-star tab flow; the traffic hierarchy.

## 4. Retrieval: required BEFORE the first edit, recorded in `## Sources` of the report
- Repo: the `MODULE.md` of every module you touch; the existing implementation of the same concept (grep for it first and reuse; never add a second formula); `fasttrack/DECISIONS.md` entries named here: `…`.
- Memory notes for the touched areas: the `§4` list `fasttrack/bin/brief_rules.py <brief>` prints (the coordinator runs it and pastes the R/D/PLATFORM/LIB rows into §3). Read each note and apply it. The script's output is local only: it can name clients, so it never goes into a committed file.
- Platform docs when the slice touches vendor behaviour (the PLATFORM row; a capture of the real page or a sandbox probe comes first, then the code): Shopee (Seller Centre / Shopee Uni via Chrome, `platform-docs` skill), TikTok Shop (the `tts-*` skills, Partner Center OpenAPI). Cite the page; never guess a field or a lag.
- Library docs: `npx ctx7@latest docs <library> <topic>` for every library API the slice touches (the LIB row), not only when unsure.

## 5. Rules
- TDD: write the failing test from the acceptance row, then make it pass. Never weaken, skip or xfail a test.
- Run targeted tests and `fasttrack/predeploy.sh --fast`. Never run whole suites (only the coordinator's `predeploy.sh` does, and it takes the `state.py suite-lock`; whole suites normally run on GitHub).
- Postgres tests: `fasttrack/bin/pg-test.sh <path>`. Any command for the owner goes through `fasttrack/bin/cmdlint.py` first.
- Wait for background jobs with Monitor; don't end your turn on a running job.
- No client data in fixtures, commits or PR text (the repo is public).

## 6. Report (your caller can't see your transcript)
```
## Sources        files / notes / doc URLs actually read
## Acceptance     the table, evidence column filled; any row not met = NOT DONE, say why
## Tests          commands run + pass/fail counts (paste the summary line)
## Not done       anything cut, deferred or uncertain
## Owner asks     questions that need the owner (also `state.py ask`)
```
"Done" with an empty evidence cell is a failed slice.
