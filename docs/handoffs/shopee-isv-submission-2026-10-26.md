# Handoff — Shopee ISV submission (2026-10-26)

**Goal:** pass the Shopee ISV (Third-party Partner Platform) application. Shopee rejected Juli twice:
"simulated interfaces or predefined results", then a generic rejection with no reason. Shopee wants
"existing e-commerce integrations identifiable via a provided trial account". Juli shows a real TikTok
sandbox shop through the reviewer account `shopee-review@app-juli.com`.

**Owner directive:** submit ASAP; focus only on what the ISV feature check needs. Later phases
(#2153 LLM-authored rules, promotion forecasting/ROI, #2157 worker pool) stay out of scope.

## Contract for the next session

1. **Do not** type passwords, solve CAPTCHAs, or receive the reviewer password. The owner signs in
   and runs `cli reset` themselves.
2. **Do not** run `systemctl restart juli-api` (legacy unit, crash-loops under blue/green).
3. Seller Center / Partner Center edits only when the owner asks. Partner Center sandbox order
   creation was approved for this task.
4. The owner merges PRs (`! gh pr merge <n> --squash --delete-branch`). Deploy = push tag
   `fasttrack-deploy-YYYYMMDDTHHMMZ` on `fasttrack/optimize-product` after the owner says go;
   fetch + merge before push, other sessions share the branch.
5. Subagents: Sonnet by default, few of them.
6. Log every new edge case in `fasttrack/p64-e2e-edge-cases.md` as found (branch below).
7. Diagnostic SQL names the schema: `silver.orders`, `public.order_items`, `public.shops`.
8. VPS journal is UTC; UI is UTC+7.

## State (verified 26/10 ~09:00 UTC+7)

- Live deploy: `2d56fb65` (fasttrack-deploy-20261024T2249Z). Live slot 8000; stop a stale
  `juli-api-candidate-*` slot after each deploy (EMAXCONN otherwise, E10).
- Sandbox shop: Juli `shops.id = 1862f13b-de2c-4fae-a4ad-70298cead913`, shown as
  SANDBOX7657274686031759124. `shops.tiktok_shop_id` holds the **cipher** `TaFcIwAA…`; webhooks
  carry numeric `7495274531001436791` (E11).
- Reviewer account: `shopee-review@app-juli.com`, **expires 14/11/2026** (reset not yet run).

**Confirmed working on production (reviewer view):**
- Connection card: connected, 22 permissions, sync 202.
- Agent runs over SSE, real TikTok reads + real OpenAI.
- Real writes, verified in Seller Center and listed in Quyết định › Đo lường ("TikTok xác nhận",
  "Không đo · shop sandbox"):
  - product created `1738157559581542019` (Nồi lẩu điện, V2 category 1216272, SKU JULI-F7B54199)
  - 12 % discount `7699734374178817800` "Combo mini tiện dụng 12%" 23/10→30/10 (keep it)
- Quyết định › Đề xuất: 1 discount card for JULI-F7B54199 + stability bands + rules panel.
- 3 new paid orders, all `delivered`, 599 000 ₫ each, in `silver.orders`:
  586792273454072842, 586792263300449290, 586792263247365130 (created 26/10 08:01 UTC+7,
  hot pot product 1736363193934775939).

**Not yet good:**
- Trang chủ GMV 0 ₫ / 0 orders and Phân tích "—": the 00:15 report covers days ≤ 25/10, where the
  only orders (21/10) were auto-cancelled by TikTok (B11). Tonight's 00:15 build should count the
  3 new orders (~1.797M).
- Quick scan counts full days up to yesterday, so the listing-edit card cannot appear before
  27/10 00:00 UTC+7. The listing card is a bonus, not required.

## Next steps, in order

1. **27/10 morning (after 00:15 UTC+7):** owner reloads demo.app-juli.com as the reviewer. Check
   Trang chủ shows GMV ≈ 1 797 000 ₫ / 3 orders. If not, check `shop_diagnosis_daily` logs and the
   `orders_source` path (`metrics_source = "orders"`).
2. Owner runs a forced quick scan (same command as before) and pastes `shop_quick_scan_done`.
   Expect `candidates>0`. If a listing card appears, optionally test Duyệt → run → products.edit →
   read-back → Seller Center.
3. Owner runs on the VPS (password printed once, owner keeps it):
   `python -m juli_backend.services.reviewer.cli reset --email shopee-review@app-juli.com --platform shopee --by <staff>@app-juli.com --days 30`
4. Final read-only walkthrough of every tab with the new account; give the owner a
   confirmed-only list (no service-information prose, the owner asked for none).
5. Owner submits to Shopee.

## Open bugs found (log has details; not blocking submission)

- **B15:** "Đồng bộ ngay" does not fetch orders — commerce steps run at most once per 60 min
  (`workers/services/polling/ingestion.py` `_commerce_due` / `commerce_interval`). A user sync
  should bypass it. Worth fixing if the reviewer is expected to create orders live.
- **E11:** order webhooks → DLQ `unknown shop` (numeric id vs stored cipher). Store both ids.
- **B12:** stored report not refreshed when orders get cancelled after the report date.
- **B11/B14:** sandbox orders auto-cancel unless walked to Delivered in Partner Center ›
  Development Shops › Test functions › Change order status (one step at a time, 3-10 s lag).
  The `tts_open_toolkit sandbox` CLI cannot see this shop.
- **E10:** stale blue/green slot after each deploy exhausts the Supavisor pool (15).

## Branches

- `fasttrack/p64-e2e-edge-cases` (worktree `.worktrees/p64-edge`), **not pushed**: edge-case log
  (A–E incl. B11–B15, E10, E11) + this handoff. Push + PR to `fasttrack/optimize-product` when
  the owner wants it.
- `fasttrack/p66-submission-text` (commit 087f87eb), not pushed; owner said no service text — leave.

## Reference

- Edge-case log: `fasttrack/p64-e2e-edge-cases.md`. Decisions D73–D75 in it.
- Previous transcript: `~/.claude/projects/-Users-macos-Juli-AI-v2/7b39deb6-9fd6-4448-a0fb-38b1a633631c.jsonl`
