# Juli Connector — Privacy policy (DRAFT, not yet reviewed)

_Last updated: 2026-10-26. Draft for the Chrome Web Store (Unlisted) submission;
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

These are **aggregated shop and product numbers**. The extension does not read
buyer names, addresses, phone numbers, messages, orders' personal details,
payment data, passwords or cookies.

## What it sends, and where

The numbers above, for whole finished days, to Juli's API
(`https://api.app-juli.com`) over HTTPS, under the seller's Juli shop. Nothing is
sent to anyone else. Nothing is sold or used for advertising.

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

Once, after the extension is first linked to a shop, it also fetches the same
numbers for each of the last 30 finished days, one day at a time and at the same
low rate, the way Seller Centre's own date picker asks for a single day. It
remembers which days are done, so it continues where it stopped after the
browser is closed, and it stops if Seller Centre or Juli refuses the request.

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
