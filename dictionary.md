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
- Definition: Seller-facing envelope wrapping workflow, reasoning, and impact.

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

**`analytics.trend.rising`**
- EN: Rising trend
- VI: xu hướng tăng
- Definition: Raw upward movement of a charted series, in the chart's screen-reader text equivalent. States what the data did, never whether it is good.

**`analytics.trend.falling`**
- EN: Falling trend
- VI: xu hướng giảm
- Definition: Raw downward movement of a charted series, in the chart's screen-reader text equivalent.

**`analytics.trend.stable`**
- EN: Stable trend
- VI: xu hướng ổn định
- Definition: A flat charted series, in the chart's screen-reader text equivalent. Never used for a series that moved.

**`analytics.trend.favorable`**
- EN: Positive (movement toward the KPI's goal)
- VI: tích cực
- _Avoid_: tốt (vague), tăng trưởng (implies rising — a favorable move can be a fall)
- Definition: Goal-aware qualifier appended to a rising/falling trend phrase when the movement runs toward the KPI's goal direction, e.g. "xu hướng giảm — tích cực" for falling cancellations. Status: needs_review.

**`analytics.trend.adverse`**
- EN: Needs attention (movement against the KPI's goal)
- VI: cần chú ý
- _Avoid_: xấu, tiêu cực (alarmist)
- Definition: Goal-aware qualifier appended to a rising/falling trend phrase when the movement runs against the KPI's goal direction, e.g. "xu hướng tăng — cần chú ý" for rising cancellations. Echoes `common.attention_needed`. Status: needs_review.

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

**`empty.settings.sign_in_required`**
- EN: Workflow templates and thresholds require Sign-in. You can still explore the full Demo with mock data.
- VI: Mẫu quy trình và ngưỡng yêu cầu Sign-in. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu.
- _Avoid_: Đăng nhập để tiếp tục (when Sign-in is not yet available)
- Definition: Honest visitor placeholder on the Settings destination.

**`empty.settings.workflow_detail.sign_in_required`**
- EN: Editing workflow templates requires Sign-in. You can still explore the full Demo with mock data.
- VI: Chỉnh sửa mẫu quy trình yêu cầu Sign-in. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu.
- Definition: Honest visitor placeholder on a Settings workflow detail route.

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

**`decisions.reasoning`**
- EN: Reasoning
- VI: Lý do đề xuất
- _Avoid_: Giải thích, Phân tích AI
- Definition: The expandable explanation for a recommendation.

**`decisions.seller_reason`**
- EN: Seller reason
- VI: Lý do nên làm
- _Avoid_: Giải thích AI, Phân tích hệ thống
- Definition: One concise benefit-led line on a recommendation card surface.

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

**`home.cta.decisions`**
- EN: View recommendations
- VI: Xem đề xuất
- _Avoid_: Mở trang (identical CTA on sibling cards)
- Definition: Home launcher CTA for the Decisions destination — every launcher card gets its own verb-phrase CTA.

**`home.cta.analytics`**
- EN: View analytics
- VI: Xem phân tích
- _Avoid_: Mở trang (identical CTA on sibling cards)
- Definition: Home launcher CTA for the Analytics destination.

**`loading.recommendations`**
- EN: Loading recommendations…
- VI: Đang tải đề xuất…
- _Avoid_: Đang tải… (says nothing about what is loading)
- Definition: Loading fallback on the Decisions destination.

**`analytics.hero_lead`**
- EN: Your shop is currently at
- VI: Shop của bạn hiện đạt
- Definition: Lead-in sentence fragment above the hero KPI value, narrating the number instead of displaying it bare. The formatted value completes the sentence.

**`analytics.back_to_gmv`**
- EN: Back to GMV (TikTok)
- VI: Về GMV (TikTok)
- _Avoid_: Xem GMV (TikTok) ("Xem" is reserved for launcher/view CTAs; "Về" signals returning to a safe known place)
- Definition: Recovery link on the invalid-KPI deep-link state.

**`forms.show_password`**
- EN: Show password
- VI: Hiện mật khẩu

**`forms.hide_password`**
- EN: Hide password
- VI: Ẩn mật khẩu

## Phrases

**`home.tagline`**
- EN: Decide fast, understand your shop.
- VI: Quyết định nhanh, hiểu rõ shop.
- _Avoid_: Bạn muốn làm gì tiếp theo? (a preference question on a tool whose pitch is decisiveness)
- Definition: Home H1 — declarative tagline stating the product promise, not a question.

**`home.intro`**
- EN: The two places you need: recommendations awaiting approval, and the full picture of your shop.
- VI: Hai nơi bạn cần: đề xuất đang chờ phê duyệt, và bức tranh toàn cảnh shop.
- Definition: Home intro orienting the seller to the two launcher cards below it.

**`decisions.intro`**
- EN: These are recommendations Juli found for your shop, based on your latest sales data — you review, adjust, then decide whether to approve.
- VI: Đây là đề xuất Juli tìm thấy cho shop của bạn, dựa trên dữ liệu bán hàng gần nhất — bạn xem, chỉnh, rồi quyết định phê duyệt hay không.
- Definition: Decisions intro making human-in-the-loop explicit — the seller approves, nothing acts on their behalf.

**`error.kpi_not_found.body`**
- EN: This KPI was not found. The link may have changed or no longer exists.
- VI: Không tìm thấy KPI này. Đường dẫn có thể đã đổi hoặc không còn tồn tại.
- _Avoid_: Juli giữ nguyên URL để bạn hiểu lỗi này (implementation reasoning leaking into user copy)
- Definition: Body of the invalid-KPI deep-link state — what happened in user terms, recovery via `analytics.back_to_gmv`.

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

**`landing.nav.features`**
- EN: Features
- VI: Tính năng
- Definition: Landing header/footer anchor to the feature showcase section.

**`landing.nav.solutions`**
- EN: Solutions
- VI: Giải pháp
- Definition: Landing header/footer anchor to the market-comparison section.

**`landing.nav.contact`**
- EN: Contact
- VI: Liên hệ
- Definition: Landing header anchor to the footer contact block.

**`landing.cta.try_demo`**
- EN: Try the Demo
- VI: Dùng thử Demo
- _Avoid_: Đăng ký (the Demo is the primary CTA; registration is not)
- Definition: Header CTA — always links to the Demo in Mock mode.

**`landing.cta.experience_demo`**
- EN: Experience the Demo
- VI: Trải nghiệm Demo
- Definition: Hero primary CTA into the Demo.

**`landing.cta.explore_features`**
- EN: Explore features
- VI: Tìm hiểu tính năng
- Definition: Hero secondary CTA — in-page anchor, not a Demo link.

**`landing.cta.see_juli_work`**
- EN: See Juli work in the Demo
- VI: Xem Juli làm việc trong Demo
- Definition: Comparison-section CTA into the Demo.

**`landing.cta.experience_now`**
- EN: Experience it now
- VI: Trải nghiệm ngay
- Definition: Feature-showcase CTA into the Demo.

**`landing.curiosity.heading`**
- EN: How is your shop doing?
- VI: Shop của bạn đang vận hành thế nào?
- Definition: Curiosity CTA heading — a question the Demo answers on sample data.

**`landing.cta.discover_performance`**
- EN: Discover your shop's performance
- VI: Khám phá hiệu suất shop của bạn
- Definition: Curiosity CTA button into the Demo.

**`landing.footer.tagline`**
- EN: The AI assistant for TikTok Shop sellers
- VI: Trợ lý AI cho người bán TikTok Shop
- Definition: Footer brand tagline under the logo lockup.

**`agent.narration.extension_grant`**
- EN: Continuing past the standard iteration limit: granting [extension_iterations] more iteration(s) (extension [granted] of [max]).
- VI: Đã đạt giới hạn số lượt thực hiện tiêu chuẩn, Juli gia hạn thêm [extension_iterations] lượt để hoàn tất công việc (lần gia hạn [granted]/[max]).
- Status: reviewed — mechanical gates (banned-pattern gate, dynamic-number tests) green, and the repo owner approved the Vietnamese register and tone on 2026-08-21, supplying the human voice review ADR-072/​#1071 requires for seller-facing copy. The reviewed wording renders "extension K of M" as the fraction `K/M` rather than translating the preposition, and carries no plural inflection because Vietnamese has none.
- Definition: `workflow.status` `phase_narration` (ADR-074 d.2) for one iteration-cap extension grant (`services/agent/narration_copy.py::extension_grant_phase_narration`, issue #1140). The one narration the agent runner produces today; every bracketed number is sourced from `TerminationPolicy`, never a literal.
