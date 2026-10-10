/**
 * P10 fixtures shaped exactly like `fasttrack/contracts/p10-quyet-dinh.md`,
 * with the artboards' illustrative numbers (docs/product/design/
 * quyet-dinh-flows/*.dc.html), so the stubbed app can be put in every
 * artboard state. Times are Vietnam time 2026-10-09 10:01 (= 03:01Z).
 */

export const SHOP = { id: "shop-p10", name: "Shop P10" };

type Lever = "cover_image" | "title" | "description" | "product_discount" | "flash_sale" | "shipping_discount" | "buy_more_save_more";
const EXECUTOR: Record<Lever, "juli" | "juli_with_photo" | "seller_center"> = {
  cover_image: "juli_with_photo",
  title: "juli",
  description: "juli",
  product_discount: "seller_center",
  flash_sale: "seller_center",
  shipping_discount: "seller_center",
  buy_more_save_more: "seller_center",
};
const LEVER_LABEL: Record<Lever, string> = {
  cover_image: "Ảnh bìa",
  title: "Tiêu đề",
  description: "Mô tả",
  product_discount: "Giảm giá sản phẩm",
  flash_sale: "Flash sale",
  shipping_discount: "Giảm phí vận chuyển",
  buy_more_save_more: "Mua nhiều giảm nhiều",
};
const STAGE: Record<string, { code: string; label: string }> = {
  ctr: { code: "card", label: "Hiển thị → Nhấp" },
  ctor: { code: "page", label: "Nhấp → Đặt hàng" },
  aov: { code: "basket", label: "Giá trị đơn hàng" },
};

export interface CardSpec {
  id: string;
  sku: string;
  name: string;
  lever: Lever;
  kpi: "ctr" | "ctor" | "aov";
  current: number;
  target: number;
  gmvMonth: number;
  reasonShort: string;
  reasonFull: string;
  codes?: string[];
  fields?: { field: string; label: string }[];
  beforeAfter?: { field: string; label: string; before: string; after: string }[];
  status?: string;
}

const KPI_LABEL = { ctr: "CTR - Thẻ sản phẩm", ctor: "CTOR - Thẻ sản phẩm", aov: "AOV (SKU)" } as const;

export function decision(spec: CardSpec) {
  const fields = spec.fields ?? [{ field: spec.lever, label: LEVER_LABEL[spec.lever] }];
  return {
    id: spec.id,
    title: `Tối ưu ${spec.name}`,
    description: "",
    severity: "high",
    priority: 1,
    computed_at: "2026-10-09T02:00:00Z",
    surfaced_at: "2026-10-09T02:00:00Z",
    is_executable: EXECUTOR[spec.lever] !== "seller_center",
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        version: "adr106-v1",
        as_of: "2026-10-09",
        rank: 1,
        status: "rule",
        status_label: "Theo quy tắc",
        stage: STAGE[spec.kpi],
        lever: { code: spec.lever, label: LEVER_LABEL[spec.lever], action: LEVER_LABEL[spec.lever], evidence: [] },
        main_kpi: { key: spec.kpi, label: spec.kpi.toUpperCase(), value: "" },
        trigger: { code: "below_median", gap: -0.3, sentence: spec.reasonShort },
        channel_scope: "PRODUCT_CARD",
        recoverable_gmv_per_day: spec.gmvMonth / 30,
        product_title: spec.name,
        tiktok_product_id: `1729000${spec.id}`,
      },
      card: {
        seller_sku: spec.sku,
        seller_sku_more: 0,
        product_title: spec.name,
        workflow_label: "Tối ưu sản phẩm",
        updated_at: "2026-10-09T02:00:00Z",
        status: spec.status ?? "pending",
        main_kpi: {
          key: spec.kpi,
          label: KPI_LABEL[spec.kpi],
          current: spec.current,
          target: spec.target,
          unit: spec.kpi === "aov" ? "vnd" : "ratio",
        },
        expected_gmv_per_month: spec.gmvMonth,
        reason_short: spec.reasonShort,
        reason_full: spec.reasonFull,
        tiktok_codes: spec.codes ?? [],
        lever: { code: spec.lever, label: LEVER_LABEL[spec.lever], executor: EXECUTOR[spec.lever] },
        change_fields: fields,
        before_after: spec.beforeAfter ?? [],
        gmv_method: "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, trung bình 30 ngày, ước tính theo quy tắc",
      },
    },
  };
}

/** Main.dc.html / Mobile.dc.html's card. */
export const MAIN_CARD: CardSpec = {
  id: "1",
  sku: "SM-012",
  name: "Son môi số 12",
  lever: "description",
  kpi: "ctor",
  current: 0.054,
  target: 0.059,
  gmvMonth: 2_100_000,
  reasonShort: "Khách thêm giỏ rồi bỏ",
  reasonFull: "Đơn/thêm giỏ của sản phẩm thấp hơn 31 % so với trung vị shop (38,9 % so với 56,4 %).",
  codes: ["Mô tả quá ngắn"],
  fields: [
    { field: "title", label: "Tiêu đề" },
    { field: "description", label: "Mô tả" },
  ],
  beforeAfter: [
    { field: "title", label: "Tiêu đề", before: "Son môi số 12", after: "Son môi lì cao cấp số 12 — màu đỏ ruby" },
    {
      field: "description",
      label: "Mô tả",
      before: "180 ký tự, một đoạn",
      after: "640 ký tự, chia mục Thành phần · Cách dùng · Bảo quản, thêm từ khoá “son lì”, “đỏ ruby”",
    },
  ],
};

/** Levers.dc.html's seven cards. */
export const LEVER_CARDS: CardSpec[] = [
  { id: "11", sku: "SR-007", name: "Sữa rửa mặt amino 150ml", lever: "cover_image", kpi: "ctr", current: 0.021, target: 0.028, gmvMonth: 1_400_000, reasonShort: "Ảnh bìa kém nổi bật", reasonFull: "Ảnh chính chất lượng thấp.", codes: ["Ảnh chính chất lượng thấp"] },
  { id: "12", sku: "SM-012", name: "Son môi số 12", lever: "title", kpi: "ctr", current: 0.03, target: 0.036, gmvMonth: 2_400_000, reasonShort: "Tiêu đề thiếu từ khoá", reasonFull: "Tiêu đề thiếu từ khoá son lì, đỏ ruby." },
  { id: "13", sku: "MN-015", name: "Mặt nạ đất sét 100g", lever: "description", kpi: "ctor", current: 0.054, target: 0.059, gmvMonth: 2_100_000, reasonShort: "Mô tả quá ngắn", reasonFull: "Mô tả 180 ký tự, một đoạn." },
  { id: "14", sku: "KD-030", name: "Kem dưỡng ẩm ceramide", lever: "product_discount", kpi: "ctor", current: 0.042, target: 0.05, gmvMonth: 3_000_000, reasonShort: "Giá cao hơn đối thủ", reasonFull: "Giá 279k, trung vị đối thủ 259k." },
  { id: "15", sku: "TN-021", name: "Toner rau má 200ml", lever: "flash_sale", kpi: "ctor", current: 0.061, target: 0.068, gmvMonth: 1_200_000, reasonShort: "Khách bỏ giỏ, chưa có flash sale", reasonFull: "Chưa tham gia flash sale." },
  { id: "16", sku: "KC-004", name: "Kem chống nắng SPF50+", lever: "shipping_discount", kpi: "ctor", current: 0.05, target: 0.055, gmvMonth: 900_000, reasonShort: "Phí vận chuyển làm khách bỏ giỏ", reasonFull: "Phí vận chuyển làm khách bỏ giỏ." },
  { id: "17", sku: "TN-021", name: "Toner rau má 200ml", lever: "buy_more_save_more", kpi: "aov", current: 182_000, target: 205_000, gmvMonth: 1_600_000, reasonShort: "Phần lớn đơn chỉ 1 món", reasonFull: "68 % đơn hiện có 1 món." },
];

export const PHOTO_CARD = LEVER_CARDS[0];
export const MANUAL_CARD = LEVER_CARDS[3];

// -- runs + SSE --------------------------------------------------------------------

export const RUN = {
  listing: "aaaaaaaa-0000-4000-8000-000000000001",
  photo: "aaaaaaaa-0000-4000-8000-000000000002",
  manual: "aaaaaaaa-0000-4000-8000-000000000003",
  revert: "aaaaaaaa-0000-4000-8000-000000000004",
  queued1: "aaaaaaaa-0000-4000-8000-000000000005",
  queued2: "aaaaaaaa-0000-4000-8000-000000000006",
};

export function runItem(id: string, name: string, over: Record<string, unknown> = {}) {
  return {
    id,
    status: "running",
    stop_reason: null,
    product_name: name,
    created_at: "2026-10-09T03:01:00Z",
    completed_at: null,
    running_seconds_elapsed: 0,
    latest_narration: null,
    decision_summary: null,
    awaiting: null,
    ...over,
  };
}

type Ev = { event_type: string; payload: Record<string, unknown>; at: string };

/** "10:01:09" Vietnam time → ISO (2026-10-09). */
export function vn(hms: string, day = "2026-10-09"): string {
  const [h, m, s] = hms.split(":").map(Number);
  return `${day}T${String(h - 7).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s ?? 0).padStart(2, "0")}Z`;
}

export function events(runId: string, list: Ev[]) {
  return list.map((e, index) => ({
    workflow_run_id: runId,
    sequence_number: index + 1,
    event_type: e.event_type,
    timestamp: e.at,
    payload: e.payload,
    v: 1,
  }));
}

const tool = (id: string, name: string, summary: string, at: string): Ev[] => [
  { event_type: "tool.started", payload: { tool_call_id: id, tool_name: name }, at },
  { event_type: "tool.completed", payload: { tool_call_id: id, tool_name: name, ok: true, summary }, at },
];
const started = (id: string, name: string, at: string): Ev => ({ event_type: "tool.started", payload: { tool_call_id: id, tool_name: name }, at });
const completed = (id: string, name: string, summary: string, at: string): Ev => ({
  event_type: "tool.completed",
  payload: { tool_call_id: id, tool_name: name, ok: true, summary },
  at,
});
const status = (text: string, at: string): Ev => ({ event_type: "workflow.status", payload: { phase_narration: text }, at });
const begin = (at: string): Ev => ({ event_type: "workflow.started", payload: { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }, at });
const end = (stop: string, at: string): Ev => ({ event_type: "workflow.completed", payload: { stop_reason: stop }, at });

export const CONSENT_EXPIRES = vn("14:59:30");
/** Clock pinned so the consent reads "Còn hiệu lực 3 giờ 58 phút". */
export const NOW = vn("11:01:30");

function approval(id: string, toolName: string, change: Record<string, unknown>, at: string): Ev {
  return {
    event_type: "workflow.approval_required",
    payload: {
      tool_call_id: id,
      tool_name: toolName,
      proposed_change: change,
      expires_at: CONSENT_EXPIRES,
      options: [{ option_id: "opt-1", proposed_change: change, rationale: "Đủ ý, dễ đọc", params_sha: "x" }],
    },
    at,
  };
}

const LISTING_CHANGE = {
  title: "Son môi lì cao cấp số 12 — màu đỏ ruby",
  description:
    "Thành phần: sáp ong, dầu jojoba, vitamin E, chiết xuất bơ hạt mỡ giúp môi mềm và giữ màu lâu suốt ngày dài mà không khô.\nCách dùng: thoa trực tiếp lên môi sạch, tô hai lớp để màu đỏ ruby lên chuẩn, có thể dặm lại sau bữa ăn.\nBảo quản: để nơi khô ráo, tránh ánh nắng trực tiếp và nhiệt độ cao, đậy nắp kín sau khi dùng để son không bị khô.\nSon lì cao cấp màu đỏ ruby phù hợp đi làm, đi tiệc, chụp ảnh, giữ màu 8 giờ, không lem, không trôi khi ăn uống nhẹ, chất son mịn, không vón cục, an toàn cho môi nhạy cảm, được kiểm nghiệm da liễu, thích hợp cho mọi tông da châu Á, từ da sáng đến da ngăm. Đóng gói hộp quà sang trọng, có kèm gương nhỏ tiện mang theo.",
};

export function listingEvents(phase: "consent" | "writing" | "review" | "done" | "declined") {
  const list: Ev[] = [
    begin(vn("10:01:05")),
    ...tool("c0", "get_product_diagnoses", 'Có mã: "Mô tả quá ngắn"', vn("10:01:09")),
    ...tool("c1", "get_product_information", "Hoàn tất", vn("10:01:15")),
    ...tool("c2", "get_seo_keywords", "Tìm được 6 từ khoá: son lì, đỏ ruby…", vn("10:01:21")),
    ...tool("c3", "inspect_product_image", "Ảnh bìa đạt chuẩn — không đổi", vn("10:01:27")),
    approval("w1", "update_product_listing", LISTING_CHANGE, vn("10:01:30")),
  ];
  if (phase === "declined") return [...list, end("confirmation_declined", vn("10:02:00"))];
  if (phase === "consent") return list;
  list.push(started("w1", "update_product_listing", vn("10:03:58")));
  if (phase === "writing") return list;
  list.push(completed("w1", "update_product_listing", "Đã ghi Tiêu đề, Mô tả · giá trị cũ đã lưu", vn("10:04:02")));
  list.push(started("s1", "check_product_status", vn("10:04:05")));
  if (phase === "review") return list;
  list.push(completed("s1", "check_product_status", "Phiên bản mới đã được duyệt", vn("10:47:30")));
  list.push(end("final_response", vn("10:47:31")));
  return list;
}

export function photoEvents(phase: "upload" | "consent" | "writing" | "review" | "done" | "declined") {
  const list: Ev[] = [
    begin(vn("10:01:05")),
    ...tool("p0", "get_product_diagnoses", 'Có mã: "Ảnh chính chất lượng thấp"', vn("10:01:09")),
    ...tool("p1", "inspect_product_image", "Nền rối · sản phẩm chiếm 35 % khung · 600 × 600 px", vn("10:01:14")),
    status("Đang chờ ảnh từ bạn", vn("10:01:15")),
  ];
  if (phase === "upload") return list;
  list.push(status("Juli đang kiểm tra ảnh mới", vn("14:22:40")));
  list.push(
    approval(
      "u1",
      "upload_product_image",
      { main_image: { from: null, to: null } },
      vn("14:22:44"),
    ),
  );
  if (phase === "declined") return [...list, end("confirmation_declined", vn("14:23:00"))];
  if (phase === "consent") return list;
  list.push(started("u1", "upload_product_image", vn("14:25:01")));
  if (phase === "writing") return list;
  list.push(completed("u1", "upload_product_image", "Đã thay ảnh bìa · ảnh cũ đã lưu", vn("14:25:10")));
  list.push(started("ps", "check_product_status", vn("14:25:12")));
  if (phase === "review") return list;
  list.push(completed("ps", "check_product_status", "Phiên bản mới đã được duyệt", vn("15:02:31")));
  list.push(end("final_response", vn("15:02:32")));
  return list;
}

export function manualEvents(phase: "guide" | "verify" | "done" | "skipped") {
  const list: Ev[] = [
    begin(vn("10:01:05")),
    ...tool("m0", "get_product_information", "Giá 279k · trung vị đối thủ 259k · chưa có khuyến mãi", vn("10:01:09")),
    ...tool("m1", "check_shop_rules", "Biên lợi nhuận sau giảm 35 % ≥ 30 % · giảm 7 % ≤ trần 10 %", vn("10:01:11")),
    ...tool("m2", "draft_seller_instructions", "4 bước trên Seller Center", vn("10:01:12")),
    status("Đang chờ bạn áp dụng trên Seller Center", vn("10:01:13")),
  ];
  if (phase === "guide") return list;
  if (phase === "skipped") return [...list, end("confirmation_declined", vn("11:20:00"))];
  list.push(status("Juli đang tìm khuyến mãi trên TikTok Shop", vn("11:20:05")));
  list.push(started("v1", "get_promotions", vn("11:20:06")));
  if (phase === "verify") return list;
  list.push(completed("v1", "get_promotions", "Tìm thấy: Giảm giá sản phẩm · KD-030 · 259k · 09/10 → 08/11", vn("11:20:09")));
  list.push(end("final_response", vn("11:20:10")));
  return list;
}

export function revertEvents(phase: "consent" | "writing" | "review" | "done" | "conflict" | "cancelled") {
  const list: Ev[] = [begin(vn("09:12:00", "2026-10-16"))];
  list.push(...tool("r0", "get_product_information", "Đã đọc Tiêu đề, Mô tả", vn("09:13:00", "2026-10-16")));
  if (phase === "conflict") return [...list, { event_type: "workflow.failed", payload: { status: "failed", stop_reason: "concurrency_conflict" }, at: vn("09:13:30", "2026-10-16") }];
  list.push(
    approval(
      "rw",
      "update_product_listing",
      { title: "Son môi số 12", description: "Son môi số 12, màu đỏ, chất son mịn, lâu trôi. Dùng hằng ngày, phù hợp đi làm và đi chơi. Sản phẩm chính hãng, đóng gói cẩn thận, giao hàng toàn quốc nhanh chóng trong 2 đến 4 ngày." },
      vn("09:14:00", "2026-10-16"),
    ),
  );
  if (phase === "cancelled") return [...list, end("confirmation_declined", vn("09:14:30", "2026-10-16"))];
  if (phase === "consent") return list;
  list.push(started("rw", "update_product_listing", vn("09:15:00", "2026-10-16")));
  if (phase === "writing") return list;
  list.push(completed("rw", "update_product_listing", "Đã khôi phục Tiêu đề, Mô tả", vn("09:15:10", "2026-10-16")));
  list.push(started("rs", "check_product_status", vn("09:15:12", "2026-10-16")));
  if (phase === "review") return list;
  list.push(completed("rs", "check_product_status", "Phiên bản cũ đã được duyệt", vn("09:48:00", "2026-10-16")));
  list.push(end("final_response", vn("09:48:01", "2026-10-16")));
  return list;
}

export function changes(runId: string, over: Record<string, unknown> = {}) {
  return {
    run_id: runId,
    reverts_run_id: null,
    changes: [
      { field: "title", label: "Tiêu đề", before: "Son môi số 12", after: LISTING_CHANGE.title, after_source: "read", recorded_at: vn("10:04:02") },
      { field: "description", label: "Mô tả", before: "Son môi số 12, màu đỏ.", after: LISTING_CHANGE.description, after_source: "read", recorded_at: vn("10:04:02") },
    ],
    revert: { available: true, reason_code: null, message: null, runs: [] },
    question: null,
    ...over,
  };
}

// -- measurement (contract §6) ----------------------------------------------------------

const BANDS = [
  { key: "impressions", label: "Lượt hiển thị/ngày", before: 9910, band_pct: 3, low: 9613, high: 10207, unit: "count" },
  { key: "ctr", label: "CTR", before: 0.0444, band_pct: 3, low: 0.0431, high: 0.0457, unit: "ratio" },
  { key: "aov", label: "AOV", before: 160_000, band_pct: 3, low: 155_000, high: 165_000, unit: "vnd" },
];

function rows(stage: "d7ok" | "d7bad" | "d14", final?: string) {
  const ctor = stage === "d14" ? (final === "dat" ? 0.06 : final === "khong_dat" ? 0.053 : final === "chua_ket_luan" ? 0.056 : 0.058) : 0.057;
  const verdict = stage === "d14" ? { dat: "Đạt", gan_dat: "Gần đạt", khong_dat: "Không đạt", chua_ket_luan: "Chưa kết luận" }[final ?? "gan_dat"]! : "Đang tăng";
  const gmv = stage === "d14" ? { dat: 74_000, gan_dat: 57_000, khong_dat: -6_000, chua_ket_luan: 0 }[final ?? "gan_dat"]! : 48_000;
  return [
    { key: "ctor", label: "CTOR (chỉ số chính)", before: 0.054, expected: "5,9 %", actual: ctor, verdict, tone: final === "khong_dat" ? "warn" : "ok" },
    { key: "impressions", label: "Lượt hiển thị/ngày", before: 9910, expected: "9.613 – 10.207", actual: stage === "d14" ? 10098 : 10029, verdict: "Ổn định", tone: "muted" },
    { key: "ctr", label: "CTR", before: 0.0444, expected: "4,31 – 4,57 %", actual: stage === "d14" ? 0.0442 : 0.044, verdict: "Ổn định", tone: "muted" },
    stage === "d7bad"
      ? { key: "aov", label: "AOV", before: 160_000, expected: "155k – 165k ₫", actual: 152_000, verdict: "Ngoài khoảng", tone: "warn" }
      : { key: "aov", label: "AOV", before: 160_000, expected: "155k – 165k ₫", actual: stage === "d14" ? 160_300 : 161_000, verdict: "Ổn định", tone: "muted" },
    {
      key: "gmv",
      label: "GMV/ngày",
      before: 3_600_000,
      expected: "+70k ₫",
      actual: gmv,
      verdict: stage === "d14" ? (final === "khong_dat" ? "Không đạt" : final === "chua_ket_luan" ? "Chưa kết luận" : `${Math.round((gmv / 70_000) * 100)} % kỳ vọng`) : "Sơ bộ",
      tone: stage === "d14" && final !== "khong_dat" && final !== "chua_ket_luan" ? "ok" : "muted",
    },
  ];
}

export function measurement(stage: "waiting" | "d7ok" | "d7bad" | "final", final: "dat" | "gan_dat" | "khong_dat" | "chua_ket_luan" = "gan_dat") {
  const pct = { dat: 106, gan_dat: 82, khong_dat: null, chua_ket_luan: null }[final];
  const gmvDay = { dat: 74_000, gan_dat: 57_000, khong_dat: -6_000, chua_ket_luan: null }[final];
  const calibration = { dat: { from: 0.5, to: 0.66 }, gan_dat: { from: 0.5, to: 0.58 }, khong_dat: { from: 0.5, to: 0.41 }, chua_ket_luan: null }[final];
  return {
    stage: stage === "waiting" ? "waiting" : stage === "final" ? "final" : "day7",
    dates: { day7: "2026-10-16", day14: "2026-10-23" },
    target: { label: "CTOR Thẻ sản phẩm", current: 0.054, target: 0.059, progress_from: 0.055, unit: "ratio" },
    expected_gmv_per_day: 70_000,
    bands: BANDS,
    rows: stage === "waiting" ? [] : rows(stage === "final" ? "d14" : stage, final),
    day7: stage === "waiting" ? null : { within_band: stage !== "d7bad", question_id: stage === "d7bad" ? "q-1" : null },
    final:
      stage === "final"
        ? { label: final, gmv_actual_per_day: gmvDay, pct_of_expected: pct, calibration: calibration ? { lever: "description", ...calibration } : null }
        : null,
  };
}

export const INSTRUCTIONS = {
  steps: [
    "Vào Marketing › Giảm giá sản phẩm › Tạo khuyến mãi",
    "Chọn sản phẩm KD-030 · Kem dưỡng ẩm ceramide 50ml",
    "Đặt giá giảm 259.000 ₫, từ 09/10/2026 đến 08/11/2026",
    "Bấm Lưu và kiểm tra khuyến mãi ở trạng thái Đang diễn ra",
  ],
  deep_link: "https://seller-vn.tiktok.com/promotion/marketing-tools/management",
  summary: "Giá 279k → 259k (−7 %) · 30 ngày · biên lợi nhuận còn 35 % (≥ 30 % bạn đặt) · trong trần giảm 10 % bạn đặt.",
};

export const PHOTO_CHECKS = [
  { key: "ratio", label: "1:1", ok: true },
  { key: "size", label: "1200 × 1200 px", ok: true },
  { key: "background", label: "nền trắng", ok: true },
  { key: "fill", label: "sản phẩm 78 % khung", ok: true },
];

export function rules() {
  const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
  const band = (value: number) => ({ value, set_by: "seller", set_by_user_id: "u", set_at: "2026-10-08T03:00:00Z" });
  return {
    stability_band: { impressions: band(3), ctr: band(3), gmv_per_order: band(3) },
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...unset, value: 30 },
    auto_levers: { ...unset, value: ["attributes", "description", "image", "title"] },
    protected_terms: { ...unset, value: [] },
    band_metrics: ["impressions", "ctr", "conversion_rate", "items_sold", "gmv", "sku_orders", "gmv_per_order"],
    listing_levers: ["title", "description", "attributes", "image"],
  };
}
