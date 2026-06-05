# Cross-Cutting Topics: TikTok — Seller + Creator

Topics that span both seller and creator identities.  
Region: Vietnam (VN) | Last reviewed: 2026-06-05

---

## 1. Affiliate Collab (Seller ↔ Creator)

The TikTok Shop affiliate program is the primary bridge between sellers and creators.
Both sides have platform-defined rights and obligations.

### 1.1 Program Architecture

| Concept | Seller perspective | Creator perspective |
|---------|------------------|-------------------|
| Open Collaboration | Sets fixed commission; passive creator discovery | Any eligible Affiliate Creator can pick up products |
| Targeted Collaboration | Invites specific creators; negotiable rate | Receive invite; accept/decline |
| Commission rate | Set and adjustable by seller (with grace period rules) | Displayed in Product Marketplace; rate locked for 30 days after decrease |
| Sample seeding | Fulfill free sample requests | Affiliate Creators can request samples |
| Tracking | Seller Center → Affiliate Center → analytics | Creator Center → affiliate orders |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en  
Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10013032&lang=en

### 1.2 Commission Lifecycle

| Stage | Rule |
|-------|------|
| Product added to showcase | Creator's commission rate locked at current rate |
| Rate decrease by seller | 30-day grace period — creator earns higher rate for 30 days |
| Rate increase by seller | Takes effect immediately |
| Order placed | Estimated commission shown; NOT final |
| Formula | `Commission = (Revenue − Refunds) × Commission rate` |
| Settlement | 3rd or 15th day after successful delivery |
| Dispute/return | Commission held until resolved |
| Payout | Creator withdraws from "Payout summary" in Creator Center |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en

### 1.3 Joint Enforcement Risk

When a seller's linked creator account violates policies, TikTok Shop may apply **joint
penalties** to both the seller's shop and the creator's account.

| Scenario | Seller impact | Creator impact |
|---------|--------------|----------------|
| Creator CHR = 0 (deactivated) | Seller loses that creator's affiliate attribution | Creator loses e-commerce permissions |
| Seller VP ≥ 48 (suspended) | Creator loses commission source | Creator's existing orders still settle; future collab blocked |
| Associated account violations | Enforcement may transfer across association | Both accounts may receive enforcement |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=10015235&lang=en §3

### 1.4 TikTok Bonus — Shared Impact

TikTok Bonus (TB) campaigns incentivize creator content and directly impact seller GMV:

| Effect | Seller | Creator |
|--------|--------|---------|
| TB increases creator content volume | More organic promotion; GMV lift | More earning opportunities |
| Campaign budget depletion | Bonus stops mid-campaign; sudden drop in creator motivation | Creator may stop promoting if TB depleted |
| New-content-only TB campaigns | Seller should encourage creators to post fresh content | Creator must create new videos to earn TB |

Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en

---

## 2. Seller Health ↔ Creator Eligibility Link

Creator e-commerce permissions are tied to their associated TikTok Shop account's health:

| Scenario | Creator impact |
|---------|---------------|
| Seller (linked to creator) has platform violation risk | Creator's e-commerce permissions may be suspended |
| Creator has active violations | Seller's affiliated products may lose creator-attributed traffic |
| Seller receives 12 VP — affiliate blocked | Creator cannot receive new collab invites from that seller |

This creates a **mutual dependency** that Juli must model when surfacing health alerts:
- A seller's VP/AHR degradation is not only a seller-money problem — it may disable
  high-performing creator relationships and suppress affiliate GMV.

---

## 3. Live Commerce (Cross-Cutting)

Live streaming is a joint activity where sellers and creators collaborate:

| Aspect | Seller | Creator |
|--------|--------|---------|
| Setup | Seller sets live commerce settings, product links, pinned items | Affiliate Creator goes LIVE with product links |
| Commission | Seller pays affiliate commission on LIVE-attributed sales | Creator earns from LIVE session |
| Traffic reduction | Seller VP ≥ 24 → LIVE traffic reduced | Creator's LIVE audience indirectly reduced if linked shop has low health |
| Phase gate | LIVE data collection is Phase 3+ in EXECUTION.md | LIVE attribution is Affiliate Creator feature only |

---

## 4. Implementation Notes for Juli

### Revenue Leakage → Affiliate Fraud

The affiliate refund pattern is a key Revenue Leakage Detection signal:

- Abnormally high return/refund rates on affiliate orders (creator-attributed) may indicate
  affiliate fraud (false returns to suppress commission payouts, or inflated orders).
- Monitor: `Commission = (Revenue − Refunds) × Rate` — if refunds spike on affiliate orders,
  it directly cuts creator earnings AND indicates potential fraud.
- Source: https://seller-vn.tiktok.com/university/essay?knowledge_id=7904880287155985&lang=en

### New Seller Copilot → Affiliate Onboarding

New sellers (Phase 2) need to understand the affiliate program structure:

- Encourage setting up Open Collaboration with competitive commission (10–15% baseline)
- Guide sellers through creator recruitment (Find Creators tool in Seller Center)
- Surface when affiliate enrollment is blocked due to VP violations → block is critical
  path blocker for seller's first collab GMV

### Creator ↔ Shop Matching (Phase 3+)

Full matching is Phase 3+ per EXECUTION.md. The data model to prepare:
- Creator eligibility gate: Affiliate type, CHR zone, follower count, KYC status
- Seller affinity signal: VP/AHR zone, category fit, open commission rate vs. targeted
- Mutual dependency: seller health → creator eligibility; creator CHR → seller affiliate risk

Cross-reference: [`creator/implementation-hooks.md`](creator/implementation-hooks.md) §Matching
