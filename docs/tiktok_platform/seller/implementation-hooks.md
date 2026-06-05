# Implementation Hooks: TikTok — Seller

Maps platform features and policies to Juli guardrails.  
Region: Vietnam (VN) | Last reviewed: 2026-06-05

---

## Feature Gates

| Feature / program | Gate condition | Phase | Source |
|-------------------|---------------|-------|--------|
| Affiliate enrollment (seller) | VP < 12 (or AHR ≥ 200 after July 2026) to stay enrolled; suspended at 12 VP / AHR milestone | Phase 2 | [account-health.md](account-health.md) §2.2 |
| Campaign enrollment | VP < 12 (or AHR healthy) | Phase 2 | [account-health.md](account-health.md) §2.2 |
| Listing creation | VP < 24 (suspended at 24 VP); AHR equivalent TBD | Phase 2 | [account-health.md](account-health.md) §2.2 |
| LIVE traffic | VP < 24 (reduced at 24 VP) | Phase 2 | [account-health.md](account-health.md) §2.2 |
| Shopping Center recommendations | VP < 24 (removed at 24 VP) | Phase 2 | [account-health.md](account-health.md) §2.2 |
| Seller balance accessible | No balance withholding event active (triggered by severe violations) | Phase 2 | [account-health.md](account-health.md) §5 |
| Appeal window | First appeal ≤ 30 days from notification; second ≤ 15 days from first rejection | Phase 2 | [account-health.md](account-health.md) §6 |

---

## Alert Candidates (Phase 1.5+)

These map directly to the **Revenue Leakage Detection** and **New Seller Copilot** workflows.

| Policy rule | Trigger | User-facing message (VI) | Module |
|-------------|---------|--------------------------|--------|
| VP approaching 12 (warning at ~7 VP) | Seller VP ≥ 7 | "Cửa hàng đang tiếp cận ngưỡng vi phạm 12 điểm — kiểm tra danh sách vi phạm" | Alerts module (Phase 2) |
| VP hit 12 — affiliate/campaign blocked | Seller VP ≥ 12 | "Chương trình liên kết và chiến dịch bị tạm dừng 7 ngày do vi phạm" | Revenue Leakage (Phase 2) |
| VP hit 24 — listing suspended, LIVE reduced | Seller VP ≥ 24 | "Đăng sản phẩm bị tạm dừng và lưu lượng LIVE bị giảm — hành động cần thiết ngay" | Revenue Leakage (Phase 2) |
| VP hit 36 — shop deactivated 28 days | Seller VP ≥ 36 | "Cửa hàng bị tạm ngừng hoạt động — liên hệ hỗ trợ để khiếu nại" | Revenue Leakage (Phase 2) |
| AHR entering Orange zone (151–199) | AHR ≤ 199 | "Điểm sức khỏe tài khoản đang giảm — xem lại vi phạm trong Seller Center" | Alerts (Phase 2, post-July 2026) |
| AHR entering Red zone (≤150) | AHR ≤ 150 | "Tài khoản ở mức nguy hiểm — hành động ngay để tránh bị tạm ngừng" | Revenue Leakage (Phase 2) |
| High SFCR (seller-fault cancellations) | SFCR trending high | "Tỷ lệ hủy đơn cao — kiểm tra hàng tồn kho và năng lực vận chuyển" | Revenue Leakage (Phase 2) |
| High LDR (late dispatch) | LDR trending high | "Tỷ lệ giao hàng trễ cao — cải thiện để tránh vi phạm SLA" | Revenue Leakage (Phase 2) |
| High return/refund rate | Return rate trending high | "Tỷ lệ hoàn hàng cao — kiểm tra chất lượng sản phẩm và mô tả sản phẩm" | Revenue Leakage (Phase 2) |
| Balance withheld (enforcement) | Balance withholding active | "Số dư tài khoản đang bị giữ — liên hệ hỗ trợ ngay" | Revenue Leakage (Phase 2) |
| Appeal window expiring | Violation date approaching 30-day deadline | "Cửa sổ khiếu nại sắp đóng — hành động trong X ngày" | Alerts (Phase 2) |

---

## ETL / Sync Behavior

| Platform rule | Sync adjustment | Source |
|---------------|-----------------|--------|
| Balance withholding (180-day max) | Mark seller's balance as `withheld`; do not treat as settled revenue | [account-health.md](account-health.md) §5 |
| Affiliate enrollment blocked (VP ≥ 12) | Suppress affiliate recruitment recommendations; flag in New Seller Copilot | [account-health.md](account-health.md) §2.2 |
| 30-day grace on commission rate decrease | Do not immediately sync lower rate; track grace period state per creator per product | [feature-guide.md](feature-guide.md) §1.2 |
| Joint creator-seller penalty | If linked creator has violations, flag seller's affiliated shop for potential enforcement risk | [account-health.md](account-health.md) §2.3 |
| AHR points from completed orders (weekly) | Treat weekly completed-order batch as input to AHR delta; do not double-count pending orders | [account-health.md](account-health.md) §3.1 |
| Settlement hold (7–14 days) | Already in `data-sources.md` Operational Rules; confirmed consistent with platform policy | `data-sources.md` |

---

## Matching / Recommendation Filters

Seller account health informs the **New Seller Copilot** decision tree and
**Revenue Leakage Detection** risk bands:

| Platform signal | Filter / rank adjustment | Source |
|----------------|--------------------------|--------|
| VP ≥ 12 (or AHR Orange) | Flag seller as elevated-risk in Copilot; suppress affiliate recruitment suggestions | [account-health.md](account-health.md) §2.2 |
| VP ≥ 24 (or AHR Red ≤150) | Downgrade seller trust score; prioritize stabilization actions over growth | [account-health.md](account-health.md) §2.2 |
| VP = 48 / AHR = 0 | Offboard seller from active recommendations; move to recovery/re-application guidance | [account-health.md](account-health.md) §2.2 |
| SFCR high | Revenue Leakage — Cancellation sub-module trigger | [policy.md](policy.md) |
| SNAD violations | Revenue Leakage — Product quality sub-module trigger | [policy.md](policy.md) |
| High return/refund rate | Revenue Leakage — Refund fraud sub-module trigger | [policy.md](policy.md) |

---

## API Cross-References

| Platform feature / rule | API exposure | api-docs link |
|------------------------|--------------|---------------|
| Seller VP / AHR score | **UNKNOWN** until P2-1 verification. Contract: `health_data_source: api | proxy | unavailable`; never scrape Seller Center (Forbidden #9). | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Seller SFCR / LDR metrics | UNKNOWN — may be in Shop Account or Order endpoints; if not exposed, compute proxy rates from Orders schema (UNVERIFIED) | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Balance withholding status | UNKNOWN — may be a dedicated field/event; if not exposed, treat as `unavailable` (do not guess) | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Affiliate enrollment status | UNKNOWN — check Affiliate API; errors (100003) are a behavioral proxy only | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Linked creator violation risk | Webhook or polling — event catalog UNKNOWN; treat as `unavailable` until verified | [`docs/tiktok_api/webhooks.md`](../../tiktok_api/webhooks.md) |

---

## data-sources.md Impact

| Row / rule | Proposed change |
|------------|-----------------|
| Operational Rules — Settlements | **Add:** "Seller balance withheld under enforcement (§7 of Seller Performance Evaluation Policy) must be treated as `frozen`, not `pending` — distinct from the 7–14 day settlement hold" |
| Operational Rules — Health check | **Add:** "Poll seller account health (VP / AHR) daily in Phase 2; alert if VP ≥ 7 or AHR ≤ 199; trigger Revenue Leakage workflow when thresholds hit" |
| Operational Rules — AHR transition | **Add:** "After July 2026, switch health-check logic from VP milestones (12/24/36/48) to AHR milestones (150/100/50/0); read both during transition period (May–July 2026)" |
| New Forbidden row candidate | "Do not surface seller-facing Seller Center internal health dashboards by scraping — Forbidden (#9 already covers this); rely exclusively on API-exposed health fields" |
