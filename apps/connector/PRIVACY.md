# Juli Connector — Privacy policy (DRAFT, not yet reviewed)

_Last updated: 2026-11-06. Draft for the Chrome Web Store (Unlisted) submission;
to be reviewed before publishing and linked from app-juli.com._

Juli Connector is a browser extension by Juli (app-juli.com) for sellers who use
Juli with their Shopee shop. It sends the seller's **own shop performance
numbers** from Shopee Seller Centre to the seller's Juli account so Juli can
analyse them and suggest improvements.

## What the extension reads

Only on `https://banhang.shopee.vn`, and only the responses Seller Centre's own
pages load from these data endpoints of the seller's shop:

- product traffic by source (Thẻ sản phẩm, Video, Live, Tiếp thị liên kết,
  Dịch vụ Hiển thị) — sales, orders, units, buyers, impressions, clicks, rates;
- product traffic and performance per product — the same metrics per product,
  with the product id and name;
- shop traffic — visitors, page views, bounce rate, by device.

On the report pages below it also reads the data those pages load for the seller's
shop — the same requests the page makes itself, repeated for a chosen day or page
number:

- **Sản phẩm › Tất cả sản phẩm** (`/portal/product/list/all`) — each product's name,
  SKU, status, price range and discount, stock per variation (sellable, in transit),
  view / like / sold counts, cover and variation images, created and modified times,
  and its promotion tags;
- **Dữ liệu › Sản phẩm › Lưu lượng** (`/datacenter/product/traffic`) — for each of
  the shop's active products and each finished day (yesterday and up to three
  earlier days not read yet), the product traffic details Seller Centre loads:
  sales, orders, units, buyers, product impressions and clicks (and their unique
  counts), split by traffic source (search, recommendation, shop page, cart,
  my purchases, promotion, other) for product cards, Live, Video and affiliate.
  Aggregate numbers per product only, no buyer data. If Seller Centre shows its
  "enter your Shopee password" box on this page, the extension stops and reads
  nothing more that day; it never types into it;
- **Marketing › Quảng cáo** (`/portal/marketing/pas/index`) — per campaign and per
  finished day: title, type, state, budgets, ROAS target and the report numbers
  (impressions, clicks, cost, sales and orders, ranks, voucher amounts), and the
  ROAS target in force that day;
- **Marketing › Voucher của shop** (`/portal/marketing/vouchers/list`) — each
  voucher's code, name, dates, discount, minimum spend, usage limit and how many
  times it has been used or handed out (not who used it);
- **Hiệu suất tài khoản** (`/portal/accounthealth`) — the shop's account-health
  metrics, their targets and whether each is met;
- **Tăng Đơn Cùng KOL** (affiliate marketing, `/portal/web-seller-affiliate/...`, from
  version 0.3.6) — the shop's own affiliate results as these pages show them:
  - *Báo cáo chuyển đổi* (conversion report): per affiliate order line of the last 30
    days, the product and variation, price, quantity, order value, refund, the programme's
    cost, status and times, the campaign type and channel, and the creator's public
    Shopee login handle. **The order id is replaced in the browser by a keyed hash**
    (with a key Juli gives the extension for this shop only) before anything is sent; the
    creator's display name, avatar and platform user id and any buyer information are
    dropped in the page and never sent;
  - *Phân tích Tăng đơn cùng KOL*, *Dữ liệu phân tích chính*, *Phân tích sản phẩm*,
    *Phân tích chiến dịch*, *Phân tích Nội dung* — totals per creator (public handle),
    per day, per product, per commission campaign and for content: clicks, orders, sales,
    units, buyers and new buyers, estimated and actual commission, ROI, views and likes;
  - *Chiến dịch mở rộng* — the shop's own affiliate campaigns: name, commission rate,
    dates, budget;
  - *Báo cáo đối soát* — the monthly affiliate bill: commission, deductions, pending.
  On these pages the extension only keeps the answers the page loads by itself (and, for
  the conversion report, asks for the next pages of the same list). It never sends any
  request that changes something and never clicks anything.

These are **aggregated shop and product numbers**. The extension does not read
buyer names, addresses, phone numbers, messages, orders' personal details,
payment data, passwords or cookies.

## What it sends, and where

The numbers above, for whole finished days, to Juli's API
(`https://api.app-juli.com`) over HTTPS, under the seller's Juli shop. Nothing is
sent to anyone else. Nothing is sold or used for advertising.

## Public market search (pilot shops only)

Once a week, for a few of the shop's own product keywords (chosen by Juli), the extension
opens the public Shopee search page (`https://shopee.vn/search?keyword=...`, no login) in a
background tab and reads only the listing cards that page loads for everyone: product name,
shop name, price, sold count, rating and image id. It reads no account, cookie, review or
buyer information, clicks nothing, and stops on a login page or CAPTCHA. It is off for every
shop except the pilot shops.

## Credentials

The extension never asks for or stores the seller's Shopee or Juli password. It
uses the seller's existing Seller Centre session in their own browser. To link to
Juli, the seller types a one-time code created in their Juli account; the
extension exchanges it for an access token that can only send data for that one
shop, expires after 90 days, is rotated automatically, and can be revoked by the
seller at any time in Juli. The token is stored in the extension's local storage.

## Automatic daily sync

Once a day, and only while a Seller Centre tab is open, the extension repeats the
same data requests Seller Centre itself makes for "yesterday", at a low rate (at
least 2 seconds apart). It never logs in, never clicks or changes anything in
Seller Centre, and does nothing when Seller Centre is closed.

## Opening the report pages itself

Once a day, at a random time, the extension also **opens the four report pages
listed above itself**, one after the other, each in a background tab that does not
take focus. It waits for the page to load, lets the page make its own requests,
asks for the same data again for one finished day or the next page of a list (at
least 2 seconds apart), then **closes the tab**. A pause of tens of seconds is kept
between pages, and the run takes a few minutes at most. It uses the seller's own
signed-in session; it opens nothing else.

These pages are only read. The extension **never clicks anything on them** — no
button, banner, pop-up or upsell offer (for example "Áp dụng cho tất cả" on the ads
page is never touched), and it never creates, applies, edits or saves anything in
Seller Centre. If Seller Centre shows a login page or a CAPTCHA / verification, the
extension **stops at once, opens no further page, and shows "tạm dừng" in its
popup** until the seller signs in or verifies themselves; after a CAPTCHA it also
leaves Seller Centre alone for several days. It does not try to get past either.
Shops can be switched off from this scheduled reading by Juli; uninstalling the
extension stops it entirely.

Once, after the extension is first linked to a shop, it also fetches the same
numbers for each of the last 30 finished days, one day at a time and at the same
low rate, the way Seller Centre's own date picker asks for a single day. It
remembers which days are done, so it continues where it stopped after the
browser is closed, and it stops if Seller Centre or Juli refuses the request.

## Filling in a product's text (pilot shops only, opt-in)

For a shop on Juli's pilot list, and only when the seller opens a product's edit
page **from Juli's "Điền bằng Connector" button**, the extension can type text the
seller has already approved in Juli into that page's product-name field or the
first line of its description. The address of the page then carries only the
approved card's code (for example `#juli-fill=JC-2611-0007`); the extension asks
Juli for that card's approved text with its access token, finds the two fields by
their visible labels, highlights them and shows "Juli đã điền — kiểm tra rồi bấm
Lưu của Shopee".

It **never clicks anything** on the page — not Lưu, Cập nhật, Xác nhận, Ẩn or any
other button — never submits a form, never leaves the page and reads nothing from
it except the current text of the field it is filling. The seller reviews the text
and presses Shopee's own Save. If the page does not look as expected the extension
fills nothing and shows the text with copy buttons instead. For a new cover image
it only shows a download link; for a variation change it shows a checklist beside
the page.

## Retention and deletion

How long Juli keeps the data depends on how the shop uses Juli:

- **Self-serve accounts:** as long as the seller's Juli account and shop exist.
- **Shops under a client contract with a data-processing or confidentiality (NDA)
  clause:** until the end of that contract plus 30 days. If the law requires Juli
  to keep some of it longer, that part is kept isolated and used for nothing else
  until the legal period ends.

Both under Juli's main privacy policy (app-juli.com). Uninstalling the extension
stops all collection. To delete data, contact lienhe@app-juli.com.

## Contact

lienhe@app-juli.com
