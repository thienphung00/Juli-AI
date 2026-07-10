# Creator Programs & Eligibility — TikTok Shop (Vietnam)

Source: https://seller-vn.tiktok.com/university/home?role=creator&menu=feature  
Region: Vietnam (VN) | Last reviewed: 2026-06-05

---

## 1. Account Type Taxonomy

TikTok Shop distinguishes four creator account types with different follower requirements and
capabilities. Understanding this taxonomy is critical for Juli's creator eligibility gate
(Phase 3+ matching, and for `GET /v1/creators` filtering in Phase 2).

### 1.1 Link-Share Only Creator

| Field | Value |
|-------|-------|
| Min followers | 0 (no minimum) |
| Showcase visibility | Hidden (creator-view only) |
| Earn from product links | Yes (via link sharing outside TikTok Shop) |
| Earn from short videos | **No** |
| Earn from LIVE | **No** |
| Earn from showcase (public) | **No** — showcase not public |
| Free sample requests | No |
| Upgrade path | Auto-upgrades to Affiliate Creator once ≥1,000 followers + general requirements met |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en |

### 1.2 Affiliate Creator

| Field | Value |
|-------|-------|
| Min followers | ≥ 1,000 |
| Showcase visibility | Public |
| Earn from short videos | **Yes** |
| Earn from LIVE | **Yes** |
| Earn from showcase links | Yes |
| Earn from product link sharing | Yes |
| Free sample requests | Yes (from sellers) |
| Once granted | Stays Affiliate even if followers drop below 1,000 threshold |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en |

### 1.3 Shop Official Account

| Field | Value |
|-------|-------|
| Min followers | 0 (no minimum) |
| Linked to | A specific TikTok Shop account |
| Products promoted | **Own shop only** — cannot earn affiliate commissions from Product Marketplace |
| Account name | Must match shop name; auto-updates if shop name changes |
| Can upgrade | Yes — can be bound as Marketing Account to access affiliate if eligible |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=104015979497218&lang=en |

### 1.4 Shop Marketing Account

| Field | Value |
|-------|-------|
| Min followers | 0 for linked-shop products; ≥ 1,000 for affiliate on Product Marketplace |
| Linked to | A specific TikTok Shop account |
| Products promoted | Own shop + Product Marketplace (once affiliate criteria met) |
| Affiliate application | In Creator Center, once follower + general requirements satisfied |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=104015979497218&lang=en |

---

## 2. General Eligibility Requirements (all creator types)

The following **must** be met at initial application and maintained to retain e-commerce permissions:

| Requirement | Detail |
|------------|--------|
| Age | ≥ 18 years old |
| Followers | ≥ 1,000 for Affiliate designation (0 for Link-Share Only, Official, Marketing) |
| Account type | Must NOT be a Government, Politician and Political Party Account (GPPPA) |
| Community guidelines | E-commerce content must comply with TikTok Community Guidelines |
| No prior revocation | Must not have had e-commerce permissions previously revoked by TikTok Shop |
| Associated shop health | Associated TikTok Shop account(s) must have no platform violation risk |
| Creator Code of Conduct | No violations |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=6837793229817601&lang=en  
Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en

### 2.1 Retention Requirements (to stay a TikTok Shop Creator)

| Rule | Threshold |
|------|----------|
| Violation points | Must NOT accumulate 24 violation points |
| Account type | Must NOT become GPPPA after approval |
| Associated shop risk | Must NOT be linked to a TikTok Shop account with platform violation risk |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=6837793229817601&lang=en

---

## 3. Identity Verification Requirements

| Creator origin | Accepted documents | Additional requirement |
|---------------|-------------------|----------------------|
| Vietnamese | Căn cước công dân (CCCD) — 12-digit ID card | Tax code (= same as CCCD number) — mandatory since Jul 1, 2025 (VN government regulation) |
| Non-Vietnamese | Passport | Proof of Address in Vietnam (utility bill, credit card statement, or bank statement containing name + full Vietnamese address) |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en

**REGION-VARIANT: VN** — Tax code submission is a Vietnam-specific government mandate
(effective July 1, 2025). Other markets may not require this step.

---

## 4. Affiliate Program Entry (step-by-step)

Creators must complete all of the following before earning:

1. Create TikTok Account with ≥ 1,000 followers (for Affiliate designation)
2. Apply via TikTok Profile → "Creator tools" → "TikTok Shop for Creator" → "Apply"
3. Complete Identity & Age Verification (KYC) — CCCD + tax code (VN)
4. Set up Commission Account — name must match bank account name (permanent)
5. Add beneficiary bank account

KYC is prompted at multiple in-app trigger points (post-onboarding, add product to showcase,
post shoppable video, go LIVE, add product during LIVE, Verification Center, notifications).

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en

---

## 5. Qualification for Restricted Products

| Product type | Additional requirement |
|-------------|----------------------|
| Pre-owned products | Violation Points = 0 **AND** Promotion Quality Points ≥ 3.5 |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=104015979497218&lang=en

---

## 6. TikTok Bonus Program

| Field | Value |
|-------|-------|
| Program | TikTok Bonus (TB) — additional incentives on qualifying sales |
| Access | Invite-only / platform-selected creators |
| Application | Automatic — no opt-in |
| Rules | Vary by campaign: new content only vs all content; LIVE-only; time windows; budget caps |
| Earning cap | Maximum reward cap per creator and per product per campaign |
| Source | https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en |

---

## 7. MCN Partnerships (Multi-Channel Networks)

| Field | Value |
|-------|-------|
| What | Talent agencies that manage creator accounts, negotiate brand deals, track performance |
| Relevance to Juli | MCN-managed creators may have different commission structures or higher leverage; known MCN affiliation is a quality signal for creator matching (Phase 3+) |
| API exposure | UNKNOWN — check if MCN affiliation is exposed via `GET /v1/creators` |
| Source | TikTok Shop Academy Feature Guide nav — article content UNKNOWN in this pass |
