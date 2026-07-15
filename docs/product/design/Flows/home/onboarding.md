# Flows/home/onboarding.md — Shop Connection & First Report

> Follows successful login + mode-select ([`login.md`](login.md)). Ends at the
> sparse launcher ([`../../Screens/home.md`](../../Screens/home.md)).

## Steps

1. **Shop connection** — seller authorizes Juli against their TikTok Shop account
   (Partner API OAuth). Progress shown as a short 2–3 step indicator
   (`Components/progress-bars.md` Standard progress) — connecting, verifying,
   done — never a bare spinner with no explanation of what's happening.
2. **Permissions** — Juli explains, in Vietnamese, exactly which data it will read
   (orders, products, inventory) and why (per [`../../soul.md`](../../soul.md)
   pillar 2, Trusted —
   this is a trust moment, not boilerplate to skip past).
3. **Shop profile classification** — backend classifies the shop `NEW_SHOP` vs.
   `MID_LARGE_SHOP` (repository-root `CONTEXT.md`); this is silent to the seller — no
   UI step asks them to self-classify.
4. **Collecting data** — immediately after connection, Home shows a truthful notice
   above the Decisions and Analytics launcher cards. KPI availability belongs to
   `/analytics`, not Home.
5. **First analysis available** — once the minimum evaluation window passes, notify
   the seller that Analytics has data; do not inject charts or metrics into Home.
6. **Autonomy mode selection** — seller is asked, once, how hands-on they want
   Decisions to be by default (e.g. review every recommendation vs. a lighter-
   touch cadence). This setting only affects notification/reminder cadence — it
   never grants Juli permission to execute without approval. The choice is saved
   under `/settings`; the human-approval gate is never configurable away.

## Error states

| Case | Copy pattern |
|---|---|
| OAuth denied/cancelled | Explain nothing was connected and offer to retry — never leave the seller on a dead-end screen |
| Shop already connected elsewhere | State the conflict plainly and explain the resolution path |
| Partner API timeout | State the connection is taking longer than usual, offer retry, not a silent infinite spinner |

## Platform parity

Same steps and copy on web/mobile-web/native. OAuth redirect mechanics differ by
platform (webview vs. native browser handoff) but the seller-visible steps and
Vietnamese copy are identical ([`../../flows.md`](../../flows.md) §Platform parity).
