# P93 — Shop team: several seller people on one shop (owner decision 2026-11-05)

- A shop can have **many seller members**; **all have the same role** (today's seller permissions: view
  every page, build / compare / choose, approve cards, plans, Cài đặt inputs, uploads, Connector fill-in).
  There is no owner-vs-member difference in the seller app.
- **Only Ops (Vận hành+) invites and removes members.** Sellers cannot invite, remove or transfer.
- Invites stay **one person per link** (e-mail bound, 7 days, one-time token, sha256 stored). Accepting adds the
  person as a member; it no longer moves the shop away from the people already on it. The legacy single-owner
  handover keeps working for shops that still have no member (the first accept makes the first member).
- Each member signs in with their own e-mail + 6-digit code; every seller action is attributed to that
  person (audit / card events carry the member's user id).
- Ops shop page: "Thành viên shop" list (e-mail, joined, last seen), "Mời thêm" and "Gỡ" (audited). Removing the
  last member is allowed (the shop stays, data untouched).
- Tenant isolation: a member sees only the shops they are a member of; RLS / `get_active_shop` resolve via
  membership; cross-tenant tests extended. Consent stays per shop (P90 contract-shop consent).
- Connector pairing codes stay per shop (any member's Connector can pair via Ops-issued codes as today).
