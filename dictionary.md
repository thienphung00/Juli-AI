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

**`decisions.card.see_more`**
- EN: See more
- VI: Xem thêm
- _Avoid_: Mở rộng, Chi tiết AI, Xem chi tiết
- Definition: The list card's third action (issue #1916, v3 draft) — opens the recommendation's detail beside the list (the list narrows, the detail takes the remainder; never an overlay or a modal). Hides itself while its card's detail is open; Phê duyệt and Từ chối stay on the card.

**`decisions.detail.title`**
- EN: Recommendation detail
- VI: Chi tiết đề xuất
- _Avoid_: Thông tin thêm, Chi tiết AI
- Definition: Accessible name of the region "Xem thêm" opens beside the list (issue #1916) — carries the recommendation's signal, reasoning, evidence, eligibility, known limits, and risks.

**`decisions.detail.back`**
- EN: Back
- VI: Quay lại
- _Avoid_: Trở về, Đóng, Thoát
- Definition: Restores the full-width recommendation grid from the beside-the-list detail (issue #1916, rendered "← Quay lại") and returns focus to the card that opened it. Distinct from any review-page control: the plan review deliberately has no "Quay lại" button.

**`review.compare.current`**
- EN: Live on your shop
- VI: Đang bán trên shop của bạn
- _Avoid_: Phiên bản cũ, Hiện trạng, Bản gốc
- Definition: Column label over the current-listing side of the review page's before/after (issue #1916, ADR-055 item 8 surface) — names the seller's live listing explicitly so they never infer which column is theirs.

**`review.compare.proposed`**
- EN: Juli proposes
- VI: Juli đề xuất
- _Avoid_: Phiên bản mới, Bản nháp, Sau khi thay đổi
- Definition: Column label over the proposed side of the review page's before/after (issue #1916). What approval — through the two-step consent gate — would submit; nothing changes until the gate's own confirm.

**`nav.home`**
- EN: Home
- VI: Trang chủ
- _Avoid_: Bảng điều khiển, Báo cáo hôm nay
- Definition: The sparse two-card launchpad.

**`nav.decisions`**
- EN: Actions
- VI: Hành động
- _Avoid_: Quyết định, Khuyến nghị
- Definition: The recommendation and execution hub — where you review Juli's proposals, approve or decline them, and watch them run. "Quyết định" is the tab's former name, retired by owner decision on #1910 (2026-09-14). Runtime constant `ACTIONS_DESTINATION_LABEL` in `apps/demo/src/lib/destination-copy.ts` (shared by the nav rail and the run header's back control); keep them byte-identical.

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

**`impact.provenance.synthetic`**
- EN: Illustrative figure
- VI: Số liệu minh hoạ
- _Avoid_: Số liệu demo
- Definition: Provenance marker rendered beside any impact figure whose `impact_readings.series_source` is `synthetic` (issue #1958; ADR-099 decision 2). Shown with a leading ◆ glyph. The marker follows the reading's own column value — never the entry mode or a client-side guess — so a real computation over invented series is structurally incapable of being mistaken for a measured one. "Số liệu demo" is avoided as developer vocabulary in front of a seller. The "minh hoạ" spelling follows the approved v3 draft verbatim.

**`impact.provenance.unprovenanced`**
- EN: Figure source not recorded — not shown as a real measurement
- VI: Chưa rõ nguồn số liệu — không hiển thị như số đo thực
- _Avoid_: Số liệu tạm thời
- Definition: Fail-closed state for an impact reading that arrives without a valid `series_source` (issue #1958 AC3). The figure itself is withheld and this copy stands where the number would have been — the view layer never reintroduces the `measured` default the column deliberately refuses. "Số liệu tạm thời" is avoided because it implies the figure will firm up on its own; the honest state is that provenance was never declared.

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

**`demo.try`**
- EN: Try the Demo
- VI: Dùng thử Demo
- Definition: The landing's sessionless, dataless client-replay entry (ADR-094 decision 1, PUI-DESIGN §1). Mints no session, calls no `/v1/*` route.

**`demo.mode.replay`**
- EN: Illustrative example (replay mode indicator)
- VI: Bản minh họa
- _Avoid_: Mock (developer vocabulary in front of a seller)
- Definition: `DemoShell`'s header mode-switcher label (issue #1907) for the replay/mock state, consistent with `demo.try`'s own "bản minh họa" wording.

**`auth.google`**
- EN: Sign in with Google
- VI: Đăng nhập với Google
- Definition: The landing's other entry — Supabase Auth (Google provider) to a real, distinct identity, then the connect-shop screen (ADR-094 decision 3).

**`auth.connect_shop`**
- EN: Connect TikTok Shop
- VI: Kết nối TikTok Shop
- Definition: The screen a signed-in seller reaches after Google sign-in. States its actual state honestly — no control implies a working merchant exchange before the live OAuth exchange is wired (a flagged follow-up).

**`auth.google.unavailable`**
- EN: Sign in with Google is not available in this environment.
- VI: Đăng nhập với Google chưa sẵn sàng trong môi trường này.
- _Avoid_: Google chưa được cấu hình (dev-facing "cấu hình" tells the seller nothing they can act on)
- Definition: Visible copy rendered beneath the disabled `auth.google` door when `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` are absent at build time (issue #1905) — the honest-disabled state stays real and lives in visible text, not only in `aria-label`.

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

**`empty.decisions.waiting_data`** — **RETIRED (ADR-103, was ADR-098 d.6).** Do not use in new
work. The 24-hour promise is replaced by the onboarding's live three-step read list, whose steps
turn done on real job completion. Kept here only so the key resolves until its last call site goes.
- EN: ~~Juli is collecting your shop data; first recommendations within 24h.~~
- VI: ~~Juli đang thu thập dữ liệu shop của bạn. Đề xuất đầu tiên sẽ xuất hiện trong vòng 24 giờ.~~

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

**`run.awaiting_you`**
- EN: Waiting for you
- VI: Đang chờ bạn
- Definition: Run ledger section heading (PUI-DESIGN.md §4) for `waiting_approval` runs, pinned to the top.

**`run.status.running`**
- EN: Running
- VI: Đang chạy
- Definition: Run ledger section heading and status chip for `queued`/`running` runs.

**`run.status.queued`**
- EN: Queued
- VI: Trong hàng đợi
- Definition: Status chip for a `queued` run with zero events yet — visible because the ledger reads the polled list, not the event stream.

**`run.section.finished`**
- EN: Finished
- VI: Hoàn tất
- Definition: Run ledger section heading for the four terminal `status` values, labelled per their honest `stop_reason`.

**`run.workflow.optimize_product`**
- EN: Optimize product
- VI: Tối ưu sản phẩm
- _Avoid_: optimize_product (the internal `workflow_key`), Tối ưu hóa, Chạy quy trình
- Definition: The run page header's workflow title (PUI-DESIGN.md §2 header row, issue #1910) — the seller-facing name of the workflow the run is executing, shown above the stepper. Runtime constant `RUN_WORKFLOW_TITLE` in `apps/demo/src/lib/run-surface/stage-copy.ts`; keep them byte-identical.

**`run.back_to_actions`**
- EN: Actions
- VI: Hành động
- _Avoid_: Quay lại, Trở về
- Definition: The run page header's back control (issue #1910, owner amendment 2026-09-14), returning you to the Hành động tab. Reads the destination tab's owner-decided name — the control tells you where you land, never a bare "back" and never a raw route path like /decisions. Runtime constant `RUN_HEADER_BACK_LABEL` in `apps/demo/src/lib/run-surface/stage-copy.ts`; keep them byte-identical.

**`run.expiry`**
- EN: Offer valid for {time}
- VI: Đề xuất còn hiệu lực {time}
- Definition: Expiry countdown on a `waiting_approval` run's card, driven by the server-carried `decision_summary.expires_at`.

**`run.declined_note`**
- EN: You chose not to change the price
- VI: Bạn đã chọn không thay đổi giá
- Definition: `completed_after_decline` terminal-state explanation (`stop_reason=confirmation_declined`) — a choice, not a failure.

**`run.worker_lost`**
- EN: Juli hit a problem while executing
- VI: Juli gặp sự cố khi thực hiện
- Definition: `worker_lost` terminal-state label/explanation (`stop_reason=worker_lost`) — named honestly, never dressed as another outcome.

**`run.terminal.cancelled`**
- EN: Cancelled
- VI: Đã hủy
- Definition: `cancelled` terminal-state label (`stop_reason=cancelled_by_seller`).

**`run.terminal.expired`**
- EN: Expired
- VI: Đã hết hạn
- Definition: `expired` terminal-state label (`stop_reason=confirmation_expired`) — distinct from `cancelled`, even though both map to `WorkflowRunStatus.CANCELLED` server-side.

**`run.terminal.timed_out`**
- EN: Timed out
- VI: Quá thời gian
- Definition: `timed_out` terminal-state label (`stop_reason` ∈ `wall_clock_timeout`, `iteration_cap_exceeded`).

**`run.terminal.failed`**
- EN: Failed
- VI: Thất bại
- Definition: `failed` terminal-state label for the remaining failure-class `stop_reason` values, with a seller-terms explanation, never a raw internal reason.

**`run.no_retry`**
- EN: Want to make a new change? Go back to Decisions to approve a new recommendation.
- VI: Muốn thực hiện thay đổi mới? Hãy quay lại Quyết định để phê duyệt đề xuất mới.
- Definition: Explanation on every failed/cancelled/expired/timed-out/worker_lost run's card — no retry-in-place control exists; a new run needs a new approval.

**`run.reconnecting`**
- EN: Reconnecting
- VI: Đang kết nối lại
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §8) inline status when the event stream drops mid-run — a stream error, never a run error; the run keeps executing server-side while this shows.

**`run.stage.back`**
- EN: Review
- VI: Xem lại
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2 footer) back-navigation control — steps to the previous frozen stage.

**`run.stage.continue`**
- EN: Continue
- VI: Tiếp
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2 footer) forward control — returns to the live edge in one action from any frozen stage.

**`run.stage.status.frozen`**
- EN: Completed
- VI: Đã hoàn tất
- Definition: Staged run view stepper node accessible status for a past, revisitable stage (issue #1316).

**`run.stage.status.active`**
- EN: In progress
- VI: Đang diễn ra
- Definition: Staged run view stepper node accessible status for the live-edge stage (issue #1316).

**`run.stage.status.locked`**
- EN: Not yet unlocked
- VI: Chưa mở khoá
- Definition: Staged run view stepper node accessible status for a stage beyond the live edge — unreachable by click, keyboard, or URL (issue #1316).

**`run.product_binding.label`**
- EN: Product being processed
- VI: Sản phẩm đang xử lý
- Definition: Label preceding the bound product's name on the staged run view (issue #1316) — visible from the first stage, well before the Đề xuất confirmation (ADR-082 decision 5's disclosure).

**`run.tool_action.get_product_information`**
- EN: Viewing product information
- VI: Xem thông tin sản phẩm
- Definition: Staged run view (issue #1316) seller-facing label for the `get_product_information` tool call — never the raw tool name, which `SELLER_COPY_BANNED_PATTERNS` forbids.

**`run.tool_action.get_seo_keywords`**
- EN: Finding SEO keywords
- VI: Tìm từ khoá SEO
- Definition: Staged run view (issue #1316) seller-facing label for the `get_seo_keywords` tool call.

**`run.tool_action.update_product_listing`**
- EN: Updating product information
- VI: Cập nhật thông tin sản phẩm
- Definition: Staged run view (issue #1316) seller-facing label for the `update_product_listing` tool call.

**`run.tool_action.upload_staged_image`**
- EN: Uploading product image
- VI: Tải ảnh sản phẩm
- Definition: Staged run view (issue #1316) seller-facing label for the `upload_staged_image` tool call.

**`run.tool_action.fallback`**
- EN: Processing
- VI: Đang xử lý
- Definition: Staged run view (issue #1316) fallback label for an unrecognized tool call — honest and generic, never the raw tool name.

**`run.confirm_option`**
- EN: Confirm this option
- VI: Xác nhận phương án này
- Definition: The Đề xuất option picker's armed CTA (issue #1317, PUI-DESIGN.md §3/§7) -- disabled until an option is selected, so no single click authorizes a mutation.

**`run.decline_option`**
- EN: Don't apply
- VI: Không thực hiện
- Definition: The Đề xuất option picker's decline control (issue #1317, PUI-DESIGN.md §3/§7) -- always reachable, never gated behind selecting an option or hidden behind the confirm CTA. A choice, not a failure exit.

**`run.option_picker.heading`**
- EN: Juli proposes {count} option(s):
- VI: Juli đề xuất {count} phương án:
- Definition: Heading above the Đề xuất option cards (issue #1317, PUI-DESIGN.md §3), generic across the N=1 (binary confirm) and N=3 cases -- `{count}` is `options.length`, never a literal.

**`run.decline_outcome`**
- EN: Juli finishes without changing anything, and the analysis is kept.
- VI: Juli sẽ hoàn tất mà không thay đổi gì, và phần phân tích được giữ lại.
- Definition: Renders immediately once a decline decision is accepted (issue #1317, PUI-DESIGN.md §3) -- states the real outcome. A choice, never an error state.

**`run.option_picker.expired`**
- EN: This offer has expired.
- VI: Đề xuất đã hết hiệu lực.
- Definition: Đề xuất option picker (issue #1317) -- shown once the server-carried `expires_at` has passed; input is disabled from this point, driven by the server's own deadline, never a client timer.

**`run.confirmation_rejected.already_decided`**
- EN: This offer has already been decided.
- VI: Đề xuất này đã được quyết định trước đó.
- Definition: `confirmation_already_decided` rejection (issue #1317) -- a distinct, honest condition, never a generic failure message.

**`run.confirmation_rejected.not_awaiting`**
- EN: This run is no longer awaiting a confirmation.
- VI: Luồng thực hiện này không còn chờ xác nhận.
- Definition: `run_not_awaiting_confirmation` rejection (issue #1317).

**`run.confirmation_rejected.fingerprint_mismatch`**
- EN: This offer changed since you last saw it; go back to Decisions to see the latest.
- VI: Đề xuất đã thay đổi kể từ khi bạn xem; hãy quay lại Quyết định để xem đề xuất mới nhất.
- Definition: `params_sha_mismatch` rejection (issue #1317) -- the change the seller saw is not the change that would run; refused rather than silently substituted.

**`run.confirmation_rejected.generic`**
- EN: This option could not be confirmed.
- VI: Không thể xác nhận lựa chọn này.
- Definition: Fallback for a rejected-confirmation `error_code` this surface has no dedicated copy for yet (issue #1317) -- still names the fact honestly, never a spinner-forever or silent retry.

**`run.option_field.price`**
- EN: Price
- VI: Giá
- Definition: Seller-facing label for a `proposed_change.price` field on an option card's diff (issue #1317) -- never the raw JSON key.

**`run.option_field.title`**
- EN: Title
- VI: Tiêu đề
- Definition: Seller-facing label for a `proposed_change.title` field on an option card's diff (issue #1317).

**`run.option_field.fallback`**
- EN: Proposed change
- VI: Thay đổi được đề xuất
- _Avoid_: raw proposed_change JSON keys
- Definition: Generic seller-facing label for a `proposed_change` key that `run.option_field.*` has no dedicated entry for yet (issue #1908, W6-FIX). Replaces `describeOptionField`'s previous raw-key fallback (`apps/demo/src/lib/run-surface/option-diff.ts`) — an English snake_case identifier such as `attach_staged_image` reached a Vietnamese seller on both the Đề xuất option cards and the Cập nhật proposed-change list. Same precedent as `run.tool_action.fallback`: generic and still honest, never the internal identifier.

**`run.option_picker.submitting`**
- EN: Sending your choice…
- VI: Đang gửi lựa chọn của bạn…
- Definition: Transient status while the confirmation POST is in flight (issue #1317) -- cards and both CTAs disable to prevent a double submission.

**`run.option_picker.rationale_fallback`**
- EN: Juli proposes this change for your product.
- VI: Juli đề xuất thay đổi này cho sản phẩm của bạn.
- _Avoid_: rendering an English rationale verbatim
- Definition: Rendered in place of an option's payload `rationale` when the option picker's guard rejects it (issue #1908, W6-FIX) — a rationale carrying a snake_case identifier or carrying no Vietnamese diacritic is a leaked internal string, not seller Vietnamese. Defence in depth at the last surface before a seller reads the text, deliberately independent of the source-side `ToolSpec.seller_rationale_vi` fix (#1904). Claims only that Juli proposes the change — never a reason the UI cannot know.

**`run.running_body_fallback`**
- EN: Juli is working on this product.
- VI: Juli đang xử lý sản phẩm này.
- Definition: Run ledger (issue #1318) "Đang chạy" card body before the first narration line arrives; reused verbatim (never re-authored) as the staged run view's (issue #1316) Phân tích stage fallback (`lib/run-surface/stage-copy.ts`'s `RUN_STAGE_ANALYZING_FALLBACK`) -- one string, one meaning, on both surfaces. Landed by issue #1321: referenced by a code comment on both surfaces since #1316/#1318 but missing from this file until now.

**`run.stage.name.phan_tich`**
- EN: Analysis
- VI: Phân tích
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2) stage 1 stepper/heading label. Landed by issue #1321.

**`run.stage.name.thong_tin_san_pham`**
- EN: Product info
- VI: Thông tin sản phẩm
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2) stage 2 stepper/heading label. Landed by issue #1321.

**`run.stage.name.seo`**
- EN: SEO
- VI: SEO
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2) stage 3 stepper/heading label. Landed by issue #1321.

**`run.stage.name.de_xuat`**
- EN: Proposal
- VI: Đề xuất
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2) stage 4 stepper/heading label -- reuses `decisions.recommendation`'s VI verbatim, per PUI-DESIGN.md §7's own footnote ("existing terms ... are reused, never renamed"). Landed by issue #1321.

**`run.stage.name.cap_nhat`**
- EN: Update
- VI: Cập nhật
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2) stage 5 stepper/heading label. Landed by issue #1321.

**`run.stage.name.hoan_tat`**
- EN: Complete
- VI: Hoàn tất
- Definition: Staged run view (issue #1316, PUI-DESIGN.md §2) stage 6 stepper/heading label -- reuses `run.section.finished`'s VI verbatim. Landed by issue #1321.

**`run.stage.empty.thong_tin_san_pham`**
- EN: No product info yet.
- VI: Chưa có thông tin sản phẩm.
- Definition: Staged run view (issue #1316) empty-state copy for stage 2 before its tool activity has produced anything. Landed by issue #1321.

**`run.stage.empty.seo`**
- EN: No SEO keyword step in this run.
- VI: Không có bước phân tích từ khoá SEO trong luồng này.
- Definition: Staged run view (issue #1316) empty-state copy for stage 3. Landed by issue #1321.

**`run.stage.empty.de_xuat`**
- EN: No proposal waiting yet.
- VI: Chưa có đề xuất nào đang chờ.
- Definition: Staged run view (issue #1316) empty-state copy for stage 4 before a `workflow.approval_required` event has arrived. Landed by issue #1321.

**`run.stage.empty.cap_nhat`**
- EN: No changes made yet.
- VI: Chưa có thay đổi nào được thực hiện.
- Definition: Staged run view (issue #1316) empty-state copy for stage 5. Landed by issue #1321.

**`run.stage.empty.hoan_tat`**
- EN: Waiting for the final result.
- VI: Đang chờ kết quả cuối cùng.
- Definition: Staged run view (issue #1316) empty-state copy for stage 6 before a terminal event has arrived. Landed by issue #1321.

**`run.terminal.completed.body`**
- EN: Juli finished and applied the approved change.
- VI: Juli đã hoàn tất và áp dụng thay đổi được phê duyệt.
- Definition: `completed` terminal-state explanation (run ledger #1318 and the staged run view's Hoàn tất stage, #1316 -- one shared table, `lib/run-ledger/copy.ts`'s `RUN_TERMINAL_STATE_COPY`). Landed by issue #1321.

**`run.terminal.cancelled.body`**
- EN: You cancelled this run before it finished.
- VI: Bạn đã hủy luồng này trước khi hoàn tất.
- Definition: `cancelled` terminal-state explanation, same shared table as above. Landed by issue #1321.

**`run.terminal.expired.body`**
- EN: The offer expired before you confirmed.
- VI: Đề xuất đã hết hạn trước khi bạn xác nhận.
- Definition: `expired` terminal-state explanation, same shared table as above. Landed by issue #1321.

**`run.terminal.timed_out.body`**
- EN: The run took too long and Juli stopped.
- VI: Luồng mất quá nhiều thời gian và Juli đã dừng lại.
- Definition: `timed_out` terminal-state explanation, same shared table as above. Landed by issue #1321.

**`run.terminal.failed.body`**
- EN: Something went wrong while Juli was executing; see Decisions for details.
- VI: Đã xảy ra lỗi khi Juli thực hiện; hãy xem lại tại Quyết định.
- Definition: `failed` terminal-state explanation, same shared table as above. Landed by issue #1321.

**`run.terminal.completed_after_decline.label`**
- EN: Complete — unchanged
- VI: Hoàn tất — không đổi
- Definition: `completed_after_decline` terminal-state chip label (same shared table as above) — distinct from the plain `completed` label so a declined-but-finished run is never dressed as a plain success. Landed by issue #1321.

**`run.terminal.worker_lost.label`**
- EN: Issue
- VI: Sự cố
- Definition: `worker_lost` terminal-state chip label (same shared table as above) — distinct, honest label alongside its already-dictionaried body (`run.worker_lost`). Landed by issue #1321.

**`run.terminal.unknown`**
- EN: Ended
- VI: Đã kết thúc
- Definition: Fallback label for a terminal `stop_reason` this table has no dedicated bucket for yet -- honest ("ended"), never one of the seven named outcomes it is not. Body: "Luồng đã kết thúc. Vui lòng xem lại tại Quyết định." ("The run has ended. Please review it in Decisions."). Landed by issue #1321.

**`run.option_rationale.get_product_information`**
- EN: View this product's current listing details.
- VI: Xem thông tin hiện tại của sản phẩm này.
- _Avoid_: Get Product Information, Lấy thông tin sản phẩm
- Definition: `ToolSpec.seller_rationale_vi` for the `get_product_information` tool (issue #1904, W6-FIX) -- the Đề xuất option picker's per-option rationale, distinct from the tool's English, model-facing `description`.

**`run.option_rationale.get_seo_keywords`**
- EN: Look up suggested SEO keywords for this product.
- VI: Tra cứu từ khoá SEO gợi ý cho sản phẩm này.
- _Avoid_: Get SEO Keywords, Lấy từ khoá SEO
- Definition: `ToolSpec.seller_rationale_vi` for the `get_seo_keywords` tool (issue #1904, W6-FIX).

**`run.option_rationale.check_product_status`**
- EN: Check this product's current status.
- VI: Kiểm tra trạng thái hiện tại của sản phẩm này.
- _Avoid_: Check Product Status
- Definition: `ToolSpec.seller_rationale_vi` for the `check_product_status` tool (issue #1904, W6-FIX).

**`run.option_rationale.inspect_product_image`**
- EN: Check whether this product's photo matches its listing copy.
- VI: Kiểm tra xem ảnh sản phẩm có khớp với nội dung mô tả không.
- _Avoid_: Inspect Product Image
- Definition: `ToolSpec.seller_rationale_vi` for the `inspect_product_image` tool (issue #1904, W6-FIX).

**`run.option_rationale.upload_product_image`**
- EN: Upload the staged image for this product; it is not applied yet.
- VI: Tải ảnh đã chuẩn bị lên cho sản phẩm này; ảnh chưa được áp dụng.
- _Avoid_: Upload Product Image
- Definition: `ToolSpec.seller_rationale_vi` for the `upload_product_image` tool (issue #1904, W6-FIX).

**`run.option_rationale.update_product_listing`**
- EN: Apply Juli's proposed title and description to this product's listing.
- VI: Áp dụng tiêu đề và mô tả Juli đã soạn cho sản phẩm này.
- _Avoid_: Update Product Listing, Apply agent-authored title/description
- Definition: `ToolSpec.seller_rationale_vi` for the `update_product_listing` tool (issue #1904, W6-FIX) -- the exact string that replaced the English `description` a seller was previously shown verbatim on the Đề xuất option picker (confirmed live in `run_confirmations` row for run `4e00d60e`).

**`run.option_rationale.update_product_price`**
- EN: Apply Juli's proposed new price to this product.
- VI: Áp dụng mức giá mới Juli đề xuất cho sản phẩm này.
- _Avoid_: Update Product Price
- Definition: `ToolSpec.seller_rationale_vi` for the `update_product_price` tool (issue #1904, W6-FIX).

**`run.option_rationale.conclude_without_changes`**
- EN: End this run without making any changes.
- VI: Kết thúc phiên xử lý này mà không thay đổi gì.
- _Avoid_: Conclude Without Changes
- Definition: `ToolSpec.seller_rationale_vi` for the `conclude_without_changes` terminal tool (issue #1904, W6-FIX) -- this tool is READ/AUTO and never reaches the option picker today, but every registered `ToolSpec` carries one so a future policy change cannot re-open the English-leak defect by omission.

**`agent.narration.extension_grant`**
- EN: Continuing past the standard iteration limit: granting [extension_iterations] more iteration(s) (extension [granted] of [max]).
- VI: Đã đạt giới hạn số lượt thực hiện tiêu chuẩn, Juli gia hạn thêm [extension_iterations] lượt để hoàn tất công việc (lần gia hạn [granted]/[max]).
- Status: reviewed — mechanical gates (banned-pattern gate, dynamic-number tests) green, and the repo owner approved the Vietnamese register and tone on 2026-08-21, supplying the human voice review ADR-072/​#1071 requires for seller-facing copy. The reviewed wording renders "extension K of M" as the fraction `K/M` rather than translating the preposition, and carries no plural inflection because Vietnamese has none.
- Definition: `workflow.status` `phase_narration` (ADR-074 d.2) for one iteration-cap extension grant (`services/agent/narration_copy.py::extension_grant_phase_narration`, issue #1140). The one narration the agent runner produces today; every bracketed number is sourced from `TerminationPolicy`, never a literal.

**`decisions.signed_in.acting_shop`**
- EN: You are acting on: [shop name]
- VI: Bạn đang thao tác trên: [tên shop]
- Definition: The signed-in Decisions surface's shop-identity line (issue #1909, #1319's surviving criterion) — reuses the connect-shop screen's exact phrasing so a seller with more than one shop can always tell which shop the `X-Shop-Id` on every request belongs to.

**`decisions.signed_in.no_shop`**
- EN: You have not chosen the shop you are acting on. Open Connect TikTok Shop to choose one.
- VI: Bạn chưa chọn shop đang thao tác. Mở Kết nối TikTok Shop để chọn shop.
- Definition: Signed-in Decisions state when a session exists but no acting shop is stored (issue #1909) — honest recovery pointing back at `auth.connect_shop`, never a silent default onto a shop the seller did not pick.

**`error.decisions.load_failed`**
- EN: Could not load recommendations for your shop. Please try again.
- VI: Không thể tải đề xuất cho shop của bạn. Vui lòng thử lại.
- _Avoid_: falling back to sample recommendations (a dead backend must never look healthy — #1320)
- Definition: Signed-in Decisions read failure (issue #1909) — rendered with a retry control; the anonymous branch's sample content is never substituted.

**`decisions.approve.confirm_title`**
- EN: Approve this recommendation?
- VI: Phê duyệt đề xuất này?
- Definition: Title of the signed-in approve consent dialog (issue #1909, two-step consent per #1317's pattern).

**`decisions.approve.confirm_body`**
- EN: Juli will start a real run on your shop. You can still review and confirm every change before it is applied.
- VI: Juli sẽ bắt đầu một luồng thực hiện thật trên shop của bạn. Bạn vẫn xem và xác nhận từng thay đổi trước khi áp dụng.
- Definition: Body of the signed-in approve consent dialog (issue #1909) — states honestly that this creates a real run (approve-is-run-creation, ADR-075 decision 1) while naming the surviving human-in-the-loop control.

**`error.approve.session_expired`**
- EN: Your sign-in session is no longer valid. Please sign in with Google again, then approve.
- VI: Phiên đăng nhập của bạn không còn hiệu lực. Vui lòng đăng nhập với Google lại, rồi phê duyệt.
- Definition: Signed-in approve 401 (issue #1909) — the token was rejected; recovery is a fresh sign-in, never a retry loop and never fixture content.

**`error.approve.not_found`**
- EN: This recommendation no longer exists or does not belong to the shop you are acting on.
- VI: Đề xuất này không còn tồn tại hoặc không thuộc shop bạn đang thao tác.
- Definition: Signed-in approve 404 (issue #1909) — the server never distinguishes unknown from cross-tenant (no existence oracle), so neither does this copy.

**`error.approve.conflict`**
- EN: This recommendation was already handled, or another run is in progress for this product. Check the In Progress tab.
- VI: Đề xuất này đã được xử lý, hoặc sản phẩm đang có luồng khác chạy. Hãy kiểm tra tab Đang thực hiện.
- Definition: Signed-in approve 409 (issue #1909) — covers a double-approve, a card already flipped, or a concurrent active run for the derived product; recovery points at the run ledger.

**`error.approve.generic`**
- EN: Could not approve this recommendation right now (error [status]). Please try again.
- VI: Chưa thể phê duyệt đề xuất này lúc này (lỗi [status]). Vui lòng thử lại.
- Definition: Signed-in approve fallback for any other non-2xx (issue #1909) — names the fact and the raw status honestly; never a spinner-forever, never a fabricated run id.
