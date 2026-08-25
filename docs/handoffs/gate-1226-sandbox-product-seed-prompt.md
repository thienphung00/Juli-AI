# Gate #1226 — agent prompt: seed the sandbox product with realistic listing data

**Issue:** #1226 (W5 gate, observation 1) · **Written:** 2026-08-25
**Blocker this unblocks:** step 7 of 7 — *confirm → write lands*.

## Why this prompt exists

The 07:04 UTC walk on 2026-08-25 got six of seven steps green. Step 7 never fired because the
agent had nothing concrete to propose: the bound sandbox product (`1736363193934775939`, sandbox
merchant `7658096633384781588`) has the title `Hình ảnh Juli Mới Nhất trên thị trường`, the
description `23432432`, and a JULI AI infographic banner as its photo. `inspect_product_image`
returned `mismatch: high` and the run ended with a `final_response` report instead of a
`update_product_listing` CONFIRM pause — twice, consistently, and for sound reasons.

So the fix is data, not code: give that product a listing a real seller could plausibly have.

**The trap to avoid:** seeding *perfect* copy fails the same way seeding garbage does. If the
listing is already optimal the agent again has nothing to propose and again ends in a
`final_response`. The target is **plausible but improvable** — the photo must match the copy
(so vision reports `aligned`/`partial`, never `mismatched`), while the text leaves obvious,
nameable headroom for the Optimize Product playbook to close.

## How to use it

Paste the block below into a fresh session of an agent that can generate or source images.
Fill the two placeholders first. Then apply the output by hand in the TikTok **sandbox** Seller
Center as merchant `7658096633384781588`. Nothing here touches Fujiwa Vietnam Store (`2b1da87b`) —
the sandbox-only rule of 2026-08-21 stays in force.

---

## The prompt

```text
You are preparing seed data for a test listing in a TikTok Shop SANDBOX account. Nothing you
produce goes to a real storefront or a real buyer — it exists so an automated listing-optimization
agent has a realistic listing to read, look at, and propose improvements to.

CONTEXT
- Sandbox product id: 1736363193934775939 (sandbox merchant 7658096633384781588).
- The product's existing category in Seller Center is: <CATEGORY — copy it from Seller Center;
  if it is generic or unusable, use "Bình giữ nhiệt / Water bottles" and say that you did>.
- The market is Vietnam. All seller-facing copy must be in Vietnamese.
- Its current title, description and photo are placeholder junk, which is the problem.

WHAT TO PRODUCE
1. A product title in Vietnamese.
2. A product description in Vietnamese.
3. One product photo (generate it, or give me an image I can download and a direct link).
4. A suggested list price in VND and a plausible "current" price to enter, plus stock quantity.

THE DESIGN CONSTRAINT THAT MATTERS MOST
The listing must be PLAUSIBLE BUT IMPROVABLE. A downstream agent reads this listing and must be
able to name concrete improvements. So:
- The title should read like a real, slightly lazy seller wrote it: the product is identifiable,
  but it omits at least three details a good title would carry (capacity/size, material, colour,
  a use-case keyword). Keep it around 40-60 characters. Do NOT keyword-stuff it.
- The description should be short and thin — 2 to 4 plain sentences, roughly 200-350 characters.
  Real, accurate, readable, no bullet list, no specification table, no shipping or returns policy.
  Those omissions are the headroom, so leave them out on purpose.
- The photo, by contrast, must be GOOD and must match the copy exactly — same product, same
  colour, same material, same item count. Photo/copy disagreement is the current failure and must
  not be reproduced.

PHOTO REQUIREMENTS (hard)
- Square 1:1, at least 800x800 px, JPEG or PNG, under 5 MB.
- One single product, centred, filling most of the frame, on a plain white or light neutral
  background, evenly lit, no harsh shadows.
- ABSOLUTELY NO text, price tags, badges, voucher graphics, promotional banners, logos,
  watermarks, collages or infographic overlays anywhere in the image. A banner-style image is
  precisely what is already there and precisely what is being replaced.
- No people, no hands, no brand marks, no packaging with readable brand names.

COPY RULES
- Invent an unbranded generic product. No real brand, trademark or lookalike brand name.
- No superlative or unverifiable claims: nothing like "chính hãng 100%", "rẻ nhất thị trường",
  "tốt nhất", "cam kết hoàn tiền", and no health, medical or safety-certification claims.
- No emoji, no ALL CAPS, no "#hashtag", no phone numbers, links, or contact details.
- Avoid these exact strings anywhere in the copy, in any language, because an automated guard
  rejects them: "webhook", "endpoint", "tool_name", "workflow_key", "feature_id", "FBS", "FBT",
  "listing.", "inventory.", "Độ tin cậy:", "Công cụ:", "Khả năng:".
- Pick something ordinary, physical and easy to photograph unambiguously — a household, kitchen,
  desk or small-accessory item. Avoid electronics with model numbers, anything age-restricted,
  and anything that would need a certificate.

DELIVER IT LIKE THIS
- Section A — "Paste into Seller Center": the title on one line, then the description, then price
  and stock, as plain text with nothing to edit before pasting.
- Section B — the photo, plus its dimensions and file size, and one line confirming it contains no
  text or overlay of any kind.
- Section C — "Headroom left on purpose": 3 to 5 bullets naming exactly what the title and
  description are missing, so I can check afterwards whether the optimization agent found them.

Ask me for the category first if I left the placeholder unfilled. Otherwise produce everything in
one pass.
```

---

## After the agent returns

1. In the **sandbox** Seller Center (merchant `7658096633384781588`), edit product
   `1736363193934775939`: replace title, description and the main image; set price and stock.
   Keep the category unchanged so the write path stays the one the walk already exercised.
2. Re-run the walk as the gate seller (`gate-1226@app-juli.com`, sandbox shop `1862f13b`):
   refresh → `/v1/demo/decisions` → approve → stream.
3. What success looks like: `inspect_product_image` reports `aligned` or `partial` (not
   `mismatched`), and the run pauses at an `update_product_listing` CONFIRM instead of ending in a
   `final_response`. Confirm it, and the sandbox write lands — step 7, and observation 1's
   remaining criterion.
4. If the run still ends in a `final_response`, the copy was seeded too good, not too bad: thin the
   description further and drop another attribute from the title before blaming the agent.
5. Capture the event log alongside the existing golden scenario at `/root/gate-1226-obs1-events.log`
   on the VPS, sanitized, and record the outcome on #1226.

**One note on step 6 of the playbook.** `OPTIMIZE_PRODUCT_TERMINATION_POLICY` lists
`update_product_price` as a required step beside `update_product_listing`, which is why the prompt
asks for a price and stock as well — a price with visible headroom lets that second CONFIRM fire
too. The gate's own criterion only needs one confirmed write to land, so a rejected or absent price
change is not a failure of this walk.
