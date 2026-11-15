# P94 — Approve several options of a card, as groups (owner decision 2026-11-05)

Scheduled by `contracts/plan-2026-11-09.md`. Built once, on the shared shell. The shared field
gate and the Shopee and TikTok gates decide which option types a platform may put in a group.
Connector fill-in prepares the group's current exclusive field on that shop's Seller Centre,
for a seller or a developer paired to the shop.

- Every card (all recommendation types, engine and manual) lets the seller / Ops **approve more than one
  version**. Example: voucher 15k/200k and 20k/250k approved together.
- **Groups.** Options approved together form a **group** ("Nhóm A") with one period (start, N days, minimum 3).
  Example: three vouchers for 3 days = Nhóm A. Further groups (Nhóm B, C …) can be added to the same card /
  product and are scheduled one after another (B starts when A ends, or on a chosen date).
- **Inside a group, options are evaluated together as one bundle** on the same orders: each buyer gets the
  best option their basket qualifies for (vouchers: best eligible voucher; combos / add-ons / gifts / flash-sale
  slots / sets / affiliate targets: coexisting offers with shared demand, no double counting). The group shows
  combined Δ GMV, Δ orders, Δ profit, margin, cost and each option's share; floor and spend-cap warnings are
  checked on the combination (warn, never block). A group is one change set for measurement (P91 D-7).
- **One live value per exclusive field.** For types where only one value can be live at a time (title, price,
  cover, description first line, a discount on the same variation, one campaign's budget / ROAS), a group can
  hold only one option of that field; approving another option of the same field puts it in the next group
  (run in turn, each group measured on its own, the better one suggested to keep).
- Draft plans (P92 B-10) take groups as steps; plan confirmation executes groups by their schedule; Connector
  fill-in prepares the exclusive-field value of the group whose turn it is.
- Card codes: a group gets `JC-…-G<A|B…>`; versions keep `-V<n>`; Excel export lists group, versions, period.
