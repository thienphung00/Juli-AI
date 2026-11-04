# Seller Centre product edit page: the one read-only recon the Connector fill-in waits for

P91 D-13 (`fill_listing`). The Connector fills the title and the first line of the description on a
product's edit page from the card's approved text. It finds the fields by visible Vietnamese label
and does nothing when it cannot. Four facts below are **assumed, not verified**; one logged-in,
read-only look at ONE product's edit page (no click on Lưu / Cập nhật / Xác nhận / Ẩn, nothing
saved) settles them. Until then the server flag `CONNECTOR_FILL_LISTING` stays off.

| # | Question | Assumed today | Where it lives |
|---|---|---|---|
| 1 | Address of one product's edit page | `/portal/product/<item id>` (a bare number; the list is `/portal/product/list/all`) | `kinds.Page.item_path`, `apps/connector/src/config.ts` `FILL_EDIT_PATH` |
| 2 | Visible label of the title field | `Tên sản phẩm` | `FILL_LABELS.title` |
| 3 | Visible label of the description field, and whether it is a `<textarea>` or a rich editor | `Mô tả sản phẩm`, either | `FILL_LABELS.description_first_line`, `fill/write.ts` |
| 4 | Does the page ignore an unknown `#juli-fill=...` fragment (it is a path-routed app) | yes | `FILL_HASH_KEY` |

Also worth one look while there (read-only): does the edit page's own XHR (product detail) carry the
description? If it does, a Connector reader can post `description_first_line` and the read-back
(`verification.DESCRIPTION_READBACK_ACTIVE`) can be switched on. The product LIST endpoint the
Connector reads today has no description.

What to record: the address, the two label texts exactly as drawn (including a required star or a
counter such as `23/100`), the control type behind each (`input` / `textarea` / `contenteditable`),
and a note if a label appears twice on the page (the Connector refuses an ambiguous label).
Then set `PILOT_SHOP_IDS` fill gate stays explicit-ids-only, flip the server flag for the pilot shop and
run the Demo button on one product.
