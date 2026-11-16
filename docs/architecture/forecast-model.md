# One forecast model for Shopee and TikTok

Owner decisions F1–F11 (forecast-model grill, 2026-11-16, owner + S1). This document is the spec
both platforms build against. S1 owns the Shopee side and the shared modules. The TikTok session
owns the TikTok side. S2 owns the seller-facing screens. Related: ADR-077 (impact reader), ADR-121
(Shopee models and learning loop), ADR-122 (one Shopee funnel), `docs/architecture/metric-registry.md`,
the UI-refinement grill (G1–G23, 2026-11-16).

## 1. Scope (F1)

One shared model with a thin adapter per platform. Triggers use the same structure (§11).

| Shared (identical on both platforms) | Platform adapter |
|---|---|
| Funnel identity: GMV = views × CTR × CTOR × AOV; every card names the one driver it moves | Levers, each mapped to a shared driver and lever family |
| Base and freshness (§2) | Traffic sources (Shopee Organic / TTLK / Quảng cáo; TikTok product card / video / LIVE / shop tab) |
| Noise band (§3) | Fees and profit (§9) |
| Display rule (§4), within-noise rule (§5) | Data route (Connector / API) and its expected lag |
| Uplift ladder (§6), prior floor (§7) | References and allowed levers for triggers (§11) |
| Middle scenario (§8), Đo lường (§10), trigger types and ranking (§11) | Rule-type triggers (stock, listing hygiene) |

## 2. Base (F2)

- **Window.** Per metric, the shortest of 14 / 30 / 60 days with enough events: clicks for CTR;
  orders for CTOR, AOV and GMV. If none qualifies, the metric is "ít dữ liệu" and not used.
- **Missing days.** Days after a dataset's last data date are missing, not zero. They leave both
  the numerator and the denominator.
- **Out-of-stock and unlisted days** are excluded from the base.
- **Stale data.** No forecast numbers when the newest data is older than the dataset's expected
  lag + 2 days. The card shows "Đơn hàng đến dd/mm" (or the dataset's equivalent) instead.

  | Dataset | Expected lag | No forecast once newest data is |
  |---|---|---|
  | Shopee orders | 0 | 2 days old |
  | Shopee traffic, ads | 1 | 3 days old |
  | TikTok analytics | 2 | 4 days old |

## 3. Noise band (F3)

The **period band** is how much the metric's total over a period of the card's length
(7 / 14 / 30 days) normally varies. It is computed from the product's own history in its §2
window, at the 80 % level, with a ±1 % minimum.
- One pure function: `services/forecast/noise.py :: period_band(...)`. No database access and no
  platform imports.
- It is used by §4 (internal range), §5, §10 and §11.
- TikTok's window-mean band (`optimize_product/volatility.py`) stays only inside its KPI target.

## 4. Display (F4)

- **On screen:** one number per metric, the likely value (P50). Examples: "+3 đơn", "+250.000 đ".
- **Not shown:** no range, no "±x %", no caption.
- **Rounding:** whole orders ("< 1 đơn" under one), whole đồng.
- **Internal only:** P10/P90 and the noise band are computed and used only internally (§5,
  ranking, break-even, §10).
- **Excel:** the Excel exports show P50 only.

## 5. Within normal swing (F5)

A metric whose effect P90 is below its noise band is shown empty ("—"). The card is still shown
and recommended. Non-uplift cards (stock alert, listing_hide, ads_pause, voucher_cap) follow
their own rule.

## 6. Uplift ladder (F6)

Each rung is used only when the one above it isn't available:
1. The shop's own measured response for that lever on that product.
2. Shop calibration from the shop's Đo lường results for that kind, once it has ≥ 5 results.
3. Pooled calibration across shops of the same platform for that kind, once there are ≥ 5 results.
   - Never cross-platform.
   - Sample and sandbox shops are excluded.
   - Per-shop rows stay lane-tagged and deletable (owner rule 2026-11-02).
4. The generic prior with the §7 floor.

The card records which rung it used.

## 7. Prior floor (F7)

Floor = 5 % × min(1, size / reference), applied only on rung 4.
- **Reference sizes:**
  - 10 % for discount levers on both platforms: price, product_discount, flash_sale,
    program_registration, BMSM.
  - 20 % for an ads budget raise.
- **Unsized kinds** get a flat 5 %.
- **No floor** for a size of 0.
- **Exempt (never floored):** description, review voucher, ads pause / remove product,
  listing_hide / relist, voucher_cap, ROAS target (its prior is on ROAS, not volume), and kinds
  with no preset prior.

## 8. Middle scenario (F8)

All shown numbers come from one scenario, so they add up (orders × đơn giá ≈ GMV).
- **Profit known:** the scenario at the middle of Δprofit.
- **Profit unknown:** the scenario at the middle of ΔGMV.
- A cost change can therefore shift the shown orders slightly; this is accepted.

## 9. Outputs (F9)

- **Target:** both platforms show ΔGMV, Δorders, Δprofit, cost and break-even.
- **Shopee:** has all of them today.
- **TikTok:** shows ΔGMV and Δorders; Δprofit is "—" (no caption) until the TikTok profit adapter
  lands.
  - The adapter takes fees from canonical `order_settlements` (fee and tax breakdown, delivered by
    TikTok W2), shaped like Shopee's fee lines.
  - Seller costs come from the same cost settings as Shopee.
  - No stopgap on the legacy `settlements` table.

## 10. Đo lường (F10)

One method on both platforms: the ADR-077 reader (`shopee_recommendations/impact.py`).
- **Window:** the run days (G12) against the same number of days before. Sale days and other
  changes on the product are dropped.
- **Effect:** before/after corrected by the K = 5 most pre-correlated untouched products (at least 3,
  mean r ≥ 0.2). Otherwise plain before/after at the lowest confidence tier.
- **TikTok:** switches to this reader. Its day-7 / day-14 readings remain progress views, and
  seller-set bands remain an extra check, not the verdict.
- **Verdict:** Tăng / Không đổi / Giảm, where "Không đổi" means inside the §3 band. It is based on
  Δ lợi nhuận where profit is known, otherwise on ΔGMV (G15, G16). A card with no estimate still
  gets its measured verdict.
- **Forecast check:** Dự kiến (P50) against Thực tế. "Đúng dự báo" when Thực tế falls inside the
  internal P10–P90 (never shown).
- **Calibration:** only medium or high confidence results, measured on fresh data (§2), feed shop
  and pooled calibration (§6). Lowest-tier results are shown but never calibrate.

## 11. Triggers (F11)

One detector with three types. The adapter supplies the lists.
1. **Problem.** A metric is below its reference by more than its §3 band.
   - GMV is checked first, then the drop is split over views / CTR / CTOR / AOV to pick the target
     metric.
   - Reference = max(shop median, own earlier level, category benchmark when one exists).
2. **Opportunity.** No drop, but a lever's forecast P50 is beyond the §3 band with positive Δprofit
   (ΔGMV when profit is unknown).
   - Opportunity cards must clear the band. §5's "still shown" covers metrics on cards already
     proposed; it does not trigger opportunities.
3. **Rule.** Stock, listing_hide, voucher_cap and similar platform rules, outside the forecast.

**Ranking:** by expected Δprofit (ΔGMV when unknown).
- At a similar value, problem cards rank ahead of opportunity cards.
- Rule cards rank by their own urgency, e.g. stock days left.

## 12. Build ownership

| Area | Shopee | TikTok | Screens |
|---|---|---|---|
| §2, §3, §5, §6, §7, §8 | S1 (`fasttrack/forecast-model-shopee`); `period_band` shared | TikTok session (`fasttrack/p101-tiktok-forecast-f2-f9`) | S2: P50 only, "—" for null, "Đơn hàng đến dd/mm" |
| §9 profit | exists | TikTok session, after W2 settlements | S2: "—" for null Δprofit |
| §10 Đo lường | S1: run-day window, verdict, calibration gating, Dự kiến · Thực tế fields | TikTok session: switch to the ADR-077 reader | S2: Đo lường screens |
| §11 triggers | S1: shared detector in `services/forecast/`, Shopee kinds onto it | TikTok session: optimize_product onto the detector | — |
