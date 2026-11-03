# P90 metrics contract — Shopee shop view (ADR-120)

The single definition of every number on Tổng quan / Phân tích / Sản phẩm / Quyết định and in
`services/shopee_profit/`. Design artboards and code must match this file; a change here is a
change to both.

## 1. Order basis
- Default order type: **Đơn đã xác nhận** (confirmed), as ORY's mapping v1. Every view states it.
- GMV (Doanh số) at shop / product / flow level = Shopee's "Doanh số" for confirmed orders.
  At order-line level, GMV = deal price × qty (before the shop voucher). A reconciliation check
  compares Σ order-line GMV with the export; a gap > 2 % is shown as a data warning, never hidden.

## 2. Traffic flows (Tổng quan shows all five; they ADD UP to shop GMV)
| Key | Label | Source |
|---|---|---|
| `the_san_pham` | Thẻ sản phẩm (ngoài Trang shop) | Shopee "Thẻ sản phẩm" total − its child "Cửa hàng" |
| `trang_shop` | Trang shop | child "Cửa hàng" of Thẻ sản phẩm |
| `live` | Live | L1 "Live" |
| `video` | Video | L1 "Video" |
| `lien_ket` | Tiếp thị liên kết (Affiliate) | L1 "Tiếp thị liên kết" incl. Affiliate Live / Video |

- Shopee's own "Thẻ sản phẩm" total includes Trang shop; we split it so the five add up.
- If Σ flows ≠ shop GMV (Shopee de-duplicates buyers across sources), a sixth row
  **"Chênh lệch nguồn"** carries the difference so the tree still adds up. Never silently scaled.
- Thẻ sản phẩm children (Tìm kiếm, Đề xuất, Giỏ hàng, Đơn mua, Khuyến mãi, Khác) are a drill-down
  of `the_san_pham`; Flash Sale page traffic is its "Khuyến mãi" child, not a top-level flow.
- **Quảng cáo is an overlay** ("trong đó"), drawn per flow it lands in; never a row of the sum.
- Per flow: Lượt xem (Live / Video: lượt xem phiên / video), Lượt nhấp, CTR = nhấp ÷ xem,
  CTOR = đơn ÷ nhấp, AOV = GMV ÷ đơn, GMV = xem × CTR × CTOR × AOV (exact identity).
  CTR is never compared across flows with different view definitions.
- Per-product flow split comes from the item × source export / connector (aggregates), not from
  order lines (orders carry no traffic source except affiliate conversions).

## 3. Price levers (from order lines; each line exactly one; they ADD UP)
`khong_uu_dai` · `voucher` (shop voucher) · `khuyen_mai` (discount programme, Flash Sale price) ·
`combo` (Combo khuyến mãi, Mua kèm deal sốc). Precedence combo > khuyen_mai > voucher > none.
Shopee-funded vouchers are not a seller cost and not a lever.

## 4. Profit
- buyer_paid (doanh thu thực) = deal × qty − shop voucher share − combo discount.
- Platform fees: actual from the income export when present, else the fee formula valid on the
  order date. **Per-order fixed fees are charged once per order**, split across its lines by value.
- Line contribution = buyer_paid − fees − giá vốn × qty − đóng gói − affiliate commission.
- **Product profit** = Σ line contribution − the product's ad spend (from the ads report by product;
  Chiến dịch Nhóm per-product rows).
- **Shop profit** = Σ line contribution − **total ad spend of all campaigns** (incl. campaigns with
  no revenue) − other shop marketing costs not on orders (e.g. game prizes).
  Σ product ad spend + "QC không gắn sản phẩm/không ra đơn" = total ad spend (checked).
- **Margin** (biên) = profit ÷ buyer_paid, everywhere (shop, product, flow, lever, card).
- **Cost coverage**: share of buyer_paid whose SKU has a giá vốn. Below 100 %, margin is shown
  "trên X % doanh thu có giá vốn" and is never extrapolated.
- Break-even ROAS = buyer_paid ÷ contribution before ads (per product).

## 5. The five numbers (VND and %; period vs previous, or card before → after)
1. **% giảm giá** = (giảm giá khuyến mãi + voucher shop + giảm combo) ÷ GMV theo giá niêm yết.
2. **Doanh thu thêm / chi thêm** = ΔGMV ÷ Δchi, chi = QC + voucher + khuyến mãi + combo + hoa hồng.
   Shown as "x đ / 1đ chi" and %; red below 1đ; "giảm chi" when Δchi ≤ 0.
3. **Biên cuối** = §4 margin (shop or the card's scope).
4. **Số đơn** (confirmed).
5. **AOV** = GMV ÷ số đơn.
Plus **chi marketing / ngày vs trần** (Cài đặt › Mục tiêu).

## 6. Floor price and max discount
Absolute floor = (giá vốn + đóng gói + phí cố định/đơn) ÷ (1 − phí sàn %).
Operating floor = (giá vốn + đóng gói + phí cố định/đơn) ÷ (1 − phí sàn % − QC % − hoa hồng % − biên mục tiêu %).
Max discount = 1 − operating floor ÷ giá niêm yết, min with the seller's cap; amount rounded down
to 1.000đ. Breach = buyer_paid per unit after all discounts < operating floor.

## 7. Voucher what-if (card)
Inputs: giá trị (đ or %, with max), đơn tối thiểu, **số lượng voucher (usage limit)**, giới hạn mỗi
người, thời gian. Every input change recomputes the whole card.
- Q = historical confirmed orders ≥ đơn tối thiểu in the window, scaled to the voucher's days.
- u = usage rate of the shop's comparable past vouchers (voucher export "Tỷ lệ sử dụng"); shown.
- used = min(Q × u, số lượng); cost = Σ discount over used orders (max cap applied).
- Per order: discount %, buyer_paid, fees, contribution, margin (organic vs ad-attributed).
- Floor breach per SKU in qualifying orders; break-even extra orders = ⌈Δcost ÷ contribution/order⌉.
- Spend check: cost ÷ days vs trần chi/ngày.
- "Chắc chắn" = the above (arithmetic on real orders and stated u). "Dự kiến" = predicted range.

## 8. Metric → recommendation wiring
| Critical metric | Card kinds (`change_kind`) | Lands on |
|---|---|---|
| Lượt xem (flow/keyword) low | `title`, `keyword`, `ads_budget` (purpose hien_thi), `affiliate_commission` | Sản phẩm › Từ khóa / Quảng cáo |
| CTR low | `cover_image`, `title`, `price_display` | Sản phẩm |
| CTOR low | `product_discount`, `min_spend_voucher`, `review_voucher`, `price` | Sản phẩm / Voucher |
| AOV low | `bundle_deal`, `add_on`, `min_spend_voucher`, `variation_set` | Combo / Voucher |
| Biên < target or floor breach | `price`, `voucher_cap`, `ads_roas_target`, `ads_pause` | Chi phí & giá sàn |
| ROAS < break-even (chuyen_doi) | `ads_roas_target`, `ads_pause`, `ads_purpose` | Quảng cáo |
| Liên kết share / commission | `affiliate_commission`, `affiliate_target_campaign` | Liên kết |
A card always carries: metric key, flow/lever, product id, change_kind, the ₫ at stake; its
"Xem phân tích ›" opens the ranking for that metric × source with the row highlighted.

## 9. Clarifications after the first alignment (2026-11-03)
- **No buyer key.** Order lines carry no buyer identifier, hashed or not (no-PII rule). The voucher
  per-user limit is shown as an input but marked "không kiểm được từ dữ liệu" and never enforced in the
  calculation. `OrderLine.buyer_key` must stay unset by every loader.
- **② on a voucher card**: the certain layer has no volume change, so ② is shown only from the
  predicted range ("dự kiến"); the certain layer shows the break-even extra orders instead. Never a red
  "0 đ / 1đ" from the certain layer.
- **Partial cost coverage**: margin = contribution of covered lines − (ad spend of covered products +
  unattributed ad spend × covered share of buyer_paid) − other costs × covered share, ÷ covered buyer_paid;
  labelled "trên X % doanh thu có giá vốn". Shop profit in đồng is shown only at 100 % coverage.
- **Chi for the daily cap** = ads + voucher + khuyến mãi + combo + commission (same chi as ②).
- **Packaging** is per order line (one pack per product line), set per SKU.

## 10. Checked against Shopee documents and ORY's exports (2026-11-03)
Sources: Học viện Shopee articles 2150 (Phí Xử Lý Giao Dịch, 24-04-2026), 2139 (Phí Cố Định non-Mall,
14-05-2026), 25223 (Phí Hạ Tầng, 12-06-2025); ads.shopee.vn/learn/faq/119/634 (Theo dõi hiệu quả chiến dịch).
- **Phí cố định** (non-Mall): % by category (VAT incl.), **per item**, base = giá sản phẩm trước Shopee trợ giá
  − khuyến mãi người bán đã áp dụng. Rate table: PDF "Shopee non-Mall_Phi Co Dinh tu 23.05.2026" (M5).
- **Phí xử lý giao dịch**: 6 % (non-Mall from 01/05/2026), **per order**, base = giá sản phẩm trước Shopee
  trợ giá + **phí vận chuyển người mua trả** − khuyến mãi người bán − khuyến mãi ngân hàng.
- **Phí hạ tầng**: **3.000đ per order** (orders created from 01/07/2025).
- **Phí dịch vụ** (Voucher Xtra / Freeship Xtra): only when enrolled; % per item with a cap.
- All three are charged only on delivered orders ("Đã giao") or refunds accepted as "Hoàn tiền ngay"
  (except "Chưa nhận được hàng"). Profit uses delivered orders; confirmed-but-cancelled orders carry no fee
  and no profit. The income export (M2) is the actual and wins over the formula.
- **Voucher cost** = seller-borne discount × orders that used it: ORY's voucher exports reconcile exactly
  (e.g. a 5.000đ voucher × 74 confirmed orders = 370.000đ "Chi phí"). So extra spend on a card = extra
  voucher cost + the discount on predicted extra orders (as implemented). "Voucher Thông Minh" created by
  Shopee from the ads service also carries a seller "Chi phí" and counts as voucher spend.
- **Ad spend per product**: Chiến dịch Nhóm per-product rows sum exactly to the campaign (cost, revenue,
  direct revenue, clicks), so product ad spend is taken from Shopee, not allocated by us.
- **Ad revenue**: Shopee "Doanh số" counts the advertised product AND other products bought within 7 days of
  the click; "Doanh số trực tiếp" counts only the advertised product. Product break-even checks use
  **ROAS trực tiếp**; shop-level ads use broad ROAS.
- **Not covered by any Shopee document** (our accounting rule, kept): for a partially costed product, its ad
  spend counts in proportion to its covered share of buyer_paid (§9).

### 10a. Fixed-fee rates for ORY's categories (non-Mall, from 23/05/2026, VAT incl.)
Source: "Shopee non-Mall_ Phi Co Dinh tu 23.05.2026.pdf" (attachment of article 2139, 47 pages).
| Category (L1 › L2 › L3) | Rate | ORY products | Category source |
|---|---|---|---|
| Nhà cửa & Đời sống › Dụng cụ nhà bếp › Tạp dề & găng tay nấu nướng | 15,00 % | Găng tay STAHAUS, Găng TPE | affiliate conversion report |
| Nhà cửa & Đời sống › Dụng cụ chăm sóc nhà cửa › Túi nilon & túi rác | 10,00 % | Túi Bio STAHAUS | affiliate conversion report |
| Nhà cửa & Đời sống › Dụng cụ chăm sóc nhà cửa › Phụ kiện giặt là | 10,50 % | Hae | affiliate conversion report |
| … › Dụng cụ chăm sóc nhà cửa › Chất tẩy rửa | 10,50 % | nước rửa chén (likely) | to confirm from product category |
| … › Dụng cụ chăm sóc nhà cửa › Miếng bọt biển, miếng chà vệ sinh | 10,00 % | xơ mướp (likely) | to confirm |
| … › Dụng cụ nhà bếp › Giấy bạc / Màng bọc thực phẩm | 16,00 % | màng nhôm (likely) | to confirm |
Per order on top: phí xử lý giao dịch 6 % (incl. buyer shipping) + phí hạ tầng 3.000đ.
Example: a 200.000đ glove order with no shipping paid by the buyer → 15 % + 6 % = 42.000đ + 3.000đ = 45.000đ
(22,5 %), versus the 15 % placeholder in the worked example.

## 11. Ranking rule (owner, 2026-11-03)
Score = how much of the gap to the month's targets an action closes, weighted toward the target that is
furthest behind: Σ_k w_k × min(ΔKPI_k(P25), gap_k) ÷ gap_k over k ∈ {GMV, đơn, AOV, biên}, with
w_k ∝ gap_k ÷ target_k (only KPIs behind target; GMV gets the weight of the shop's north star when tied).
ΔKPI uses the cautious end (P25) of the predicted range plus the certain layer.
Eligibility (hard filters, before scoring): expected Δprofit ≥ 0 (P50), no SKU below its operating floor,
spend within the daily cap, one change per product per measurement window, product in stock.
No targets set → fall back to expected ΔGMV/tháng (P25) under the same filters.
"Xếp theo" switch keeps ₫ GMV/ngày, ₫ lợi nhuận/ngày and the five numbers as alternatives.
Model use and learning loop: as described to the owner 2026-11-03 (flow baseline = band + counterfactual;
lift model ported to Shopee = predicted range; calibration per change_kind from frozen predictions vs
ADR-077 readings; coverage scored; acceptance stats from approve/dismiss/whatif_adjusted; ORY learns from
ORY only — no pooling, ADR-116 / Shopee ToS §6.2(c)).

## 12. Recommendation card families (owner, 2026-11-03)
Every card belongs to one family; §8 maps critical metrics to families and change kinds.
| Family | Change kinds (examples) | Certain layer computes |
|---|---|---|
| `ads` | budget, ROAS target, purpose, pause/resume, keyword bid, add/remove product from a group campaign | spend/day, ROAS vs break-even (direct), profit after ads |
| `promotion` | product discount (Khuyến mãi), price change | discount %, buyer_paid vs floor, margin |
| `voucher` | value (đ or %), max, min spend, quantity, per-user limit, days | §7 |
| `sale` | Flash Sale slot (shop), Shopee programme registration (Rẻ Vô Địch, campaign day) | slot price vs floor, units cap, cost |
| `combo` | Combo khuyến mãi tiers, Mua kèm deal sốc, gift with purchase, set size | AOV, units/order, margin per bundle vs floor |
| `affiliate` | open-campaign commission %, targeted campaign (KOLs, rate, products) | commission cost per order, margin after commission |
| `mega_sale` | a **composite** for a campaign window (e.g. 11/11): a set of child changes from the families above with one schedule (day-by-day on/off times), one budget cap and one approval | Σ child certain layers on the same orders without double counting (one order gets one price lever, §3), total spend/day vs cap, floor check per SKU across all stacked discounts |
- A `mega_sale` is approved as one card (children listed, editable before approval) and **measured as one bundle**
  (ADR-121 d.4 stacked changes); its children are not credited separately.
- A product inside an active `mega_sale` window is locked from other cards for that window.

## 13. Cost fallback and fees without the income export (owner, 2026-11-03)
- **Step 3 (income export) is skipped for now.** Actual fees per order come from the order export (Phí cố định, Phí Dịch Vụ, Phí xử lý giao dịch; fields A19); the §10 formula is the fallback (fixed fee by category from the
  23/05/2026 table, 6 % transaction incl. buyer shipping, 3.000đ/order); actual fees replace them if an income
  export is ever loaded.
- **Giá vốn fallback = 1/3 of the SKU's list price** when no imported cost exists. Every number that uses it is
  marked "giá vốn giả định (1/3 giá)"; imported costs always win; the shop shows two coverages:
  "giá vốn thật" % and "giả định 1/3" % of buyer_paid. Supersedes §9's "shop profit in đồng only at 100 %
  coverage": profit in đồng is shown, labelled with the assumed share. Packaging fallback = 0 (labelled).

## 14. Order basis and GMV reconciliation, proven on ORY's order exports (2026-11-03, Step 2)
- Seller Centre's "Đơn đã xác nhận" = orders **with a payment time** ("Thời gian đơn hàng được thanh toán"), even if
  later cancelled. On ORY October 01–28: 121 orders, AOV = Σ(deal × qty − shop voucher) ÷ orders = 172.025đ — equal to
  the client's own figure; per day 28/28 match shop-stats. GMV gap vs `Tổng doanh số` (confirmed): +0,01 %.
- Profit still uses delivered / refund-accepted orders only (§4); the confirmed basis is for GMV, orders and AOV.
- **Shopee changed the `Doanh số` definition in 2026** (ORY mapping note: no longer net of Shopee subsidy). For periods
  before 2026 the reconciliation target is Σ(deal × qty − shop voucher − Shopee voucher) (Nov 2025: within +2,0 %;
  the 2026 formula would be +18 %). The 2 % gate uses the formula for the period's definition.
