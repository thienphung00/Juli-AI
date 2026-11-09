# shopee_builder/combo_options

## Purpose
P98 S7 pure core of the combo builder: `generate` (multi-pack of one product, bundles of several),
`count` (before building), `price` (ladder / target margin / per box, rounded, with margin and floor),
names, SKUs, suggested stock. No I/O; input = `variations.variation_rows` rows (+ `UnitCost`).

## Rules
- Margin / profit go through `variations.unit_margin` (the shop's fee schedule); a member without
  giá vốn makes the row "chưa tính", never the 1/3 fallback. A floor breach warns, never blocks.
- Every `SHOPEE_*` constant in `config` is unconfirmed: confirm at recon.
- Suggested stock = min over members of floor(stock / quantity), labelled "không tự đồng bộ".

## Must not
- Re-implement a fee or a floor. Read a database. Call a model.
