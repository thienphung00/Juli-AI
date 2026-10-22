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
sample or predefined data: every screen is read live from the TikTok Shop Open API, and the
reviewer can see the connection itself (status, authorisation date, granted scopes), the time of
the last sync, and a **"Đồng bộ ngay"** (Sync now) button. A TikTok sandbox shop has no buyer
traffic, so views and click-through are empty; revenue, orders and best-sellers are computed from
the shop's real TikTok orders and labelled as such. Recommendations run through the same AI agent
workflow our sellers use: an OpenAI model drafts the change, every step streams live, the reviewer
confirms, and Juli **really writes** the change to the shop through the Open API and reads it back.
For the review only, the sandbox account can also let Juli **create a new product listing** (the
model picks the TikTok category from TikTok's own category list); product creation is not offered
to sellers' real shops. We use our own sandbox shop so that a reviewer never changes a real
seller's shop. The interface is in Vietnamese; the steps below give the English meaning.

<!-- P64 S4: re-verify every label below in a fresh browser as shopee-review@ before pasting. -->

## Steps for the reviewer

1. Open https://demo.app-juli.com/auth/email#doi-tac and sign in with the username and password
   above. The banner reads "Tài khoản đối tác · kết nối thật tới shop sandbox TikTok của Juli ·
   thay đổi được ghi thật lên TikTok" (partner account · real connection to Juli's TikTok sandbox
   shop · changes are really written to TikTok).
2. **Trang chủ** (Home), card **"Kết nối TikTok Shop"**: shop name, "Đã kết nối" (Connected),
   "Ủy quyền lúc …" (Authorised at …), "Quyền đã cấp" (granted scopes), "Đồng bộ lúc …" (Synced
   at …). Press **"Đồng bộ ngay"** (Sync now) to pull the shop from TikTok again.
3. **Trang chủ** and **Phân tích** (Analysis): revenue, orders, average order value and the
   best-selling products, marked "Tính từ đơn hàng TikTok (Orders API)" (computed from TikTok
   orders). The note "TikTok sandbox chưa có lượt xem/traffic" explains why view metrics are empty.
4. **Quyết định** (Decisions): first press **"Đặt ngưỡng"** (Set stability thresholds) and
   **"Lưu"** (Save) — Juli asks every seller for these limits before it changes a listing.
5. On a listing card ("Chờ duyệt", awaiting approval) press **"Duyệt"** (Approve). The
   **Đang thực hiện** (In progress) tab opens and the agent's steps appear live: reading TikTok's
   diagnosis, reading the product, analysing keywords and the product image, then **"Xác nhận
   một lần"** (confirm once) showing the drafted change before and after.
6. Press **"Xác nhận thay đổi này"** (Confirm this change). Juli writes it to TikTok Shop
   ("Ghi lên TikTok Shop") and reads the product back; the result reads "Đã ghi lên shop sandbox
   TikTok của Juli" and the card shows **"Đã ghi lên TikTok"** (Written to TikTok).
7. Product creation: on the card **"Tạo sản phẩm mới từ «…»"** press **"Duyệt"**. The run reads
   the source product and TikTok's categories, the model chooses the category, Juli checks TikTok's
   listing requirements, then **"Xác nhận tạo sản phẩm"** (Confirm product creation). The result
   "Đã tạo sản phẩm trên TikTok" shows the new TikTok product id and the status TikTok returned.
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
> the product. Recommendations run through our real AI agent workflow: an OpenAI model drafts the
> change, each step streams live, and after you confirm, Juli writes the change to the shop through
> the Open API and shows TikTok's confirmation read back from the shop. For the review, the account
> can also create a new product listing on the sandbox shop. We use our own
> sandbox shop so that reviewers never modify a real seller's shop.
>
> The updated step-by-step guide is in the Services Information section of our profile.
>
> Best regards,
> Juli AI team — lienhe@app-juli.com

Contact: lienhe@app-juli.com · https://app-juli.com/contact
