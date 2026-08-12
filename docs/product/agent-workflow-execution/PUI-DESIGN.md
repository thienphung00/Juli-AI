# P-UI Design Spec — Optimize Product execution experience

**Status:** Design settled 2026-08-12 (grill session, [ADR-076](../../adr/076-agent-demo-execution-experience.md)).
**Mandate:** structural design policy is lifted for these surfaces (user directive) —
layout, components, flows, and **visual identity (theme tokens)** may be redefined for
the Optimize Product workflow (all its states/flows) + the In-Progress sub-tab, and
**motion is a first-class requirement**, especially for response streaming.
**Still binding:** Vietnamese copy via `dictionary.md` + "bạn" voice; the other 10
workflows' existing flows; accessibility basics (focus, contrast, reduced-motion).
The event protocol is consumed as-is; new events may be **requested additively**
(flagged as ADR-074 amendments, never improvised client-side).

---

## 1. Entry flows (dual entry)

```
                    Landing
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
  [ Dùng thử Demo ]          [ Đăng nhập với Google ]
        │                             │
  Supabase anonymous            Supabase Auth (Google
  sign-in → real JWT            provider) → real JWT
        │                             │
  active shop pinned to         "Kết nối TikTok Shop"
  the reference shop            (live merchant OAuth —
  (structural, not a flag)      wired in a follow-up;
        │                       screen built now)
        ▼                             ▼
    Decisions tab               own shop, own data
```

- **Demo sessions are real authenticated sessions** (anonymous JWT) — ADR-075 holds
  with zero carve-outs. Each visitor is a distinct user: distinct audit rows, and
  rate buckets keyed **per user-session** on the demo shop (config).
- Demo runs are **recorded replays** of real sandbox runs (golden scenarios) served
  through the identical SSE endpoint; live mode sits behind a config flag (used for
  the phase gate, stakeholder demos, and later real users). An anonymous session can
  be upgraded to a Google identity later (Supabase identity linking).
- **Realism requirements (replay must seem real):** paced by recorded timestamp
  deltas (the LLM's thinking pauses included); timestamps rebased to now; typewriter
  on `assistant.text`; the decision request is genuinely interactive — the visitor's
  pick selects its recorded continuation; no replay tells in the UI.

## 2. The staged run view

One stage on screen at a time (cognitive-load directive). Approve navigates to a
dedicated run page; a **top stepper** carries position; the stage owns the full
canvas. Back = revisit frozen completed stages; forward = return to the live edge;
stages beyond the edge are locked. Finished runs open in the same view with all
stages frozen (replay-powered history).

```
┌────────────────────────────────────────────────────┐
│ ← Quyết định        Tối ưu sản phẩm     ● Đang chạy │
│  ✓───────✓───────✓───────[◉ Đề xuất]───○───────○   │
│  Phân    Thông   SEO      Đề xuất   Cập     Hoàn   │
│  tích    tin                        nhật    tất    │
├────────────────────────────────────────────────────┤
│                                                    │
│                 (stage canvas)                     │
│                                                    │
│  [← Xem lại]                          [Tiếp →]     │
└────────────────────────────────────────────────────┘
```

### Stage model (derived from playbook + events, not invented)

| # | Stage (VI) | Content | Driven by |
|---|---|---|---|
| 1 | Phân tích | Thinking state → agent's case summary (signals narration) | `workflow.started`, first `assistant.text` |
| 2 | Thông tin sản phẩm | Product snapshot digest | `tool.*` for `get_product_information` |
| 3 | SEO | Keywords found, coverage highlights | `tool.*` for `get_seo_keywords` |
| 4 | Đề xuất | **The decision request** — N option cards (§3) | `workflow.approval_required` |
| 5 | Cập nhật | Writes executing; selected option as header | `tool.*` for `update_*`/`upload_*` |
| 6 | Hoàn tất | Final summary, actions taken, honest outcome | `workflow.completed`/`failed` |

- A thinking/loading state is a **stage state**, not a separate screen.
- During Đề xuất the run is paused server-side — back-navigation to verify SEO/
  analysis before choosing is explicitly encouraged by the layout.

## 3. Đề xuất — the option picker (consent-grade)

This click authorizes a real mutation; the interaction is designed like consent:

```
│  Juli đề xuất 3 mức giá:                          │
│  ┌─────────┐  ┏━━━━━━━━━┓  ┌─────────┐           │
│  │ ₫189.000│  ┃ ₫199.000┃  │ ₫209.000│           │
│  │ 219k→189k│ ┃ 219k→199k┃ │ 219k→209k│          │
│  │ lý do…  │  ┃ lý do…  ┃  │ lý do…  │           │
│  └─────────┘  ┗━━(chọn)━┛  └─────────┘           │
│  Đề xuất còn hiệu lực 3 giờ 58 phút               │
│  [Không thực hiện]      [Xác nhận phương án này]  │
```

- **Option card anatomy:** proposed value prominent; **before → after diff rendered
  on a miniature of the actual listing element** (price on the product card; titles:
  old struck / new highlighted); 2–3-line rationale from the option's `rationale`;
  expected-effect line sourced from the signals payload (never invented client-side).
- **Two-step consent:** select (card elevates, siblings dim, CTA arms) → confirm.
  No single click authorizes anything.
- **Decline is quiet and first-class:** "Không thực hiện" — copy states the outcome
  (Juli hoàn tất mà không thay đổi). It is a choice, not a failure exit.
- Subtle 4h expiry countdown; stepper shows the run is waiting on the seller.

## 4. In-Progress sub-tab — the run ledger

Three priority sections; every card is a real `workflow_run`:

1. **Đang chờ bạn** (`waiting_approval`) — pinned top, visual weight, pending-
   decision summary + expiry countdown. Click → straight into Đề xuất.
2. **Đang chạy** (`queued`/`running`) — status chip, mini-stepper dots (6 stages),
   latest narration line so the card breathes. Active run's card subscribes to its
   stream (≤1–2 active per session, inside the 10-stream limit); others refetch.
3. **Hoàn tất** — honest, distinct terminal states: completed ✓; completed-with-
   decline ("Bạn đã chọn không thay đổi giá" — a choice); cancelled; timed out;
   failed with seller-terms reason; `worker_lost` honest ("Juli gặp sự cố khi thực
   hiện"). No state dressed as another.

No retry-in-place: a failed run's card explains and points to the Decisions tab (a
new run requires a new approval — the gate's design). Clicking any finished run
reopens the frozen staged view via the replay endpoint.

## 5. Motion spec

| Moment | Motion | Duration/easing | Reduced-motion |
|---|---|---|---|
| Stage advance | Canvas slides left, stepper node fills | 320ms ease-out | Crossfade 150ms |
| `assistant.text` | Typewriter reveal (block-paced, ~30ms/char cap) | — | Full text fade-in |
| Thinking state | Soft breathing indicator on the active stepper node | 1.6s loop | Static pulse dot |
| Option cards arrive | Stagger-in, 150ms offsets (agent "presenting") | 240ms each, ease-out | Simultaneous fade |
| Select option | Card elevates, siblings dim to 60% | 180ms | Border emphasis only |
| Confirm → Cập nhật | Selected card animates forward into the next stage's header | 400ms ease-in-out | Cut with header carry |
| Tool chip complete | Check-in with subtle scale settle | 200ms | Instant check |
| Terminal (Hoàn tất) | Stepper completes in sequence, then summary rises | 600ms total | Fade |

Motion is choreography for the stream — every animated moment corresponds to a real
event; nothing animates to fake progress.

## 6. Visual identity (scoped to these surfaces)

Token freedom is granted for this surface. Direction (final palette at
implementation with the `ui-ux-design` skill): a **focus surface** — quieter ground
than the dashboard (reduced chrome, deeper neutral), a single accent reserved for
the live edge (stepper active node, streaming caret, armed CTA), and semantic
status colors unchanged from the app's meaning system (success/warn/error). Type may
gain a distinct display treatment for the agent's narration. New tokens are defined
in a scoped layer (`packages/theme` extension or surface-local tokens), never by
overwriting the app-wide values.

## 7. Copy table (to land in `dictionary.md` with implementation)

| Key | EN | VI |
|---|---|---|
| `demo.try` | Try the Demo | Dùng thử Demo |
| `auth.google` | Sign in with Google | Đăng nhập với Google |
| `auth.connect_shop` | Connect TikTok Shop | Kết nối TikTok Shop |
| `run.status.running` | Running | Đang chạy |
| `run.awaiting_you` | Waiting for you | Đang chờ bạn |
| `run.confirm_option` | Confirm this option | Xác nhận phương án này |
| `run.decline_option` | Don't apply | Không thực hiện |
| `run.reconnecting` | Reconnecting | Đang kết nối lại |
| `run.declined_note` | You chose not to change the price | Bạn đã chọn không thay đổi giá |
| `run.worker_lost` | Juli hit a problem while executing | Juli gặp sự cố khi thực hiện |
| `run.expiry` | Offer valid for {time} | Đề xuất còn hiệu lực {time} |

Existing terms (Đề xuất, Phê duyệt, Đang thực hiện…) are reused, never renamed.

## 8. Client architecture

- **`useRunStream(runId)`** — fetch-streaming SSE (bearer in headers), tracks
  `lastSeq`, backoff reconnect with `Last-Event-ID`, emits the typed event union.
- **Pure reducer** `RunViewState = reduce(events)` → `{stages[], liveEdge,
  currentStage, decisionRequest?, terminal?}`; stage derivation is the §2 mapping
  table. Golden fixtures test it directly; **replay and live share one code path by
  construction**.
- Mock layer retired for this workflow: `startExecution`/localStorage deleted;
  `fetchRecommendations()` path bug fixed; silent fixture fallback removed (failures
  surface honestly). State local to the run view; run list via refetch.
- **Reconnect UX:** stream error ≠ run error. Dropped stream → quiet inline "Đang
  kết nối lại…" while the run continues server-side; reconnect folds missed events
  through the reducer (gapless); closed tab → In-Progress reopens the full view from
  replay. Offline → calm banner, auto-retry, never a modal.

## 9. Tests & gate

Reducer units on golden fixtures (every event type + full scenario logs); component
tests (two-step consent, decline, stepper navigation incl. locked future); **replay-
based Playwright E2E in CI** (deterministic: Try Demo → approve → stages → pick
₫199k → completion); a11y (reduced-motion, focus order, contrast on new tokens);
regression — the other 10 workflows' flows stay green.

**Gate:** replay E2E green in CI + one observed live-mode run (flag on, real GPT-5.4
nano + sandbox) end-to-end in browser + dictionary entries landed + `apps/demo/
MODULE.md` invariant updated + this spec published + zero regressions elsewhere.
