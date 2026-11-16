# Juli UI standing rules (owner decisions; they apply to every UI slice and every canvas)

Each rule comes from an owner decision that was previously kept only in session memory. When a rule conflicts with a brief, ask the owner; don't pick one yourself.

## Words on screen
- No explanatory captions, footnotes, notices, "Số minh hoạ" / "ước tính" / "(tham khảo)" badges, or AI-sounding explanation lines. Use labels, numbers and controls only. Honesty notes go to the owner in chat, never on screen. (2026-11-13)
- "Shop" means all products together, and Shop is the default view. DVHT Shop+ is the Shop (tab) surface; don't add an "assumption" label. (2026-11-13)
- Ads are named **Dịch vụ hiển thị Sản phẩm** and **Dịch vụ hiển thị Shop+**; **DVHT** is the short form. Copy Shopee's labels word for word. Stored keys and enums stay unchanged. (2026-11-12)
- Strategy cards show "Chi phí: …" only when the strategy costs money. Metrics appear as colour-coded chips: Lượt xem blue, CTR teal, CTOR purple, AOV amber, Đơn green.
- ROI = Lợi nhuận ÷ (ads + affiliate + ưu đãi cost), shown in points ("5,4"), never as %.

## Flow (north star, 2026-11-13)
Tổng quan (% shift per metric, each one links to Phân tích) → Phân tích (one metric at a time, linking to its cards) → Quyết định (Đề xuất [Thẻ | Kế hoạch nháp] · Thực hiện · Đo lường) → Tối ưu, which is a row of actions on measured cards, not a tab. Plus Dữ liệu shop.
A screen that doesn't move the seller to the next stage gets folded into one that does.
Period presets: 7 / 30 / 90 / Tùy chọn (no "Tháng này"), plus a Tổng | Trung bình / ngày switch.

## Traffic hierarchy (2026-11-13)
- Three sources: **Organic**, **TTLK** (affiliate), **Quảng cáo**.
- DVHT Sản phẩm → Thẻ sản phẩm; DVHT Shop+ → Shop tab. In Tổng quan, Thẻ sản phẩm and Shop tab are shown separately.
- TTLK has no views: it shows clicks and orders.
- The builder has no "Ẩn / đưa lại listing" and no "Listing combo mới".

## Surfaces
- The same UI serves the Shopee seller, Ops, and the ISV reviewer's sample shop. The sample shop copies the real app; sample-only code exists only for safety (no outbound calls, LLM quota, audit). Don't keep a separate feature allowlist.
- No manual steps: a design that ends with "owner runs X" is incomplete. Make it a triggered job. (2026-11-15)
