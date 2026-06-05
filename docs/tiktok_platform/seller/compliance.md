# TikTok Shop — Seller Compliance

Source: `https://seller-vn.tiktok.com/university/essay?identity=1&role=1&knowledge_id=8831988245645057&from=policy`
Last reviewed: 2026-06-05

---

## Prohibited and Restricted Products

### Illegal products

Products that may not comply with local laws, regulations, product qualifications,
certifications, or technical standards are prohibited. This includes:
- Products not lawfully importable in the buyer's country
- Counterfeit or fraudulent products
- Products infringing intellectual property rights
- Products determined unsafe by local authorities

TikTok Shop reserves the right to remove any listing it determines is prohibited,
potentially illegal, or inappropriate.

Source: Apr 2026 policy reminder

### Dangerous goods

Must be declared during product listing (required from Sep 16, 2024). Common examples:
- Lithium battery products (powerbanks, laptops, smartphones)
- Corrosive or flammable liquids (household cleaners)
- Aerosol products (insecticides, air fresheners)
- Oxidizing products (fertilizers)

**How to declare:** Seller Center → Add/Edit product → Shipping section → "Dangerous Goods" attribute = Yes.

**Non-declaration:** May result in seizure/destruction of parcels, order cancellation, and enforcement actions.

### Mandatory product attributes (effective Mar 20, 2026)

All product categories must include:
- Country of Origin
- Manufacturer or Trader Name
- Manufacturer or Trader Address

Additional requirements for **Beauty & Personal Care, Health, Baby & Maternity, Food & Beverages**:
- Product License Type
- Product License Number
- Date of Issuance
- Place of Issuance

### Electronic product certifications

All electronic products must meet local safety certification and attribute requirements
before listing. Mandatory attributes marked with `*`. Non-compliance may lead to
listing deactivation.

Source: Dec 2025 policy reminder

---

## Intellectual Property (IP) and Branded Products

### Brand Qualification (BQ)

Required for sellers wishing to list branded products.

**Application process:**
1. Seller Center → My Account → Account Settings → Qualification Centre → Brand Qualification → Add Brand Qualification
2. Option: Apply without written LOA if brand owner has agreed (from May 1, 2026):
   - Select "I don't have written authorisation"
   - Trademark Owner confirms via IPPC portal
   - Processing up to 7 calendar days

**Important changes:**
- Mall sellers cannot use Proof of Purchase for Brand Qualification (from Mar 12, 2025)
- 1st Level Authorization Letters are optional for 2nd-Level Authorized Sellers (`UNKNOWN` launch date — "coming soon" as of early 2025)

### Brand Circumvention Policy (updated May 28, 2026)

Brand circumvention now explicitly includes **text-based evasion tactics**:
- Misspelling brand names ("Nik3", "N!ke", "N i k e")
- Inserting symbols, numbers, or spaces to evade detection

Applies to listings, videos, and live stream content. May result in listing removal and
enforcement actions.

Source: May 2026 update

### Unsupported Brands (from May 22, 2026)

TikTok Shop restricts brands with consistently high negative customer feedback rates.
Active listings for restricted brands must be removed immediately.

Source: May 2026 update

### Switched/Recycled Listings

Editing a product listing to represent a different item is strictly prohibited.
Listings must accurately reflect the actual product.

Source: Early 2025 policy reminder

---

## Listing Standards

| Rule | Detail |
|------|--------|
| **Accurate pricing** | Must reflect actual product value; underpricing vs market rate is a violation (electronics example: listing $1,000 phone at $150) |
| **Fictitious listings** | Prohibited — no non-existent/impossible products, listings involving humans, meme/joke items |
| **Packaging changes** | Update listing images and descriptions when packaging changes |
| **Branded product listings** | Must explicitly state brand; attributes must be consistent with listing Brand field |
| **Misleading AI-generated content** | Applies content policy — AI-generated (AIGC) content subject to same rules |

Source: Mar 2026, Feb/Mar 2026 updates

---

## After-Sales Compliance

| Obligation | Requirement |
|------------|-------------|
| Review after-sales requests | ≥ 90% reviewed on time — otherwise Auto-Approval Tool activated |
| Reject Change-of-Mind returns | Only with valid reason; unreasonable rejection may lead to enforcement + buyer compensation |
| Seller-to-Customer Returns | Must ship within 3 business days when required; submit shipping docs via Seller Center |
| Return/refund appeal window | Must use appeal within defined window (see account-health.md) |

Source: Jan 2026, Apr/May 2026 updates

---

## Platform Security

### Two-Step Authentication (2FA)

From February 5, 2026, selected sellers required to enable ≥2 modes of 2FA.
Impacted sellers notified via Seller Inbox, Email, or Pop-Ups.

### Tax Code Compliance

Sellers must submit valid tax code via Seller Center to unblock payouts. Any third
party claiming to unblock payouts for a fee is a scam.

### Account Re-verification

Triggered by risk signals (see [account-health.md](account-health.md)). Only Owner
Account (admin) can submit — sub-accounts not eligible.

---

## Prohibited Promotional Practices

| Practice | Rule |
|----------|------|
| Gambling-style promotions | Prohibited: red packets (lucky money), "purchase to win" mechanics, wheel spinning, card games, lucky draws |
| Bait-and-Switch pricing | Prohibited: "system bug / pricing error" stories, manual flash sale claims without Flash Sale tool, fake voucher promotions |
| FIFA World Cup IP | Unauthorized commercial use of FIFA Official IP strictly prohibited |
| Misleading claims | Misleading health/beauty claims, weight management claims without basis, "TikTok PayLater" false claims |
| Harmful pricing | Mobile phones listed significantly below market rate are a violation |
| Sensitive Events exploitation | Cannot use disaster/emergency events to drive engagement or profit |

Source: Multiple 2025-2026 policy updates

---

## ISV / Data Obligations

- **Buyer PII:** Only masked `buyer_id` may be stored. Full buyer contact information,
  DM content, or private chat is strictly prohibited. (`data-sources.md` #17)
- **Unofficial data streams:** Realtime websocket streams and Seller Center browser
  scraping are permanently forbidden. (`data-sources.md` #8, #9)
- **Official API only:** All TikTok Shop data integrations must use the official
  TikTok Shop Partner API. No scraping of any seller dashboard pages.
