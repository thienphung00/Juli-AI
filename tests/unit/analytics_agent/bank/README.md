# Chat regression bank

Owner decision #109: every Chat question that has passed must keep passing before any tag.

| File | What |
|------|------|
| `cases.json` | the bank: one case per seller question (Vietnamese as sellers write it) |
| `test_chat_bank.py` | runs every case end to end on the seeded shop (SQLite), one test id per case |
| `tests/integration/analytics_agent/test_chat_bank_pg.py` | the `"pg": true` cases on real Postgres, with the production `ServiceData` |
| `ratchet.json` + `test_bank_ratchet.py` | the bank only grows: removed, changed or unrecorded cases fail |
| `advisor_cases.json` + `tests/integration/analytics_agent/test_chat_bank_advisor.py` | the opt-in paid set (real parser, router and advisor), not run by default |
| `runner.py`, `world.py`, `sqlite_data.py` | the runner, the seeded shop, the SQLite dialect adapter |

No paid call runs in the bank. The parser output (`intents`) and the router answers (`jev`)
are written into the case, so a case pins what Chat does with a given parse. The paid set
checks the parse itself.

## Add a case

1. Append an object to `cases.json`:
   - `id` (unique, kebab-case), `area` (see `test_bank_covers_the_owner_areas`), `question`
     (paraphrased, invented figures, no client names or shop ids: the repo is public).
   - `intents`: the parser output, only the fields that differ from `runner.INTENT_DEFAULT`
     (English phrases, as the parser writes them; `metric_key` = the registry key).
   - `jev`: the router answers (defaults: a clear lookup of the parsed metric). A value is a
     clear pick, or `[[pick, p], ...]` for a split router. One object per intent as a list.
   - optional: `as_of`, `platform`, `template`, `jev_down`, `parse_fails`, `ungated` (a known
     profit: the 70 % gate lowered for Chat and the tabs alike), `writer` (the writer LLM's
     text), `then` (a follow-up tap on the `needs_choice`), `pg` (also run on Postgres).
2. `expect`: `stop` (the stop reasons, in order), `routes` (per intent: outcome, mode, lookup,
   metric, window, entity, chain, card_type), `answers` (per data answer: `window` start,
   `title_vi` / `title_has`, `rows_have`, and `screen` + `from` / `to` for the figure the tab
   shows, e.g. `overview.gmv`, `voucher.orders`, `kol.orders`, `product.1001.profit`,
   `metric_view.gmv` for a ranking; `missing_as` for a missing figure; `before_screen`), plus
   `events`, `no_events`, `require`, `no_numbers`, `more_items`, `needs_choice_item`,
   `followup`. Never write a figure by hand: the check reads the screen's service.
   Every answer is also checked for the freshness line, no `0` where the screen has no
   figure, no internal keys and no forbidden words (`runner.FORBIDDEN`).
3. A case that fails today because of a known gap: `"status": "xfail"` and `"reason"` naming
   the gap. It runs `xfail(strict=True)`: the fix makes it pass, the run fails, and the
   marker must come off. A case waiting for tag 2: `"status": "pending"` (also strict).
   There is no skip.
4. Run the bank, then record it:

       PYTHONPATH=$PWD/backend/src:$PWD .venv/bin/python -m pytest tests/unit/analytics_agent/bank -q
       PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.ratchet --update

   Changing or removing a recorded case (a looser expectation, a pass turned xfail) shows in
   the `ratchet.json` diff and needs the owner's OK; removal also needs `--allow-remove <id>`.

## The paid set

Estimate first and ask the owner before running:

    PYTHONPATH=backend/src:. python scripts/chat_bank_advisor_cost.py
    JULI_CHAT_BANK_PAID=1 fasttrack/bin/pg-test.sh tests/integration/analytics_agent/test_chat_bank_advisor.py -m live

## The generated bank (every combination)

`dimensions.py` enumerates the dimensions from the code (windows, scopes / entity words,
every registry metric key, outputs, card kinds, goals, advisor tools, draft kinds, templates,
1..5 intents); `combos.py` builds every combination at the structured-intent level (the parse
is given), the ORACLE (`data_expect` and the family tables: what a correct Chat answers, each
rule written once) and the GAP RULES (one per known gap, a predicate over the dimensions plus
the problem lines it explains). `test_chat_bank_combos.py` runs them:

- default = the deploy gate: a covering array (every pair of every two data dimensions and every
  period x metric x scope triple) plus every non-data combination;
- `-m bank_full` (or `JULI_BANK_FULL=1`) = the full cross product, nightly / before a tag.

A combination passes, or xfails with the gap rules that explain all its problems, or FAILS (a
problem no rule explains). Mismatch cases (a scope that cannot carry the metric, a card kind
that does not move it; `combos.MISMATCH_RULE`) are pinned to their CURRENT outcome bucket.
`combo_record.json` holds each rule's footprint (count + hash) and each mismatch bucket; the
last test compares them, so a fix or a regression inside a rule moves the record. Re-record
after a change (one process at a time):

    PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.combo_eval --gate
    PYTHONPATH=backend/src:. python -m tests.unit.analytics_agent.bank.combo_eval --full

New dimension value: add it to `dimensions.py` (with its code constant), its words to
`text_variants.py`, then regenerate `text_variants.json` and `paid_sample.json`
(`python -m tests.unit.analytics_agent.bank.text_variants` / `.paid_sample`) and re-record.
A fixed gap: narrow or delete its rule, then re-record.
