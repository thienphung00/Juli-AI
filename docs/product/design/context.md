# Context — Vietnamese Copy Rules & Glossary

> Locked terminology for every screen, component, and flow in this design
> system. No synonyms. If a new term is needed, add it here first.

## Product information architecture

Juli has exactly four primary destinations on every platform:

1. **Trang chủ (Home)** — a sparse launchpad with two prominent cards:
   Decisions and Analytics.
2. **Quyết định (Decisions)** — recommendations and approved work.
3. **Phân tích (Analytics)** — all metrics, KPIs, forecasts, and reporting.
4. **Cài đặt (Settings)** — workflow templates, thresholds, and related
   configuration.

Juli is contextual assistance within these destinations, not a standalone tab.
She explains the active metric, recommendation, workflow, or setting without
replacing the Decisions approval flow.

## Address form

Juli addresses the seller as **"bạn"** — informal-respectful, never the more
distant "quý khách" or the overly casual "em/anh/chị". This applies to every
first-person and second-person string Juli writes, including empty states,
errors, and contextual assistance.

- Correct: "Bạn có thể xem lại đề xuất này trước khi phê duyệt."
- Avoid: "Quý khách vui lòng xem lại..." (too formal/distant)
- Avoid: "Anh/chị xem lại..." (assumes gender/seniority)

## Fixed terminology glossary

| Vietnamese term | English concept | Definition | Never use instead |
|---|---|---|---|
| **Đề xuất** | Recommendation | The seller-facing envelope wrapping one workflow, reasoning, impact, and confidence in Decisions | "Gợi ý hành động", "Thẻ AI", "Khuyến nghị" |
| **Phê duyệt** | Approve | The seller action that authorizes a recommendation to enter its workflow | "Đồng ý", "Chấp thuận", "Xác nhận" |
| **Từ chối** | Reject | The seller action that removes a recommendation | "Bỏ qua", "Huỷ" |
| **Mở rộng** | Expand | Reveals a recommendation's reasoning and details in place | "Xem xét", "Chi tiết AI" |
| **Trang chủ** | Home | The sparse two-card launchpad | "Bảng điều khiển", "Báo cáo hôm nay" |
| **Quyết định** | Decisions | The recommendation and execution hub | "Hành động", "Khuyến nghị" |
| **Đề xuất** | Recommendations (sub-tab) | Ranked recommendations awaiting a seller decision | "Được đề xuất", "Khuyến nghị" |
| **Đang thực hiện** | In Progress (sub-tab) | Approved decisions in `needs_input`, `executing`, or `completed` | "Đang xử lý" |
| **Phân tích** | Analytics | The destination for all KPI, metric, comparison, and forecast reporting | "Bảng điều khiển" |
| **KPI chính** | Main KPI | The representative KPI marked `(main)` for one visual-layer category | "KPI nổi bật", "Chỉ số chính" |
| **Chưa khả dụng** | Unavailable | A visible KPI whose required source is not connected or legally available; never implies zero | "Không có dữ liệu" when the source itself is missing |
| **Nguồn dữ liệu** | Data source | The disclosed origin used to calculate a KPI | "Dữ liệu hệ thống" without naming the source |
| **Cập nhật lần cuối** | Last updated | The freshness timestamp for available KPI data | Raw ISO timestamps |
| **So sánh kỳ trước** | Compare previous period | Hero-only control that overlays the equivalent prior period | "So với trước" |
| **Cài đặt** | Settings | The destination that owns workflow templates and thresholds | "Mẫu quy trình" as a primary destination |
| **Mẫu quy trình** | Workflow templates | Workflow configuration within Settings | "Cài đặt nâng cao" as its name |
| **Ngưỡng** | Thresholds | Trigger and tolerance configuration within Settings | "Quy tắc tự động" when no automation exists |
| **Gợi ý từ Juli** | Juli assistance | Contextual explanation tied to the active surface | "Lời khuyên AI", "Tab Juli" |
| **Tác động dự kiến** | Estimated impact | Projected business value of a recommendation | "Kết quả dự kiến", "Lợi ích" |
| **Độ tin cậy** | Confidence | `high`, `medium`, or `low` confidence label | "Xác suất", "Chắc chắn" |
| **Lý do đề xuất** | Reasoning | The expandable explanation for a recommendation | "Giải thích", "Phân tích AI" |

## Naming conventions

- Component names stay in English in code and `Components/*.md`; user-visible
  copy is Vietnamese.
- Primary route labels are `Trang chủ`, `Quyết định`, `Phân tích`, and
  `Cài đặt`; route paths stay English (`/`, `/decisions`, `/analytics`,
  `/settings`).
- Workflow display names are Vietnamese in `Screens/` and `Flows/`; stable
  `workflow_id` values remain English slugs.
- Never call a recommendation an "AI Action Card" or "recommendation card" in
  user-facing copy; those are internal terms.
- Keep canonical KPI names (SPS, Net Revenue, ROAS, Inventory Turnover,
  Fulfillment Accuracy Rate, CSAT) unchanged; use **KPI chính** for the set or
  role, not as a replacement for an individual KPI name.

## Money, dates, and numbers

| Type | Rule |
|---|---|
| Currency | Use the currency formatter (`₫` suffix and thousands separator); never hand-format |
| Dates | Use ICT and the date/date-time formatter; never expose a raw ISO string |
| Numbers | Format impact values consistently for separators and rounding |

## Error and empty-state copy

Every error states the **problem** and the **recovery step** in one message:

> "Mã OTP không đúng. Vui lòng thử lại."

Every empty state explains **why it is empty** and **what happens next**:

> "Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ xuất hiện trong vòng 24 giờ."

## Financial data handling

Seller financial fields may appear in formatted UI, but:

- Never leak raw values into logs, prompts, or handoff documents.
- Prefer deltas, trend direction, and tier labels in explanatory copy.
- Mask sensitive drill-down values where the underlying data requires it.

## Governance

This file is the terminology authority. `Screens/`, `Flows/`, and
`Components/` must match it. Update this file first, then propagate a term
change downward; lower-tier evidence cannot redefine the glossary.
