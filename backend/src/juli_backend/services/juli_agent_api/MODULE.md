# backend/src/juli_backend/services/juli_agent_api

## Purpose

The Juli tab's HTTP-facing service (batch-1120 T3): a seller's question, the answer's event
stream, the shared history, and Gửi / Bỏ qua on an engine card. Routes:
`api/routes/juli_agent.py` (`/v1/demo/juli`). Storage: migration 137, `models/agent_chat.py`.
Contract: `fasttrack-notes/2026-11-20/juli-tab/CONTRACT.md` (owner workspace).

## Files

| File | Does |
|---|---|
| `config.py` | `JULI_AGENT_ENABLED` (off by default; `true` or a list of shop UUIDs), limits 30/h, 200/day |
| `chat.py` | `start_ask` (one running answer per conversation, limits, needs_choice pending), cancel flag, history |
| `events.py` | `PersistingSink` (the engine's `EventSink`), `event_stream` (SSE replay by `Last-Event-ID`) |
| `runner.py` | `execute` / `schedule`: the run as a task, ending rows in one transaction |
| `engine.py` | the only file naming T1 (`analytics_agent`) and T2 (`llm_gate`); read-only analysis sessions |
| `cards.py` | send through `shopee_recommendations.manual.create_manual(origin="agent")`, dismiss |

## Rules

- Analysis sessions are read-only at the database (`default_transaction_read_only`); only
  conversation / message / routing / draft rows and the sent card are written.
- `done.routing` and `needs_choice.pending` never reach the client.
- History is shared per shop; nothing expires.
- The service never commits on the request session; the route does.
