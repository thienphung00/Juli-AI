# Copy dictionary — EN → VI

Sole English-to-Vietnamese catalog for Juli seller-facing UI, reports, and copy-layer
output. Voice, address form, money/date rules, and governance live in
[`docs/product/design/design-context.md`](docs/product/design/design-context.md).
Agents look up Vietnamese here before writing user-visible copy. If a needed string is
missing, draft per Design context, then add a keyed entry here in the same change
([ADR-028](docs/adr/028-vietnamese-copy-dictionary-and-design-context.md)).

## Keywords

**`decisions.recommendation`**
- EN: Recommendation
- VI: Đề xuất
- _Avoid_: Gợi ý hành động, Thẻ AI, Khuyến nghị
- Definition: Seller-facing envelope wrapping workflow, reasoning, impact, and confidence.

**`decisions.approve`**
- EN: Approve
- VI: Phê duyệt
- _Avoid_: Đồng ý, Chấp thuận, Xác nhận
- Definition: Authorizes a recommendation to enter its workflow.

**`decisions.reject`**
- EN: Reject
- VI: Từ chối
- _Avoid_: Bỏ qua, Huỷ
- Definition: Removes a recommendation.

**`decisions.expand`**
- EN: Expand
- VI: Mở rộng
- _Avoid_: Xem xét, Chi tiết AI
- Definition: Reveals a recommendation's reasoning and details in place.

**`nav.home`**
- EN: Home
- VI: Trang chủ
- _Avoid_: Bảng điều khiển, Báo cáo hôm nay
- Definition: The sparse two-card launchpad.

**`nav.decisions`**
- EN: Decisions
- VI: Quyết định
- _Avoid_: Hành động, Khuyến nghị
- Definition: The recommendation and execution hub.

**`decisions.tab.recommendations`**
- EN: Recommendations (sub-tab)
- VI: Đề xuất
- _Avoid_: Được đề xuất, Khuyến nghị
- Definition: Ranked recommendations awaiting a seller decision.

**`decisions.tab.in_progress`**
- EN: In Progress (sub-tab)
- VI: Đang thực hiện
- _Avoid_: Đang xử lý
- Definition: Approved decisions in `needs_input`, `executing`, or `completed`.

**`nav.analytics`**
- EN: Analytics
- VI: Phân tích
- _Avoid_: Bảng điều khiển
- Definition: The destination for KPI, metric, comparison, and forecast reporting.

**`analytics.main_kpi`**
- EN: Main KPI
- VI: KPI chính
- _Avoid_: KPI nổi bật, Chỉ số chính
- Definition: The representative KPI marked `(main)` for one visual-layer category.

**`analytics.unavailable`**
- EN: Unavailable
- VI: Chưa khả dụng
- _Avoid_: Không có dữ liệu (when source missing)
- Definition: A visible KPI whose required source is not connected or legally available; never implies zero.

**`analytics.data_source`**
- EN: Data source
- VI: Nguồn dữ liệu
- _Avoid_: Dữ liệu hệ thống (unnamed)

**`analytics.last_updated`**
- EN: Last updated
- VI: Cập nhật lần cuối
- _Avoid_: raw ISO timestamps
- Definition: The freshness timestamp for available KPI data.

**`analytics.compare_previous_period`**
- EN: Compare previous period
- VI: So sánh kỳ trước
- _Avoid_: So với trước
- Definition: Hero-only control that overlays the equivalent prior period.

**`nav.settings`**
- EN: Settings
- VI: Cài đặt
- _Avoid_: Mẫu quy trình as primary destination
- Definition: The destination that owns workflow templates and thresholds.

**`settings.workflow_templates`**
- EN: Workflow templates
- VI: Mẫu quy trình
- _Avoid_: Cài đặt nâng cao as its name
- Definition: Workflow configuration within Settings.

**`settings.thresholds`**
- EN: Thresholds
- VI: Ngưỡng
- _Avoid_: Quy tắc tự động when no automation exists
- Definition: Trigger and tolerance configuration within Settings.

**`common.juli_assistance`**
- EN: Juli assistance
- VI: Gợi ý từ Juli
- _Avoid_: Lời khuyên AI, Tab Juli
- Definition: Contextual explanation tied to the active surface.

**`decisions.estimated_impact`**
- EN: Estimated impact
- VI: Tác động dự kiến
- _Avoid_: Kết quả dự kiến, Lợi ích
- Definition: Projected business value of a recommendation.

**`decisions.confidence`**
- EN: Confidence
- VI: Độ tin cậy
- _Avoid_: Xác suất, Chắc chắn
- Definition: `high`, `medium`, or `low` confidence label.

**`decisions.reasoning`**
- EN: Reasoning
- VI: Lý do đề xuất
- _Avoid_: Giải thích, Phân tích AI
- Definition: The expandable explanation for a recommendation.

**`decisions.status.needs_input`**
- EN: Needs input
- VI: Cần thêm thông tin
- Definition: Approval exists but a required seller value or external prerequisite is missing.

**`decisions.status.executing`**
- EN: Executing
- VI: Đang thực hiện
- Definition: An action is queued/running or the workflow is waiting for an authoritative webhook/external event.

**`decisions.status.completed`**
- EN: Completed
- VI: Hoàn tất
- Definition: Terminal success or terminal handled outcome.

**`decisions.status.waiting`**
- EN: Waiting
- VI: Đang chờ

**`analytics.range.7_days`**
- EN: 7 days
- VI: 7 ngày

**`analytics.range.30_days`**
- EN: 30 days
- VI: 30 ngày

**`analytics.range.90_days`**
- EN: 90 days
- VI: 90 ngày

**`common.attention_needed`**
- EN: Needs attention
- VI: Cần chú ý

**`common.undo`**
- EN: Undo
- VI: Hoàn tác

**`common.retry`**
- EN: Retry
- VI: Thử lại

**`common.close_explanation`**
- EN: Close explanation
- VI: Đóng giải thích

**`forms.show_password`**
- EN: Show password
- VI: Hiện mật khẩu

**`forms.hide_password`**
- EN: Hide password
- VI: Ẩn mật khẩu

## Phrases

**`error.otp_incorrect`**
- EN: OTP code is incorrect. Please try again.
- VI: Mã OTP không đúng. Vui lòng thử lại.

**`empty.decisions.waiting_data`**
- EN: Juli is collecting your shop data; first recommendations within 24h.
- VI: Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ xuất hiện trong vòng 24 giờ.

**`toast.decision.approved`**
- EN: Recommendation approved.
- VI: Đã phê duyệt đề xuất.

**`error.login.wrong_password`**
- EN: Wrong email or password. Please try again.
- VI: Sai email hoặc mật khẩu. Vui lòng thử lại.

**`error.login.account_not_found`**
- EN: No account found with this email.
- VI: Không tìm thấy tài khoản với email này.

**`error.network`**
- EN: Cannot connect. Please check your network and try again.
- VI: Không thể kết nối. Vui lòng kiểm tra mạng và thử lại.

**`empty.decisions.in_progress_filtered`**
- EN: No decisions are currently in progress.
- VI: Chưa có quyết định nào đang thực hiện.

**`analytics.primary_question`**
- EN: What is happening in my shop?
- VI: Điều gì đang xảy ra trong shop của tôi?

**`popover.unavailable_kpi.trigger`**
- EN: Why is [KPI] unavailable?
- VI: Vì sao [KPI] chưa khả dụng?

**`popover.unavailable_kpi.heading`**
- EN: [KPI] unavailable
- VI: [KPI] chưa khả dụng

**`badge.confidence.high`**
- EN: Confidence: High
- VI: Độ tin cậy: Cao
