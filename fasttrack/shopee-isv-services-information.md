# Shopee ISV — Services Information (D42 item 7, rewritten for D73 / P64)

Paste the sections below into Shopee Open Platform Console → App List → Go to Profile → Edit →
Services Information. Keep this file in sync with what the site and the trial account actually
show (Platform Partner Rules §4). The account expires 30 days after creation — renew with
`python -m juli_backend.services.reviewer.cli renew --email shopee-review@app-juli.com --by <staff>`
if the review runs longer. The password is printed once by the `create` command; it is never
stored in this repository.

## Platform URL

https://app-juli.com

## Software login address

https://demo.app-juli.com

## Test account

- Username: `shopee-review@app-juli.com`
- Password: (from `reviewer.cli create`)

## Brief introduction

Juli AI (https://app-juli.com), operated by Công ty TNHH Công Nghệ Juli AI (tax code 0319617654,
1B Đường số 30 Trần Não, Phường An Khánh, Ho Chi Minh City, Vietnam), is an AI operations
assistant for e-commerce sellers in Vietnam. It connects to a seller's shop through the
marketplace's official Open API, analyses the shop's traffic funnel (impressions → click-through
rate → click-to-order rate → average order value) per traffic source and per product, and proposes
concrete improvements (product title, description, cover image; promotions the seller applies
in Seller Center). The seller reviews every proposal; Juli changes the shop only after the seller
approves it, then measures the effect on GMV at day 7 and day 14.

**Existing ecommerce integration.** Juli works today with **TikTok Shop** through the TikTok Shop
Partner Center Open API: shop authorisation by OAuth, product / order / shop-analytics reads, and
product-listing updates after seller approval. How the connection works, what is read and what is
written is described at https://app-juli.com/ket-noi/tiktok-shop; the product is described at
https://app-juli.com/san-pham and its three capability pages.

**What we apply for on Shopee.** The same service for Shopee sellers through Shopee Open
Platform: shop authorisation, read access to shop, product, order and performance data for the
analysis, and product-listing updates (title, description, images) only after the seller approves
each change. We do not crawl Shopee, do not move listings off Shopee, and handle Shopee data under
the Shopee Open Platform Data Protection Policy (Privacy Policy §4A,
https://app-juli.com/privacy; Terms §4, https://app-juli.com/terms).

**How sellers sign up.** A free 3-month trial at https://app-juli.com/dang-ky; the Juli team then
connects the seller's shop with them.

**About the trial account.** It is a partner account connected, through TikTok Shop Partner
Center OAuth, to **Juli's own TikTok Shop sandbox (test) shop** in Vietnam. Nothing in it is
sample or predefined data: every screen is fetched live from the TikTok Shop Open API, and the
reviewer can see the connection itself (status, authorisation date, granted scopes), the time of
the last sync, and a **"Sync now"** button that pulls the shop again. When the reviewer approves a
recommendation and executes it, Juli **really writes** the change (product title, description or
image) to the sandbox shop through the Open API, then reads the product back from TikTok and shows
the confirmed result. We use our own sandbox shop so that a reviewer never changes a real
seller's shop; the integration, the API calls and the write path are the ones our sellers use.
The interface is in Vietnamese; the steps below give the English meaning of each label.

<!-- P64 S4: re-verify every label below in a fresh browser as shopee-review@ before pasting. -->

## Steps for the reviewer

1. Open https://demo.app-juli.com/auth/email#doi-tac (opens the partner sign-in form directly)
   and sign in with the username and password above. The banner reads "Tài khoản đối tác · kết
   nối thật tới shop sandbox TikTok của Juli · thay đổi được ghi thật lên TikTok" (partner account
   · real connection to Juli's TikTok sandbox shop · changes are really written to TikTok).
2. **Trang chủ** (Home), card **"Kết nối TikTok Shop"** (TikTok Shop connection): the shop name
   and TikTok shop id, "Đã kết nối" (Connected), "Ủy quyền lúc …" (Authorised at …), "Quyền đã
   cấp" (granted scopes) and "Đồng bộ lúc …" (Synced at …). Press **"Đồng bộ ngay"** (Sync now) to
   pull the shop from the TikTok Shop Open API again; the time updates a few seconds later.
3. **Trang chủ** (Home): the shop's orders, revenue and products as returned by TikTok. A sandbox
   shop has no buyer traffic, so view / click metrics show the note "TikTok sandbox chưa có lượt
   xem/traffic — số liệu đơn hàng và sản phẩm vẫn lấy trực tiếp từ TikTok" (the TikTok sandbox has
   no views/traffic yet — order and product figures still come directly from TikTok).
4. **Phân tích** (Analysis): the shop's products and orders broken down by product, from the same
   live data.
5. **Quyết định** (Decisions): Juli's recommendation cards — product, target metric, evidence and
   the proposed change.
6. Open a listing card (title / description / cover image) and press **"Duyệt"** (Approve). The
   dialog "Thay đổi Juli sẽ ghi lên TikTok" (The change Juli will write to TikTok) shows each field
   before ("Trước") and after ("Sau"); you may edit "Tiêu đề mới" (new title) or "Mô tả mới" (new
   description), or choose "Ảnh bìa mới" (new cover image).
7. Press **"Thực thi"** (Execute). Juli writes the change to the shop through the TikTok Shop Open
   API, then reads the product back. The result "Đã ghi lên TikTok" (Written to TikTok) shows each
   field before and after and **"TikTok xác nhận lúc …"** (Confirmed by TikTok at …).
8. Product and integration details: https://app-juli.com/san-pham ·
   https://app-juli.com/ket-noi/tiktok-shop · trial sign-up https://app-juli.com/dang-ky.

## Reply to Shopee (same email thread)

> Dear Shopee Open Platform team,
>
> Thank you for the clarification. We have updated the trial account so it demonstrates our
> actual working TikTok Shop integration rather than sample data.
>
> The account `shopee-review@app-juli.com` (sign in at
> https://demo.app-juli.com/auth/email#doi-tac) is now connected through TikTok Shop Partner
> Center OAuth to our own TikTok Shop sandbox (test) shop. All data is fetched live from the
> TikTok Shop Open API — the connection, the last sync time and a "Sync now" button are visible in
> the product. When you approve and execute a recommendation, Juli writes the change to the shop
> through the Open API and shows TikTok's confirmation read back from the shop. We use our own
> sandbox shop so that reviewers never modify a real seller's shop.
>
> The updated step-by-step guide is in the Services Information section of our profile.
>
> Best regards,
> Juli AI team — lienhe@app-juli.com

Contact: lienhe@app-juli.com · https://app-juli.com/contact
