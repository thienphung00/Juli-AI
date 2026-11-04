# Seller Centre product edit page: recon result and what the Connector fill-in does with it

P91 D-13 (`fill_listing`). The Connector fills the title and the first line of the description on a
product's edit page from the card's approved text. It finds the fields by visible Vietnamese label
and does nothing when it cannot.

**Recon done 2026-11-04** (one logged-in, read-only look at the ORY product edit page by the owner;
no click on Cập nhật / Lưu / Xác nhận / Ẩn, nothing saved). The four facts that were assumed are now
verified:

| # | Question | Result (2026-11-04) | Where it lives |
|---|---|---|---|
| 1 | Address of one product's edit page | `/portal/product/<item id>` (confirmed) | `kinds.Page.item_path`, `apps/connector/src/config.ts` `FILL_EDIT_PATH` |
| 2 | Visible label of the title field | `*Tên sản phẩm` (the required star is drawn with the label). The control is `<input type=text>` with placeholder `Tên thương hiệu + Loại sản phẩm + Đặc điểm nổi bật …` and a counter `NN/120` beside it. | `FILL_LABELS.title` |
| 3 | Visible label of the description field and its control | `*Mô tả sản phẩm`. A contenteditable rich editor (not a textarea). Inserting a new first line at the start and pressing Enter works. | `FILL_LABELS.description_first_line`, `fill/write.ts` |
| 4 | The save button | `Cập nhật`. The Connector never clicks it (nor Lưu, Xác nhận, Ẩn). | `fill-never-clicks.test.ts` |
| 5 | A note on the page | Some listings show a note that edits sync to the linked shops in other markets. The Connector does not read or act on it; a person saving the change accepts it. Worth saying in the operator's hand-over: a title change on ORY can reach the other markets. | - |

What changed in the Connector for this (v0.3.4):

- Matching ignores a leading `*`, a colon and a `NN/NNN` counter on both sides, so `*Tên sản phẩm`,
  `Tên sản phẩm` and `Tên sản phẩm 23/120` are one label. `FILL_LABELS` now carry the star exactly as
  the page draws it. A label used twice, or two inputs under one label, still fills nothing.
- A rich editor that keeps one block (`div` / `p` / `li`) per line is written line by line: only the
  first line's text changes, the other lines (and their elements) stay as they are; an editor without
  blocks gets its text replaced as before. Fixture: `test/fixtures/fill/edit-ory-recon.html`.
- Fill-in is available for the ORY pilot shop: `PILOT_SHOP_IDS` already holds only ORY's Juli shop id
  and `FILL_LISTING_ACTIVE` is on; the "*" wildcard of the readers does not count for fill-in.

**The server flag.** `CONNECTOR_FILL_LISTING` stays **off by default in code**. After the P91 deploy the
owner turns it on in the AWS secret (`juli/api/production`: `CONNECTOR_FILL_LISTING=1`), re-runs
`fetch-secrets.sh` and restarts the API; until then the Connector gets `fill_disabled` and the button
only opens the page. Switching it off again is the kill switch.

**Description read-back stays off.** The recon looked at the page, not at its network calls: it did not
show that the edit page's own product-detail request carries the description. Until someone confirms it
does (read-only, DevTools network tab on the same page) the Connector has no description reader, so
`verification.DESCRIPTION_READBACK_ACTIVE` stays off and a first-line change is marked done by a
person ("Đã làm") without an automatic read-back. The product list endpoint the Connector reads today
has no description.

Still unverified (no recon needed to ship; watch the first real fill): that the page ignores an unknown
`#juli-fill=...` fragment (path-routed app; `FILL_HASH_KEY`). If the page strips or reacts to it, the
Connector still finds the code in the address at load time; report anything odd.

Smoke test after the flag is on: open one ORY product's card in Demo or Ops, press "Điền bằng Connector",
check that the title / first line is typed and highlighted, and that nothing was saved; press Cập nhật
yourself only when the text is right.
