# Shopee ISV — Services Information (D42 item 7 + amendment, AC-32.10)

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

**About the trial account.** It is a partner account that opens the full product on a **sample
shop** ("Cửa hàng Mẫu Hoa Mai", sample data, labelled as such), so no real seller's data is shown
to third parties. Approving and executing a recommendation is **simulated**: the screen shows the
exact change Juli would send to the marketplace API, but nothing is sent. Every other feature a
seller has — rejecting a recommendation, editing a draft before applying it, the photo and Seller
Center steps, video / LIVE scripts, reverting a change, the day-7 / day-14 measurement, shop
rules, video analysis — is enabled the same way: it runs in the browser on the sample data and is
labelled "Mô phỏng" (simulation). "Đặt lại dữ liệu mẫu" in the banner resets the sample. The
interface is in Vietnamese; the steps below give the English meaning of each label.

## Steps for the reviewer

1. Open https://demo.app-juli.com and choose **"Tài khoản đối tác (đăng nhập bằng mật khẩu)"**
   (Partner account — sign in with password); enter the username and password above. A banner at
   the top reads "Tài khoản dùng thử cho đối tác · dữ liệu mẫu · thao tác chỉ mô phỏng" (partner
   trial account · sample data · actions are simulated only).
2. **Trang chủ** (Home): the shop's GMV and its traffic sources (product card, video, LIVE, …),
   last 30 days against the 30 days before.
3. **Phân tích** (Analysis): open a traffic source to see its funnel — impressions, CTR, CTOR
   (click-to-order rate), AOV — with the weakest step highlighted and the products pulling it down
   ranked by GMV impact.
4. **Quyết định** (Decisions): Juli's recommendation cards. Open one to see the product, the
   target metric, the evidence and the proposed change.
5. Press **"Duyệt"** (Approve), then **"Thực thi"** (Execute). The result, labelled "Mô phỏng ·
   không gửi tới TikTok" (Simulation · not sent to TikTok), shows the API call Juli would make
   (for example `update_product_listing`) with the field before and after. For a connected seller
   this is when Juli writes the approved change through the Open API.
6. Press **"Theo dõi lượt chạy (mô phỏng)"** (Follow the run): the **Đang thực hiện** (In
   progress) tab shows each step of the run. Use **"✎ Sửa nội dung trước khi áp dụng"** (Edit
   before applying) to change the draft, then **"Xác nhận thay đổi này"** (Confirm this change).
   Once applied, **"Hoàn tác"** (Revert) restores the old content, with a reason.
7. Back on **Đề xuất** (Recommendations): **"Từ chối"** (Reject) asks for a reason; the
   cover-image card asks for a photo; the promotion card shows the Seller Center checklist and
   **"Tôi đã áp dụng"** (I have applied it); the video / LIVE cards ("Juli soạn · bạn làm") show
   Juli's script with **"Soạn lại"** (Redraft) and **"Dùng kịch bản này"** (Use this script), and
   a **"Phân tích video"** (Video analysis) block — picking a file shows a sample analysis; the
   file is not uploaded.
8. **Đo lường** (Measurement): **"Ngày 7 (mô phỏng)"** / **"Ngày 14 (mô phỏng)"** preview the
   day-7 check and the day-14 verdict on the runs you completed.
9. **Quy tắc** (Rules — "Sửa" on Quyết định, or Cài đặt in the shop menu): edit and save the
   shop's rules, labelled "Mô phỏng · không lưu" (simulation · not saved).
10. Product and integration details: https://app-juli.com/san-pham ·
   https://app-juli.com/ket-noi/tiktok-shop · trial sign-up https://app-juli.com/dang-ky.

Contact: lienhe@app-juli.com · https://app-juli.com/contact
