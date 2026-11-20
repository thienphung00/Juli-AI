/**
 * One synthetic event stream per design board (canvas v17). Names and numbers are invented; the
 * mock client replays these until the backend is wired, and the tests render every board from them.
 */
import type { JuliAgentEvent, JuliCardVersion, JuliEventMap, JuliTemplate } from "@juli/contracts";

type Ev = { [K in keyof JuliEventMap]: { type: K; data: JuliEventMap[K] } }[keyof JuliEventMap];
const e = <K extends keyof JuliEventMap>(type: K, data: JuliEventMap[K]): JuliAgentEvent => ({ type, data }) as Ev;

export const TEMPLATES: readonly JuliTemplate[] = [
  { key: "improve_gmv", label_vi: "Cải thiện GMV" },
  { key: "improve_margin", label_vi: "Cải thiện biên lợi nhuận" },
  { key: "improve_conversion", label_vi: "Cải thiện tỷ lệ chuyển đổi" },
  { key: "reduce_cost", label_vi: "Giảm chi phí" },
  { key: "increase_visibility", label_vi: "Tăng lượt hiển thị" },
];

const RESTATED_CONVERSION =
  "Đang tìm hiểu: vì sao tỷ lệ chuyển đổi (CTOR) 7 ngày qua thay đổi so với 7 ngày trước và nên làm gì?";

/** Board 2: mid-run, streamed text not finished. */
export const RUNNING: readonly JuliAgentEvent[] = [
  e("status", { key: "thinking", text_vi: "Đang tìm hiểu" }),
  e("restated", { text_vi: RESTATED_CONVERSION }),
  e("status", { key: "checking_data", text_vi: "Đang kiểm tra dữ liệu" }),
  e("status", { key: "comparing", text_vi: "Đang so sánh 12/11–18/11 với 05/11–11/11" }),
  e("status", { key: "finding_cause", text_vi: "Đang tìm nguyên nhân" }),
  e("text_delta", { text: "CTOR giảm từ 7,94% xuống 4,78%. Phần lớn mức giảm nằm ở " }),
  e("text_delta", { text: "Thẻ sản phẩm." }),
];

const VERSIONS: readonly JuliCardVersion[] = [
  {
    label_vi: "11.000đ từ 220.000đ",
    inputs: {},
    recommended: false,
    estimable: true,
    gmv_p50: 15833,
    profit_p50: -29032,
    days: 14,
    cost_total: 33851,
    cost_text_vi: "33.851đ · hoà vốn ≥ 2 đơn",
    margin_before_pct: 16.1,
    margin_after_pct: 14.9,
  },
  {
    label_vi: "8.000đ từ 150.000đ",
    inputs: {},
    recommended: true,
    estimable: true,
    gmv_p50: 111104,
    profit_p50: -665,
    days: 14,
    cost_total: 32000,
    cost_text_vi: "32.000đ · hoà vốn ≥ 2 đơn",
    margin_before_pct: 16.1,
    margin_after_pct: 15.5,
  },
  {
    label_vi: "14.000đ từ 290.000đ",
    inputs: {},
    recommended: false,
    estimable: true,
    gmv_p50: 84766,
    profit_p50: 24016,
    days: 14,
    cost_total: 45423,
    cost_text_vi: "45.423đ · hoà vốn ≥ 2 đơn",
    margin_before_pct: 16.1,
    margin_after_pct: 16.4,
  },
  {
    label_vi: "18.000đ từ 350.000đ",
    inputs: {},
    recommended: false,
    estimable: false,
    gmv_p50: null,
    profit_p50: null,
    days: 14,
    cost_total: null,
    cost_text_vi: "",
    margin_before_pct: null,
    margin_after_pct: null,
  },
];

/** Board 3: explanation + path + card. */
export const EXPLANATION_CARD: readonly JuliAgentEvent[] = [
  e("status", { key: "thinking", text_vi: "Đang tìm hiểu" }),
  e("restated", { text_vi: RESTATED_CONVERSION }),
  e("status", { key: "checking_data", text_vi: "Đang kiểm tra dữ liệu" }),
  e("status", { key: "finding_cause", text_vi: "Đang tìm nguyên nhân" }),
  e("text_delta", { text: "CTOR 12/11–18/11 giảm từ 7,94% xuống 4,78%. " }),
  e("text_delta", { text: "Gần như toàn bộ mức giảm nằm ở Thẻ sản phẩm." }),
  e("path", {
    steps: [
      {
        label_vi: "CTOR shop",
        value_vi: "4,78%",
        delta: { dir: "down", text_vi: "▼ 39,8%" },
        link: { kind: "metric", metric: "ctor", from: "2026-11-12", to: "2026-11-18" },
      },
      {
        label_vi: "Thẻ sản phẩm",
        value_vi: "98%",
        delta: null,
        link: { kind: "channel", metric: "ctor", channel: "product_card", from: "2026-11-12", to: "2026-11-18" },
      },
      {
        label_vi: "Sản phẩm mẫu A",
        value_vi: "",
        delta: null,
        link: { kind: "product", item_id: "1001" },
      },
    ],
  }),
  e("status", { key: "preparing_card", text_vi: "Đang chuẩn bị đề xuất" }),
  e("card", {
    draft_ref: "draft-1",
    kind: "voucher_min_spend",
    kind_vi: "Voucher đơn tối thiểu",
    item_id: "1001",
    item_name: "Sản phẩm mẫu A",
    title_vi: "Voucher đơn tối thiểu · Sản phẩm mẫu A",
    versions: VERSIONS,
    recommendation_vi: "Juli gợi ý 8.000đ từ 150.000đ: GMV tăng nhiều nhất, lợi nhuận gần như giữ nguyên.",
  }),
  e("done", { stop_reasons: ["explained"] }),
];

/** The same answer where the alignment check rewrote the streamed text (text_replace). */
export const EXPLANATION_REPLACED: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: RESTATED_CONVERSION }),
  e("text_delta", { text: "Đoạn nháp sẽ bị thay." }),
  e("text_replace", { text: "CTOR giảm từ 7,94% xuống 4,78%, chủ yếu ở Thẻ sản phẩm." }),
  e("done", { stop_reasons: ["explained"] }),
];

/** Board 4: a sent card is shown from the saved message; this is the answer before sending (no-card case). */
export const NO_CARD_EXISTING: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: vì sao biên lợi nhuận 7 ngày qua thay đổi so với 7 ngày trước và nên làm gì?" }),
  e("text_delta", { text: "Biên lợi nhuận giảm từ 17,3% xuống 16,5%. Phần lớn đến từ Sản phẩm mẫu A, nơi giá bán vừa đổi." }),
  e("no_card", { reason_vi: "Đã có thẻ JC-2611-0031 đang làm việc này", existing_card_code: "JC-2611-0031" }),
  e("done", { stop_reasons: ["explained"] }),
];

export const NO_CARD_PLAIN: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: chi phí 7 ngày qua thay đổi thế nào so với 7 ngày trước và nên giảm ở đâu?" }),
  e("text_delta", { text: "Tổng chi phí là 26,1% doanh thu thực, gần như không đổi." }),
  e("no_card", { reason_vi: "Chưa có đề xuất: Juli chưa tìm được mức phù hợp." }),
  e("done", { stop_reasons: ["explained"] }),
];

/** Board 5: data answers. */
export const DATA_METRIC: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: tổng số đơn tháng này so với cùng kỳ tháng trước." }),
  e("data_answer", {
    kind: "metric_total",
    title_vi: "Số đơn",
    value: "47 đơn",
    delta: { dir: "down", text_vi: "▼ 43,4%" },
    window_vi: "01/11–18/11 so với 01/10–18/10 (83 đơn)",
    fresh_vi: "Số liệu đến hết 18/11",
  }),
  e("done", { stop_reasons: [] }),
];

export const DATA_TOP: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: các sản phẩm có GMV cao nhất 12/11–18/11." }),
  e("data_answer", {
    kind: "top_products",
    title_vi: "Top sản phẩm",
    window_vi: "12/11–18/11",
    rows: [
      { label_vi: "Sản phẩm mẫu A", value_vi: "1.147.888đ · 9 đơn", link: { kind: "product", item_id: "1001" } },
      { label_vi: "Sản phẩm mẫu B", value_vi: "758.160đ · 3 đơn", link: { kind: "product", item_id: "1002" } },
      { label_vi: "Sản phẩm mẫu C", value_vi: "170.538đ · 2 đơn", link: { kind: "product", item_id: "1003" } },
    ],
    fresh_vi: "Số liệu đến hết 18/11",
  }),
  e("done", { stop_reasons: [] }),
];

export const DATA_DAILY: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: GMV theo ngày 12/11–18/11." }),
  e("data_answer", {
    kind: "daily_trend",
    title_vi: "GMV theo ngày",
    window_vi: "12/11–18/11",
    series: [
      { label_vi: "12/11", value: 471744, value_vi: "471.744đ" },
      { label_vi: "13/11", value: 371952, value_vi: "371.952đ" },
      { label_vi: "14/11", value: 0, value_vi: "0đ", missing: true },
      { label_vi: "15/11", value: 662256, value_vi: "662.256đ" },
      { label_vi: "16/11", value: 263088, value_vi: "263.088đ" },
      { label_vi: "17/11", value: 907200, value_vi: "907.200đ" },
      { label_vi: "18/11", value: 0, value_vi: "0đ", missing: true },
    ],
    fresh_vi: "Số liệu đến hết 18/11",
  }),
  e("done", { stop_reasons: [] }),
];

export const DATA_CHANNEL: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: CTR của từng kênh 20/10–18/11." }),
  e("data_answer", {
    kind: "channel_breakdown",
    title_vi: "CTR theo kênh",
    window_vi: "20/10–18/11",
    rows: [
      { label_vi: "Trang shop", value_vi: "3,93%", missing: true, link: { kind: "channel", metric: "ctr", channel: "shop_page" } },
      { label_vi: "Video", value_vi: "0,00%", link: { kind: "channel", metric: "ctr", channel: "video" } },
      { label_vi: "Dịch vụ hiển thị Sản phẩm", value_vi: "2,96%", link: { kind: "ads" } },
    ],
    fresh_vi: "Số liệu đến hết 18/11",
  }),
  e("done", { stop_reasons: [] }),
];

/** Board 6: stop labels. */
export const LABEL_NOISE: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: vì sao CTR tháng này thay đổi so với tháng trước?" }),
  e("label", { stop_reason: "within_noise", text_vi: "Không phát hiện gì bất thường", detail_vi: "Mức thường thấy: 2,46%–3,82%" }),
  e("text_delta", { text: "CTR 01/11–18/11 là 3,07%, so với 3,11% cùng kỳ tháng trước." }),
  e("done", { stop_reasons: ["within_noise"] }),
];
export const LABEL_UNEXPLAINED: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: vì sao hôm qua không có đơn?" }),
  e("label", {
    stop_reason: "unexplained",
    text_vi: "Chưa rõ nguyên nhân",
    detail_vi: "Trong kỳ: chi quảng cáo thấp bất thường 18/11\nTrong kỳ: 2 sản phẩm sắp hết hàng",
  }),
  e("text_delta", { text: "18/11 có 0 đơn, 606 lượt xem và 25 lượt bấm. Không có phần nào giải thích rõ." }),
  e("done", { stop_reasons: ["unexplained"] }),
];
export const LABEL_STALE: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: đơn hôm nay thế nào?" }),
  e("label", { stop_reason: "data_stale", text_vi: "Dữ liệu đến 18/11" }),
  e("text_delta", { text: "Dữ liệu hôm nay chưa đủ. Hỏi lại sau khi đồng bộ sáng mai." }),
  e("done", { stop_reasons: ["data_stale"] }),
];
export const LABEL_MISSING: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: vì sao Sản phẩm mẫu B tháng này bán ít hơn tháng trước?" }),
  e("label", { stop_reason: "data_missing", text_vi: "Thiếu dữ liệu" }),
  e("text_delta", { text: "Chưa có số liệu của sản phẩm này cho 01/10–18/10 để so sánh." }),
  e("done", { stop_reasons: ["data_missing"] }),
];

/** Board 6: multi-intent with "Xem tiếp". */
export const MULTI_INTENT: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: bốn chỉ số 12/11–18/11 so với 05/11–11/11. Juli trả lời 3 chỉ số đầu." }),
  e("intent_block", { index: 1, total: 3, title_vi: "GMV" }),
  e("text_delta", { text: "Giảm chủ yếu ở hai sản phẩm Deal 15.11." }),
  e("path", {
    steps: [
      { label_vi: "GMV shop", value_vi: "", delta: { dir: "down", text_vi: "▼ 45,7%" }, link: { kind: "metric", metric: "gmv" } },
      { label_vi: "Thẻ sản phẩm", value_vi: "", delta: null, link: { kind: "channel", metric: "gmv", channel: "product_card" } },
    ],
  }),
  e("intent_block", { index: 2, total: 3, title_vi: "Đơn hàng" }),
  e("text_delta", { text: "Lượt xem gần như giữ nguyên, tỷ lệ đặt hàng sau khi bấm giảm." }),
  e("intent_block", { index: 3, total: 3, title_vi: "CTR" }),
  e("label", { stop_reason: "within_noise", text_vi: "Không phát hiện gì bất thường" }),
  e("more", { items: [{ label_vi: "Xem tiếp: CTOR", text: "CTOR tuần này so với tuần trước" }] }),
  e("done", { stop_reasons: ["explained", "explained", "within_noise"] }),
];

/** Board 7: needs_choice (metric / window / product), unsupported, other platform. */
export const CHOICE_METRIC: readonly JuliAgentEvent[] = [
  e("needs_choice", {
    item: "metric",
    question_vi: "Bạn muốn xem chỉ số nào?",
    options: [
      { label_vi: "Doanh thu", value: "gmv" },
      { label_vi: "Đơn hàng", value: "orders" },
      { label_vi: "CTR", value: "ctr" },
      { label_vi: "Tỷ lệ chuyển đổi", value: "ctor" },
      { label_vi: "Lợi nhuận", value: "profit" },
      { label_vi: "Chi phí", value: "cost" },
    ],
    pending: { step: 1 },
  }),
  e("done", { stop_reasons: [] }),
];
export const CHOICE_WINDOW: readonly JuliAgentEvent[] = [
  e("needs_choice", {
    item: "window",
    question_vi: "Bạn muốn so sánh kỳ nào?",
    options: [
      { label_vi: "01/11–18/11 so với 01/10–18/10", value: "mtd_vs_prev_mtd" },
      { label_vi: "01/11–18/11 so với cả tháng 10", value: "mtd_vs_prev_month" },
    ],
    pending: { step: 2 },
  }),
  e("done", { stop_reasons: [] }),
];
export const CHOICE_PRODUCT: readonly JuliAgentEvent[] = [
  e("needs_choice", {
    item: "product",
    question_vi: "Bạn muốn xem sản phẩm nào?",
    options: [
      { label_vi: "Sản phẩm mẫu A · size L/M", value: "1001" },
      { label_vi: "Sản phẩm mẫu B", value: "1002" },
      { label_vi: "Sản phẩm mẫu C", value: "1003" },
    ],
    pending: { step: 3 },
  }),
  e("done", { stop_reasons: [] }),
];
export const UNSUPPORTED: readonly JuliAgentEvent[] = [
  e("unsupported", {
    text_vi: "Juli chưa hỗ trợ câu hỏi này",
    templates: TEMPLATES.map((t) => t.key),
  }),
  e("done", { stop_reasons: [] }),
];
export const UNSUPPORTED_OTHER_PLATFORM: readonly JuliAgentEvent[] = [
  e("unsupported", {
    text_vi: "Juli chưa hỗ trợ câu hỏi này",
    templates: ["improve_gmv", "improve_conversion"],
    switch_platform: "tiktok",
  }),
  e("done", { stop_reasons: [] }),
];

/** Board 8: system states. */
export const ERROR_FAILED: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: RESTATED_CONVERSION }),
  e("error", { code: "failed" }),
];
export const ERROR_BUSY: readonly JuliAgentEvent[] = [e("error", { code: "busy" })];

/** Board 10: TikTok before W3. */
export const PLATFORM_DATA_MISSING: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: vì sao GMV 7 ngày qua thay đổi so với 7 ngày trước và nên làm gì?" }),
  e("label", { stop_reason: "data_missing", text_vi: "Thiếu dữ liệu" }),
  e("data_answer", {
    kind: "metric_total",
    title_vi: "Báo cáo gần nhất",
    value: "Báo cáo ngày 18/11: GMV 30 ngày 12.345.000đ",
    window_vi: "30 ngày",
    fresh_vi: "Số liệu đến hết 18/11",
  }),
  e("no_card", { reason_vi: "Chưa có đề xuất cho TikTok" }),
  e("done", { stop_reasons: ["data_missing"] }),
];

/** Which fixture answers a free-text or template ask in the mock client. */
export const FIXTURE_BY_KEY: Readonly<Record<string, readonly JuliAgentEvent[]>> = {
  improve_gmv: EXPLANATION_CARD,
  improve_margin: NO_CARD_EXISTING,
  improve_conversion: EXPLANATION_CARD,
  reduce_cost: NO_CARD_PLAIN,
  increase_visibility: LABEL_NOISE,
};
