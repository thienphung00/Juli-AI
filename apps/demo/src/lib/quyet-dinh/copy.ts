/**
 * Vietnamese copy for Quyết định (AC-8.7, ADR-109 d.6, 8–13). Every string
 * here is also in `dictionary.md` (section "Quyết định — P8-F"); keep them
 * byte-identical. No endpoint name, tool name or code ever reaches the
 * screen: tools and rule keys are looked up here, unknown ones get a neutral
 * Vietnamese label.
 */

/** The three sub-tabs (d.13) and their URL slugs. */
export const QD_TABS = [
  { slug: "de-xuat", label: "Đề xuất" },
  { slug: "dang-thuc-hien", label: "Đang thực hiện" },
  { slug: "do-luong", label: "Đo lường" },
] as const;

export type QdTabSlug = (typeof QD_TABS)[number]["slug"];

export function resolveTab(value: string | null | undefined): QdTabSlug {
  return QD_TABS.find((tab) => tab.slug === value)?.slug ?? "de-xuat";
}

/** The five-stage stepper (d.8), inside Quyết định only. */
export const FIVE_STAGES = ["Phân tích", "Đề xuất", "Duyệt", "Thực thi", "Đo lường"] as const;

/** Timeline step label per playbook tool (d.13's mapping table). */
export const TOOL_STEP_LABELS: Readonly<Record<string, string>> = Object.freeze({
  get_product_diagnoses: "Đọc chẩn đoán TikTok",
  get_product_information: "Đọc thông tin sản phẩm",
  get_seo_keywords: "Phân tích từ khoá",
  inspect_product_image: "Phân tích ảnh sản phẩm",
  update_product_listing: "Ghi lên TikTok Shop",
  upload_product_image: "Tải ảnh lên TikTok Shop",
  update_product_price: "Cập nhật giá trên TikTok Shop",
  check_product_status: "TikTok duyệt lại trang sản phẩm",
});

/** A revert run's write restores the before-values (d.9). */
export const REVERT_WRITE_LABEL = "Khôi phục giá trị cũ trên TikTok Shop";
export const UNKNOWN_TOOL_LABEL = "Bước xử lý";
export const CONSENT_STEP_LABEL = "Xác nhận một lần";
export const TERMINAL_STEP_LABEL = "Kết thúc · đặt lịch đo";
export const TERMINAL_STEP_LABEL_NO_MEASURE = "Kết thúc lượt chạy";

/** Proposed-change field → Vietnamese name (consent step one-liner). */
export const FIELD_LABELS: Readonly<Record<string, string>> = Object.freeze({
  title: "Tiêu đề",
  description: "Mô tả",
  attributes: "Thuộc tính",
  product_attributes: "Thuộc tính",
  main_images: "Ảnh chính",
  image: "Ảnh",
  price: "Giá",
});

/** Stability-band metrics (backend `BAND_METRICS`) → TikTok KPI names. */
export const BAND_METRIC_LABELS: Readonly<Record<string, string>> = Object.freeze({
  impressions: "Lượt hiển thị sản phẩm",
  ctr: "CTR",
  conversion_rate: "Tỷ lệ chuyển đổi",
  items_sold: "Số sản phẩm bán",
  gmv: "GMV",
  sku_orders: "Đơn hàng SKU",
  gmv_per_order: "AOV",
});

export function bandMetricLabel(metric: string): string {
  return BAND_METRIC_LABELS[metric] ?? "Chỉ số khác";
}

/** Listing levers (backend `LISTING_LEVERS`). */
export const LEVER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  title: "Tiêu đề",
  description: "Mô tả",
  attributes: "Thuộc tính",
  image: "Ảnh",
});

/** ADR-109 d.12's rule table, in its order. */
export const RULE_LABELS: Readonly<Record<string, string>> = Object.freeze({
  stability_band: "Ngưỡng giữ ổn định",
  product_cost: "Giá vốn theo sản phẩm",
  min_margin_pct: "Biên lợi nhuận tối thiểu",
  max_discount_pct: "Trần giảm giá theo SKU",
  max_open_cards: "Số thẻ mở cùng lúc",
  auto_levers: "Đòn bẩy được tự thực thi",
  protected_terms: "Từ / thông tin không được sửa",
});

export function setByLabel(setBy: string | null | undefined): string {
  if (setBy === "team") return "Đội ngũ Juli đặt";
  if (setBy === "seller") return "Bạn đặt";
  return "Mặc định";
}

export const MANUAL_CARD_NOTE = "Bạn áp dụng trên Seller Center";
export const RULE_BASED_ESTIMATE = "ước tính theo quy tắc";
export const BANDS_MISSING_PROMPT = "Đặt ngưỡng giữ ổn định trước khi chạy";
export const BANDS_MISSING_BODY =
  "Juli cần biết mỗi chỉ số không phải mục tiêu được phép lệch bao nhiêu (gợi ý ±3 %) trước lượt chạy đầu tiên. Ngày thứ 7, chỉ số vượt ngưỡng thì Juli hỏi bạn có hoàn tác không — Juli không tự hoàn tác.";
export const TEAM_TOGGLE_LABEL = "Điền thay Seller (đội ngũ Juli)";
export const MEASURE_WAITING = (date: string) => `Đang chờ đủ 7 ngày dữ liệu · đo lúc ${date}`;
export const MEASURE_NO_READING =
  "Đã qua ngày 7 nhưng Juli chưa có số đo cho lượt chạy này. Số đo sẽ hiện ở đây khi có.";
export const REVERT_LABEL = "Hoàn tác";
export const KEEP_CHANGE_LABEL = "Giữ thay đổi";
