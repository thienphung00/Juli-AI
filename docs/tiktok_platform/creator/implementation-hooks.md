# Implementation Hooks: TikTok — Creator

Maps platform features and policies to Juli guardrails.  
Region: Vietnam (VN) | Last reviewed: 2026-06-05

---

## Feature Gates

| Feature / program | Gate condition | Phase | Source |
|-------------------|---------------|-------|--------|
| Affiliate Creator badge / matching | Creator must have ≥ 1,000 followers AND completed KYC AND have no e-commerce permission revocation | Phase 2 (`GET /v1/creators` filter) | [programs-and-eligibility.md](programs-and-eligibility.md) |
| Creator commission display | Creator must have verified Commission Account (bank name match) before showing withdrawable earnings | Phase 2 | [feature-guide.md](feature-guide.md) §1.1 |
| Free sample requests | Affiliate Creator designation only (≥1,000 followers) | Phase 2 | [programs-and-eligibility.md](programs-and-eligibility.md) |
| LIVE commerce attribution | Affiliate Creator only; LIVE data collection is **Phase 3+** (EXECUTION.md) | Phase 3+ | [feature-guide.md](feature-guide.md) §3 |
| Pre-owned product promotion | Violation Points = 0 AND Promotion Quality Points ≥ 3.5 | Phase 2+ | [programs-and-eligibility.md](programs-and-eligibility.md) §5 |
| TikTok Bonus eligibility | Platform-selected; no Juli action needed (auto-applied by TikTok) | Phase 2 (read-only signal) | [feature-guide.md](feature-guide.md) §6 |

---

## Alert Candidates (Phase 1.5+)

| Policy rule | Trigger | User-facing message (VI) | Module |
|-------------|---------|--------------------------|--------|
| CHR milestone at 150 | Creator CHR drops to ≤ 150 | "Điểm CHR của nhà sáng tạo đang ở mức rủi ro — kiểm tra vi phạm tài khoản" | Alerts / dashboard (Phase 3+ — creator matching out of scope P1–2) |
| Commission Account not set up | Creator has no verified payout account | "Nhà sáng tạo chưa thiết lập tài khoản nhận hoa hồng — không thể rút tiền" | Onboarding guard (Phase 2) |
| KYC incomplete | Creator has not completed identity verification | "Nhà sáng tạo chưa xác minh danh tính — không thể đăng nội dung mua sắm" | Onboarding guard (Phase 2) |
| Affiliate status lost (below 24 VP) | Creator loses e-commerce permissions | "Nhà sáng tạo đã mất quyền thương mại điện tử" | Creator eligibility gate (Phase 3+) |
| Commission payout delayed (refund dispute) | Order in dispute state; commission held | "Hoa hồng đang bị giữ do tranh chấp hoàn trả" | Revenue Leakage signal (Phase 2) |

---

## Matching / Recommendation Filters (Phase 3+)

Creator ↔ Shop matching is explicitly **Phase 3+** per EXECUTION.md. These filters
should be loaded as context when that work begins:

| Platform signal | Filter / rank adjustment | Source |
|----------------|--------------------------|--------|
| Creator type = Affiliate (≥1,000 followers) | Hard filter: only match Affiliate creators | [programs-and-eligibility.md](programs-and-eligibility.md) |
| CHR zone = Red (≤150) | Penalize rank or filter out | [policy.md](policy.md) §6 |
| CHR zone = Black (0) | Hard filter: exclude | [policy.md](policy.md) §6 |
| KYC completed | Hard filter: only match verified creators | [programs-and-eligibility.md](programs-and-eligibility.md) §3 |
| MCN affiliation | Positive rank signal (MCN-backed = quality signal) | [feature-guide.md](feature-guide.md) §6 |
| Free sample request capability | Affiliate type gate; filter for sample-based collab | [programs-and-eligibility.md](programs-and-eligibility.md) §1.2 |
| Associated shop violation risk | Hard filter: exclude creators linked to violating shops | [compliance.md](compliance.md) §5 |
| GPPPA account | Hard filter: exclude | [policy.md](policy.md) §1.1 |

---

## ETL / Sync Behavior

| Platform rule | Sync adjustment | Source |
|---------------|-----------------|--------|
| Commission settlement: 3rd or 15th day | Treat as `pending` until settlement date passes; do not count as final revenue | [feature-guide.md](feature-guide.md) §7 + `data-sources.md` Operational Rules |
| Commission on hold due to dispute | Hold `pending` indefinitely until dispute resolves; flag as leakage signal | [feature-guide.md](feature-guide.md) §7 |
| Commission rate decreased by seller → 30-day grace | Do not update creator's rate immediately — 30-day transition | [feature-guide.md](feature-guide.md) §7 |
| Tax code (VN) mandatory | Treat creators without tax code verification as KYC-incomplete | [programs-and-eligibility.md](programs-and-eligibility.md) §3 |
| Link-Share Only account | Treat as ineligible for video/LIVE commission attribution in reporting | [programs-and-eligibility.md](programs-and-eligibility.md) §1.1 |

---

## API Cross-References

| Platform feature / rule | API exposure | api-docs link |
|------------------------|--------------|---------------|
| Creator follower count | `GET /v1/creators` — `follower_count` field | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Creator affiliate status | `GET /v1/creators` — eligibility fields; check if `is_affiliate` exposed | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Creator CHR / health score | UNKNOWN — check if TikTok API exposes CHR; not in current endpoint catalog | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Commission settlement dates | Affiliate order events via webhook or polling | [`docs/tiktok_api/webhooks.md`](../../tiktok_api/webhooks.md) |
| TikTok Bonus (TB) attribution | UNKNOWN — may be a field on affiliate order or separate endpoint | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| MCN affiliation | UNKNOWN — not confirmed in current API catalog | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |
| Creator KYC status | UNKNOWN — likely not exposed via official API | [`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md) |

---

## data-sources.md Impact

| Row / rule | Proposed change |
|------------|-----------------|
| `data-sources.md` Operational Rules — Settlements | **Reinforce:** Creator commissions follow the same 7–14 day hold logic as seller settlements; treat as `pending` until 3rd/15th day payout triggers |
| New operational rule: Commission disputes | Add: "Creator commissions on disputed or refunded orders must be held in `pending` state until dispute resolution; flag as Revenue Leakage signal" |
| Forbidden #17 (Buyer PII) | Confirmed: Creator data should never include buyer contact info; only commission amounts, order counts, and seller-affiliate attribution signals |
