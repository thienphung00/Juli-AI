# Juli / Shopee / TikTok Shop glossary (owner-confirmed meanings)

Every term here was misread by an agent at least once and then corrected by the owner (pipeline baseline 2026-W46, `/insights` 2026-11-16). **If a term in a brief isn't here, or seems to mean something else in context, ask before building.** Never build on a guessed meaning. When the owner corrects a term, add it here in the same PR.

## Shop scope
| Term | Means | Not |
|---|---|---|
| **Shop** (level / view) | all products of the shop together, the whole shop. This is the default view. | the Shop tab |
| **Shop tab** (Trang shop) | one traffic surface inside Shopee: the shop's own page | the whole shop |
| **Shop+** / **DVHT Shop+** | the same entity as the Shop (tab) surface. Ads on it land on the Shop tab. | a separate shop or a separate builder |
| **shop-level** | scoped to the whole shop | scoped to the Shop tab |
| **Sản phẩm** (level) | one product, picked with the product picker. There is no Shop+ at this level. | |

## Ads and traffic
| Term | Means |
|---|---|
| **Dịch vụ hiển thị Sản phẩm** (DVHT SP) | Shopee product ads (both GMV-max bidding modes). They land on **Thẻ sản phẩm**. It is part of the main ads builder, **not a separate builder**. |
| **Dịch vụ hiển thị Shop+** (DVHT Shop+) | Shopee shop ads (formerly "Quảng cáo cửa hàng"). They land on the Shop tab. |
| **Organic / TTLK / Quảng cáo** | the three traffic sources. TTLK = Tiếp thị liên kết (affiliate). TTLK has clicks and orders, no views. Organic = all sources minus "trong đó Quảng cáo". |
| **Thẻ sản phẩm** | the product-card surface. Tổng quan shows it separately from the Shop tab. |
| **Two ad bases** | the traffic overview's "trong đó Quảng cáo" and the ads report are different numbers. Name each one where it's shown; **never add them together**. |

## Numbers
| Term | Means |
|---|---|
| **GMV (headline)** | the Seller Centre shop total. **Doanh thu thực** (net) sits beside it. There is one shop-GMV source; screens must not compute their own. |
| **Biên cuối ở giá hiện tại** vs **Biên thực hiện 30 ngày** | the only two margins. Both are labelled every time and never mixed. Profit and margins use net revenue. |
| **Δ lợi nhuận / Δ GMV** | totals for the whole period (the plan's or version's days), with "≈ …/ngày" as the secondary figure |
| **ROI** | Lợi nhuận ÷ (ads + affiliate + ưu đãi cost), shown in points ("5,4"), **never as %** |
| **Tax** | Juli doesn't calculate withheld VAT or PIT. Don't add tax settings or "trước thuế" labels. |

## Order statuses (owner 2026-11-18, D2; Shopee and TikTok the same)
| Term | Means | Not |
|---|---|---|
| **returned** | the goods are back with the seller and the buyer is refunded. Revenue 0, no goods cost; the cost is the refund cost below plus the packaging. Not counted in đơn / GMV / AOV. | an open refund |
| **refunded_accepted** | the refund window is still open (the buyer may still get a refund) | a finished return |
| **refunded_not_received** | the return parcel is on its way back to the seller | goods already back (that is `returned`) |
| **Refund cost** (owner 2026-11-18) | for `refunded_accepted`, `refunded_not_received` and `returned`: what the settlement deducted from the seller, max(0, −payout) of the order's settlement row, counted as soon as a settlement row exists whatever the status says; no settlement row = no cost yet. Revenue 0. | the sum of the fee / shipping / return-shipping columns (the payout already nets them; summing double counts) |
| **Canonical order tables** | `order_lines`, `order_settlements`, `affiliate_lines`, `stock_history` and the `*_metrics_daily` tables (migration 134, T5): one table per fact for every platform; `day` is the GMT+7 day of the order | Shopee-only tables (`shopee_*` names stay as views for one release) |

## Flow and surfaces
| Term | Means |
|---|---|
| **Tổng quan → Phân tích → Quyết định (Đề xuất · Thực hiện · Đo lường) → Tối ưu** | the seller's path. **Tối ưu** is a row of actions on measured cards, not a tab. |
| **Tự tạo phương án** | the 4-step builder: Sản phẩm → Chiến lược → Phương án → So sánh & lưu. It has no "Ẩn / đưa lại listing" and no "Listing combo mới". |
| **Kế hoạch** | the plan: totals of the accepted cards over their date ranges, with goal progress |
| **Juli Connector** | the Chrome extension that reads Seller Centre pages and fills forms. The seller confirms; it syncs status back. |
| **Sample shop** | the ISV reviewer's mock shop. It copies the real app; sample-only code exists only for safety. |
| **Real client shop** | production data. Read-only for agents, and never written without the owner. |

## Who changed the data?
Before saying "Juli changed X", check the actor or source field of the row (Connector, file import, Seller Centre, the owner). Don't assume.
