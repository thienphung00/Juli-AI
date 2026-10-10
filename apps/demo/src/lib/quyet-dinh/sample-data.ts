/**
 * The signed-out Quyết định sample ("Bản minh họa"): an invented shop's
 * cards, runs, changes and measurement, each built in the exact P10 wire
 * shape (`fasttrack/contracts/p10-quyet-dinh.md` §1–§7) with the artboards'
 * illustrative numbers (`docs/product/design/quyet-dinh-flows/*.dc.html`:
 * SM-012 Son môi số 12, CTOR 5,4 % → 5,9 %, +2,1 tr ₫/tháng). Pure data and
 * builders — bundled, never fetched (ADR-094 d.1); `sample-clients.ts` serves
 * them through the same `QdClients` interface the real door uses.
 */

import { validateAgentEvent, type AgentEvent, type DemoDecisionItem } from "@juli/contracts";

import type {
  ContentRunDetail,
  ContentScript,
  ContentStage,
  LeverCode,
  LeverExecutor,
  Measurement,
  P10DecisionItem,
  PhotoCheck,
  SellerInstructions,
} from "./p10-types";
import type { FieldChange, RunChanges, ShopRules } from "./types";

export const SAMPLE_SHOP = { id: "sample-shop", name: "Cửa hàng Mẫu Hoa Mai" } as const;
/** Never sent anywhere: the sample clients ignore it. */
export const SAMPLE_TOKEN = "sample";

const DAY_MS = 86_400_000;
const HOUR_MS = 3_600_000;

const EXECUTOR: Record<LeverCode, LeverExecutor> = {
  cover_image: "juli_with_photo",
  title: "juli",
  description: "juli",
  product_discount: "seller_center",
  flash_sale: "seller_center",
  shipping_discount: "seller_center",
  buy_more_save_more: "seller_center",
};
const LEVER_LABEL: Record<LeverCode, string> = {
  cover_image: "Ảnh bìa",
  title: "Tiêu đề",
  description: "Mô tả",
  product_discount: "Giảm giá sản phẩm",
  flash_sale: "Flash sale",
  shipping_discount: "Giảm phí vận chuyển",
  buy_more_save_more: "Mua nhiều giảm nhiều",
};
const STAGE = {
  ctr: { code: "card", label: "Hiển thị → Nhấp" },
  ctor: { code: "page", label: "Nhấp → Đặt hàng" },
  aov: { code: "basket", label: "Giá trị đơn hàng" },
} as const;
const KPI_LABEL = { ctr: "CTR - Thẻ sản phẩm", ctor: "CTOR - Thẻ sản phẩm", aov: "AOV (SKU)" } as const;
const GMV_METHOD = "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, trung bình 30 ngày, ước tính theo quy tắc";

export interface SampleCardSpec {
  readonly id: string;
  readonly sku: string;
  readonly name: string;
  readonly lever: LeverCode;
  readonly kpi: keyof typeof KPI_LABEL;
  readonly current: number;
  readonly target: number;
  readonly gmvMonth: number;
  readonly reasonShort: string;
  readonly reasonFull: string;
  readonly codes?: readonly string[];
  readonly fields?: readonly { readonly field: string; readonly label: string }[];
  readonly beforeAfter?: readonly { readonly field: string; readonly label: string; readonly before: string; readonly after: string }[];
  readonly status?: "pending" | "running" | "applied" | "rejected" | "expired";
  /** The listing a `juli` run proposes at the consent step (title / description). */
  readonly proposal?: Readonly<Record<string, string>>;
}

/** A `GET /v1/demo/decisions` item (contract §1), `updated_at` relative to `nowMs`. */
export function sampleDecision(spec: SampleCardSpec, nowMs: number): P10DecisionItem {
  const fields = spec.fields ?? [{ field: spec.lever, label: LEVER_LABEL[spec.lever] }];
  const at = new Date(nowMs - HOUR_MS).toISOString();
  const item = {
    id: spec.id,
    title: `Tối ưu ${spec.name}`,
    description: "",
    severity: "high",
    priority: 1,
    computed_at: at,
    surfaced_at: at,
    is_executable: EXECUTOR[spec.lever] !== "seller_center",
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        version: "adr106-v1",
        as_of: at.slice(0, 10),
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
        tiktok_product_id: `1729000${spec.sku.replace(/\D/g, "")}`,
      },
      card: {
        seller_sku: spec.sku,
        seller_sku_more: 0,
        product_title: spec.name,
        workflow_label: "Tối ưu sản phẩm",
        updated_at: at,
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
        gmv_method: GMV_METHOD,
      },
    },
  };
  return item as unknown as DemoDecisionItem as P10DecisionItem;
}

export function executorOf(spec: SampleCardSpec): LeverExecutor {
  return EXECUTOR[spec.lever];
}

const SON_MOI_DESCRIPTION =
  "Thành phần: sáp ong, dầu jojoba, vitamin E, chiết xuất bơ hạt mỡ giúp môi mềm và giữ màu lâu suốt ngày dài mà không khô.\n" +
  "Cách dùng: thoa trực tiếp lên môi sạch, tô hai lớp để màu đỏ ruby lên chuẩn, có thể dặm lại sau bữa ăn.\n" +
  "Bảo quản: để nơi khô ráo, tránh ánh nắng trực tiếp và nhiệt độ cao, đậy nắp kín sau khi dùng để son không bị khô.\n" +
  "Son lì cao cấp màu đỏ ruby phù hợp đi làm, đi tiệc, chụp ảnh, giữ màu 8 giờ, không lem, không trôi khi ăn uống nhẹ, chất son mịn, không vón cục, an toàn cho môi nhạy cảm, được kiểm nghiệm da liễu, thích hợp cho mọi tông da châu Á, từ da sáng đến da ngăm. Đóng gói hộp quà sang trọng, có kèm gương nhỏ tiện mang theo.";

/** Main.dc.html / Mobile.dc.html's card — Juli writes it (`juli`). */
export const SAMPLE_MAIN_CARD: SampleCardSpec = {
  id: "sample-sm-012",
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
  proposal: { title: "Son môi lì cao cấp số 12 — màu đỏ ruby", description: SON_MOI_DESCRIPTION },
};

/** Levers.dc.html's cover-image card — Juli uploads the seller's photo (`juli_with_photo`). */
export const SAMPLE_PHOTO_CARD: SampleCardSpec = {
  id: "sample-sr-007",
  sku: "SR-007",
  name: "Sữa rửa mặt amino 150ml",
  lever: "cover_image",
  kpi: "ctr",
  current: 0.021,
  target: 0.028,
  gmvMonth: 1_400_000,
  reasonShort: "Ảnh bìa kém nổi bật",
  reasonFull: "Ảnh bìa nền rối, sản phẩm chỉ chiếm 35 % khung, 600 × 600 px.",
  codes: ["Ảnh chính chất lượng thấp"],
};

/** Levers.dc.html's discount card — the seller applies it on Seller Center (`seller_center`). */
export const SAMPLE_MANUAL_CARD: SampleCardSpec = {
  id: "sample-kd-030",
  sku: "KD-030",
  name: "Kem dưỡng ẩm ceramide",
  lever: "product_discount",
  kpi: "ctor",
  current: 0.042,
  target: 0.05,
  gmvMonth: 3_000_000,
  reasonShort: "Giá cao hơn đối thủ",
  reasonFull: "Giá 279k, trung vị đối thủ 259k.",
};

/** Levers.dc.html's description card — a second Juli card in the same group. */
export const SAMPLE_DESCRIPTION_CARD: SampleCardSpec = {
  id: "sample-mn-015",
  sku: "MN-015",
  name: "Mặt nạ đất sét 100g",
  lever: "description",
  kpi: "ctor",
  current: 0.054,
  target: 0.059,
  gmvMonth: 2_100_000,
  reasonShort: "Mô tả quá ngắn",
  reasonFull: "Mô tả 180 ký tự, một đoạn.",
  codes: ["Mô tả quá ngắn"],
  proposal: {
    description:
      "Thành phần: đất sét kaolin, bentonite, chiết xuất trà xanh.\nCách dùng: thoa lớp mỏng lên da sạch, để 10 phút rồi rửa sạch với nước ấm, 2–3 lần mỗi tuần.\nBảo quản: đậy nắp kín, để nơi khô ráo, tránh ánh nắng trực tiếp.",
  },
};

/** The applied card behind the sample's finished run (Đo lường has something to show). */
export const SAMPLE_APPLIED_CARD: SampleCardSpec = {
  id: "sample-tn-021",
  sku: "TN-021",
  name: "Toner rau má 200ml",
  lever: "title",
  kpi: "ctor",
  current: 0.054,
  target: 0.059,
  gmvMonth: 2_100_000,
  reasonShort: "Tiêu đề thiếu từ khoá",
  reasonFull: "Tiêu đề thiếu từ khoá “rau má”, “cấp ẩm”.",
  status: "applied",
};

export const SAMPLE_CARDS: readonly SampleCardSpec[] = [
  SAMPLE_MAIN_CARD,
  SAMPLE_PHOTO_CARD,
  SAMPLE_MANUAL_CARD,
  SAMPLE_DESCRIPTION_CARD,
  SAMPLE_APPLIED_CARD,
];

export const SAMPLE_FINISHED_RUN_ID = "sample-run-tn-021";
export const SAMPLE_FINISHED_CHANGES: readonly FieldChange[] = [
  {
    field: "title",
    label: "Tiêu đề",
    before: "Toner rau má 200ml",
    after: "Toner rau má cấp ẩm, làm dịu da 200ml",
    after_source: "read",
    recorded_at: null,
  } as FieldChange,
];

// -- events ------------------------------------------------------------------------------

export interface EventDraft {
  readonly event_type: string;
  readonly payload: Record<string, unknown>;
}

/** Contract-validated events, numbered from `firstSeq`, one second apart from `startMs`. */
export function toEvents(runId: string, drafts: readonly EventDraft[], firstSeq: number, startMs: number): AgentEvent[] {
  return drafts.map((draft, index) =>
    validateAgentEvent({
      workflow_run_id: runId,
      sequence_number: firstSeq + index,
      event_type: draft.event_type,
      timestamp: new Date(startMs + index * 1000).toISOString(),
      payload: draft.payload,
      v: 1,
    }),
  );
}

const begin: EventDraft = {
  event_type: "workflow.started",
  payload: { workflow_key: "optimize_product_2", product_ref: "sample", prompt_version: "v3" },
};
const tool = (id: string, name: string, summary: string): EventDraft[] => [
  { event_type: "tool.started", payload: { tool_call_id: id, tool_name: name } },
  { event_type: "tool.completed", payload: { tool_call_id: id, tool_name: name, ok: true, summary } },
];
const started = (id: string, name: string): EventDraft => ({ event_type: "tool.started", payload: { tool_call_id: id, tool_name: name } });
const completed = (id: string, name: string, summary: string): EventDraft => ({
  event_type: "tool.completed",
  payload: { tool_call_id: id, tool_name: name, ok: true, summary },
});
const status = (text: string): EventDraft => ({ event_type: "workflow.status", payload: { phase_narration: text } });
export const endDraft = (stop: string): EventDraft => ({ event_type: "workflow.completed", payload: { stop_reason: stop } });

function approval(id: string, toolName: string, change: Record<string, unknown>, expiresAt: string, rationale: string): EventDraft {
  return {
    event_type: "workflow.approval_required",
    payload: {
      tool_call_id: id,
      tool_name: toolName,
      proposed_change: change,
      expires_at: expiresAt,
      options: [{ option_id: "opt-1", proposed_change: change, rationale, params_sha: "sample" }],
    },
  };
}

/** Run.dc.html up to the consent (title / description written by Juli). */
export function listingUntilConsent(spec: SampleCardSpec, expiresAt: string): EventDraft[] {
  const change = spec.proposal ?? { description: spec.reasonFull };
  const code = spec.codes?.[0];
  return [
    begin,
    ...tool("c0", "get_product_diagnoses", code ? `Có mã: "${code}"` : "Không có mã chẩn đoán"),
    ...tool("c1", "get_product_information", "Hoàn tất"),
    ...tool("c2", "get_seo_keywords", "Tìm được 6 từ khoá: son lì, đỏ ruby…"),
    ...tool("c3", "inspect_product_image", "Ảnh bìa đạt chuẩn — không đổi"),
    approval("w1", "update_product_listing", change, expiresAt, "Đủ ý, dễ đọc"),
  ];
}

/** The write after the seller's Xác nhận, then TikTok's review and the end. */
export function writeAndReview(toolCallId: string, written: string, reviewed: string): EventDraft[][] {
  return [
    [started(toolCallId, "update_product_listing")],
    [completed(toolCallId, "update_product_listing", written), started("s1", "check_product_status")],
    [completed("s1", "check_product_status", reviewed), endDraft("final_response")],
  ];
}

/** RunPhoto.dc.html up to "Đang chờ ảnh từ bạn". */
export function photoUntilUpload(spec: SampleCardSpec): EventDraft[] {
  return [
    begin,
    ...tool("p0", "get_product_diagnoses", `Có mã: "${spec.codes?.[0] ?? "Ảnh chính chất lượng thấp"}"`),
    ...tool("p1", "inspect_product_image", "Nền rối · sản phẩm chiếm 35 % khung · 600 × 600 px"),
    status("Đang chờ ảnh từ bạn"),
  ];
}

/** P10-B order (contract §7): the photo is staged, then the consent is on `update_product_listing`. */
export function photoToConsent(expiresAt: string): EventDraft[] {
  return [
    status("Juli đang kiểm tra ảnh mới"),
    ...tool("p2", "upload_product_image", "Đã tải ảnh lên, chờ bạn xác nhận"),
    approval("p3", "update_product_listing", { attach_staged_image: true }, expiresAt, "Ảnh đạt đủ 4 yêu cầu"),
  ];
}

/** RunManual.dc.html up to "Đang chờ bạn áp dụng trên Seller Center" (P10-B's promotion planner). */
export function manualUntilGuide(): EventDraft[] {
  return [
    begin,
    ...tool("m0", "get_product_information", "Giá 279k · trung vị đối thủ 259k"),
    ...tool("m1", "find_product_promotions", "Chưa có khuyến mãi"),
    { event_type: "assistant.text", payload: { text: "Biên lợi nhuận sau giảm 35 % ≥ 30 % · giảm 7 % ≤ trần 10 %" } },
    status("Đang chờ bạn áp dụng trên Seller Center"),
  ];
}

export function manualVerify(): EventDraft[][] {
  return [
    [status("Juli đang tìm khuyến mãi trên TikTok Shop"), started("v1", "find_product_promotions")],
    [completed("v1", "find_product_promotions", "Tìm thấy: Giảm giá sản phẩm · KD-030 · 259k"), endDraft("final_response")],
  ];
}

/** Revert.dc.html up to the consent: restore the values Juli replaced. */
export function revertUntilConsent(before: Record<string, string>, expiresAt: string): EventDraft[] {
  const labels = Object.keys(before)
    .map((field) => (field === "title" ? "Tiêu đề" : field === "description" ? "Mô tả" : field))
    .join(", ");
  return [
    begin,
    ...tool("r0", "get_product_information", `Đã đọc ${labels}`),
    approval("rw", "update_product_listing", before, expiresAt, "Nội dung trước khi Juli ghi"),
  ];
}

/** The sample's finished listing run (TN-021), completed `daysAgo` days before `nowMs`. */
export function finishedListingEvents(runId: string, nowMs: number, daysAgo: number): AgentEvent[] {
  const start = nowMs - daysAgo * DAY_MS - 2 * HOUR_MS;
  const change = { title: "Toner rau má cấp ẩm, làm dịu da 200ml" };
  const drafts: EventDraft[] = [
    begin,
    ...tool("c0", "get_product_diagnoses", "Không có mã chẩn đoán"),
    ...tool("c1", "get_product_information", "Hoàn tất"),
    ...tool("c2", "get_seo_keywords", "Tìm được 4 từ khoá: toner rau má, cấp ẩm…"),
    ...tool("c3", "inspect_product_image", "Ảnh bìa đạt chuẩn — không đổi"),
    approval("w1", "update_product_listing", change, new Date(start + 4 * HOUR_MS).toISOString(), "Thêm từ khoá"),
    ...writeAndReview("w1", "Đã ghi Tiêu đề · giá trị cũ đã lưu", "Phiên bản mới đã được duyệt").flat(),
  ];
  return toEvents(runId, drafts, 1, start);
}

// -- reads ---------------------------------------------------------------------------------

export const SAMPLE_PHOTO_CHECKS: readonly PhotoCheck[] = [
  { key: "ratio", label: "1:1", ok: true },
  { key: "size", label: "1200 × 1200 px", ok: true },
  { key: "background", label: "nền trắng", ok: true, heuristic: true },
  { key: "fill", label: "sản phẩm 78 % khung", ok: true, heuristic: true },
];

export const SAMPLE_INSTRUCTIONS: SellerInstructions = {
  steps: [
    "Vào Marketing › Giảm giá sản phẩm › Tạo khuyến mãi",
    "Chọn sản phẩm KD-030 · Kem dưỡng ẩm ceramide 50ml",
    "Đặt giá giảm 259.000 ₫, áp dụng trong 30 ngày",
    "Bấm Lưu và kiểm tra khuyến mãi ở trạng thái Đang diễn ra",
  ],
  deep_link: "https://seller-vn.tiktok.com/promotion/marketing-tools/management",
  summary: "Giá 279k → 259k (−7 %) · 30 ngày · biên lợi nhuận còn 35 % (≥ 30 % bạn đặt) · trong trần giảm 10 % bạn đặt.",
};

export function sampleRules(): ShopRules {
  const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
  const band = (value: unknown) => ({ value, set_by: "seller" as const, set_by_user_id: "sample", set_at: "2026-10-08T03:00:00Z" });
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
    // P14-F sample values (read-only in the signed-out sample).
    sku_cost: { "1729700293904534135": band(120_000) },
    default_gross_margin_pct: band(40),
    default_max_discount_pct: band(15),
    program_fee_pct: band(4),
    joins_platform_campaigns: band(true),
    platform_campaign_note: band("11.11 — giảm 15 % cho Kem dưỡng ẩm ceramide"),
    target_roas: band(6),
    gmv_max_daily_budget: band(500_000),
    live_schedule: band([{ days: ["tue", "thu"], start: "20:00", end: "22:00" }]),
    weekdays: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
  };
}

export function sampleChanges(runId: string, changes: readonly FieldChange[], over: Partial<RunChanges> = {}): RunChanges {
  return {
    run_id: runId,
    reverts_run_id: null,
    changes,
    revert: { available: changes.length > 0, reason_code: null, message: null, runs: [] },
    question: null,
    ...over,
  } as RunChanges;
}

function isoDay(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10);
}

/** Measure.dc.html / Day7.dc.html "within band": the day-7 check of a run completed at `completedMs`. */
export function sampleDay7Measurement(completedMs: number): Measurement {
  return {
    stage: "day7",
    dates: { day7: isoDay(completedMs + 7 * DAY_MS), day14: isoDay(completedMs + 14 * DAY_MS) },
    target: { label: "CTOR Thẻ sản phẩm", current: 0.054, target: 0.059, progress_from: 0.055, unit: "ratio" },
    expected_gmv_per_day: 70_000,
    bands: [
      { key: "impressions", label: "Lượt hiển thị/ngày", before: 9910, band_pct: 3, low: 9613, high: 10207, unit: "count" },
      { key: "ctr", label: "CTR", before: 0.0444, band_pct: 3, low: 0.0431, high: 0.0457, unit: "ratio" },
      { key: "aov", label: "AOV", before: 160_000, band_pct: 3, low: 155_000, high: 165_000, unit: "vnd" },
    ],
    rows: [
      { key: "ctor", label: "CTOR (chỉ số chính)", before: 0.054, expected: "5,9 %", actual: 0.057, verdict: "Đang tăng", tone: "ok" },
      { key: "impressions", label: "Lượt hiển thị/ngày", before: 9910, expected: "9.613 – 10.207", actual: 10029, verdict: "Ổn định", tone: "muted" },
      { key: "ctr", label: "CTR", before: 0.0444, expected: "4,31 – 4,57 %", actual: 0.044, verdict: "Ổn định", tone: "muted" },
      { key: "aov", label: "AOV", before: 160_000, expected: "155k – 165k ₫", actual: 161_000, verdict: "Ổn định", tone: "muted" },
      { key: "gmv_per_day", label: "GMV/ngày", before: 3_600_000, expected: "+70k ₫", actual: 48_000, verdict: "Sơ bộ", tone: "muted" },
    ],
    day7: { within_band: true, question_id: null },
    final: null,
  };
}

/** A run just finished: the clock started, nothing measured yet (contract §6 `waiting`, `rows=[]`). */
export function sampleWaitingMeasurement(completedMs: number, spec: SampleCardSpec): Measurement {
  const ratio = spec.kpi !== "aov";
  return {
    stage: "waiting",
    dates: { day7: isoDay(completedMs + 7 * DAY_MS), day14: isoDay(completedMs + 14 * DAY_MS) },
    target: {
      label: KPI_LABEL[spec.kpi].replace(" - ", " "),
      current: spec.current,
      target: spec.target,
      progress_from: spec.current,
      unit: ratio ? "ratio" : "vnd",
    },
    expected_gmv_per_day: Math.round(spec.gmvMonth / 30),
    bands: sampleDay7Measurement(completedMs).bands,
    rows: [],
    day7: null,
    final: null,
  };
}

// -- P14-E content cards ("Juli soạn · bạn làm", ContentCards.dc.html / ContentRun.dc.html) --

export type SampleContentKind = "video" | "live";

export interface SampleContentSpec {
  readonly id: string;
  readonly sku: string;
  readonly name: string;
  readonly kind: SampleContentKind;
  readonly current: number;
  readonly target: number;
  readonly gmvMonth: number;
  readonly reasonShort: string;
  readonly reasonFull: string;
  readonly actionLabel: string;
  readonly willDraft: readonly string[];
  readonly measure: string;
}

const CONTENT_KPI: Readonly<Record<SampleContentKind, { key: string; label: string; lever: string; workflow: string; method: string }>> = {
  video: {
    key: "video_ctr",
    label: "CTR - Video của người bán",
    lever: "video_script",
    workflow: "Tối ưu nội dung · Video",
    method: "lượt hiển thị × (CTR mục tiêu − CTR hiện tại) × CTOR × AOV, trung bình 30 ngày, ước tính theo quy tắc",
  },
  live: {
    key: "live_ctor",
    label: "CTOR - LIVE của người bán",
    lever: "live_script",
    workflow: "Tối ưu nội dung · LIVE",
    method: "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, trung bình 30 ngày, ước tính theo quy tắc",
  },
};

/** ContentCards.dc.html's video card. */
export const SAMPLE_CONTENT_VIDEO: SampleContentSpec = {
  id: "sample-content-mn-015",
  sku: "MN-015",
  name: "Mặt nạ đất sét 100g",
  kind: "video",
  current: 0.019,
  target: 0.032,
  gmvMonth: 1_700_000,
  reasonShort: "Video có lượt xem nhưng ít bấm vào sản phẩm",
  reasonFull:
    'Video "Mặt nạ đất sét: trước và sau" có 118k lượt hiển thị, CTR 1,9 % so với 3,2 % của các video khác trong shop. Giỏ hàng xuất hiện sau giây 20.',
  actionLabel: "Kịch bản video mới",
  willDraft: [
    "Hook 3 giây và 2 phương án mở đầu",
    "Kịch bản 25–35 giây theo cảnh, sản phẩm xuất hiện trước giây 3",
    "Lời kêu gọi bấm giỏ, gợi ý hashtag và nhạc đang lên",
  ],
  measure: "CTR trên các video mới gắn MN-015 trong 7 và 14 ngày, so với video cũ.",
};

/** ContentCards.dc.html's LIVE card. */
export const SAMPLE_CONTENT_LIVE: SampleContentSpec = {
  id: "sample-content-sm-012",
  sku: "SM-012",
  name: "Son môi số 12",
  kind: "live",
  current: 0.059,
  target: 0.075,
  gmvMonth: 900_000,
  reasonShort: "Người xem bấm vào nhưng ít chốt đơn",
  reasonFull:
    'Phiên "LIVE xả kho 27/09" có CTOR 5,9 % so với 7,5 % trung bình 30 ngày trước. SM-012 nằm ở vị trí 9 trong giỏ, không được ghim.',
  actionLabel: "Kịch bản host + thứ tự giỏ",
  willDraft: [
    "Kịch bản host theo khung ASBC cho SM-012, có so sánh giá và giới hạn số lượng",
    "Thứ tự giỏ: sản phẩm chủ lực lên đầu, thời điểm ghim",
    "Gợi ý flash sale trong LIVE trong mức trần giảm giá của bạn",
  ],
  measure: "CTOR của SM-012 ở 3 phiên LIVE kế tiếp, so với phiên trước.",
};

export const SAMPLE_CONTENT_CARDS: readonly SampleContentSpec[] = [SAMPLE_CONTENT_VIDEO, SAMPLE_CONTENT_LIVE];

/** A content card as `GET /v1/demo/decisions` sends it (`p14-content-cards.md` §1): no diagnosis. */
export function sampleContentDecision(spec: SampleContentSpec, nowMs: number, status: string = "pending"): P10DecisionItem {
  const kpi = CONTENT_KPI[spec.kind];
  const at = new Date(nowMs - HOUR_MS).toISOString();
  const item = {
    id: spec.id,
    title: `${spec.actionLabel} · ${spec.name}`,
    description: spec.reasonShort,
    severity: "warning",
    priority: 2,
    computed_at: at,
    surfaced_at: at,
    is_executable: true,
    recommendation: {
      source_kpi_ids: [],
      workflow_name: kpi.workflow,
      card: {
        seller_sku: spec.sku,
        seller_sku_more: 0,
        product_title: spec.name,
        workflow_label: kpi.workflow,
        updated_at: at,
        status,
        main_kpi: { key: kpi.key, label: kpi.label, current: spec.current, target: spec.target, unit: "ratio" },
        expected_gmv_per_month: spec.gmvMonth,
        reason_short: spec.reasonShort,
        reason_full: spec.reasonFull,
        tiktok_codes: [],
        lever: { code: kpi.lever, label: spec.actionLabel, executor: "juli_drafts" },
        change_fields: [{ field: kpi.lever, label: spec.actionLabel }],
        before_after: [],
        gmv_method: kpi.method,
        content: {
          kind: spec.kind,
          action_label: spec.actionLabel,
          chip: "Juli soạn · bạn làm",
          will_draft: spec.willDraft,
          measure: spec.measure,
        },
      },
    },
  };
  return item as unknown as DemoDecisionItem as P10DecisionItem;
}

interface ContentCopy {
  readonly title: string;
  readonly headline: string;
  readonly steps: readonly (readonly [string, string])[];
  readonly scriptTitle: string;
  readonly blocks: Readonly<Record<1 | 2, readonly { readonly key: string; readonly label: string; readonly text: string }[]>>;
  readonly wait: { readonly title: string; readonly body: string; readonly done_label: string; readonly detect_what: string };
  readonly measureBody: string;
  readonly readTools: readonly [string, string][];
}

/** ContentRun.dc.html's canned copy, verbatim (no model call in the sample). */
export const SAMPLE_CONTENT_COPY: Readonly<Record<SampleContentKind, ContentCopy>> = {
  video: {
    title: "MN-015 · Mặt nạ đất sét 100g · kịch bản video",
    headline: "Juli đã soạn kịch bản video, bạn quay và đăng",
    steps: [
      ["Đọc số liệu video và sản phẩm", "3 video gắn MN-015 · CTR 1,9 % · giỏ hàng xuất hiện giây 20"],
      ["Đọc thông tin sản phẩm, từ khoá", 'Mô tả, ảnh, từ khoá "mặt nạ đất sét", "se khít lỗ chân lông"'],
      ["Soạn kịch bản", "gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra"],
      ["Bạn xem, sửa và chọn", ""],
      ["Bạn quay và đăng video gắn MN-015", ""],
      ["Đo CTR trên video mới · ngày 7, ngày 14", ""],
    ],
    scriptTitle: "Kịch bản video 25–35 giây",
    blocks: {
      1: [
        { key: "hook", label: "Hook (0–3 giây)", text: '"Lỗ chân lông to sau 1 tuần dùng cái này…" · cận mặt trước khi đắp' },
        { key: "scene_2", label: "Cảnh 2 (3–15 giây)", text: "Đắp mặt nạ, đồng hồ đếm 10 phút\nSản phẩm và giỏ hàng xuất hiện từ giây 3" },
        { key: "scene_3", label: "Cảnh 3 (15–28 giây)", text: "Rửa mặt, so sánh trước/sau cùng ánh sáng" },
        { key: "cta", label: "Kêu gọi + gợi ý", text: '"Bấm giỏ vàng, đang giảm hôm nay"\n#matnadatset #skincare · nhạc đang lên tuần này' },
      ],
      2: [
        { key: "hook", label: "Hook (0–3 giây)", text: '"Mình thử mặt nạ 69k này 7 ngày liền" · cầm sản phẩm lên khung hình' },
        { key: "scene_2", label: "Cảnh 2 (3–15 giây)", text: "Ngày 1 → ngày 7, mỗi ngày 2 giây\nGiỏ hàng ghim từ giây 3" },
        { key: "scene_3", label: "Cảnh 3 (15–28 giây)", text: "Kết quả cuối, chạm vào da" },
        { key: "cta", label: "Kêu gọi + gợi ý", text: '"Link ở giỏ vàng"\n#reviewthat #matnadatset' },
      ],
    },
    wait: {
      title: "Đang chờ bạn đăng video",
      body: "Đăng video có gắn link MN-015 trong 7 ngày. Juli bắt đầu đo khi video mới có lượt hiển thị.",
      done_label: "Tôi đã đăng video",
      detect_what: "video mới gắn MN-015",
    },
    measureBody:
      'Video mới "7 ngày mặt nạ đất sét" đăng 12/10. CTR sau 2 ngày: 2,8 % (video cũ 1,9 %, mục tiêu 3,2 %). Kết quả ngày 7: 19/10.',
    readTools: [
      ["get_content_performance", "3 video gắn MN-015 · CTR 1,9 % · giỏ hàng xuất hiện giây 20"],
      ["get_product_information", "Hoàn tất"],
      ["get_seo_keywords", 'Từ khoá "mặt nạ đất sét", "se khít lỗ chân lông"'],
      ["get_seller_content_rules", "Không có từ cấm · 0 từ bảo vệ"],
    ],
  },
  live: {
    title: "SM-012 · Son môi số 12 · kịch bản LIVE",
    headline: "Juli đã soạn kịch bản host và thứ tự giỏ, bạn LIVE",
    steps: [
      ["Đọc số liệu các phiên LIVE", "Phiên 27/09: CTOR SM-012 5,9 % · vị trí 9 trong giỏ, không ghim"],
      ["Đọc sản phẩm, giá, khuyến mãi, Quy tắc", "Trần giảm giá 10 % · biên tối thiểu 30 %"],
      ["Soạn kịch bản host và thứ tự giỏ", "gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra"],
      ["Bạn xem, sửa và chọn", ""],
      ["Bạn LIVE theo kịch bản", ""],
      ["Đo CTOR ở 3 phiên kế tiếp", ""],
    ],
    scriptTitle: "Kịch bản host cho SM-012 + thứ tự giỏ",
    blocks: {
      1: [
        { key: "opening", label: "Mở (A · Attention)", text: '"Màu đỏ ruby đang hết hàng trên TikTok, hôm nay shop còn 50 thỏi"' },
        { key: "show", label: "Thử màu (S · Show)", text: "Thoa trên môi và tay dưới 2 loại ánh sáng · so sánh với son 300k" },
        {
          key: "close",
          label: "Chốt (B · Benefit + C · Close)",
          text: "Flash sale trong LIVE −8 % (trong trần 10 %) · 10 phút · ghim SM-012 ngay lúc nói giá",
        },
        { key: "basket", label: "Thứ tự giỏ", text: "1. SM-012 (ghim) · 2. MN-015 · 3. TN-021 · 4. combo son + mặt nạ" },
      ],
      2: [
        { key: "opening", label: "Mở", text: '"Ai môi khô mà vẫn muốn son lì thì ở lại 5 phút"' },
        { key: "show", label: "Thử màu", text: "Đeo khẩu trang rồi tháo ra: không lem" },
        { key: "close", label: "Chốt", text: "Voucher LIVE từ 199k (≈ 1,3 × AOV) · đếm ngược 5 phút" },
        { key: "basket", label: "Thứ tự giỏ", text: "1. SM-012 (ghim) · 2. combo son + mặt nạ · 3. MN-015" },
      ],
    },
    wait: {
      title: "Đang chờ phiên LIVE kế tiếp",
      body: "Juli đo CTOR của SM-012 ở 3 phiên LIVE kế tiếp có bán SM-012.",
      done_label: "Tôi đã LIVE xong",
      detect_what: "phiên LIVE mới có SM-012",
    },
    measureBody: "Phiên 14/10: CTOR SM-012 7,2 % (trước 5,9 %, mục tiêu 7,5 %). Còn 2 phiên nữa để chốt.",
    readTools: [
      ["get_content_performance", "Phiên 27/09: CTOR SM-012 5,9 % · vị trí 9 trong giỏ, không ghim"],
      ["get_product_information", "Hoàn tất"],
      ["find_product_promotions", "Chưa có khuyến mãi"],
      ["get_seller_content_rules", "Trần giảm giá 10 % · biên tối thiểu 30 %"],
    ],
  },
};

export const CONTENT_CHECKS_LINE =
  "Đã kiểm tra: không có từ cấm, giữ từ bảo vệ của bạn, đúng thông tin sản phẩm, trong trần giảm giá.";

export interface SampleContentState {
  stage: ContentStage;
  version: 1 | 2;
  chosenVersion: number | null;
  edited: boolean;
  /** When each of the 6 steps finished (ISO), null while not done. */
  stepAt: (string | null)[];
}

/** `GET /v1/demo/runs/{id}` → `data.content` for a sample content run. */
export function sampleContentDetail(spec: SampleContentSpec, state: SampleContentState): ContentRunDetail {
  const copy = SAMPLE_CONTENT_COPY[spec.kind];
  const blocks = copy.blocks[state.version];
  const script: ContentScript | null =
    state.stage === "drafting"
      ? null
      : {
          version: state.version,
          title: copy.scriptTitle,
          blocks,
          checks: [
            { key: "banned", label: "không có từ cấm", ok: true },
            { key: "protected", label: "giữ từ bảo vệ của bạn", ok: true },
            { key: "facts", label: "đúng thông tin sản phẩm", ok: true },
            { key: "discount", label: "trong trần giảm giá", ok: true },
          ],
          checks_line: CONTENT_CHECKS_LINE,
          plain_text: [copy.scriptTitle, ...blocks.map((block) => `${block.label}\n${block.text}`)].join("\n\n"),
          raw: null,
        };
  return {
    kind: spec.kind,
    stage: state.stage,
    title: copy.title,
    headline: copy.headline,
    steps: copy.steps.map(([label, result], index) => ({
      key: ["read_content", "read_product", "draft", "choose", "publish", "measure"][index],
      label,
      result: state.stepAt[index] && result ? result : null,
      at: state.stepAt[index],
    })),
    script,
    versions: state.version,
    can_redraft: state.version < 2,
    chosen_version: state.chosenVersion,
    edited: state.edited,
    wait: state.stage === "publish" ? copy.wait : null,
    measure_body: state.stage === "measuring" ? copy.measureBody : null,
    published_at: null,
    detected: null,
  };
}

/** Approve → reads → bản 1 → "Đang chờ bạn xem kịch bản". */
export function contentUntilChoice(spec: SampleContentSpec): EventDraft[] {
  const copy = SAMPLE_CONTENT_COPY[spec.kind];
  return [
    { event_type: "workflow.started", payload: { workflow_key: `content_${spec.kind}`, product_ref: "sample", prompt_version: "v1" } },
    ...copy.readTools.flatMap(([name, summary], index) => tool(`k${index}`, name, summary)),
    { event_type: "assistant.text", payload: { text: "Đã soạn kịch bản (bản 1) · gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra" } },
    status("Đang chờ bạn xem kịch bản"),
  ];
}

/** Soạn lại → bản 2. */
export function contentRedraft(): EventDraft[] {
  return [
    status("Juli đang soạn lại kịch bản"),
    { event_type: "assistant.text", payload: { text: "Đã soạn kịch bản (bản 2) · gpt-5.4-nano · đầu ra JSON schema · đã kiểm tra" } },
    status("Đang chờ bạn xem kịch bản"),
  ];
}

/** Dùng kịch bản này → waiting for the video / the LIVE. */
export function contentPublishWait(spec: SampleContentSpec): EventDraft[] {
  return [status(SAMPLE_CONTENT_COPY[spec.kind].wait.title)];
}

/** "Tôi đã đăng video" / "Tôi đã LIVE xong" → Juli looks, then measures. */
export function contentPublished(spec: SampleContentSpec): EventDraft[][] {
  const found = spec.kind === "video" ? 'Video mới "7 ngày mặt nạ đất sét" gắn MN-015' : "Phiên 14/10 có bán SM-012";
  return [[started("d1", "find_new_content")], [completed("d1", "find_new_content", found), endDraft("final_response")]];
}

/** Đo lường for a finished sample content run: waiting for the day-7 / first-session reading. */
export function sampleContentMeasurement(completedMs: number, spec: SampleContentSpec): Measurement {
  const kpi = CONTENT_KPI[spec.kind];
  return {
    stage: "waiting",
    dates: { day7: isoDay(completedMs + 7 * DAY_MS), day14: isoDay(completedMs + 14 * DAY_MS) },
    target: { label: kpi.label, current: spec.current, target: spec.target, progress_from: spec.current, unit: "ratio" },
    expected_gmv_per_day: Math.round(spec.gmvMonth / 30),
    bands: [],
    rows: [],
    day7: null,
    final: null,
  };
}
