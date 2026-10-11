import type { AgentEvent, DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";
import { validateAgentEvent } from "@juli/contracts";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  QdApiError,
  declineRun,
  fetchRunMeasurement,
  rejectDecision,
  startRunRevert,
  uploadRunPhoto,
} from "../../lib/quyet-dinh/api-client";
import { cardView } from "../../lib/quyet-dinh/card-model";
import { bandRows, day14Steps, finalBox, measureHead, resultRows, targetBlock } from "../../lib/quyet-dinh/measure-model";
import { kpiPair, rangeText, ratioText, signedVnd, summariseText, upliftChip, validityText } from "../../lib/quyet-dinh/p10-format";
import type { Measurement, P10DecisionItem, RecommendationCardPayload } from "../../lib/quyet-dinh/p10-types";
import { DECLINE_REASONS, REJECT_REASONS, REVERT_REASONS } from "../../lib/quyet-dinh/reasons";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import type { RunChanges, ShopRules } from "../../lib/quyet-dinh/types";
import { submitConfirmationDecision } from "../../lib/run-surface/confirmation-client";
import { ConfirmationRejectedError } from "../../lib/run-surface/confirmation-decision";
import { DoLuongPanel, IDLE_REVERT, type MeasureItem } from "../quyet-dinh/do-luong-panel";
import { ReasonDialog, REJECT_DIALOG_BODY } from "../quyet-dinh/reason-dialog";
import { RecommendationCard } from "../quyet-dinh/recommendation-card";
import { REAL_QD_CLIENTS, SignedInQuyetDinh, type QdClients, type QdQuery } from "../quyet-dinh/signed-in-quyet-dinh";

/**
 * AC-10.3 (ADR-109 Amendment 1, the artboards in
 * docs/product/design/quyet-dinh-flows/): the P10 card from the contract
 * payload, the three reason dialogs (one reason required), consent edits →
 * `edited_values`, the cover-image upload, the Seller Center checklist gate,
 * the measurement stages and the Thu gọn / Mở rộng toggles.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

// -- fixtures -------------------------------------------------------------------------

const CARD: RecommendationCardPayload = {
  seller_sku: "SM-012",
  seller_sku_more: 0,
  product_title: "Son môi số 12",
  workflow_label: "Tối ưu sản phẩm",
  updated_at: "2026-10-09T02:00:00Z",
  status: "pending",
  main_kpi: { key: "ctor", label: "CTOR - Thẻ sản phẩm", current: 0.054, target: 0.059, unit: "ratio" },
  expected_gmv_per_month: 2_100_000,
  reason_short: "Khách thêm giỏ rồi bỏ",
  reason_full: "Đơn/thêm giỏ của sản phẩm thấp hơn 31 % so với trung vị shop (38,9 % so với 56,4 %).",
  tiktok_codes: ["Mô tả quá ngắn"],
  lever: { code: "description", label: "Mô tả", executor: "juli" },
  change_fields: [
    { field: "title", label: "Tiêu đề" },
    { field: "description", label: "Mô tả" },
  ],
  before_after: [
    { field: "title", label: "Tiêu đề", before: "Son môi số 12", after: "Son môi lì cao cấp số 12 — màu đỏ ruby" },
    { field: "description", label: "Mô tả", before: "180 ký tự, một đoạn", after: "640 ký tự, chia mục Thành phần · Cách dùng · Bảo quản" },
  ],
  gmv_method: "lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV, trung bình 30 ngày, ước tính theo quy tắc",
};

function item(id: string, card: Partial<RecommendationCardPayload> | null = {}): P10DecisionItem {
  return {
    id,
    title: "Tối ưu Son môi số 12",
    description: "",
    severity: "high",
    priority: 1,
    computed_at: null,
    surfaced_at: null,
    is_executable: true,
    recommendation: {
      source_kpi_ids: [],
      diagnosis: {
        version: "adr106-v1",
        as_of: "2026-10-09",
        rank: 1,
        status: "rule",
        status_label: "Theo quy tắc",
        stage: { code: "page", label: "Nhấp → Đặt hàng" },
        lever: { code: card?.lever?.code ?? "description", label: "Mô tả", action: "Viết lại mô tả" },
        main_kpi: { key: "ctor", label: "CTOR", value: "5,4 %" },
        trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
        channel_scope: "PRODUCT_CARD",
        recoverable_gmv_per_day: 70_000,
        product_title: card?.product_title ?? "Son môi số 12",
        tiktok_product_id: "1729",
      },
      card: card === null ? undefined : { ...CARD, ...card },
    },
  } as P10DecisionItem;
}

function rules(): ShopRules {
  const unset = { value: null, set_by: null, set_by_user_id: null, set_at: null };
  return {
    stability_band: { ctr: { value: 3, set_by: "seller", set_by_user_id: "u", set_at: "2026-10-08T00:00:00Z" } },
    product_cost: {},
    max_discount_pct: {},
    min_margin_pct: null,
    max_open_cards: { ...unset, value: 30 },
    auto_levers: { ...unset, value: [] },
    protected_terms: { ...unset, value: [] },
    band_metrics: ["ctr"],
    listing_levers: ["title", "description"],
  };
}

const RUN_ID = "11111111-1111-4111-8111-111111111111";

function ev(seq: number, event_type: string, payload: Record<string, unknown>): AgentEvent {
  return validateAgentEvent({
    workflow_run_id: RUN_ID,
    sequence_number: seq,
    event_type,
    timestamp: `2026-10-09T03:01:${String(seq).padStart(2, "0")}Z`,
    payload,
    v: 1,
  });
}

const CHANGE = { title: "Son môi lì cao cấp số 12 — màu đỏ ruby", description: "Thành phần: sáp ong.\nCách dùng: thoa đều.\nBảo quản: nơi khô ráo." };

const CONSENT_RUN: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "tool.started", { tool_call_id: "c0", tool_name: "get_product_diagnoses" }),
  ev(3, "tool.completed", { tool_call_id: "c0", tool_name: "get_product_diagnoses", ok: true, summary: 'Có mã: "Mô tả quá ngắn"' }),
  ev(4, "workflow.approval_required", {
    tool_call_id: "w1",
    tool_name: "update_product_listing",
    proposed_change: CHANGE,
    expires_at: "2099-10-09T07:00:00Z",
    options: [{ option_id: "opt-1", proposed_change: CHANGE, rationale: "Đủ ý", params_sha: "x" }],
  }),
];

const PHOTO_RUN: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "tool.started", { tool_call_id: "p0", tool_name: "inspect_product_image" }),
  ev(3, "tool.completed", { tool_call_id: "p0", tool_name: "inspect_product_image", ok: true, summary: "Nền rối" }),
  ev(4, "workflow.status", { phase_narration: "Đang chờ ảnh từ bạn" }),
];

// P10-B's promotion run, as the backend emits it (planner.py PromotionPlanner).
const MANUAL_RUN: AgentEvent[] = [
  ev(1, "workflow.started", { workflow_key: "optimize_product_2", product_ref: "p", prompt_version: "v3" }),
  ev(2, "tool.started", { tool_call_id: "m0", tool_name: "get_product_information" }),
  ev(3, "tool.completed", { tool_call_id: "m0", tool_name: "get_product_information", ok: true, summary: "Giá 279k" }),
  ev(4, "tool.started", { tool_call_id: "m1", tool_name: "find_product_promotions" }),
  ev(5, "tool.completed", { tool_call_id: "m1", tool_name: "find_product_promotions", ok: true, summary: "Chưa có khuyến mãi" }),
  ev(6, "assistant.text", { text: "Giảm 7 % vẫn trên biên lợi nhuận tối thiểu bạn đặt." }),
  ev(7, "workflow.status", { phase_narration: "Đang chờ bạn áp dụng trên Seller Center" }),
];

// P10-B's cover-photo run after the seller's photo: staged before the consent,
// the consent on `update_product_listing` (ADR-069 order).
const PHOTO_RUN_AT_CONSENT: AgentEvent[] = [
  ...PHOTO_RUN,
  ev(5, "tool.started", { tool_call_id: "p1", tool_name: "upload_product_image" }),
  ev(6, "tool.completed", { tool_call_id: "p1", tool_name: "upload_product_image", ok: true, summary: "Đã tải ảnh" }),
  ev(7, "workflow.approval_required", {
    tool_call_id: "p2",
    tool_name: "update_product_listing",
    expires_at: "2099-10-12T03:00:00Z",
    proposed_change: { attach_staged_image: true },
    options: [{ option_id: "opt-1", proposed_change: { attach_staged_image: true }, rationale: "", params_sha: "x" }],
  }),
];

function run(over: Partial<WorkflowRunListItem> & { awaiting?: string | null } = {}): WorkflowRunListItem {
  return {
    id: RUN_ID,
    status: "waiting_approval",
    stop_reason: null,
    product_name: "Son môi số 12",
    created_at: "2026-10-09T03:00:00Z",
    completed_at: null,
    running_seconds_elapsed: 0,
    latest_narration: null,
    decision_summary: null,
    ...over,
  } as WorkflowRunListItem;
}

function noChanges(): RunChanges {
  return { run_id: RUN_ID, reverts_run_id: null, changes: [], revert: { available: false, reason_code: null, message: null, runs: [] }, question: null };
}

function sse(events: readonly AgentEvent[]): typeof fetch {
  return vi.fn(async () =>
    new Response(events.map((e) => `id: ${e.sequence_number}\nevent: ${e.event_type}\ndata: ${JSON.stringify(e)}\n\n`).join(""), {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    }),
  ) as unknown as typeof fetch;
}

function clients(over: Partial<QdClients> = {}): QdClients {
  return {
    ...REAL_QD_CLIENTS,
    fetchDecisions: vi.fn().mockResolvedValue([item("1")] as DemoDecisionItem[]),
    approve: vi.fn().mockResolvedValue({ runId: RUN_ID }),
    reject: vi.fn().mockResolvedValue({ status: "rejected", cooldown_until: null }),
    fetchRuns: vi.fn().mockResolvedValue([run()]),
    fetchRules: vi.fn().mockResolvedValue(rules()),
    fetchChanges: vi.fn().mockResolvedValue(noChanges()),
    fetchQuestions: vi.fn().mockResolvedValue([]),
    confirm: vi.fn().mockResolvedValue({ decision: "approve", status: "accepted", celeryTaskId: "t" }),
    decline: vi.fn().mockResolvedValue({ status: "declined", cooldown_until: null }),
    uploadPhoto: vi.fn().mockResolvedValue([{ key: "ratio", label: "1:1", ok: true }]),
    fetchInstructions: vi.fn().mockResolvedValue({ steps: ["Bước một", "Bước hai"], deep_link: "https://seller-vn.tiktok.com", summary: "Giá 279k → 259k" }),
    markApplied: vi.fn().mockResolvedValue(undefined),
    fetchMeasurement: vi.fn().mockResolvedValue(null),
    fetchRunDetail: vi.fn().mockResolvedValue(null),
    startRevert: vi.fn().mockResolvedValue({ runId: "rev" }),
    dismissQuestion: vi.fn().mockResolvedValue(undefined),
    streamFetch: sse(CONSENT_RUN),
    ...over,
  };
}

function signedIn(query: Partial<QdQuery>, c: QdClients) {
  const onNavigate = vi.fn();
  render(
    <SignedInQuyetDinh
      clients={c}
      onNavigate={onNavigate}
      query={{ tab: "de-xuat", run: null, rulesOpen: false, ...query }}
      shop={{ id: "shop-1", name: "Shop" }}
      token="tok"
    />,
  );
  return onNavigate;
}

// -- formats ------------------------------------------------------------------------

describe("artboard number formats", () => {
  it("prints figures the way the artboards do", () => {
    expect(ratioText(0.054)).toBe("5,4 %");
    expect(ratioText(0.0444)).toBe("4,44 %");
    expect(ratioText(0.06)).toBe("6,0 %");
    expect(upliftChip(0.054, 0.059)).toBe("▲ 9,3 %");
    expect(kpiPair(182_000, 205_000, "vnd")).toBe("182k → 205k ₫");
    expect(signedVnd(2_100_000)).toBe("+2,1 tr ₫");
    expect(signedVnd(-6_000)).toBe("−6k ₫");
    expect(rangeText(9613, 10207, "count")).toBe("9.613 – 10.207");
    expect(rangeText(155_000, 165_000, "vnd")).toBe("155k – 165k ₫");
    expect(rangeText(0.0431, 0.0457, "ratio")).toBe("4,31 % – 4,57 %");
    expect(validityText("2026-10-09T07:00:00Z", Date.parse("2026-10-09T03:02:00Z"))).toBe("Còn hiệu lực 3 giờ 58 phút");
    expect(summariseText("Thành phần: a.\nCách dùng: b.\nBảo quản: c. " + "x".repeat(80), "after")).toMatch(/^\d+ ký tự · Thành phần · Cách dùng · Bảo quản$/);
  });
});

// -- card ---------------------------------------------------------------------------

function renderCard(props: Partial<React.ComponentProps<typeof RecommendationCard>> = {}) {
  const handlers = { onToggle: vi.fn(), onApprove: vi.fn(), onReject: vi.fn() };
  const view = cardView(item("1"));
  render(
    <RecommendationCard
      card={view}
      expanded={false}
      narrow={false}
      progressHref="/decisions?tab=dang-thuc-hien&run=r1"
      status="pending"
      {...handlers}
      {...props}
    />,
  );
  return handlers;
}

describe("the recommendation card (Main.dc.html)", () => {
  it("collapsed: SKU, name, workflow · date, status chip, KPI current → target, GMV/tháng, reason, field chips", async () => {
    const handlers = renderCard();
    const card = screen.getByTestId("recommendation-card");
    expect(card).toHaveTextContent("SKU · SM-012");
    expect(within(card).getByRole("heading", { level: 3 })).toHaveTextContent("Son môi số 12");
    expect(card).toHaveTextContent("Tối ưu sản phẩm · Cập nhật 09/10/2026");
    expect(within(card).getByTestId("card-status")).toHaveTextContent("Chờ duyệt");
    expect(card).toHaveTextContent("CTOR - Thẻ sản phẩm");
    expect(card).toHaveTextContent("5,4 %");
    expect(card).toHaveTextContent("5,9 %");
    expect(card).toHaveTextContent("▲ 9,3 %");
    expect(card).toHaveTextContent("+2,1 tr ₫/tháng");
    expect(card).toHaveTextContent("Khách thêm giỏ rồi bỏ");
    expect(card).not.toHaveTextContent("Lý do đầy đủ");
    expect(within(card).queryByTestId("executor-chip")).toBeNull();
    await userEvent.click(within(card).getByRole("button", { name: "Xem thêm" }));
    expect(handlers.onToggle).toHaveBeenCalled();
    await userEvent.click(within(card).getByRole("button", { name: "Phê duyệt" }));
    expect(handlers.onApprove).toHaveBeenCalled();
    await userEvent.click(within(card).getByRole("button", { name: "Từ chối" }));
    expect(handlers.onReject).toHaveBeenCalled();
  });

  it("Xem thêm: full reason with TikTok's code, before → after per field, the GMV method", () => {
    renderCard({ expanded: true });
    const more = screen.getByRole("region", { name: "Chi tiết đề xuất" });
    expect(more).toHaveTextContent(
      "Đơn/thêm giỏ của sản phẩm thấp hơn 31 % so với trung vị shop (38,9 % so với 56,4 %). TikTok báo mã chẩn đoán: “Mô tả quá ngắn”.",
    );
    expect(more).toHaveTextContent("Trước: Son môi số 12");
    expect(more).toHaveTextContent("Sau: Son môi lì cao cấp số 12 — màu đỏ ruby");
    expect(more).toHaveTextContent("Hiện tại: 180 ký tự, một đoạn.");
    expect(more).toHaveTextContent("Đề xuất: 640 ký tự, chia mục Thành phần · Cách dùng · Bảo quản.");
    expect(more).toHaveTextContent("GMV dự kiến tính theo cách của TikTok: lượt bấm × (CTOR mục tiêu − CTOR hiện tại) × AOV");
    expect(screen.getByRole("button", { name: "Thu gọn" })).toHaveAttribute("aria-expanded", "true");
    expect(screen.queryByTestId("adjusted-by-history")).toBeNull();
  });

  it("P14-B: a card ranked by the shop's history says so under Xem thêm", () => {
    const view = cardView(item("1", { adjusted_by_history: true }));
    expect(view.adjustedByHistory).toBe(true);
    render(
      <RecommendationCard card={view} expanded narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />,
    );
    expect(screen.getByTestId("adjusted-by-history")).toHaveTextContent("đã điều chỉnh theo kết quả trước");
  });

  it("P17: a quick-scan card shows its label chip and confidence 'Tham khảo' near the GMV", () => {
    const quick = {
      label: "Đề xuất nhanh · dựa trên 14 ngày",
      confidence: "Tham khảo",
      window_days: 14,
      basis: "GMV dự kiến theo công thức D22 trên 14 ngày gần nhất",
    };
    const view = cardView(item("q1", { quick_scan: quick }));
    expect(view.quickScan).toEqual({ label: quick.label, confidence: "Tham khảo", basis: quick.basis });
    for (const narrow of [false, true]) {
      const { unmount } = render(
        <RecommendationCard card={view} expanded={false} narrow={narrow} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />,
      );
      expect(screen.getByTestId("quick-scan-chip")).toHaveTextContent("Đề xuất nhanh · dựa trên 14 ngày");
      expect(screen.getByTestId("quick-scan-confidence")).toHaveTextContent("Độ tin cậy: Tham khảo");
      unmount();
    }
  });

  it("P17: a full card (no quick_scan, or null) shows no quick chip", () => {
    for (const card of [{}, { quick_scan: null }]) {
      const view = cardView(item("f1", card));
      expect(view.quickScan).toBeNull();
      const { unmount } = render(
        <RecommendationCard card={view} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />,
      );
      expect(screen.queryByTestId("quick-scan-chip")).toBeNull();
      expect(screen.queryByTestId("quick-scan-confidence")).toBeNull();
      unmount();
    }
  });

  it("status chips per state; approved shows the blue notice with Xem tiến độ ›, rejected the grey one", () => {
    const { unmount } = render(
      <RecommendationCard card={cardView(item("1"))} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref="/x" status="running" />,
    );
    expect(screen.getByTestId("card-status")).toHaveTextContent("Đang thực hiện");
    expect(screen.getByRole("status")).toHaveTextContent("Đã tạo lượt chạy. Juli đọc chẩn đoán TikTok và soạn nội dung");
    expect(screen.getByRole("link", { name: "Xem tiến độ ›" })).toHaveAttribute("href", "/x");
    expect(screen.queryByRole("button", { name: "Phê duyệt" })).toBeNull();
    unmount();
    renderCard({ status: "rejected" });
    expect(screen.getByTestId("card-status")).toHaveTextContent("Đã từ chối");
    expect(screen.getByRole("status")).toHaveTextContent("Đã từ chối. Juli không thay đổi gì trên sản phẩm này.");
    cleanup();
    // Rejected in this visit (a0382006): the green completion message with the picked reason.
    render(
      <RecommendationCard card={cardView(item("1"))} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} rejectReason="other_campaign" status="rejected" />,
    );
    const done = screen.getByTestId("reason-done");
    expect(done).toHaveTextContent("Hoàn thành · đã từ chối thẻ");
    expect(done).toHaveTextContent("Đang chạy chiến dịch khác cho sản phẩm này");
    expect(done).toHaveTextContent("Lý do giúp Juli đưa ra đề xuất tốt hơn: Juli chờ chiến dịch kết thúc để không lẫn kết quả.");
    expect(done).toHaveTextContent("Juli không đề xuất lại cùng thay đổi cho sản phẩm này trong 7 ngày.");
    expect(done).toHaveTextContent("Chỗ trống trong Đề xuất được dành cho sản phẩm có GMV tiềm năng kế tiếp.");
    for (const [status, label] of [["applied", "Đã áp dụng"], ["expired", "Hết hạn"]] as const) {
      const { container } = render(
        <RecommendationCard card={cardView(item("1"))} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status={status} />,
      );
      expect(within(container).getByTestId("card-status")).toHaveTextContent(label);
    }
  });

  it("Levers: photo and Seller Center cards carry the executor chip and what happens after Phê duyệt", () => {
    const photo = cardView(item("2", { lever: { code: "cover_image", label: "Ảnh bìa", executor: "juli_with_photo" } }));
    const { unmount } = render(
      <RecommendationCard card={photo} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />,
    );
    expect(screen.getByTestId("executor-chip")).toHaveTextContent("Juli tải lên — cần ảnh từ bạn");
    expect(screen.getByTestId("recommendation-card")).toHaveTextContent("Phê duyệt → Juli hỏi ảnh → bạn tải ảnh → xác nhận → Juli thay ảnh bìa.");
    unmount();
    const promo = cardView(item("3", { lever: { code: "product_discount", label: "Giảm giá sản phẩm", executor: "seller_center" } }));
    render(<RecommendationCard card={promo} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />);
    expect(screen.getByTestId("executor-chip")).toHaveTextContent("Bạn thực hiện trên Seller Center");
    expect(screen.getByRole("button", { name: "Phê duyệt" })).toBeEnabled();
  });

  it("Mobile.dc.html below 768 px: stacked KPI, inline before → after, two-column buttons, Xem thêm ›", () => {
    renderCard({ narrow: true });
    const card = screen.getByTestId("recommendation-card");
    expect(card).toHaveClass("qv-card--mobile");
    expect(card).toHaveTextContent("Chỉ số chính · CTOR Thẻ sản phẩm");
    expect(card).toHaveTextContent("5,4 % → 5,9 %");
    expect(card).toHaveTextContent("ước tính");
    expect(card).toHaveTextContent("Khách thêm giỏ rồi bỏ: Đơn/thêm giỏ của sản phẩm thấp hơn 31 % so với trung vị shop");
    expect(card).toHaveTextContent("Tiêu đề: “Son môi số 12” → “Son môi lì cao cấp số 12 — màu đỏ ruby”");
    expect(card).toHaveTextContent("Mô tả: 180 → 640 ký tự, chia mục Thành phần · Cách dùng · Bảo quản");
    expect(screen.getByRole("button", { name: "Xem thêm ›" })).toBeInTheDocument();
  });

  it("degrades to the P7-B diagnosis when the backend sends no card yet", () => {
    const view = cardView(item("9", null));
    expect(view.fromContract).toBe(false);
    expect(view.sku).toBeNull();
    expect(view.kpiCurrent).toBe("5,4 %");
    expect(view.kpiTarget).toBeNull();
    expect(view.gmvPerMonth).toBe("+2,1 tr ₫/tháng");
    expect(view.reasonShort).toBe("Thấp hơn trung vị shop");
  });

  it("Từ chối from Đề xuất posts the chosen reason and the card turns Đã từ chối", async () => {
    const c = clients();
    signedIn({}, c);
    const card = await screen.findByTestId("recommendation-card");
    await userEvent.click(within(card).getByRole("button", { name: "Từ chối" }));
    const dialog = screen.getByRole("dialog", { name: "Từ chối thẻ này?" });
    await userEvent.click(within(dialog).getByRole("radio", { name: "Sản phẩm sắp ngừng bán hoặc hết hàng" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Từ chối thẻ" }));
    await waitFor(() => expect(within(card).getByTestId("card-status")).toHaveTextContent("Đã từ chối"));
    expect(c.reject).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, "1", { reason_code: "discontinued" });
  });

  it("Phê duyệt on one card shows the notice in place (no navigation)", async () => {
    const c = clients();
    const onNavigate = signedIn({}, c);
    const card = await screen.findByTestId("recommendation-card");
    await userEvent.click(within(card).getByRole("button", { name: "Phê duyệt" }));
    await waitFor(() => expect(within(card).getByTestId("card-status")).toHaveTextContent("Đang thực hiện"));
    expect(within(card).getByRole("link", { name: "Xem tiến độ ›" })).toHaveAttribute("href", `/decisions?tab=dang-thuc-hien&run=${RUN_ID}`);
    expect(onNavigate).not.toHaveBeenCalled();
  });
});

// -- reason dialogs ------------------------------------------------------------------

describe("reason dialogs (Decline.dc.html, Revert.dc.html)", () => {
  it.each([
    ["reject", "Từ chối thẻ này?", "Từ chối thẻ", "Quay lại", REJECT_REASONS],
    ["skip", "Không thực hiện thay đổi này?", "Đồng ý", "Quay lại", DECLINE_REASONS],
    ["revert", "Hoàn tác thay đổi này?", "Bắt đầu hoàn tác", "Huỷ, giữ thay đổi", REVERT_REASONS],
  ] as const)("%s: exact labels, one reason required, optional note, cancel does nothing", async (mode, title, submit, cancel, reasons) => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();
    render(<ReasonDialog body={REJECT_DIALOG_BODY} mode={mode} onCancel={onCancel} onSubmit={onSubmit} open />);
    const dialog = screen.getByRole("dialog", { name: title });
    expect(within(dialog).getAllByRole("radio").map((radio) => radio.closest("label")?.textContent)).toEqual(reasons.map((r) => r.label));
    // a0382006: "(chọn một)" on Từ chối / Không thực hiện; the note moved to the completion message.
    expect(dialog).toHaveTextContent(mode === "revert" ? "(chọn một · bắt buộc)" : "(chọn một)");
    if (mode !== "revert") expect(dialog).not.toHaveTextContent("chọn một · bắt buộc");
    expect(dialog).not.toHaveTextContent("Lý do giúp Juli");
    expect(dialog).not.toHaveTextContent("Để sau");
    const button = within(dialog).getByRole("button", { name: submit });
    expect(button).toBeDisabled();
    await userEvent.click(button);
    expect(onSubmit).not.toHaveBeenCalled();
    await userEvent.click(within(dialog).getByRole("radio", { name: reasons[1].label }));
    expect(button).toBeEnabled();
    await userEvent.click(button);
    expect(onSubmit).toHaveBeenLastCalledWith({ reason_code: reasons[1].code });
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Ghi chú thêm/ }), "  ghi chú  ");
    await userEvent.click(button);
    expect(onSubmit).toHaveBeenLastCalledWith({ reason_code: reasons[1].code, note: "ghi chú" });
    await userEvent.click(within(dialog).getByRole("button", { name: cancel }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("reason codes are the contract's", () => {
    expect(REJECT_REASONS.map((r) => r.code)).toEqual(["brand_mismatch", "not_convincing", "editing_myself", "discontinued", "other_campaign", "other"]);
    expect(DECLINE_REASONS.map((r) => r.code)).toEqual(["wrong_info", "tone", "too_much_change", "changed_mind", "other"]);
    expect(REVERT_REASONS.map((r) => r.code)).toEqual(["metrics_dropped", "bad_feedback", "wrong_info", "off_brand", "tiktok_warning", "other"]);
  });
});

// -- Đang thực hiện ----------------------------------------------------------------

describe("consent with an edit (Run.dc.html)", () => {
  it("✎ Sửa nội dung → Lưu bản sửa marks 'Bạn đã sửa' and Xác nhận sends edited_values", async () => {
    const c = clients();
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    const consent = await screen.findByTestId("consent-block");
    expect(consent).toHaveTextContent("Juli đề xuất thay đổi sau — chọn rồi xác nhận");
    const confirm = within(consent).getByRole("button", { name: "Xác nhận thay đổi này" });
    expect(confirm).toBeDisabled();
    await userEvent.click(within(consent).getByRole("button", { name: "✎ Sửa nội dung trước khi áp dụng" }));
    const title = screen.getByLabelText("Tiêu đề (bạn sửa)");
    await userEvent.clear(title);
    await userEvent.type(title, "Son môi lì số 12 — màu đỏ ruby");
    await userEvent.click(screen.getByRole("button", { name: "Lưu bản sửa" }));
    expect(consent).toHaveTextContent("Bạn đã sửa");
    expect(consent).toHaveTextContent("Son môi lì số 12 — màu đỏ ruby");
    await userEvent.click(within(consent).getByRole("button", { name: "Xác nhận thay đổi này" }));
    await waitFor(() =>
      expect(c.confirm).toHaveBeenCalledWith(RUN_ID, "w1", "approve", "opt-1", {
        token: "tok",
        shopId: "shop-1",
        editedValues: { title: "Son môi lì số 12 — màu đỏ ruby" },
      }),
    );
  });

  it("a 422 rule_violation reopens the edit with the backend's sentence", async () => {
    const c = clients({
      confirm: vi.fn().mockRejectedValue(new ConfirmationRejectedError(422, "rule_violation", "Tiêu đề dài quá 255 ký tự.", "title")),
    });
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    const consent = await screen.findByTestId("consent-block");
    await userEvent.click(consent.querySelector(".qv-option") as HTMLElement);
    await userEvent.click(within(consent).getByRole("button", { name: "Xác nhận thay đổi này" }));
    expect(await screen.findByTestId("edit-panel")).toHaveTextContent("Tiêu đề dài quá 255 ký tự.");
  });

  it("Không thực hiện opens the decline dialog and posts the reason", async () => {
    const c = clients();
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    await userEvent.click(await screen.findByRole("button", { name: "Không thực hiện" }));
    const dialog = screen.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    await userEvent.click(within(dialog).getByRole("radio", { name: "Thay đổi quá nhiều so với hiện tại" }));
    expect(dialog).toHaveTextContent("Khi đồng ý, gợi ý sẽ không quay lại");
    await userEvent.click(within(dialog).getByRole("button", { name: "Đồng ý" }));
    await waitFor(() => expect(c.decline).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, RUN_ID, { reason_code: "too_much_change" }));
    const done = await screen.findByTestId("reason-done");
    expect(done).toHaveTextContent("Hoàn thành · không thực hiện thay đổi");
    expect(done).toHaveTextContent("Lý do bạn chọnThay đổi quá nhiều so với hiện tại");
    expect(done).toHaveTextContent("Lý do giúp Juli đưa ra đề xuất tốt hơn: Juli đề xuất thay đổi nhỏ hơn, giữ phần bạn đã viết.");
    expect(done).toHaveTextContent("Không có gì được ghi lên TikTok Shop. Lần sau chỉ muốn sửa vài chữ, chọn Sửa nội dung ở bước xác nhận.");
    expect(done).toHaveTextContent("Thẻ không quay lại Đề xuất ngay. Juli có thể đề xuất lại sản phẩm này sau 7 ngày với nội dung mới.");
  });

  it("Thu gọn / Mở rộng collapses the run to its name and status", async () => {
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, clients());
    const panel = await screen.findByTestId("run-detail");
    await screen.findByTestId("run-timeline");
    const toggle = within(panel).getByRole("button", { name: "Thu gọn" });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(toggle);
    expect(within(panel).queryByTestId("run-timeline")).toBeNull();
    expect(within(panel).getByRole("button", { name: "Mở rộng" })).toHaveAttribute("aria-expanded", "false");
    expect(within(panel).getByTestId("run-chip")).toHaveTextContent("Đang chờ bạn");
  });
});

describe("cover image (RunPhoto.dc.html)", () => {
  it("awaiting photo: requirements, file picker → POST photo, the checks shown; wrong type refused locally", async () => {
    const c = clients({
      fetchRuns: vi.fn().mockResolvedValue([run({ status: "waiting_external", awaiting: "photo" })]),
      streamFetch: sse(PHOTO_RUN),
    });
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    const request = await screen.findByTestId("photo-request");
    expect(request).toHaveTextContent("Tỉ lệ 1:1, tối thiểu 800 × 800 px");
    // The page heading follows the selected run's kind, reported after its first render.
    await waitFor(() => expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Juli tải ảnh của bạn lên TikTok Shop"));
    const input = screen.getByTestId("photo-input") as HTMLInputElement;
    await userEvent.upload(input, new File(["gif"], "a.gif", { type: "image/gif" }), { applyAccept: false });
    expect(within(request).getByRole("alert")).toHaveTextContent("Ảnh cần là JPG hoặc PNG.");
    expect(c.uploadPhoto).not.toHaveBeenCalled();
    const file = new File(["png"], "a.png", { type: "image/png" });
    await userEvent.upload(input, file);
    await waitFor(() => expect(c.uploadPhoto).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, RUN_ID, file));
    expect(await screen.findByTestId("photo-checks")).toHaveTextContent("✓ 1:1");
  });

  it("the consent shows the before/after photos from the run detail (P10-B stores them, not the payload)", async () => {
    const c = clients({
      fetchRuns: vi.fn().mockResolvedValue([run({ status: "waiting_approval", awaiting: null })]),
      streamFetch: sse(PHOTO_RUN_AT_CONSENT),
      fetchDecisions: vi.fn().mockResolvedValue([item("1", { lever: { code: "cover_image", label: "Ảnh bìa", executor: "juli_with_photo" } })]),
      fetchRunDetail: vi.fn().mockResolvedValue({
        id: RUN_ID,
        status: "waiting_approval",
        awaiting: null,
        awaiting_expires_at: null,
        decision_id: "1",
        lever: { code: "cover_image", kind: "photo" },
        photo: {
          before_url: "/v1/demo/photos/shop-1/before-token",
          after_url: "/v1/demo/photos/shop-1/after-token",
          checks: [{ key: "square", label: "Tỉ lệ 1:1", ok: true }],
        },
        promotion: null,
      }),
    });
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    expect(await screen.findByRole("img", { name: "Ảnh bìa hiện tại" })).toHaveAttribute("src", "/v1/demo/photos/shop-1/before-token");
    expect(screen.getByRole("img", { name: "Ảnh bạn gửi" })).toHaveAttribute("src", "/v1/demo/photos/shop-1/after-token");
    expect(c.fetchRunDetail).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, RUN_ID);
  });

  it("422 failing checks are listed", async () => {
    const c = clients({
      fetchRuns: vi.fn().mockResolvedValue([run({ status: "waiting_external", awaiting: "photo" })]),
      streamFetch: sse(PHOTO_RUN),
      uploadPhoto: vi.fn().mockRejectedValue(new QdApiError(422, null, null, { checks: [{ key: "size", label: "≥ 800 px", ok: false }] })),
    });
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    await screen.findByTestId("photo-request");
    await userEvent.upload(screen.getByTestId("photo-input") as HTMLInputElement, new File(["png"], "a.png", { type: "image/png" }));
    expect(await screen.findByTestId("photo-checks")).toHaveTextContent("✗ ≥ 800 px");
    expect(screen.getByText("Ảnh chưa đạt yêu cầu. Vui lòng chọn ảnh khác.")).toBeInTheDocument();
  });
});

describe("promotion on Seller Center (RunManual.dc.html)", () => {
  it("checklist gates 'Tôi đã áp dụng' → POST applied → verifying; no Hoàn tác", async () => {
    const c = clients({
      fetchRuns: vi.fn().mockResolvedValue([run({ status: "waiting_external", awaiting: "seller_action" })]),
      streamFetch: sse(MANUAL_RUN),
    });
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    const guide = await screen.findByTestId("seller-guide");
    await waitFor(() => expect(guide).toHaveTextContent("Làm theo 2 bước trên Seller Center"));
    expect(within(guide).getByRole("link", { name: "Mở Seller Center ↗" })).toHaveAttribute("href", "https://seller-vn.tiktok.com");
    const applied = within(guide).getByRole("button", { name: "Tôi đã áp dụng" });
    const boxes = within(guide).getAllByRole("checkbox");
    await userEvent.click(boxes[0]);
    expect(applied).toBeDisabled();
    await userEvent.click(boxes[1]);
    expect(applied).toBeEnabled();
    await userEvent.click(applied);
    await waitFor(() => expect(c.markApplied).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, RUN_ID));
    expect(await screen.findByText("Juli đang tìm khuyến mãi trên TikTok Shop để xác nhận…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Hoàn tác/ })).toBeNull();
  });

  it("Không áp dụng at the seller step posts a decline and joins the card by decision_id", async () => {
    const c = clients({
      fetchRuns: vi.fn().mockResolvedValue([
        run({ status: "waiting_external", awaiting: "seller_action", product_name: "Tên khác trên TikTok", decision_id: "1" }),
      ]),
      streamFetch: sse(MANUAL_RUN),
      fetchDecisions: vi.fn().mockResolvedValue([
        item("1", { seller_sku: "SM-012", lever: { code: "product_discount", label: "Giảm giá sản phẩm", executor: "seller_center" } }),
      ]),
    });
    signedIn({ tab: "dang-thuc-hien", run: RUN_ID }, c);
    const panel = await screen.findByTestId("run-detail");
    // Joined by id although the run's product name differs from the card's title.
    await waitFor(() => expect(within(panel).getByRole("heading", { level: 2 })).toHaveTextContent("SM-012"));
    const guide = await screen.findByTestId("seller-guide");
    const skip = within(guide).queryAllByRole("button").find((button) => /Không/.test(button.textContent ?? ""));
    expect(skip).toBeDefined();
    await userEvent.click(skip!);
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getAllByRole("radio")[0]);
    const submit = within(dialog).getAllByRole("button").find((button) => button.textContent !== "Huỷ" && !/Quay lại|Huỷ/.test(button.textContent ?? ""));
    await userEvent.click(submit!);
    await waitFor(() => expect(c.decline).toHaveBeenCalledWith({ token: "tok", shopId: "shop-1" }, RUN_ID, expect.objectContaining({ reason_code: expect.any(String) })));
  });

  it("the manual timeline puts the seller's step between Juli's, with Juli / Bạn tags", () => {
    const timeline = buildRunTimeline(MANUAL_RUN, { kind: "manual", awaiting: "seller_action" });
    expect(timeline.steps.map((step) => [step.label, step.status, step.who])).toEqual([
      ["Đọc giá và khuyến mãi hiện có", "done", "juli"],
      ["Kiểm tra quy tắc bạn đặt", "done", "juli"],
      ["Soạn hướng dẫn", "done", "juli"],
      ["Áp dụng trên Seller Center", "current", "you"],
      ["Kiểm tra trên TikTok", "upcoming", "juli"],
      ["Kết thúc · đặt lịch đo", "upcoming", "juli"],
    ]);
  });

  it("verification reads after the pause land on Kiểm tra trên TikTok", () => {
    const after: AgentEvent[] = [
      ...MANUAL_RUN,
      ev(8, "tool.started", { tool_call_id: "m2", tool_name: "find_product_promotions" }),
      ev(9, "tool.completed", { tool_call_id: "m2", tool_name: "find_product_promotions", ok: true, summary: "Đã thấy" }),
    ];
    const timeline = buildRunTimeline(after, { kind: "manual", awaiting: null });
    const rows = Object.fromEntries(timeline.steps.map((step) => [step.label, step.status]));
    expect(rows["Đọc giá và khuyến mãi hiện có"]).toBe("done");
    expect(rows["Kiểm tra trên TikTok"]).toBe("done");
    expect(timeline.steps.filter((step) => step.label === "Bước xử lý")).toEqual([]);
  });
});

describe("cover photo timeline against P10-B's tool order", () => {
  it("the staged upload before the consent is not the write", () => {
    const timeline = buildRunTimeline(PHOTO_RUN_AT_CONSENT, { kind: "photo", awaiting: null });
    const rows = Object.fromEntries(timeline.steps.map((step) => [step.label, step.status]));
    expect(rows["Xác nhận một lần"]).toBe("current");
    expect(rows["Tải ảnh lên TikTok Shop"]).toBe("upcoming");
    expect(timeline.steps.filter((step) => step.label === "Bước xử lý")).toEqual([]);
    expect(timeline.pendingConsent?.toolName).toBe("update_product_listing");
  });
});

// -- Đo lường -----------------------------------------------------------------------

function measurement(stage: Measurement["stage"], over: Partial<Measurement> = {}): Measurement {
  return {
    stage,
    dates: { day7: "2026-10-16", day14: "2026-10-23" },
    target: { label: "CTOR Thẻ sản phẩm", current: 0.054, target: 0.059, progress_from: 0.055, unit: "ratio" },
    expected_gmv_per_day: 70_000,
    bands: [
      { key: "impressions", label: "Lượt hiển thị/ngày", before: 9910, band_pct: 3, low: 9613, high: 10207, unit: "count" },
      { key: "aov", label: "AOV", before: 160_000, band_pct: 3, low: 155_000, high: 165_000, unit: "vnd" },
    ],
    rows:
      stage === "waiting"
        ? []
        : [
            { key: "ctor", label: "CTOR (chỉ số chính)", before: 0.054, expected: "5,9 %", actual: 0.057, verdict: "Đang tăng", tone: "ok" },
            { key: "impressions", label: "Lượt hiển thị/ngày", before: 9910, expected: "9.613 – 10.207", actual: 10029, verdict: "Ổn định", tone: "muted" },
            { key: "aov", label: "AOV", before: 160_000, expected: "155k – 165k ₫", actual: 152_000, verdict: "Ngoài khoảng", tone: "warn" },
          ],
    day7: stage === "waiting" ? null : { within_band: false, question_id: "q-1" },
    final: null,
    ...over,
  };
}

describe("measurement model (Measure.dc.html, Day7, Day14)", () => {
  it("target, band table and result rows as the artboards print them", () => {
    const m = measurement("day7");
    expect(targetBlock(m)).toEqual({
      label: "Chỉ số mục tiêu · CTOR Thẻ sản phẩm",
      pair: "5,4 % → 5,9 %",
      note: "Đạt khi ≥ 5,9 %; đang tiến triển từ 5,5 % trở lên",
      gmv: "+70k ₫/ngày · +2,1 tr ₫/tháng",
    });
    expect(bandRows(m)[0]).toEqual({ key: "impressions", label: "Lượt hiển thị/ngày", before: "9.910", band: "±3 %", range: "9.613 – 10.207" });
    expect(resultRows(m).map((row) => row.actual)).toEqual(["5,7 %", "10.029 (+1,2 %)", "152k ₫ (−5,0 %)"]);
    expect(measureHead(m).chip).toEqual({ label: "Ngày 7 · cần bạn quyết", tone: "warn" });
    expect(measureHead(measurement("waiting")).headline).toBe("Đang chờ dữ liệu sau khi áp dụng");
  });

  it("day-14 boxes per label; calibration not updated for Chưa kết luận", () => {
    const final = (label: "dat" | "gan_dat" | "khong_dat" | "chua_ket_luan") =>
      measurement("final", { final: { label, gmv_actual_per_day: 57_000, pct_of_expected: 82, calibration: label === "chua_ket_luan" ? null : { lever: "description", from: 0.5, to: 0.58 } } });
    expect(finalBox(final("gan_dat"), "Mô tả")).toMatchObject({ tone: "info", title: "Gần đạt: 82 % mức kỳ vọng", offerRevert: false });
    expect(finalBox(final("khong_dat"), "Mô tả")).toMatchObject({ tone: "warn", offerRevert: true, next: "Xem đề xuất khác cho sản phẩm này ›" });
    expect(finalBox(final("dat"), "Mô tả")?.tone).toBe("ok");
    expect(finalBox(final("chua_ket_luan"), "Mô tả")?.tone).toBe("muted");
    expect(day14Steps(final("gan_dat"), "Mô tả")[4]).toMatchObject({ label: 'Cập nhật mức kỳ vọng cho loại "Mô tả"', result: "Hệ số hiệu chỉnh 0,50 → 0,58" });
    expect(day14Steps(final("chua_ket_luan"), "Mô tả")[4].result).toBe("Hệ số hiệu chỉnh Giữ nguyên");
  });
});

function measureItem(m: Measurement | null): MeasureItem {
  return {
    run: run({ status: "completed", stop_reason: "final_response", completed_at: "2026-10-09T03:47:31Z" }),
    card: cardView(item("1")),
    changes: { status: "ready", changes: { ...noChanges(), revert: { available: true, reason_code: null, message: null, runs: [] } } },
    measurement: { status: "ready", measurement: m },
    question: null,
    action: IDLE_REVERT,
  };
}

describe("Đo lường panel", () => {
  it("the tabs follow measurement.stage; day 7 outside the band asks Hoàn tác? with a reason dialog", async () => {
    const onRevert = vi.fn();
    const onKeep = vi.fn();
    const items = [measureItem(measurement("day7"))];
    const { rerender } = render(
      <DoLuongPanel items={items} nowMs={null} onKeep={onKeep} onOpenProposals={vi.fn()} onOpenRun={vi.fn()} onRevert={onRevert} onTab={vi.fn()} proposalsHref="/d" tab="d7" />,
    );
    expect(screen.getByRole("tab", { name: "Ngày 7 · kiểm tra" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("measure-target")).toHaveTextContent("Mục tiêu và ngưỡng dao động");
    expect(screen.getByTestId("day7-steps")).toHaveTextContent("Hỏi bạn: Hoàn tác?");
    const ask = screen.getByTestId("day7-ask");
    expect(ask).toHaveTextContent("AOV còn 152k ₫ (−5,0 %), ngoài khoảng 155k – 165k ₫ bạn cho phép. Juli không tự hoàn tác — bạn quyết định.");
    await userEvent.click(within(ask).getByRole("button", { name: "Giữ thay đổi" }));
    expect(onKeep).toHaveBeenCalled();
    await userEvent.click(within(ask).getByRole("button", { name: "Hoàn tác" }));
    await userEvent.click(screen.getByRole("radio", { name: "Không hợp giọng thương hiệu" }));
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu hoàn tác" }));
    expect(onRevert).toHaveBeenCalledWith(items[0], { reason_code: "off_brand" });

    rerender(
      <DoLuongPanel items={items} nowMs={null} onKeep={onKeep} onOpenProposals={vi.fn()} onOpenRun={vi.fn()} onRevert={onRevert} onTab={vi.fn()} proposalsHref="/d" tab="d0" />,
    );
    expect(screen.getByTestId("measure-list")).toHaveTextContent("Chưa có thay đổi nào ở mốc này.");
  });

  it("waiting: the waiting line and a Hoàn tác at the foot; Thu gọn collapses to name + status", async () => {
    render(
      <DoLuongPanel
        items={[measureItem(measurement("waiting"))]}
        nowMs={null}
        onKeep={vi.fn()}
        onOpenProposals={vi.fn()}
        onOpenRun={vi.fn()}
        onRevert={vi.fn()}
        onTab={vi.fn()}
        proposalsHref="/d"
        tab="d0"
      />,
    );
    const panel = screen.getByTestId("measure-panel");
    expect(screen.getByTestId("measure-waiting")).toHaveTextContent("Đang chờ đủ 7 ngày dữ liệu · Kết quả ngày 16/10/2026.");
    expect(within(panel).getByTestId("measure-chip")).toHaveTextContent("Chờ đo · ngày 0");
    expect(within(panel).getByRole("button", { name: "Hoàn tác" })).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Thu gọn" }));
    expect(within(panel).queryByTestId("measure-target")).toBeNull();
    expect(within(panel).getByRole("heading", { level: 2 })).toHaveTextContent("Son môi số 12");
    expect(within(panel).getByRole("button", { name: "Mở rộng" })).toBeInTheDocument();
  });
});

// -- clients ----------------------------------------------------------------------------

function capture(status = 200, body: unknown = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fetchImpl = vi.fn(async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return { calls, fetchImpl };
}

describe("P10 clients", () => {
  it("reject / decline / revert send exactly {reason_code, note?}", async () => {
    const a = capture(200, { status: "rejected", cooldown_until: null });
    await rejectDecision({ token: "t", shopId: "s", fetchImpl: a.fetchImpl }, "d1", { reason_code: "other", note: " x " });
    expect(a.calls[0].url).toBe("/v1/demo/decisions/d1/reject");
    expect(JSON.parse(a.calls[0].init.body as string)).toEqual({ reason_code: "other", note: "x" });
    const b = capture(200, { status: "declined" });
    await declineRun({ token: "t", shopId: "s", fetchImpl: b.fetchImpl }, "r1", { reason_code: "tone" });
    expect(b.calls[0].url).toBe("/v1/demo/runs/r1/decline");
    expect(JSON.parse(b.calls[0].init.body as string)).toEqual({ reason_code: "tone" });
    const c = capture(202, { success: true, data: { run_id: "new" } });
    await expect(startRunRevert({ token: "t", shopId: "s", fetchImpl: c.fetchImpl }, "r1", { reason_code: "metrics_dropped" })).resolves.toEqual({ runId: "new" });
    expect(JSON.parse(c.calls[0].init.body as string)).toEqual({ reason_code: "metrics_dropped" });
  });

  it("photo upload is multipart; measurement 404 means not deployed", async () => {
    const a = capture(202, { checks: [{ key: "ratio", label: "1:1", ok: true }] });
    const checks = await uploadRunPhoto({ token: "t", shopId: "s", fetchImpl: a.fetchImpl }, "r1", new File(["x"], "a.png", { type: "image/png" }));
    expect(checks).toEqual([{ key: "ratio", label: "1:1", ok: true }]);
    expect(a.calls[0].init.body).toBeInstanceOf(FormData);
    const b = capture(404, {});
    await expect(fetchRunMeasurement({ token: "t", shopId: "s", fetchImpl: b.fetchImpl }, "r1")).resolves.toBeNull();
  });

  it("the confirmation carries edited_values only on approve; a rule_violation keeps its field", async () => {
    const a = capture(202, { decision: "approve", status: "accepted", celery_task_id: "c" });
    await submitConfirmationDecision("r1", "t1", "approve", "o1", { fetchImpl: a.fetchImpl, editedValues: { title: "Mới" } });
    expect(JSON.parse(a.calls[0].init.body as string)).toEqual({ decision: "approve", option_id: "o1", edited_values: { title: "Mới" } });
    const b = capture(422, { detail: { code: "rule_violation", message: "Có từ không được sửa.", field: "description" } });
    const error = await submitConfirmationDecision("r1", "t1", "approve", "o1", { fetchImpl: b.fetchImpl }).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ConfirmationRejectedError);
    expect(error).toMatchObject({ errorCode: "rule_violation", field: "description", message: "Có từ không được sửa." });
  });
});
