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
| **Juli card** (prediction type "Juli") | a card from Juli's backend rules (origin engine) or Juli chat (origin agent). Tự tạo (manual), imported (Làm ngoài Juli) cards and past promotions are shop data, not Juli (owner 2026-11-20). |
| **Thẻ sản phẩm** | the product-card surface. Tổng quan shows it separately from the Shop tab. |
| **Two ad bases** | the traffic overview's "trong đó Quảng cáo" and the ads report are different numbers. Name each one where it's shown; **never add them together**. |

## Numbers
| Term | Means |
|---|---|
| **GMV (headline)** | the Seller Centre shop total. **Doanh thu thực** (net) sits beside it. There is one shop-GMV source; screens must not compute their own. |
| **Biên cuối ở giá hiện tại** vs **Biên thực hiện 30 ngày** | the only two margins. Both are labelled every time and never mixed. Profit and margins use net revenue. |
| **Δ lợi nhuận / Δ GMV** | totals for the whole period (the plan's or version's days), with "≈ …/ngày" as the secondary figure |
| **ROI** | "ROI (lợi nhuận ÷ chi phí QC + AFF)": profit ÷ (ads + affiliate), shown in points ("5,4"), **never as %**. Ưu đãi is deducted from revenue, never a cost (owner 2026-11-18, option A). |
| **Tax** | Juli doesn't calculate withheld VAT or PIT. Don't add tax settings or "trước thuế" labels. |

## Order statuses (owner 2026-11-18, D2; Shopee and TikTok the same)
| Term | Means | Not |
|---|---|---|
| **returned** | the goods are back with the seller and the buyer is refunded. Revenue 0, no goods cost; the cost is the refund cost below plus the packaging. Not counted in đơn / GMV / AOV. | an open refund |
| **refunded_accepted** | the refund window is still open (the buyer may still get a refund). Revenue 0, cost = the refund cost below. Not counted in đơn / GMV / AOV (owner 2026-11-18). | a finished return |
| **refunded_not_received** | the return parcel is on its way back to the seller. Revenue 0, cost = the refund cost below. Not counted in đơn / GMV / AOV (owner 2026-11-18). | goods already back (that is `returned`) |
| **Refund cost** (owner 2026-11-18) | for `refunded_accepted`, `refunded_not_received` and `returned`: what the settlement deducted from the seller, max(0, −payout) of the order's settlement row, counted as soon as a settlement row exists whatever the status says; no settlement row = no cost yet. Revenue 0. | the sum of the fee / shipping / return-shipping columns (the payout already nets them; summing double counts) |
| **Canonical order tables** | `order_lines`, `order_settlements`, `affiliate_lines`, `stock_history` and the `*_metrics_daily` tables (migration 134, T5): one table per fact for every platform; `day` is the GMT+7 day of the order | Shopee-only tables (`shopee_*` names stay as views for one release) |
| **Source precedence** (owner 2026-11-18) | API > Connector > file. On `order_lines`, `affiliate_lines` and `order_settlements`: a post of the same or a higher rank replaces with its non-null values (a NULL never clears a stored value); a lower-ranked post (a file under the Connector) only fills columns that are NULL in the stored row, and the row's source / rank / version / payload stay with the higher writer (each fill is counted in one `ingest_gap_fill` log line). An order no higher source wrote comes from the file in full (history backfill). | a file overwriting what the Connector read |

## Flow and surfaces
| Term | Means |
|---|---|
| **Tổng quan → Phân tích → Quyết định (Đề xuất · Thực hiện · Đo lường) → Tối ưu** | the seller's path. **Tối ưu** is a row of actions on measured cards, not a tab. |
| **Tự tạo phương án** | the 4-step builder: Sản phẩm → Chiến lược → Phương án → So sánh & lưu. It has no "Ẩn / đưa lại listing" and no "Listing combo mới". |
| **Kế hoạch** | the plan: totals of the accepted cards over their date ranges, with goal progress |
| **Juli Connector** | the Chrome extension that reads Seller Centre pages and fills forms. The seller confirms; it syncs status back. |
| **Sample shop** | the ISV reviewer's mock shop. It copies the real app; sample-only code exists only for safety. |
| **Reader block** | a Connector page that could not be read on a run; shown on Thực hiện with its section and reason (`reader_blocks`). It clears as soon as that page's data arrives again. |
| **Shopee tạm chặn** (`traffic_check`) | Shopee sent a Connector tab to its traffic-check page (`shopee.vn/verify/traffic…`). Connector 0.3.28 stops every read, fill and read-back for 6 h (nothing lifts it early) and Thực hiện shows "Shopee tạm chặn — Juli dừng đến HH:mm". Cause seen 19/11: untrusted clicks by the fill; since 0.3.28 the Connector never clicks on Shopee (guided fill). |
| **password_recheck** | Shopee's "vui lòng nhập mật khẩu Shopee của bạn" dialog on Phân tích bán hàng (/datacenter). The owner confirms it once; the Connector never types it. Not a logout (that is `login`). |
| **Re-read (`reread`)** | the Connector reading again, the same day, the pages a block stopped, right after the block clears. |
| **Real client shop** | production data. Read-only for agents, and never written without the owner. |

## Who changed the data?
Before saying "Juli changed X", check the actor or source field of the row (Connector, file import, Seller Centre, the owner). Don't assume.
