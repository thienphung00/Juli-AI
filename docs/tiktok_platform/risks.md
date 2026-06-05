# Platform Documentation Risks — TikTok (Vietnam)

Region: Vietnam (VN) | Last reviewed: 2026-06-05

---

## 1. Active System Transitions

### 1.1 Violation Points → Account Health Rating (Seller)

| Risk | Detail |
|------|--------|
| Dual system during transition (May–July 2026) | Enforcement logic must handle both VP and AHR during the preview/transition window |
| AHR formula differs from VP | VP counts up (bad); AHR counts down (bad) — inversion risk in alert logic |
| VN AHR zones vs US zones | US orange = 51–199, red = ≤50; VN orange = 151–199, red = 1–150 — different thresholds |
| Timeline drift | TikTok said "gradually from mid-June, fully July 2026" — exact date per shop not specified |
| Action | When implementing account health alerts in Phase 2, **do not assume** VP/AHR are exposed via Partner API. Add a P2-1 verification gate (API Reference + API Testing Tool). Implement `health_data_source: api | proxy | unavailable` and only do VP/AHR dual-read if fields exist. Never scrape Seller Center (Forbidden #9). |

### 1.2 Creator Age Verification → Tax Info (VN-specific)

| Risk | Detail |
|------|--------|
| Policy article moved | The knowledge_id=2069202009917200 article now redirects to Tax Information |
| Tax code requirement since July 1, 2025 | Vietnamese government mandate; creators without tax code cannot withdraw commissions |
| Not universal | This is REGION-VARIANT: VN — other markets do not have this requirement |
| Action | KYC completion check must include tax code verification for VN creators |

---

## 2. Documentation Gaps (UNKNOWN)

The following policy areas were NOT retrieved in this pass. They represent knowledge gaps
that could affect Juli's implementation correctness:

| Gap | Impact | Priority |
|-----|--------|---------|
| VN-specific CHR thresholds and enforcement actions | Creator eligibility gates may be misconfigured if US thresholds differ from VN | HIGH |
| Restricted & Prohibited Content article (VN) | Cannot gate creator eligibility for restricted categories without this | HIGH |
| Full Seller Feature Guide (product, finance, logistics, programs) | New Seller Copilot and Growth Copilot decisions incomplete | HIGH |
| Settlement policy details (seller-side) | 7–14 day hold is in `data-sources.md` but not sourced to official policy article | MEDIUM |
| Star Seller / Mall eligibility criteria | New Seller Copilot tier-based advice requires these thresholds | MEDIUM |
| Creator campaign eligibility criteria | Cannot advise creators on campaign participation | MEDIUM |
| MCN partnership details and API exposure | Creator quality signals incomplete | LOW |
| VN affiliate disclosure obligations | Compliance gap for creators promoting products | MEDIUM |
| CHR point deduction catalog | Cannot surface specific violation warnings for creators | MEDIUM |
| Creator-side appeal timelines | Onboarding guidance incomplete | LOW |

---

## 3. Regional Variance Risks

| Topic | Known VN-specific variant |
|-------|--------------------------|
| Tax code for creators | CCCD = tax code; mandatory from Jul 1, 2025 |
| AHR zone thresholds | VN: orange 151–199 / red 1–150 vs US: orange 51–199 / red ≤50 |
| AHR launch timeline | VN: preview May 2026, full replacement July 2026 |
| Follower threshold for affiliate | 1,000 (confirmed VN); US market is 5,000 for Open Collaboration (DISCREPANCY — verify VN Open Collab requirement for creators) |
| Seller Center language | Vietnamese; some articles may lag in English translation |

---

## 4. Policy Change Cadence Risk

| Risk | Detail |
|------|--------|
| Frequent policy updates | TikTok Shop updates policies without stable versioning; URLs and knowledge_ids may change |
| No official changelog API | Policy changes must be monitored via the "Latest Policy Updates" article |
| VP → AHR migration mid-quarter | Any hardcoded VP thresholds in Juli code will break after July 2026 |
| Commission rules | "Tiered Commission for Creators" article referenced but not retrieved — may contain additional rate rules |
| Action | Subscribe to https://seller-vn.tiktok.com/university/essay?knowledge_id=8831988245645057&lang=en as changelog; re-run `platform-docs` each quarter |

---

## 5. Forbidden Boundary Confirmations

These Forbidden rows from `docs/architecture/data-sources.md` are confirmed by this policy pass:

| Forbidden (#) | Confirmation |
|--------------|-------------|
| #8 Realtime unofficial streams | Creator LIVE data via unofficial websockets remains Forbidden; official LIVE data (Phase 3+) must use TikTok LIVE API only |
| #9 Seller Center scraping | Shop Health page, Violation Records, AHR scores must come from official TikTok API only — **not** browser-scraped from Seller Center |
| #17 Buyer PII | Commission formula uses `Revenue − Refunds`; buyer contact details are never required; masked buyer_id only |

---

## 6. ADR Candidates

| ADR | Title | Rationale |
|-----|-------|-----------|
| ADR-NNN | Alert on VP/AHR vs silent degradation | VP and AHR milestone hits block affiliate enrollment — Juli must surface these immediately rather than silently failing to recommend collab actions |
| ADR-NNN | Dual-system health-check during VP → AHR transition | Phase 2 launches ~Weeks 9–13; AHR fully replaces VP in July 2026; requires feature-flagged dual-read logic |
| ADR-NNN | VN-specific regional config for creator eligibility | Tax code, 1k follower threshold, CHR zone boundaries differ from US; need configurable per-market rules rather than hardcoded global values |
