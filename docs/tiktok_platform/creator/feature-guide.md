# Creator Feature Guide — TikTok Shop (Vietnam)

Source: https://seller-vn.tiktok.com/university/home?role=creator&menu=feature  
Region: Vietnam (VN) | Last reviewed: 2026-06-05

---

## 1. Getting Started — Account Setup

### 1.1 Commission Account (Payout Account)

| Field | Value |
|-------|-------|
| Feature | Commission / Payout Account Setup |
| Applies to | All affiliate creators |
| What it does | Enables commission withdrawal; links creator identity to a bank account |
| Prerequisites | Successful Creator Account creation first |
| Where | Entirely in TikTok App (not Seller Center) |
| Critical constraint | Account name **cannot be changed** after submission; must exactly match bank account name |
| Source | https://seller-vn.tiktok.com/university/essay?identity=1&role=2&knowledge_id=6837827107358465&from=feature_guide |

**Steps (in-app):**
1. Open TikTok App → Creator tools
2. Set up Commission Account
3. Confirm name matches bank account name exactly

**Impact on Juli:** Commission withdrawal is gated on this setup. An onboarding alert should
flag creators who have not completed their Commission Account before they attempt to withdraw
earnings. See [implementation-hooks.md](implementation-hooks.md).

---

### 1.2 Identity Verification (KYC)

| Field | Value |
|-------|-------|
| Feature | Identity & Age Verification |
| Applies to | All creators before any e-commerce action |
| Trigger points | Post onboarding, adding product to showcase, posting shoppable video, going LIVE, adding product during LIVE, Verification Center, in-app notification |
| Documents (Vietnamese) | Căn cước công dân (CCCD) 12-digit ID card + Tax code (mandatory since Jul 1, 2025) |
| Documents (Non-Vietnamese) | Passport + Proof of Address (utility bill / credit card / bank statement with Vietnamese address) |
| Constraint | All docs must be valid, unaltered, <5 MB (PDF, JPEG, PNG), matching name |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en |

**Tax requirement (REGION-VARIANT: VN):** Vietnamese government regulation effective
July 1, 2025 requires creators to submit their tax code (same as CCCD 12-digit number)
before commission withdrawal is permitted.

---

## 2. Product Selection

| Feature | Description | Source |
|---------|-------------|--------|
| Add products to Showcase | Creator links products to their TikTok profile showcase; Link-Share Only showcases remain hidden | https://seller-vn.tiktok.com/university/essay?knowledge_id=104015979497218&lang=en |
| Free Sample Requests | Affiliate Creators (≥1000 followers) can request free products from sellers for content | https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en |
| Store Rating Score | Seller-facing signal visible to creators; affects product marketplace ranking | UNKNOWN — article not retrieved in this pass |
| Product Marketplace | Affiliate Creators browse products to promote; available commission rates visible | https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en |

---

## 3. Live Streaming (Creator)

| Feature | Description |
|---------|-------------|
| Live setup | In-app TikTok LIVE configuration |
| LIVE PC Management | Desktop/OBS-based streaming workflow |
| OBS integration | Third-party OBS Studio support for professional setups |
| Live activities | Interactive audience features during LIVE sessions |
| Product links during LIVE | Affiliate Creators can add and sell products during live sessions |
| LIVE commission | Affiliate Creators earn commission from LIVE-attributed sales |

Source: TikTok Shop Academy Feature Guide nav — detailed article content not retrieved in this pass (UNKNOWN per article).  
Cross-reference: API exposure — UNKNOWN (check `docs/tiktok_api/endpoints.md` for livestream endpoint status).

**Note:** `sync_livestreams` polling worker is **out of scope for Phase 1–2** per
`EXECUTION.md`. LIVE data is a Phase 3+ signal.

---

## 4. Selling via Video (Short-form)

| Feature | Description |
|---------|-------------|
| Shoppable videos | Affiliate Creators embed product links in TikTok short videos |
| Commission from videos | Affiliate Creators (≥1000 followers) earn on video-attributed sales |
| Link-Share Only restriction | Link-Share Only creators CANNOT earn commission from video attribution |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en

---

## 5. TikTok Shop Showcase

| Feature | Description |
|---------|-------------|
| Creator showcase | Product storefront on creator's TikTok profile page |
| Visibility | Affiliate Creators: public; Link-Share Only: hidden (creator-only view) |
| Showcase link sharing | Affiliate Creators can share showcase link; all products eligible for commission |
| Official account showcase | Shop page only (own-shop products, not Product Marketplace) |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en

---

## 6. Creator Growth Programs

| Program | Description | Eligibility |
|---------|-------------|------------|
| Creator Tasks | Platform-assigned tasks rewarding engagement/content performance | UNKNOWN — not retrieved |
| Top Creators List | Leaderboard of high-performing creators | UNKNOWN — not retrieved |
| MCN Partnerships | Talent agencies (Multi-Channel Networks) managing creators; can link accounts | UNKNOWN — not retrieved |
| TikTok Bonus (TB) | Additional incentive program applied automatically to qualifying sales | Selected creators (invite/campaign basis) |

Source (TB): https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en

**TikTok Bonus rules:**
- Applied automatically — no opt-in required
- Rewarding rules vary by campaign (new content only vs all content; LIVE only; etc.)
- Budget caps apply per creator/product per campaign
- If campaign budget depleted, bonuses stop

---

## 7. Finance — Commission & Withdrawal

### Commission Calculation

| Rule | Value |
|------|-------|
| Formula | `Commission = (Revenue − Refunds) × Commission rate` |
| Display | Estimated commission shown on orders page; **not final** until order closes |
| Commission rate | Set by seller; varies by product; typically 5–50% |
| Rate changes | Increase → immediate; Decrease → 30-day grace period for creators who already added product |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en |

### Settlement / Payout Schedule

| Rule | Value |
|------|-------|
| Payout dates | 3rd or 15th day after order successfully delivered |
| Settlement period | Based on seller's settlement period with TikTok Shop |
| Delay triggers | Disputes, refund requests, return requests — commission held until resolved |
| Withdrawable commissions | Visible in "Payout summary" in E-commerce Creator Center |
| Prerequisite | Must have verified Commission Account and matching name |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en |

**Impact on Juli (seller-side):** Commission payout delays (due to returns/refunds) are a
**Revenue Leakage signal** — affiliate fraud detection should flag abnormal refund patterns that
may be depressing seller GMV. See `docs/tiktok_api/endpoints.md` for affiliate endpoint.

### Check Orders

Feature: Creators can view their affiliate order status in Creator Center. This is a read-only
in-app view; Juli does not replicate this — sellers see creator-attributed orders in Seller Center.

---

## 8. Performance Data (Creator Analytics)

| Analytics Module | Description |
|----------------|-------------|
| Data Overview | Aggregate commission, GMV, orders across all channels |
| Video Analytics | Views, click-through rate, commission from individual shoppable videos |
| Live Analytics | LIVE viewer count, GMV, peak moments |
| Product Analytics | Which products performed best in creator's catalog |
| User Analytics | Audience demographics and reach |

Source: TikTok Shop Academy Feature Guide nav — article content UNKNOWN in this pass.  
API cross-reference: Creator analytics is not directly exposed in Juli's current `GET /v1/creators`
endpoint — it returns catalog-level signals, not content analytics. See
[`docs/tiktok_api/endpoints.md`](../../tiktok_api/endpoints.md).

---

## 9. Advertising (Creator-Side)

| Feature | Description |
|---------|-------------|
| Ads | Creator-promoted paid content |
| Ad Manager | Platform to manage creator ad campaigns |

Source: Feature Guide nav — article content UNKNOWN in this pass.  
Note: Creator advertising is distinct from seller-managed TikTok Ads (`TikTok Ads` row in
`data-sources.md`). Creator Ad Manager access is separate from Seller Center ads.
