# Q4 notification channels · Q6 consent + flags · Q-extra automation digests

**[D]** = documented in cited source · **[I]** = my inference.

## Q4 — Channels for time-critical seller reminders

**Shopee Seller** — Seller Centre + Seller Center app push; per-category notification settings (Me → Settings → Notification Settings), with a master push toggle gating all sub-toggles. Safety: granular opt-out instead of all-or-nothing. [D] https://seller.shopee.com.my/edu/article/1437

**Shopee returns** — seller gets **48 h**; silence auto-approves for the buyer. Safety: platform never waits indefinitely; the deadline is the forcing function. [D] https://seller.shopee.com.my/edu/article/11775

**TikTok Shop** — Seller Center homepage + **Message Center** + mobile push + email (tiktokshopsupport@shop.tiktok.com); channel is chosen *per event type* (stock alerts: "email, Message Center, or both"). [D] https://seller-us.tiktok.com/university/essay?knowledge_id=4186564050126593

**Lazada** — in-app notification settings + Seller Center app push; a partner-facing **Seller Notification Centre API** exists. Safety: the notification centre is the durable record, push is only the nudge. [D] https://sellercenter.lazada.sg/seller/helpcenter/how-do-i-set-in-app-notifications-16531.html

**Amazon Seller Central** — Settings → **Notification Preferences**: per-category channel *and per-category recipient address*; separate SMS settings page; app push toggles. Safety: routing by category to different people; explicit SMS opt-in. [D] https://sellercentral.amazon.com/help/hub/reference/external/G200955960

### Zalo ZNS constraints (all [D])

- **Consent is a precondition**: send only to users who have a relationship with the business and gave a phone number, and the business must notify them **in advance** of purpose and conditions. https://www.infobip.com/docs/zalo/compliance-guidelines
- **Pre-approved templates only** — no free-form body; ≥1 transaction/account variable required; no promotional content; categories = OTP/account, financial, transaction/shipping; **one message per transaction**. (same)
- **Delivery window 07:00–22:00** daily, OTP excepted. https://zoa.vn/quy-dinh-gui-tin-zns/
- **Quality ladder**: OA scored on bad-report rate, safe **<0.1%/day**; since 2024-03-12 a 7-day "Kém" rating downgrades sending entitlements, and persistent poor quality can suspend ZNS. https://zalo.cloud/blog/co-che-danh-gia-chat-luong-va-quyen-loi-gui-zns/qsuhj60o4oteiy7rnrf0ohpe
- **Cost per message** = template type + CTA buttons + image + send time. Reminder/CSKH base ~200 VND; first CTA free, extra CTAs 100–500; image +200; realistic 300–1,100 VND — under SMS brandname (600–1,000). https://miniai.vn/bang-gia-zalo-zns/

### Vietnamese seller tools — Zalo OA/ZNS confirmed as the default ops channel

KiotViet ships native Zalo OA linking with automatic ZNS, gated on a **funded balance and a daily message quota**, with the customer's phone required to be their Zalo number [D] (https://www.kiotviet.vn/tich-hop-zalo-official-account-tren-kiotviet-gui-tin-nhan-zns-tu-dong-cham-soc-khach-hang-hieu-qua/). Zalo's own docs list **KiotViet, Sapo, Haravan** and Zalo Mini App as ZNS-integrable [D]. **Nhanh.vn** runs a ZNS service with **scheduled send times** [D] (https://nhanh.vn/thong-bao-tinh-nang-hen-thoi-gian-gui-tin-zns-an789.html). Caveat [I]: these send to the shop's *buyers*; Juli sends to the *seller*, a different data subject who must consent at onboarding.

**Legal.** Decree 13/2023 required clear, voluntary, affirmative consent plus notice of the content, method, form and **frequency** of contact [D]; note a new PDP Law took effect 2026-01-01 and **Decree 356/2025 replaces Decree 13** — consent copy must be re-checked against it (I did not read 356) [D that it exists]. https://securiti.ai/vietnam-personal-data-protection-decree/ · Decree 91/2020 requires prior express consent and immediate opt-out honouring for *advertising* [D]; deadline reminders are transactional so it mostly doesn't bite [I]. https://www.tilleke.com/insights/vietnams-new-decree-91-sets-out-stricter-anti-spam-regulations/

**Industry anti-spam practice** [D] (https://www.courier.com/blog/how-to-reduce-notification-fatigue-7-proven-product-strategies-for-saas): tier by urgency — critical bypasses batching, routine batches into 15 min–1 h, low-priority rolls into a daily digest; quiet-hours DND queues non-urgent and releases next morning; escalate on **non-acknowledgement** (push → SMS on delivery timeout); granular per-type controls beat a master switch, which drives full opt-out.

**Borrow for v1 (in-app first, Zalo second):**
1. In-app notification centre = system of record; push/Zalo are idempotent nudges against it. Every send gets a delivery record (channel, template id, send time, provider message id, result) — you need this to defend a bad-report rate [I].
2. Urgency ladder on the *platform's* clock: 2 h dispatch → in-app + push; 48 h cancellation → in-app now, ZNS at ~T+24 h **only if unacknowledged**.
3. Hard-code 07:00–22:00 in the scheduler with a hold-until-07:00 queue. Platform rule, not a user preference.
4. Per-event-type channel preferences (Amazon/TikTok) + separate phone/Zalo consent capture storing timestamp, purpose text and stated frequency.
5. Fix a small approved template set before launch (≤3: dispatch deadline, cancellation deadline, digest) — templates can't be edited at runtime.
6. Treat bad-report rate <0.1%/day as an SLO; ZNS only for deadline-bearing events.

**Contradicting evidence:** none against in-app-first. Two frictions: (a) the one-message-per-transaction + no-marketing rules make a 2–3 ping ZNS ladder on one order likely non-compliant — send **one** ZNS per deadline [I]; (b) ZNS is prepaid and quota'd, so a cost/quota guard belongs in v1's dispatcher, not v2 [D].

## Q6 — Automation consent UX + dark launch

**TikTok Shop auto-approve rules** — Orders → Return settings → Returns and refunds. Each rule scoped by accepted refund reasons (default All), categories, **refund price range**, "effective from" date, optional per-customer cap in 30 days; auto-approve returns adds a trigger point (after drop-off / delivered) and **approval delay: immediately or 1–24 h**. Per-rule enable/disable toggle, edit/delete. Safety: bounded blast radius + one-tap off + an intervention window. [D] https://seller-us.tiktok.com/university/essay?knowledge_id=4875447742662443

**Amazon Automate Pricing** — opt-in per rule/SKU; **minimum price mandatory** (hard floor), max optional; pause freezes prices at the last repriced value and takes up to 1 h to propagate. Safety: consent carries a numeric cap; pause ≠ revert, and the lag is disclosed. [D] https://sell.amazon.com/tools/automate-pricing

**Shopify Flow** — workflows are **draft by default**, must be activated; version history records edits, activations and deactivations with staff member + timestamp. Safety: default-off plus a who-turned-it-on audit trail. [D] https://help.shopify.com/en/manual/shopify-flow/manage

**Zapier** — auto-disables a Zap at ~95% errors over 7 days and emails the owner (grace period on Team/Enterprise); an "Error in Zap" trigger routes failures to Slack/email. Safety: circuit breaker on the automation itself, with notice. [D] https://help.zapier.com/hc/en-us/articles/8496037690637

**Make** — failed runs stored as **incomplete executions** for manual resolution/retry. Safety: no silent loss. [D] https://help.make.com/manage-incomplete-executions

**Shopee** — auto-approval is the platform *default on seller silence*, not an opt-in. Useful counterfactual: doing nothing is also an automated decision. [D]

**Flags** — LaunchDarkly: kill switches for instant shutdown; canary/percentage rollouts from 1–5% with scheduled increases; attribute targeting on account ID / plan level (per-tenant) via reusable segments; **audit log of every flag change**; hygiene = owner + expiry + stale-flag tracking. [D] https://docs.launchdarkly.com/home/releases/create-progressive-rollouts · https://launchdarkly.com/blog/what-are-feature-flags/

**Borrow:**
1. Two independent default-off switches: the **tenant flag** (is the component visible) and the **seller's consent toggle** (is this rule opted in). Killing the flag must never read as revoked consent, or vice versa [I].
2. Consent = a **scoped rule**, TikTok-shaped: action type, đ value cap, effective-from, optional per-period count cap. Following Amazon, **require** at least one numeric bound before the toggle can turn on.
3. **Delay window before the act** (TikTok's 1–24 h) — the highest-value borrow: turns "automation acted" into "about to act, tap to stop", and composes with in-app-first notification.
4. One-tap disable that **freezes rather than reverts**, with propagation lag stated honestly.
5. Error-rate circuit breaker (Zapier) that auto-disables and notifies; hold the failure as a resolvable item (Make), don't drop it.
6. Audit every state change (who, when, where) — also the PDPD evidence trail.

**Contradicting evidence:** nothing against dark-launching. Caution [I]: a per-tenant flag that silently *widens* automation behaviour for an already-consented seller is a consent violation, not a rollout. Flags may gate visibility and new capabilities, never the scope of existing consent.

## Q-extra — after-the-fact digests

Shopify Flow "Recent runs": per-run log, expandable step data with resource IDs, retained **14 days** then deleted [D] (https://help.shopify.com/en/manual/shopify-flow/manage/monitor). Amazon Automate Pricing: dashboard of active/paused rules plus per-rule performance metrics [D]. Zapier Task History: per-task record with error message and deep link, used as the notification target [D]. TikTok Shop auto-approve documents rule setup but **no post-act notification or log** — a real gap in our best consent-UX precedent [D by absence].

**A good digest entry** [I]: *what* (order id, amount), *when* (act time, not digest time), *why* (rule + matched condition — Flow's step data is the model), *what would otherwise have happened*, *how to undo* (a real reversal, or an honest "cannot undo; contact X"), and *state* (succeeded / failed / held) so failures surface beside successes. Retention: 14 days is too short for a commerce action — hold at least the platform's dispute window.

## Cross-cutting

Both questions converge on one object: a **per-act record** that is at once the in-app notification, the ZNS delivery record, the automation audit entry, and the undo affordance. Build that in v1; in-app renders it, the digest groups it, Zalo escalates it, the consent/flag audit reads it.
