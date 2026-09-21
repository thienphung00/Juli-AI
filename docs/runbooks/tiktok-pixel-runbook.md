# TikTok pixel and Events API runbook

One TikTok data source, `DAO9C6JC77U88MSNU74G`, fed by two connections:

| Connection | Where it runs | What carries it |
|---|---|---|
| Pixel (browser) | every visitor's browser | `TikTokPixel` in each app's root layout |
| Events API (server) | the Next.js process of each app | `POST /api/tt/event` |

Both report the same events under the same `event_id`. TikTok collapses a
pixel event and an Events API event sharing an event name and an `event_id`,
arriving within 48 hours, into one conversion — keeping the first and
enriching it with the second. That is why the two channels are additive rather
than double-counting, and why `event_id` is not optional.

Code: [`packages/tiktok-events`](../../packages/tiktok-events/MODULE.md).

## What is reported

| Event | Standard? | Fires when |
|---|---|---|
| `Pageview` | yes | every document load (base code), and every Demo route change |
| `ViewContent` | yes | the landing page mounts |
| `StartDemo` | no — custom | a click on any link to `demo.app-juli.com` from the landing page |
| `CompleteRegistration` | yes | a Google sign-up completes on the Demo, once per seller per browser |

`StartDemo` is custom because TikTok's standard list has no name for "clicked
through to a product demo". Both standard events can be selected as campaign
optimisation goals; a custom one can too, once TikTok has seen enough of them.

## First-time setup

The browser channel needs nothing — it is live as soon as the apps deploy.
The server channel needs a token.

1. **Generate the token.** Events Manager → the data source → Settings →
   Events API → *Generate access token*. It authorises writes to this one data
   source and nothing else.

2. **Store it.** On the VPS, as root — the value must not pass through a shell
   history, a commit, or a chat message:

   ```bash
   aws secretsmanager create-secret \
     --region us-east-2 \
     --name juli/frontend/production \
     --secret-string "$(jq -n --arg t "$(cat)" '{TIKTOK_EVENTS_API_ACCESS_TOKEN: $t}')"
   # paste the token, then Ctrl-D
   ```

   Rotating later is `update-secret` with the same shape.

3. **Pull it onto the host.**

   ```bash
   sudo ./infra/scripts/fetch-secrets.sh          # writes /etc/juli/frontend.env
   sudo systemctl restart juli-landing juli-demo  # or just deploy
   ```

Until step 2 exists, nothing breaks: `fetch-secrets.sh` treats this secret as
optional (making it mandatory would stop `juli-api` booting, since the script
is its `ExecStartPre`), the relay answers `503`, and the browser channel keeps
reporting on its own.

## Verifying

```bash
# The pixel is in the served HTML:
curl -s https://app-juli.com/ | grep -c "ttq.load('DAO9C6JC77U88MSNU74G')"   # 1

# The relay refuses a foreign origin:
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://app-juli.com/api/tt/event \
  -H 'Content-Type: application/json' -H 'Origin: https://example.com' \
  -d '{"event":"StartDemo","event_id":"probe"}'                             # 403

# The relay accepts our own, and says whether it is configured:
curl -s -X POST https://app-juli.com/api/tt/event \
  -H 'Content-Type: application/json' -H 'Origin: https://app-juli.com' \
  -d '{"event":"StartDemo","event_id":"probe-1"}'
# {"status":"accepted"}    -> delivered to TikTok
# {"status":"unavailable"} -> no token on the host; see setup above
# {"status":"failed"}      -> TikTok rejected it; the reason is in the journal
```

```bash
# What the server channel is doing, on the host:
journalctl -u 'juli-landing*' -u 'juli-demo*' --since '1 hour ago' | grep tiktok-events
```

A missing token logs at most once a minute, not once a visitor — so an empty
grep over a busy hour means the token is present, not that nothing happened.

To watch events arrive without polluting live conversions, set
`TIKTOK_EVENTS_API_TEST_EVENT_CODE` (Events Manager → Test Events) in the same
secret and restart. Unset it again afterwards: with it set, nothing is
reported.

## Where the token lives, and why there

`/etc/juli/frontend.env`, a file of its own, read by `juli-landing`,
`juli-demo`, and by the transient candidate units both deploy lanes promote.

- **Not `landing-runtime.env` / `demo-runtime.env`.** Both deploy scripts
  truncate and rewrite those on every release (`write_runtime_env`,
  `write_demo_runtime_env`), so a secret there survives until the next deploy
  and no longer.
- **Not a `NEXT_PUBLIC_*` value, ever.** Next inlines those into the browser
  bundle at build time, which would publish the token.
- **Passed to the candidates explicitly.** Before this, the Landing and Demo
  lanes started their candidate with `systemd-run` and no `EnvironmentFile` at
  all — only the API lane passed one. A promoted candidate would therefore
  have had no token, and the server channel would have stopped silently after
  every deploy. `deploy.sh` and `deploy-demo-release.sh` now pass
  `--property=EnvironmentFile=-/etc/juli/frontend.env`.

## What bounds abuse

`/api/tt/event` is unauthenticated, because an anonymous visitor reporting
their own pageview cannot be authenticated. What bounds it:

- **Origin allowlist** — stops another site's JavaScript writing into the data
  source. It does not stop a script that sets the header itself; nothing can.
- **Event-name allowlist and a closed schema** — only the four events above,
  only recognised properties, only values of the right shape. Nothing else
  reaches TikTok.
- **Identifiers must be SHA-256 digests** — the browser hashes before sending,
  so no raw address ever reaches a Juli server or TikTok through this path.
- **`limit_req zone=tiktok_relay` (10 r/s, burst 20)** at nginx, per visitor
  address — `infra/nginx/rate-limits.conf`.
- **Server-set event time** — taken from the server clock, never the body.

## Consent

There is no consent gate. The sites have no cookie banner today and no
jurisdiction served requires one of them. The pixel's own
`ttq.holdConsent()` / `ttq.grantConsent()` are the hooks to use if that
changes — hold before `ttq.page()` in the base code, grant when the banner is
accepted, and gate `relayTikTokEvent` on the same decision.
