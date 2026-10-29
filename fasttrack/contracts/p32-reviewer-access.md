# P32-A contract — partner reviewer trial account (Shopee ISV review)

Owner decision: DECISIONS **D42** (Shopee ISV resubmission), with D25.3 ("Xem như shop" is
always read-only, every write refused server-side), D25.6 / ADR-038 §8 (identity mask, real
magnitudes), ADR-038 §9 (demo execution is a dry run), D13 (what a real execute writes), D8
(database, credentials, tenant isolation and TikTok writes need tests).

> **D42 amendment (owner, 2026-10-15, P32-D).** `REVIEWER_SHOP_ID` is optional and is not set
> in production: the reviewer lands on the demo's **sample shop** ("Cửa hàng Mẫu Hoa Mai",
> P11/P13, bundled, no network) and the Fujiwa pin below applies only when the env is set.
> See §1 (no-pin row), §3 and §8.
>
> **D42 amendment 2 (owner, 2026-10-15, P32-E).** In sample mode every seller write is usable as a
> browser-side simulation over the sample fixtures (§4 note, §6). Server side nothing changes.

> **D73 amendment (owner, 2026-10-21, P64).** Shopee rejected the sample shop and simulated
> execution. With `REVIEWER_SHOP_ID` pinned to the `sandbox_write` sandbox shop, the reviewer reads
> it live and **unmasked**, sees the connection, last sync and a pin-scoped "Sync now", and
> **really executes** listing edits and image uploads through the sandbox write credential, with a
> TikTok read-back. The allowlist below gains approve / execute / sync for the pin only; every
> other shop and every production credential stay unreachable (pin gate, sandbox-only factory for
> reviewer claims, tests). Sample mode and browser simulation stay for anonymous visitors only.
> Where this contract says "simulation" or "never writes", read it as "never writes outside the
> pinned sandbox shop".

> **D77 amendment (owner, 2026-10-29, P74-A).** Shopee rejected again ("the product has to be live,
> with existing e-commerce integrations identifiable via the trial account"). The reviewer now holds
> **two pins**: `REVIEWER_SHOP_IDS=<Fujiwa shops.id>,<sandbox shops.id>` (first = default; wins over
> `REVIEWER_SHOP_ID`, which stays as the one-pin form). It opens on **Fujiwa, masked, read-only, with
> the simulated Duyệt / Thực thi** (this contract as written) and switches with `X-Shop-Id` to the
> **sandbox shop** (the D73 amendment). Each pin is classified on its own (`sandbox.classify_pin`);
> the mask, the simulation and every sandbox-only refusal follow the selected pin. Nothing the
> reviewer does writes to Fujiwa: every run / rule / Hoàn tác route and "Đồng bộ ngay" answer 403
> `sandbox_only` there. The reviewer mask never says "demo" (Shopee reads it as not live): the
> masked shop is `Shop TikTok (ẩn danh)`, products `Sản phẩm NNN`, ids `an-<kind>-…`. See §3.

A partner platform's reviewer signs in on demo.app-juli.com with a **team-created e-mail +
password**, lands on the reference shop **Fujiwa, masked** (only when pinned, see the amendment), reads Trang chủ / Phân tích /
Quyết định through the real read path, and walks **Duyệt → Thực thi** as a simulation that
shows the change Juli would send. Nothing a reviewer does can reach an executor, a Celery
queue, a TikTok write client or a write to any Fujiwa row. The guarantee is an allowlist at the
API boundary, not the UI.

## 1. Where the role lives

Two marks, both written only by the provisioning command (§6):

1. **Supabase `app_metadata`** of the auth user: `{"juli_role": "reviewer", "juli_platform":
   "shopee"}`. `app_metadata` is writable only with the service-role key (a user cannot edit
   it), and Supabase copies it into every access token. `core/security/claims.py` reads it into
   `VerifiedToken.reviewer_platform` — no database round trip for sellers.
2. **`ops_reviewer_accounts`** (migration **`090_reviewer_accounts`**, chained after
   `089_card_groups`; the deferred phone cleanup is re-parented onto 090): one row per account
   — `user_id` (the Supabase `sub`), `email`, `role` (`reviewer` only, check constraint),
   `platform` (lower-case label, e.g. `shopee`), `expires_at`, `revoked_at`, `created_by`,
   `last_session_id`, `last_sign_in_at`. An **ops table** like the 083 ones: RLS on, the only
   policy is `FOR ALL TO juli_ops`, `juli_app` / `anon` / `authenticated` get no grant
   (classified `ops_only`). A seller request can neither read nor change it.

A token that carries the reviewer mark is a reviewer session. Fail closed everywhere:

| State | Result on every `/v1` route |
|---|---|
| mark present, no `ops_reviewer_accounts` row (or another platform) | 403, `X-Juli-Reviewer-Denied: unknown` |
| row `revoked_at` set | 403, `revoked` |
| row `expires_at` ≤ now | 403, `expired` |
| gate not bound in the process (wiring bug) | 403, `unavailable` |
| `REVIEWER_SHOP_ID` set but the shop row missing | 503, `unconfigured` (on the shop-reading routes) |
| active, `REVIEWER_SHOP_ID` set (Fujiwa pin) | §2 allowlist, §3 pin + mask |
| active, `REVIEWER_SHOP_ID` **unset** (P32-D, sample mode) | §2 allowlist unchanged; `/v1/reviewer/me` → 200 `shop: null`, `/v1/shops` → `[]`, every other allowlisted (shop-scoped) route → 403 `shop`, `simulate` included |

Before P32-D an unset `REVIEWER_SHOP_ID` answered 503 `unconfigured` on every route; it no longer
does — the demo shows a `shop: null` reviewer the bundled sample shop and calls no shop route.

Account rows are cached in-process for **30 s** (`REVIEWER_ACCOUNT_CACHE_SECONDS`; 15 s before
P69), so a revoke takes effect within 30 s on every API worker; an expiry is compared with the
clock on every request (exact). The revoke also bans the Supabase user, so no new token is
minted. P69: the same TTL caches the reviewer's `users` row (keyed by the verified `sub`, read
only after the gate admits the request) and the pinned shop's row + sandbox classification
(`services/reviewer/pin_cache`); the shop's tenant scope (`SET LOCAL`) is still applied on every
request, and the sign-in claim, audits and writes are never cached. A token **without** the mark is never a reviewer (a password user created any
other way is an ordinary seller with no shop and gets the P13 sample — never Fujiwa).

Staff console: `/v1/ops/*` refuses a reviewer token outright (`get_ops_user`, 403) before the
Access / staff checks.

## 2. The gate (`api/reviewer.py`, bound into `get_current_user`)

`core/security/get_current_user` verifies the JWT; when the token is a reviewer's it calls the
bound gate **before** the `users` read and before any route code or other dependency with side
effects. Every Supabase-authenticated `/v1` route depends on `get_current_user` (directly or via
`get_active_shop` / `require_writable_shop`), so the gate sees every one. Routes that do not take
a Supabase bearer (TikTok OAuth callbacks — state-bound to the user who started, and starting is
refused; the ingest device-token routes; `/v1/ingest/pair`, which takes a one-time code a
reviewer cannot mint) cannot be driven with a reviewer's identity at all.

The gate, in order: account state (§1 table) → route allowlist → sign-in audit (§5) → sets
`request.state.juli_reviewer` (platform, account, pinned shop id and its alias).

**Allowlist** (`(method, endpoint)` — the endpoint function FastAPI matched, as
`module:function`, never the raw URL; FastAPI ≥ 0.13x keeps only the innermost router's prefix
in `route.path`, so the template alone is ambiguous. `test_allowlist_is_pinned_to_real_routes`
pins each entry to the URL template below); anything else → **403** `Tài khoản dùng thử chỉ xem · thao tác này bị chặn`,
`X-Juli-Reviewer-Denied: read_only`, audited when the method is not GET:

| Method | Route | Page |
|---|---|---|
| GET | `/v1/shops`, `/v1/shops/me`, `/v1/shops/me/term`, `/v1/shops/me/permissions`, `/v1/shops/me/onboarding` | shell |
| GET | `/v1/demo/analysis`, `/v1/demo/analysis/rankings` | Trang chủ, Phân tích |
| GET | `/v1/demo/decisions`, `/v1/demo/decisions/{action_card_id}` | Quyết định |
| GET | `/v1/demo/runs`, `/v1/demo/runs/{run_id}`, `…/changes`, `…/instructions`, `…/measurement`, `/v1/demo/revert-questions` | Quyết định (history) |
| GET | `/v1/demo/rules` | Quy tắc (read) |
| GET | `/v1/demo/content-analysis`, `/v1/demo/content-analysis/{analysis_id}` | Phân tích (read) |
| GET | `/v1/reviewer/me` | reviewer shell |
| POST | `/v1/reviewer/decisions/{action_card_id}/simulate` | Duyệt → Thực thi (§4) |

The SSE stream `/v1/demo/runs/{run_id}/events` is **not** allowed (no live run for a reviewer).

**Write paths and how each is barred** (all: not on the allowlist → 403 at the gate, before the
route body, `require_writable_shop`, rate limiter or body parsing):

| Write a reviewer could try | Route(s) | Barred by |
|---|---|---|
| Approve a card (creates a run, enqueues `run_agent_workflow`) | `POST /v1/demo/decisions/{id}/approve` | gate → 403; the UI calls `/v1/reviewer/.../simulate` instead |
| Reject a card ("Từ chối") | `POST /v1/demo/decisions/{id}/reject` | gate → 403 |
| Execute: confirm a draft (listing / image / price write, D13) | `POST /v1/demo/runs/{id}/confirmations/{tool_call_id}` | gate → 403 |
| Create / cancel a run | `POST /v1/demo/runs`, `POST /v1/demo/runs/{id}/cancel` | gate → 403 |
| Card edit ("Sửa nội dung trước khi áp dụng") | `edited_values` of the confirmation route | gate → 403 |
| Seller photo / "đã làm trên Seller Center" (image upload, promotion) | `POST /v1/demo/runs/{id}/photo`, `…/applied` | gate → 403 |
| Content publish / use / redraft | `POST /v1/demo/runs/{id}/content/{use,redraft,published}` | gate → 403 |
| Hoàn tác (revert run) / decline / dismiss | `POST /v1/demo/runs/{id}/revert`, `…/decline`, `POST /v1/demo/revert-questions/{id}/dismiss` | gate → 403 |
| Quy tắc | `PUT /v1/demo/rules/{key}`, `DELETE /v1/demo/rules/{key}` | gate → 403 |
| Uploads (content analysis) | `POST /v1/demo/content-analysis`, `PUT …/{id}/file` | gate → 403 |
| Shop connect | `GET /v1/auth/tiktok/start` (and the business OAuth starts) | gate → 403 (GET not on the allowlist) |
| Shopee shop create | `POST /v1/shops/shopee` | gate → 403 |
| Invites | `POST /v1/shop-invites/preview`, `/accept` | gate → 403 |
| Juli Connector pairing / tokens | `POST /v1/ingest/pairing-codes`, `GET /v1/ingest/tokens`, `DELETE …/{id}` | gate → 403 |
| Legacy writes | `POST /v1/action-cards/refresh`, `POST /v1/executions`, `POST /v1/outcomes`, `POST /v1/orders/{id}/confirm-shipment` | gate → 403 |
| Shop settings, Huỷ kết nối, staff, ops Quy tắc, view-as, costs, terms | `/v1/ops/*` | `get_ops_user` refuses reviewer tokens (403); not staff anyway |
| Photo bytes | `GET /v1/demo/photos/{shop_id}/{token}` | gate → 403 (GET not on the allowlist) |

`tests/unit/test_reviewer_no_write.py` enumerates **every** route of the real app (not this
table), drives each one as a reviewer with a real signed token, and fails on any status other
than the allowlist's, any TikTok client constructed, any Celery `apply_async` / `send_task`, or
any change to any table except the audit log and the reviewer's own account row (§7).

## 3. Pin + mask (D25.6 / ADR-038 §8)

**Pin.** Optional (P32-D). Unset: no pin, no shop, nothing to mask (the audit rows carry
`shop_id = NULL`). Set: the reference shop is `REVIEWER_SHOP_ID` (env, the Fujiwa `shops.id`; no shop id in
code). A reviewer never sees the real id: the shop is presented as the **alias id**
`uuid5(REVIEWER_ALIAS_NAMESPACE, "reviewer-shop:<id>")`. `get_active_shop` for a reviewer
accepts **only** that alias in `X-Shop-Id` (any other value — the real Fujiwa id, another shop's
id, garbage — is 403) and enters the shop's read scope through the ops view-as machinery
(`services/ops/view_as.enter_shop_read_scope`: `juli_ops` reads the shop and sets the seller's
tenant GUCs in one statement, exactly "Xem như shop"). `GET /v1/shops` returns that one aliased
shop; the reviewer owns no shop row.

**Several pins (P74-A, D77).** `REVIEWER_SHOP_IDS` lists the pins, default first. The gate selects
one per request (`config.select_pin`): the pin whose alias or real id `X-Shop-Id` names, else the
default. The shop entry then accepts, for the selected pin, its alias and -- only when it classifies
as the writable sandbox -- its real id; anything else is 403 `shop` (a masked pin's real id
included). Identity load, pin cache, mask dictionary and sync slots are keyed per pin id. `GET
/v1/shops` and `GET /v1/reviewer/me` (`shops`) list every pin, default first: a masked pin only as
its alias id + `Shop TikTok (ẩn danh)` (built by the route, so it holds even when the selected pin
is the unmasked sandbox), the sandbox pin as it is. `/v1/reviewer/me` answers the pin the header
selects and falls back to the default for a value that names no pin (the demo then stores the
default).

**Mask** (`services/reviewer/masking.py`, applied by `api/reviewer.ReviewerMaskMiddleware` to
every JSON response of a reviewer request — fail closed: a reviewer response that is not JSON
becomes 502):

- the real shop id → the alias id, everywhere it appears (keys and inside strings);
- shop name → `Shop TikTok (ẩn danh)`; product titles → `Sản phẩm NNN`; video / LIVE / creator /
  file titles → `Video NNN` / `LIVE NNN` / `Nhà sáng tạo NNN` / `Tệp NNN`; ids (`tiktok_shop_id`,
  TikTok product / SKU / video / LIVE ids, `seller_sku`) → `an-<kind>-<hash8>`; any 12–20-digit run
  inside a string → `id-<hash8>`. P74-A (D77): the reviewer mask's own labels and HMAC key, never
  "demo" (Shopee reads it as not live); before P74-A these were ADR-038's `Demo Shop NNN` / `Demo
  Product NNN` / `demo-<kind>-<hash>`, which the seller / ops analytics mask keeps;
- titles and ids are collected from the response itself (entity keys) **and** from the shop's
  catalog (products, SKUs, LIVE titles; cached 10 min) and replaced wherever they occur inside
  free text (card titles, reasons, run narration);
- **P75 — structural, fail closed.** On a masked pin every product / SKU / shop / video / LIVE /
  creator field is aliased **by its key**, whether or not the catalog knows the value: title keys
  (`product_title`, `product_name`, `product_label`, `item_name`, `sku_name`, `shop_name`,
  `video_title`, `live_title`, `creator_name`, …), SKU keys (`seller_sku`, `sku`, `skus`,
  `sku_code(s)`, `seller_sku_code(s)`, `sku_ref`, `basket_skus`, …), the `title` / `name` of an
  entity record (a dict carrying a TikTok product / SKU / video / LIVE id), the VALUES of the
  report's `{product_id: title}` maps (`titles`, `product_titles`, `product_names`) and
  `{product_id: seller_sku}` maps (`seller_skus`), and the `{id, name}` rows of a ranking table
  (row kind from its `stream`). The catalog dictionary is the second layer, for free text; a
  title cut short with "…" (card headings) is still replaced. Why: on 29/10 the Phân tích
  promotions table showed real titles and a short seller SKU for products only the report
  carried (edge case D32);
- **P75 — one alias per product.** A product's `Sản phẩm NNN` is keyed on its TikTok product id
  (else its SKU, else the raw title), resolved through the catalog's `product_refs` (Juli product
  id, TikTok SKU id, seller SKU, catalog title → TikTok product id). The same product reads the
  same alias on Quyết định, Phân tích and Đo lường; two products sharing a title read two
  aliases. A video / LIVE / creator title is keyed on its own id the same way;
- brand words of the shop name (`Fujiwa`; stop words like Store / Vietnam / Official dropped)
  plus `REVIEWER_MASK_TERMS` (comma-separated) → `Thương hiệu`, case-insensitive;
- image / media keys and every external `http(s)` URL → `null` (product photos identify the
  shop); buyer PII masked as in D25.6 (`mask_pii`);
- **magnitudes are untouched**: numbers are never rewritten.

Juli's own record ids (card, run, analysis UUIDs) are opaque and stay as they are — the reviewer
needs them to open a card.

## 4. Simulated Duyệt → Thực thi

`POST /v1/reviewer/decisions/{action_card_id}/simulate`, body `{"step": "approve" | "execute"}`.
Reads the surfaced card through the same code as `GET /v1/demo/decisions/{id}` (404 for a card
that is not on Fujiwa's desk); writes **only** an audit row. Response (then masked, §3):

```json
{
  "simulated": true,
  "step": "execute",
  "action_card_id": "…",
  "label": "Mô phỏng · không gửi tới TikTok",
  "steps": [{"key": "approve", "label": "Duyệt", "done": true},
            {"key": "execute", "label": "Thực thi", "done": true}],
  "change": {
    "executor": "juli",
    "lever": {"code": "title", "label": "Tiêu đề"},
    "product": {"title": "Sản phẩm 123", "tiktok_product_id": "an-product-…"},
    "request": {"method": "PUT", "path": "/product/202309/products/{product_id}",
                "operation": "update_product_listing", "fields": ["title"]},
    "fields": [{"field": "title", "label": "Tiêu đề", "before": "…", "after": "…"}],
    "note": "…"
  },
  "enqueued": false,
  "tiktok_write": false
}
```

`request` per lever (D13): `title` / `description` → `update_product_listing`
(`PUT /product/202309/products/{product_id}`); `cover_image` → `upload_product_image` then the
listing edit (needs the seller's photo); promotion levers (`seller_center`) → no TikTok write
even for a seller (the seller acts in Seller Center, Juli measures). `fields[].after` is the
card's stored proposal when one exists, else `"Juli soạn nội dung mới sau khi duyệt"` (no model
call, D24.1). `step: "approve"` returns the same body with only the first step done. Nothing is
enqueued, no run row, no card status change, no TikTok client.

**Sample mode (P32-E, D42 amendment 2).** With no pin the demo never calls this route: the same
body is computed in the browser (`lib/reviewer/sample-simulation.ts`). After "Thực thi (mô
phỏng)" the dialog offers "Theo dõi lượt chạy (mô phỏng) ›", which plays the card through the
P11 in-memory sample store (`lib/reviewer/sample-store.ts`, one per browser tab): consent with
edits, cover photo (object URL, never uploaded), Seller Center checklist, content drafts, Hoàn
tác, Đo lường day 7 / day 14 ("tua nhanh"). Every write of §2's table that a seller has —
except shop connect, invites and ops, which stay hidden — is usable this way; none reaches the
API. The pinned mode keeps the read-only UI and this route.

## 5. Audit (`ops_audit_log`, D25.2)

Actor `reviewer:<platform>:<email>` (no staff id), `shop_id` = the pinned shop, `after` carries
`{"platform": …}` plus the detail. Actions (all classified **view**, 90-day retention):

- `reviewer_sign_in` — the first request of each Supabase session (`session_id` claim): a
  conditional `UPDATE ops_reviewer_accounts SET last_session_id … WHERE last_session_id IS
  DISTINCT FROM :sid` decides, so concurrent workers write one row.
- `reviewer_simulated_approve`, `reviewer_simulated_execute` — with card id, lever, request.
- `reviewer_write_refused` — any non-GET outside the allowlist (method, route).
- `reviewer_read_refused` — a GET outside the allowlist (method, route).

Reads on the allowlist are logged (`reviewer_request`, structured log), not audited.

## 6. Sign-in and provisioning

**Sign-in (AC-32.2).** `/auth/email` (and the landing door) gains a second mode
"Đăng nhập bằng mật khẩu" for team-created accounts: GoTrue `POST
/auth/v1/token?grant_type=password` with the anon key; session stored exactly like Google / OTP.
No sign-up form, no "forgot password". Then `GET /v1/reviewer/me` → `{reviewer: true, platform,
expires_at, shop: {id: <alias>, name}}`, the active shop is stored, and the browser goes to `/`.
With no pin (P32-D) it answers `shop: null`: **no** active shop is stored (a stale one is
cleared), the reviewer record carries `sample: true`, and every page takes P13's no-shop door —
the sample shop over fixtures, no shop request — with the banner `reviewer.banner_sample` ("…
dữ liệu mẫu …"), no "Kết nối TikTok Shop" strip, and Duyệt → Thực thi as the same labelled
simulation computed in the browser from the sample card (`lib/reviewer/sample-simulation.ts`, a
port of §4; no request). P32-E (D42 amendment 2): in sample mode nothing is read-only — every
other write (Từ chối, the run after "Theo dõi lượt chạy (mô phỏng)", consent edits, photo,
Seller Center, content cards, Hoàn tác, Đo lường day 7 / day 14, Quy tắc on Quyết định and
`/settings`, "Phân tích video") runs on the tab's in-memory sample store, labelled "Mô phỏng ·
không gửi tới TikTok" (settings: "Mô phỏng · không lưu"); the banner carries "Đặt lại dữ liệu
mẫu". Still the only request of the session: `GET /v1/reviewer/me`.
Errors (dictionary `auth.password.*`): wrong e-mail or password (GoTrue `invalid_credentials` /
`invalid_grant`), revoked (`user_banned`, or `X-Juli-Reviewer-Denied: revoked`), expired
(`expired`), not a trial account (`/v1/reviewer/me` → `reviewer: false`: signed out again),
rate limited, network. Google and OTP unchanged.

**Provisioning (AC-32.3).** `python -m juli_backend.services.reviewer.cli`
(env: `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`):

- `create --email shopee-review@app-juli.com --platform shopee [--days 30] --by <staff e-mail>`
  → creates (or takes over) the Supabase user with a generated password (printed **once** to
  stdout, never stored or logged), `email_confirm: true`, the `app_metadata` mark; inserts the
  row.
- `renew --email … [--days 30] [--rotate-password] --by …` → `expires_at = now + days`,
  `revoked_at = NULL`, Supabase ban lifted.
- `revoke --email … --by …` → `revoked_at = now`, Supabase user banned (≈ 100 years).
- `show --email …` → the row.

Every command writes an ops audit row (`reviewer_account_create` / `_renew` / `_revoke`, config
kind). No password in the repository, in a log line or in the database.

## 7. Proof (AC-32.6)

- `tests/unit/test_reviewer_no_write.py` — every route × reviewer token; whole-database
  snapshot before/after (every table but `ops_audit_log` / `ops_reviewer_accounts`); TikTok
  client constructors and Celery dispatch patched to fail the test; the simulate route
  exercised for approve and execute.
- `tests/unit/test_reviewer_access.py` — expiry / revoke / unknown / ops refusal, alias pin
  (real id, another shop's id → 403), masking (no Fujiwa name / title / id in any allowlisted
  response; numbers equal to the seller's own response), audit rows.
- `tests/integration/test_reviewer_two_tenant.py` (Postgres, RLS) — two shops; the reviewer
  pinned to shop A reads only A (B's id in `X-Shop-Id` → 403, no B value in any response); the
  `juli_app` role cannot read or write `ops_reviewer_accounts`.

## 8. Owner steps

1. Supabase → Authentication → Providers → Email: enabled (already, P9-A). Password sign-in
   uses the same provider; nothing else to switch on. Keep "Allow new users to sign up" as P9-A
   needs it for OTP — a self-signed-up password user is an ordinary seller (no mark), never a
   reviewer.
2. API env: **nothing** for the sample-shop reviewer (D42 amendment, 2026-10-15 — production
   leaves `REVIEWER_SHOP_ID` unset). Only to pin the reviewer to Fujiwa instead:
   `REVIEWER_SHOP_ID=<Fujiwa shops.id>`, optional `REVIEWER_MASK_TERMS`.
   **P74-A (D77):** `REVIEWER_SHOP_IDS=<Fujiwa shops.id>,<sandbox shops.id>` (Fujiwa first = the
   default; the sandbox second), then restart the API. `REVIEWER_SHOP_ID` may stay; the list wins.
3. On the VPS after deploy: `python -m juli_backend.services.reviewer.cli create --email
   shopee-review@app-juli.com --platform shopee --by <you>@app-juli.com`; hand the printed
   password to Shopee in the Services Information form; renew / revoke as needed.
