# Seller Journey — Customers & Customer Service (TikTok Shop VN)

Corpus: `docs/integrations/tiktok_corpora/academy-catalog.json`; bodies under
`/Users/macos/Juli-AI-local/tiktok-corpora/academy_documents/<path>`.
~40 candidate pages matched (full match list produced during research; the 20 read are cited inline).
Curated Juli summaries already exist — **cite, don't duplicate**:
`docs/integrations/tiktok_platform/seller/account-health.md:67`, `policy.md:48-58`,
`operational-limits.md:70-78`, `programs-and-eligibility.md:32,85`.

---

## A. Buyer messaging journey

Surface: Seller Center → **Tin nhắn của khách hàng / Chat với khách hàng** (floating window).
Source: *Tính Năng Chat dành cho Dịch Vụ Khách Hàng* (`feature-guides/seller/dich-vu-khach-hang/tinh-nang-chat-danh-cho-dich-vu-khach-hang-3031784435435265.md`).

1. **Set agent status** — "Chấp nhận chat tự động gán" on/off. Gotcha: the chat window must be *open in a browser* or no auto-assignment happens at all. [human-only]
2. **Triage the inbox** — statuses (quá hạn / sắp hết hạn / chưa trả lời / chưa đọc / gắn sao / đã đóng); category filter (pre-purchase, post-sales, logistics); sort by wait time or recency. [API-automatable — read side]
3. **Reply in the chat window** — text, emoji, image, video, **voucher**; side workspaces show the buyer's past orders, the catalog, and available vouchers. [API-automatable: `send_message`; voucher send is UI-only]
4. **Transfer (Chuyển phiên) or close (Kết thúc phiên)** the session. Closing frees agent capacity and triggers the CSAT survey. [human-only]
5. **Session timeout** — no reply for **>7 days** auto-closes the session into history, permanently unanswerable (same page).
6. **Configure automation** (below, §E) and **watch Service Analytics** (§D/E).

**SLA numbers** (agreement page *Hướng dẫn Dịch vụ Khách hàng của TikTok Shop*,
`agreement-center/online-agreement/huong-dan-dich-vu-khach-hang-cua-tiktok-shop-6837793230014209.md`, §6.1):

| Metric | Definition | Target | Enforcement |
|---|---|---|---|
| **12h response rate (Tỷ lệ phản hồi 12 giờ, 12HRR)** | chats answered ≤12h / chats received | **≥ 85 %** | Warning or 1 Violation Point |
| **First response time (Thời gian phản hồi lần đầu, ART)** | minutes to first reply | **< 30 min** | none (reference) |
| **Satisfaction (Tỷ lệ hài lòng, CSAT)** | 4–5★ sessions / rated sessions | **≥ 70 %** | none (reference) |

Escalating enforcement (*Yêu cầu về giao tiếp đối với Dịch vụ khách hàng*,
`policy-center/seller/yeu-cau-ve-giao-tiep-oi-voi-dich-vu-khach-hang-7199855642370.md`):
12HRR 75–84 % = warning; 51–74 % = **−10 AHR**; ≤50 % = **−20 AHR**. Only applies to shops with >2 chats in 30 days.
Evaluated **every Monday on the trailing 7 days**, weekends and holidays included.

**Working hours.** There are no protected hours — weekend/holiday/night chats all count.
The only exempt state is **Chế độ nghỉ lễ (Holiday Mode)**: chats received then are excluded
from metrics. Also excluded: seller-initiated chats (incl. broadcasts), chats resolved by
auto-reply/FAQ, chats from blocked buyers. Buyer choosing "contact the LSP" counts as a seller response. [policy-gated]

Note the **24h vs 12h split**: the in-product Service Analytics tile and Store Rating still use a
24-hour response rate (chat feature page; *"Xếp hạng cửa hàng" được tính như thế nào?*,
`faq/seller/tinh-trang-cua-hang/xep-hang-cua-hang-uoc-tinh-nhu-the-nao-2933163354801921.md`; and Juli's `account-health.md:67`),
while policy/enforcement and the newer Store-Chat-Performance dashboard use **12h**. Juli must model both.

## B. Complaints and negative reviews

Sources: *Hướng dẫn về Phản hồi Tiêu cực của Khách hàng* (`policy-center/seller/huong-dan-ve-phan-hoi-tieu-cuc-cua-khach-hang-cua-tiktok-sho-7438161806657282.md`),
*Chính sách về đánh giá của khách hàng* (`policy-center/seller/chinh-sach-ve-anh-gia-cua-khach-hang-6837791128422146.md`),
*Báo cáo các đánh giá không hợp lệ* (`policy-center/seller/bao-cao-cac-anh-gia-khong-hop-le-hoac-khong-chinh-xac-1506206733321985.md`).

Three inbound channels: (1) 1–2★ product review; (2) return/refund reason chosen by the buyer;
(3) direct complaint to the seller **or to TikTok Shop**. Reviews are per-product, postable within a
window after delivery, plus one follow-up review within 180 days; anonymous allowed.

Seller options:
- **Reply publicly to the review** — must be respectful, must not disclose buyer info; a policy-breaching reply is itself enforceable. [human-only / policy-gated]
- **Report an invalid review** (Product Score page → Chi tiết đánh giá → Báo cáo đánh giá) for repeat-malicious, coercive, competitor, traffic-diversion, factually-wrong or irrelevant reviews; evidence (chat screenshots, listing screenshots) required; approval is discretionary. [human-only]
- **Report abusive buyers** (bullying, threats, extortionate demands, spam) via Seller Center ticket with chat history — verified cases are **excluded from performance evaluation** (agreement §5.3). This is the only legitimate way to "repair" a 12HRR hit.
- **Appeal a violation ticket** — *Tài liệu kháng nghị đối với các Vi phạm liên quan đến dịch vụ khách hàng* (`policy-center/seller/tai-lieu-khang-nghi-oi-voi-cac-vi-pham-lien-quan-en-dich-vu-5696656206464769.md`): reason-specific evidence (buyer spam screenshots + timestamps; system-error screenshots; force-majeure proof). Success restores penalties and deducted points.

## C. Customer management ("Khách hàng" / CRM)

*Tính Năng Truyền Thông* (`feature-guides/seller/tinh-nang-truyen-thong-3721371931543297.md`) — Seller Center → Tiếp thị → Khách hàng. Three parts: Customer Overview dashboard, **7 default segments**
(Khách mới tiềm năng, Khách gần đây, Khách mua tiếp, Khách quen, Khách lâu không mua, Người theo dõi mới, Người theo dõi đang hoạt động) plus custom segments (demographics, browse/cart/review behaviour, order value; ≥3 conditions recommended), and bulk CRM messaging plans/vouchers.

Gating (*Điều Kiện Tham Gia Và Cấp Độ Tin Nhắn CRM Hàng Loạt*, `feature-guides/seller/ieu-kien-tham-gia-va-cap-o-tin-nhan-crm-hang-loat-5223167807293200.md`): access requires **12HRR ≥85 %, SES ≥3.5, violation points <12**; re-evaluated on the 1st of each month (22nd-to-22nd window); no appeal — only performance recovery. Tiers (start at Tier 2) set weekly broadcast quota, ranked by read rate and block/unsubscribe rate.

**API exposure: none.** The Customer Service API surfaces only conversations/messages
(`docs/integrations/tiktok_api/endpoints.md:375-405`). Segments, CRM broadcasts, vouchers-over-chat and buyer PII are Seller-Center-only. Buyer PII is masked and unmask requests are per-order, only while status is To Ship / Shipped / Delivery Failed, and never >30 days after completion (*Truy cập vào thông tin khách hàng*, `feature-guides/seller/on-hang-van-chuyen/truy-cap-vao-thong-tin-khach-hang-1731624127465232.md`).

## D. Shop-health metrics driven by service

| Metric | Target | Penalty | Juli workflow |
|---|---|---|---|
| 12h response rate (12HRR) | ≥85 % | warn → −10 AHR → −20 AHR; 1 VP legacy | **none** (deferred, §F) |
| First response time (ART) | <30 min | reference only | none |
| Chat satisfaction (CSAT) | ≥70 % (4–5★) | reference; feeds Store Rating | none |
| Seller-related NRR | <0.5 % | listing warnings, deactivation, visibility cuts, OVL | T4 anomaly (advisory) |
| Service-related NRR | <0.5 % | shop visibility cut, suspension, permanent ban | T4 advisory; affiliate disqualifier (`operational-limits.md:70-78`) |
| Product-related NRR | <0.5 % | product warnings/removal/freeze | Optimize Product (indirect) |
| Seller-fault return/refund rate (SFRR) | <1.5 % | 2 VP | Post-sales 8b/8c |
| After-Sales Handling Time (AHT) | **<20 h** avg over 60d | counts into Store Rating from Jul 2026 | T4 anomaly on AHT (`execution_layer.md:446-448`) |
| Customer complaint rate | Store-Rating input | Store Rating subscore | none |
| AHR (account health) | ≥200 of 0–1000 | tiered: 150/100/50/0 → benefit locks, 28-day then permanent deactivation | none |

(NRR: `policy-center/seller/ty-le-anh-gia-tieu-cuc-nrr-89407390992129.md`. AHT: `policy-center/seller/thoi-gian-xu-ly-hau-mai-3665493270857473.md`. AHR: `policy-center/seller/iem-tinh-trang-tai-khoan-8055182777779984.md`.)
Store Rating (60d, buyer-visible) has a Customer Service sub-score = complaint rate + 24h reply rate; AHR is compliance-only and private.

## E. TikTok's own automation — do not rebuild

From *Trợ lý trò chuyện dịch vụ khách hàng* (`…/tro-ly-tro-chuyen-dich-vu-khach-hang-10015355.md`),
*Tin Nhắn Dịch Vụ Khách Hàng Tự Động* (`…/tin-nhan-dich-vu-khach-hang-tu-ong-1555377489839874.md`),
*Cách thiết lập tính năng phản hồi tự động về hậu mãi* (`feature-guides/seller/on-hang-van-chuyen/cach-thiet-lap-tinh-nang-phan-hoi-tu-ong-ve-hau-mai-2990230115665665.md`),
*Cách hoạt động của Trợ lý Nhà Bán Hàng* (`…/cach-hoat-ong-cua-tro-ly-nha-ban-hang-8109059019573009.md`):

- **Chat greeting**, **saved replies**, **FAQ library**.
- **Suggested answers** with optional **auto-send** (intent-matched against the seller's FAQ DB; label "Tự động gửi" hidden from the buyer; stops when an agent opens the window or the same answer repeats).
- **Chatbot** — all-day or **out-of-working-hours only**; falls back to "agent offline" message; buyer can rate the bot answer Đã xử lý / Chưa xử lý.
- **Proactive messages** — shipped / out-for-delivery updates, auto-sent on order-status change, suppressed during **do-not-disturb 07:00–23:00 boundary** (only sent 07:00–23:00; suppressed messages are never re-sent).
- **After-sales auto-reply** — rule-based dispatch-schedule answers (per warehouse, weekday/holiday, order-time windows).
- **Seller Assistant (Trợ lý Nhà Bán Hàng)** — TikTok's own 24/7 in-console AI copilot: insights, self-serve actions (violation tickets, order lookups, promo setup), and policy Q&A. **This is the closest competitor to Juli's copilot surface.**

TikTok already owns first-line deflection and status messaging. Juli should not build another FAQ bot.

## F. Alignment with Juli — MATCH / GAP

`docs/product/execution_layer.md:430-443` defers all buyer-messaging execution to Phase 3;
`:444-449` keeps *Resolve Recurring Customer Complaints* as ML-advisory only (T4 EWMA/z-score on AHT and Return Request Rate); `:461-475` lists the deferrals (buyer-messaging execution, complaint text mining, root-cause classification); `:479-487` lists deferred actions incl. **Contact Customers → `create_conversation` / `send_message`**.

- **MATCH** — the API genuinely offers only `create_conversation` / `send_message` / `read_message` (`endpoints.md:395-401`), so "Contact Customers" is correctly scoped. The chat webhooks (#13 New conversation, #14 New message, `execution_layer.md:89-90`) are exactly what a response-SLA workflow would need.
- **MATCH** — deferring complaint text mining is consistent with buyer chat being **Forbidden for ML training** (`endpoints.md:404-406`, `compliance.md:167`).
- **GAP 1 — the metric Juli optimises isn't the one TikTok enforces.** T4 watches AHT and Return Request Rate; the *enforced*, AHR-deducting metric is **12HRR**, and nothing in Juli's layer moves it.
- **GAP 2 — no 12HRR/CSAT/ART ingestion.** Not in the shop-health signals; `account-health.md:67` still records only the legacy "24-hour response rate, 1 VP".
- **GAP 3 — reviews are absent.** NRR (service vs product split) drives suspension, yet no workflow surfaces negative-review analytics, and "report invalid review" / "report abusive buyer" — both high-ROI and evidence-shaped — appear nowhere.
- **GAP 4 — CRM segments are invisible to Juli** and are themselves gated on 12HRR ≥85 %, so a service regression silently removes a marketing capability. Nothing warns about that coupling.

## G. Judgment vs safe-to-automate

Safe to draft-and-auto-send: order-status/shipping-timeline answers (TikTok already does this — see §E; Juli should *not* duplicate), stock/variant availability, published return-policy restatements, closing greetings before session end.
Requires human judgment: any refund/compensation/goodwill offer; disputes over item condition; replies to negative reviews; anything about a buyer's PII; escalations; anything touching a violation appeal.

**Policy limits on automated messaging** (agreement §4.2, plus *Chính sách về đánh giá của khách hàng*):
no off-platform redirection (links, bank/payment accounts, QR codes, emails, phone contacts); no
off-platform return/refund suggestions; no asking buyers to cancel; **no unsolicited marketing or
spam through the customer-service messaging function at all** (§4.2.4 — CS messaging is explicitly
barred from marketing use; that is what the CRM tool is for); **no review solicitation, incentives,
threats or intimidation** (§4.2.7); no false/inaccurate promo, feature, price or stock claims; no
third-party plug-ins or unauthorised tools against the messaging platform (§4.2.7 — read this before
designing any auto-send path). Buyer PII must never be disclosed, including in public review replies.

## H. Top 5 recommendations, ranked

1. **Ingest and alert on 12HRR, ART and CSAT weekly (Monday evaluation cadence), with AHR-deduction bands (85/75/51/50).** Highest ROI: it is the only service metric that deducts account health, it is invisible in Juli today, and it also gates CRM access.
2. **Negative-review workflow: NRR service/product split + drill-down to the offending listings and reasons**, mirroring La bàn dữ liệu → Sau mua hàng → Hiệu suất đánh giá tiêu cực (`feature-guides/seller/analytics/huong-dan-su-dung-hieu-suat-anh-gia-tieu-cuc-10019123.md`). Turns T4's "complaint anomaly" into an actionable product/service cause.
3. **Draft-only reply assistant over the unanswered queue** (`read_message` + webhooks #13/#14 → ranked by time-to-SLA-breach → seller approves → `send_message`). Approval-gated, no auto-send: it dodges §4.2.7's unauthorised-tool language and TikTok's own auto-reply already covers the trivial cases.
4. **Evidence-pack generator for the two repair paths**: report-invalid-review and report-abusive-buyer (chat transcript + timestamps + listing screenshot), since verified abuse cases are removed from performance evaluation — a direct, sanctioned 12HRR/NRR repair.
5. **Automation-hygiene audit card**: is Chatbot enabled and scoped, is the FAQ library populated, are proactive shipping messages on, is Holiday Mode set before a break, is per-agent max capacity ≥200, is the waiting queue at zero. All of it is TikTok-native configuration whose absence is the usual root cause of a low 12HRR.

---

**Summary.** For a TikTok Shop seller, customer service is a metered obligation, not a discretionary
activity: every buyer-opened chat starts a clock, and TikTok grades the shop every Monday on whether
85 % of them were answered within 12 hours, with an average first reply under 30 minutes and a 70 %
satisfaction rate — missing the first target costs 10 to 20 Account Health points, and a sustained
miss drives the AHR toward deactivation while also silently revoking access to the CRM broadcast
tool. Negative reviews and complaints run on a parallel track: 1–2★ ratings and refund reasons are
split into product-related and service-related NRR, both capped at 0.5 %, with service-related
failures escalating to shop visibility cuts and suspension. TikTok already ships the first line of
defence — a chatbot, FAQ-matched auto-send, proactive shipping messages, after-sales auto-replies,
and its own Seller Assistant copilot — so the seller's real work is triage, judgement calls on
refunds and complaints, and the evidence-shaped repair paths (report an invalid review, report an
abusive buyer, appeal a violation). Juli today defers all of this to Phase 3 and, where it does act,
watches after-sales handling time rather than the response rate TikTok actually enforces; the
highest-value near-term move is not a messaging bot but ingesting 12HRR/CSAT/NRR into shop health and
generating the approval-gated drafts and evidence packs that a human then sends.
