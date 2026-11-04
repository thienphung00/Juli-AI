# P91 deploy checklist (branch fasttrack/reco-versions)

One deploy for all of P91 (D-1 to D-14). Never pushed, tagged or merged into another branch by the
integration agent. The owner runs the deploy. Never write Fujiwa (shop 2b1da87b...). Synthetic data only
in the repo and its tests; the client files named below stay outside it.

Builds on P90 (`p90-deploy-checklist.md`, deployed as `fasttrack-deploy-20261104T0513Z`); production is
at `115_shopee_recommendations`.

## 1. Migrations 116-120 (all additive / expand-only; single head = 120_planned_changes)

| Rev | Adds | Downgrade |
|---|---|---|
| 116_shopee_reco_codes | `shop_proposals.code` (partial unique per shop), `shop_proposals.product_queue`, table `shop_proposal_code_counters` (RLS, juli_app SELECT/INSERT/UPDATE) | drops the three objects |
| 117_shopee_reco_plans | tables `shop_reco_plans`, `shop_reco_plan_cards`, `shop_reco_plan_counters`, `shop_reco_change_sets` (RLS, SELECT/INSERT/UPDATE); `shop_proposals.status` CHECK widened with `planned` | drops the tables; the narrower CHECK comes back NOT VALID |
| 118_shopee_kol_lines | five nullable KOL columns on `shopee_order_lines` (`kol_key`, `kol_handle`, `affiliate_channel`, `affiliate_campaign_type`, `affiliate_mcn`) + one partial index | drops them |
| 119_shopee_order_income | table `shopee_order_income` (RLS, SELECT/INSERT/UPDATE) + nullable `shopee_order_lines.variation_name` | drops both |
| 120_planned_changes | tables `planned_change_imports`, `planned_change_refs` (RLS, SELECT/INSERT/UPDATE) | drops both |

The chain is `115 -> 116 -> 117 -> 118 -> 119 -> 120`, and the deferred write-mode backfill
(`deferred/101_write_mode_backfill.py`) hangs on 120. No migration moves or rewrites a row, so the
pre-deploy dump is the only real safety net for a downgrade that drops tables holding data. Run through
`infra/safe-alembic-upgrade.sh`; confirm `alembic current` = `120_planned_changes`. Verified here: empty
-> head (120), head -> 115 -> head, and the additive gate from 115 (see the LOG entry for counts).

The card codes (116) are NOT backfilled by the migration (the additive gate forbids a data step): see
section 5.

## 2. New environment variables / flags

| Name | Where | Default | Purpose |
|---|---|---|---|
| `CONNECTOR_FILL_LISTING` | API environment (AWS secret `juli/api/production`) | **off in code** (unset = off) | Server kill switch for the Connector fill-in ("Điền bằng Connector": types an approved title / first description line into the ORY product edit page; never clicks Cập nhật). Off: `GET /v1/ingest/fill/{code}` answers `fill_disabled` and the Demo / Ops button only opens the page. **The owner turns it on after the deploy**: set `CONNECTOR_FILL_LISTING=1` in the AWS secret, run `fetch-secrets.sh` / `refresh-secrets.sh` on the VPS, restart the API. Turn it off the same way to stop. |
| `RECO_LEARNING_SHOP_IDS` | worker / beat environment | empty | Optional comma-separated Juli shop ids that join the daily recommendation learning step in addition to the shops whose Ops stage is "Pilot đặc biệt". Only needed if ORY is not in stage `pilot` (check Ops > ORY > settings; set the stage rather than the variable if you can). |
| `NEXT_PUBLIC_P91_PLAN` | demo web build | on (anything but `0`) | Kế hoạch (draft plan) screens. `0` switches them off. |
| `NEXT_PUBLIC_P91_KOL` | demo web build | on (anything but `0`) | KOL screens and the Mẫu KOL step. `0` switches them off. |

Existing, still needed: `JULI_ORDER_REF_MASTER_KEY` (set at the P90 deploy; the income export is keyed with the
same per-shop order hash, so it must be the same key).

## 3. Beat entries

No new beat entry. The daily learning / calibration of the recommendations (D-14) runs as the last step of the
existing `shopee-kpi-daily` task (`juli_backend.shopee_kpi_daily`, 18:29 UTC), right after the KPI run and the
proposal measurement: `services/shopee_reco_learning_daily.run_daily_learning`. DB only, idempotent, pilot
shops only, one session per shop, a failure is logged by type and never fails the KPI task. The task result
gains `learning_shops`, `learning_failed`, `learning_observations`. Restart beat and the default-queue worker so
they load the new code. Ops can still run it by hand (`POST .../recommendations/learning/run`).

Already registered from P90 and unchanged: `card-change-verification` (01:17, 07:17, 13:17, 19:17 UTC).

## 4. New routes (summary)

- Seller (Demo): recommendation versions / compare / manual / plan / change-set windows under
  `/v1/demo/shopee/recommendations`; KOL analytics under `/v1/demo/shopee`; planned-changes import under
  `/v1/demo/shop-inputs/planned-changes` (template, preview, apply, versions); connector flag
  `GET /v1/demo/connector-fill`.
- Ops (operator role, masked): the same under `/v1/ops/shops/{id}/...`, plus
  `POST .../shopee/recommendations/backfill-codes` and `.../requeue`, planned changes under
  `/v1/ops/shops/{id}/planned-changes`, `GET /v1/ops/connector-fill`.
- Connector (ingest token): `GET /v1/ingest/fill/{code}` (flag-gated, approved cards only), and the new
  ingest dataset `order_income` (`POST /v1/ingest/shopee/order_income`).

## 5. Post-deploy steps (in this order)

1. Smoke: `GET /health`; Ops opens the ORY shop; Tổng quan loads; the Thông số shop template downloads and has
   the sheets SKU, Mục tiêu, Mẫu KOL, Thành phần combo, VAT.
2. **Backfill card codes per shop** (once, idempotent, `created_at` order): as Ops, for each Shopee shop that
   already has recommendation cards (ORY): `POST /v1/ops/shops/{shop_id}/shopee/recommendations/backfill-codes`,
   then `POST .../recommendations/requeue` so each product's queue is numbered. Check a card now shows
   `JC-yymm-nnnn`. New cards get their code when first saved.
3. **Connector 0.3.4 reload**: `cd apps/connector && pnpm install --frozen-lockfile && node scripts/build.mjs`
   (Node 20) -> `apps/connector/dist` (manifest 0.3.4). On the ORY operator's Chrome:
   `chrome://extensions` -> reload the unpacked extension (or ship the Unlisted build). 0.3.4 contains the 0.3.2 /
   0.3.3 live fixes (ads money and ROAS targets in VND x 100 000, Shopee's -1000000 "no value", a real rate above
   1 goes to extra) and the listing fill-in. `PILOT_SHOP_IDS` stays ORY only; fill-in is explicit-ids-only.
   Check the first reader run posts without new "drift" pauses.
4. **Turn on fill-in** (optional, when you want it): set `CONNECTOR_FILL_LISTING=1` in the AWS secret and restart
   the API (section 2). Then on ORY, approve one title card, press "Điền bằng Connector", check the title is
   typed and highlighted and that nothing was saved; press Cập nhật yourself only when it is right. Recon facts
   (labels `*Tên sản phẩm` / `*Mô tả sản phẩm`, rich-text description, save button `Cập nhật`, the note that edits
   sync to linked shops in other markets) are in `docs/integrations/shopee/product-edit-recon-checklist.md`.
   Description read-back stays off (the recon did not show the detail call carries the description).
5. **Import the planned-changes list** (Cài đặt > Đề xuất kế hoạch, `.xlsx`): download the template, put the
   TD / XM rows in, preview, give a reason, apply. Each row becomes a manual card (`origin = import`, JC code,
   `external_ref` kept); rows already executed carry their real date. Fix rejected rows (title > 100 chars,
   unknown item id, two changes of one product within 3 days) and re-apply: a re-import creates nothing twice.
6. **Upload the income files** (Tài chính > Doanh thu, `Income.T<m>.<from>_<to>.xlsx`, Aug-Oct 2026 = 3 files)
   with the loader, never by hand:
   `JULI_ORDER_REF_MASTER_KEY=... python scripts/load_shopee_exports.py FOLDER --api-url https://api.app-juli.com --shop-id <ORY id>`
   (token in `JULI_INGEST_TOKEN`). Load the order exports first (they carry the variation names); the loader
   prints, per income file, how many orders match an order line and the month's reconciliation. **Watch for the
   Ops warning** `seller_support_shipping_nonzero` in the loader output: it appears the first time a non-zero
   "Phí vận chuyển - Người bán hỗ trợ" is stored (it is reference only and is NOT subtracted from the profit).
   The Ops order-upload page also sends `variation_name` now.
7. **Upload the cost file through the converter**: download the Cài đặt template, then
   `python scripts/convert_seller_cost_file.py "Tồn kho và giá.xlsx" --template mau-thong-so.xlsx` (output goes to the
   OS temp directory, never into the repo), check the printed counts and the codes with no template row, upload the
   written file through the normal import (preview -> reason -> apply). Then answer the VAT questions in the
   VAT sheet (company? rate per SKU, prices / costs include VAT): until `prices_include_vat` is stated the profit,
   and every card's delta profit, is shown before VAT and says so.
   ORY's answers (owner, 2026-11-04): both flags **Có** (prices and giá vốn include VAT); rate per SKU from the
   private list kept with the client files (never in the repo), filled into the `VAT (%)` column of the same
   template before upload. The rate is per listing, so a combo mixing rates carries one value.
8. Check the Ops pilot stage of ORY (or set `RECO_LEARNING_SHOP_IDS`) so tonight's 18:29 UTC beat learns for it;
   next morning `GET .../recommendations/learning` shows fresh calibration rows.
9. Optional switches if something misbehaves on the screens: build the demo with `NEXT_PUBLIC_P91_PLAN=0` /
   `NEXT_PUBLIC_P91_KOL=0`.

## 6. Rollback

- Backend: redeploy the previous release; the new tables and columns are unused by old code, so migrations can
  stay applied (preferred). `shop_proposals.status = 'planned'` cards left behind are only read by new code.
- Migrations: downgrade to 115 only if required; it drops the plan, change-set, income and planned-change tables
  (data loss): restore from the pre-deploy dump where the data matters.
- Connector: remove / disable the extension, or ship a build with `PILOT_SHOP_IDS = []`. Fill-in has its own
  kill switch (`CONNECTOR_FILL_LISTING` off). It never writes to Seller Centre: a person presses Cập nhật.
- Learning: remove the ORY pilot stage (or leave `RECO_LEARNING_SHOP_IDS` empty); the step then does nothing.

## 7. Known limits

- The 23 older tables that hold UPDATE without a registered call site still fail
  `tests/integration/test_migrations.py::test_no_public_table_holds_update_beyond_its_call_site` (separate
  ticket after P91, owner decision D-14); the P90 / P91 tables (`shopee_order_lines`, `shopee_sim_prior_runs`,
  `shopee_reco_calibrations` and the P91 tables) are registered with their call sites in
  `tests/unit/test_juli_app_grants_cover_mutations.py`.
- Seller-support shipping is stored as a reference value and never subtracted (D-14); VAT withheld by Shopee is
  a cost, VAT the company invoices itself is a profit adjustment only once the flags are stated.
- Nothing writes to Seller Centre. Every change is applied by a person who presses the platform's own save.
- Test status and counts of the deploy gate are in the LOG entry of this integration (fasttrack/LOG.md).
