import type { DemoDecisionItem, WorkflowRunListItem } from "@juli/contracts";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { cardView, gmvRangeText, groupSiblings, kpiChannelText, kpiTargetTexts, kpiWindowText } from "../../lib/quyet-dinh/card-model";
import { groupDecisions } from "../../lib/quyet-dinh/grouping";
import { day14Steps, externalChangeLines, finalBox, measureHead } from "../../lib/quyet-dinh/measure-model";
import type { Measurement, P10DecisionItem, RecommendationCardPayload } from "../../lib/quyet-dinh/p10-types";
import { bandDefault, type ShopRules } from "../../lib/quyet-dinh/types";
import { DeXuatPanel } from "../quyet-dinh/de-xuat-panel";
import { DoLuongPanel, IDLE_REVERT, type MeasureItem } from "../quyet-dinh/do-luong-panel";
import { RecommendationCard } from "../quyet-dinh/recommendation-card";
import { RulesEditor } from "../quyet-dinh/rules-editor";
import { READ_ONLY_TITLE, SellerViewProvider } from "../seller-view-context";

/**
 * P23 (D29 / D30): confidence pill, KPI range + window, GMV range, sibling
 * cards under one product header, day-7 / day-14 verdict words, the
 * "Bị ảnh hưởng bởi thay đổi khác" note, band-based hold thresholds. Every
 * field is optional: without it the card and Đo lường look as before.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const CARD: RecommendationCardPayload = {
  seller_sku: "SM-012",
  seller_sku_more: 0,
  product_title: "Son môi số 12",
  workflow_label: "Tối ưu sản phẩm",
  updated_at: "2026-10-09T02:00:00Z",
  status: "pending",
  main_kpi: { key: "ctr", label: "CTR - Thẻ sản phẩm", current: 0.0322, target: 0.0457, unit: "ratio" },
  expected_gmv_per_month: 2_100_000,
  reason_short: "Ít người bấm vào thẻ",
  reason_full: "CTR thấp hơn trung vị shop.",
  tiktok_codes: [],
  lever: { code: "title", label: "Tiêu đề", executor: "juli" },
  change_fields: [{ field: "title", label: "Tiêu đề" }],
  before_after: [],
  gmv_method: null,
};

const P23: Partial<RecommendationCardPayload> = {
  target_metric: "ctr",
  confidence: "low",
  kpi: { metric: "ctr", current: 0.0322, target: 0.041, target_min: 0.038, target_max: 0.044, display: "range", band_pct: 9, window_days: 30, low_data: false },
  gmv_estimate: { per_month_min: 500_000, per_month_max: 1_200_000 },
};

function item(id: string, card: Partial<RecommendationCardPayload> = {}, productId = "1729"): P10DecisionItem {
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
        stage: { code: "card", label: "Lượt hiển thị → Lượt nhấp" },
        lever: { code: card.lever?.code ?? "title", label: "Tiêu đề", action: "Viết lại tiêu đề" },
        main_kpi: { key: "ctr", label: "CTR", value: "3,22 %" },
        trigger: { code: "below_median", gap: -0.3, sentence: "Thấp hơn trung vị shop" },
        channel_scope: "PRODUCT_CARD",
        recoverable_gmv_per_day: 70_000,
        product_title: card.product_title ?? "Son môi số 12",
        tiktok_product_id: productId,
      },
      card: { ...CARD, ...card },
    },
  } as P10DecisionItem;
}

function renderCard(view = cardView(item("1", P23)), narrow = false) {
  return render(
    <RecommendationCard card={view} expanded={false} narrow={narrow} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />,
  );
}

describe("P23 card: confidence, KPI range, window, GMV range", () => {
  it("formats a range KPI, a point KPI and a GMV range", () => {
    expect(kpiTargetTexts(P23.kpi)?.kpiPairText).toBe("3,22 % → 3,8–4,4 %");
    expect(kpiTargetTexts({ metric: "ctr", current: 0.0322, target: 0.0457, display: "point" })?.kpiPairText).toBe("3,22 % → 4,57 %");
    expect(kpiTargetTexts({ metric: "aov", current: 182_000, target: null, target_min: 190_000, target_max: 205_000, display: "range" })?.kpiPairText).toBe(
      "182k → 190k–205k ₫",
    );
    expect(kpiTargetTexts(null)).toBeNull();
    expect(gmvRangeText({ per_month_min: 500_000, per_month_max: 1_200_000 })).toBe("+0,5–1,2 tr ₫/tháng");
    expect(gmvRangeText({ per_month_min: 40_000, per_month_max: 90_000 })).toBe("+40–90k ₫/tháng");
    expect(gmvRangeText({ per_month_min: null, per_month_max: 1 })).toBeNull();
  });

  it.each([false, true])("with the new fields (narrow=%s): pill, range, window note, GMV range", (narrow) => {
    renderCard(cardView(item("1", P23)), narrow);
    const card = screen.getByTestId("recommendation-card");
    expect(within(card).getByTestId("confidence-pill")).toHaveTextContent("Độ tin cậy: Thấp");
    expect(within(card).getByTestId("confidence-pill")).toHaveClass("qv-tone--muted");
    expect(card).toHaveTextContent("3,22 %");
    expect(card).toHaveTextContent("3,8–4,4 %");
    expect(card).not.toHaveTextContent("4,57 %");
    expect(within(card).getByTestId("kpi-window")).toHaveTextContent("· 30 ngày");
    expect(card).toHaveTextContent("+0,5–1,2 tr ₫/tháng");
    expect(card).not.toHaveTextContent("+2,1 tr ₫/tháng");
  });

  it("confidence tones: Cao green, Vừa amber", () => {
    const { unmount } = renderCard(cardView(item("1", { ...P23, confidence: "high" })));
    expect(screen.getByTestId("confidence-pill")).toHaveTextContent("Độ tin cậy: Cao");
    expect(screen.getByTestId("confidence-pill")).toHaveClass("qv-tone--ok");
    unmount();
    renderCard(cardView(item("1", { ...P23, confidence: "medium" })));
    expect(screen.getByTestId("confidence-pill")).toHaveTextContent("Độ tin cậy: Vừa");
    expect(screen.getByTestId("confidence-pill")).toHaveClass("qv-tone--wait");
  });

  it("a point KPI keeps today's line", () => {
    renderCard(cardView(item("1", { ...P23, kpi: { ...P23.kpi!, display: "point" } })));
    const card = screen.getByTestId("recommendation-card");
    expect(card).toHaveTextContent("3,22 %");
    expect(card).toHaveTextContent("4,57 %");
    expect(card).toHaveTextContent("· 30 ngày");
  });

  it("D32: the window note names the channel the KPI is measured on", () => {
    renderCard(cardView(item("1", { ...P23, kpi: { ...P23.kpi!, channel: "product_card" } })));
    expect(screen.getByTestId("kpi-window")).toHaveTextContent("· 30 ngày · đo trên kênh Thẻ sản phẩm");
    expect(kpiWindowText({ ...P23.kpi!, channel: "total" })).toBe("30 ngày · đo trên tất cả kênh");
    expect(kpiWindowText({ ...P23.kpi!, window_days: null, channel: "video" })).toBe("đo trên kênh Video");
    // A card from before D32 carries no channel: the note stays the window alone.
    expect(kpiWindowText(P23.kpi)).toBe("30 ngày");
    expect(kpiChannelText(null)).toBeNull();
    expect(kpiChannelText("live")).toBe("đo trên kênh LIVE");
  });

  it("without the new fields the card looks as before", () => {
    const view = cardView(item("1"));
    expect(view.confidence).toBeNull();
    expect(view.kpiWindow).toBeNull();
    expect(view.siblingCards).toBe(0);
    renderCard(view);
    const card = screen.getByTestId("recommendation-card");
    expect(screen.queryByTestId("confidence-pill")).toBeNull();
    expect(screen.queryByTestId("kpi-window")).toBeNull();
    expect(card).toHaveTextContent("3,22 %");
    expect(card).toHaveTextContent("4,57 %");
    expect(card).toHaveTextContent("+2,1 tr ₫/tháng");
  });

  it("a quick-scan card with the new confidence shows the pill only (no second 'Độ tin cậy')", () => {
    renderCard(cardView(item("1", { ...P23, quick_scan: { label: "Đề xuất nhanh", confidence: "Tham khảo", window_days: 14, basis: "" } })));
    expect(screen.getAllByText(/Độ tin cậy/)).toHaveLength(1);
  });

  it("view-as (read-only) shows the same card UI, buttons disabled", () => {
    render(
      <SellerViewProvider readOnly>
        <RecommendationCard card={cardView(item("1", P23))} expanded={false} narrow={false} onApprove={vi.fn()} onReject={vi.fn()} onToggle={vi.fn()} progressHref={null} status="pending" />
      </SellerViewProvider>,
    );
    expect(screen.getByTestId("confidence-pill")).toHaveTextContent("Độ tin cậy: Thấp");
    expect(screen.getByTestId("recommendation-card")).toHaveTextContent("3,8–4,4 %");
    expect(screen.getByRole("button", { name: "Duyệt" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Duyệt" })).toHaveAttribute("title", READ_ONLY_TITLE);
  });
});

function rules(over: Partial<ShopRules> = {}): ShopRules {
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
    ...over,
  };
}

function panel(items: readonly DemoDecisionItem[]) {
  return render(
    <DeXuatPanel
      busy={false}
      cardErrors={{}}
      groups={groupDecisions(items)}
      onApprove={vi.fn()}
      onOpenRules={vi.fn()}
      onOpenRun={vi.fn()}
      onReject={vi.fn()}
      progress={null}
      progressHref={() => "/x"}
      rules={rules()}
      rulesStatus="ready"
      runByCard={{}}
      statusOverrides={{}}
    />,
  );
}

describe("P23 sibling cards (D29.4)", () => {
  it("groups cards of one product + metric under one header; approving stays per card", () => {
    const a = item("a", { ...P23, sibling_cards: 1, lever: { code: "title", label: "Tiêu đề", executor: "juli" } });
    const b = item("b", { ...P23, sibling_cards: 1, lever: { code: "cover_image", label: "Ảnh bìa", executor: "juli_with_photo" } });
    const other = item("c", { ...P23, product_title: "Kem chống nắng" }, "9999");
    const runs = groupSiblings([a, other, b].map(cardView));
    expect(runs.map((r) => r.kind)).toEqual(["siblings", "single"]);
    panel([a, other, b] as DemoDecisionItem[]);
    const group = screen.getByTestId("sibling-group");
    expect(group).toHaveTextContent("Son môi số 12");
    expect(group).toHaveTextContent("2 thay đổi cho CTR");
    expect(within(group).getAllByTestId("recommendation-card")).toHaveLength(2);
    expect(within(group).getAllByRole("button", { name: "Duyệt" })).toHaveLength(2);
    expect(screen.getAllByTestId("recommendation-card")).toHaveLength(3);
  });

  it("without sibling_cards nothing is grouped", () => {
    panel([item("a"), item("b")] as DemoDecisionItem[]);
    expect(screen.queryByTestId("sibling-group")).toBeNull();
    expect(screen.getAllByTestId("recommendation-card")).toHaveLength(2);
  });
});

function measurement(stage: Measurement["stage"], over: Partial<Measurement> = {}): Measurement {
  return {
    stage,
    dates: { day7: "2026-10-16", day14: "2026-10-23" },
    target: { label: "CTR Thẻ sản phẩm", current: 0.0322, target: 0.041, progress_from: 0.033, unit: "ratio" },
    expected_gmv_per_day: 30_000,
    bands: [],
    rows: stage === "waiting" ? [] : [{ key: "ctr", label: "CTR (chỉ số chính)", before: 0.0322, expected: "4,1 %", actual: 0.036, verdict: "Đang lên", tone: "ok" }],
    day7: stage === "waiting" ? null : { within_band: true, question_id: null },
    final:
      stage === "final" ? { label: "gan_dat", gmv_actual_per_day: 20_000, pct_of_expected: 70, calibration: { lever: "title", from: 0.5, to: 0.45 } } : null,
    ...over,
  };
}

function run(): WorkflowRunListItem {
  return {
    id: "r1",
    status: "completed",
    stop_reason: "final_response",
    product_name: "Son môi số 12",
    created_at: "2026-10-09T03:00:00Z",
    completed_at: "2026-10-09T03:47:31Z",
    running_seconds_elapsed: 0,
    latest_narration: null,
    decision_summary: null,
  } as WorkflowRunListItem;
}

function measureItem(m: Measurement): MeasureItem {
  return {
    run: run(),
    card: cardView(item("1")),
    changes: undefined,
    measurement: { status: "ready", measurement: m },
    question: null,
    action: IDLE_REVERT,
  };
}

function renderMeasure(m: Measurement, tab: "d0" | "d7" | "d14") {
  return render(
    <DoLuongPanel items={[measureItem(m)]} nowMs={null} onKeep={vi.fn()} onOpenProposals={vi.fn()} onOpenRun={vi.fn()} onRevert={vi.fn()} onTab={vi.fn()} proposalsHref="/d" tab={tab} />,
  );
}

describe("P23 measurement verdicts and external changes (D29.8, D30.4)", () => {
  it("day 7: Đang lên / Chưa rõ; without a verdict the old chip", () => {
    expect(measureHead(measurement("day7", { verdict: { day7: "rising", day14: null, affected_by_external_change: false } }))).toEqual({
      headline: "Ngày 7: CTR đang lên",
      chip: { label: "Đang lên", tone: "ok" },
    });
    expect(measureHead(measurement("day7", { verdict: { day7: "unclear" } })).chip).toEqual({ label: "Chưa rõ", tone: "muted" });
    expect(measureHead(measurement("day7")).chip).toEqual({ label: "Ngày 7 · trong khoảng", tone: "ok" });
    // a band breach still asks first
    expect(measureHead(measurement("day7", { verdict: { day7: "rising" }, day7: { within_band: false, question_id: "q" } })).chip.label).toBe(
      "Ngày 7 · cần bạn quyết",
    );
  });

  it("day 14: Đạt / Một phần / Không đạt; without a verdict the final label", () => {
    expect(measureHead(measurement("final", { verdict: { day14: "met" } })).chip).toEqual({ label: "Đạt", tone: "ok" });
    expect(measureHead(measurement("final", { verdict: { day14: "partial" } })).chip).toEqual({ label: "Một phần", tone: "info" });
    expect(measureHead(measurement("final", { verdict: { day14: "not_met" } })).chip).toEqual({ label: "Không đạt", tone: "warn" });
    expect(measureHead(measurement("final")).chip.label).toBe("Một phần");
    const partial = measurement("final", { verdict: { day14: "partial" } });
    expect(finalBox(partial)?.title).toBe("Một phần: 70 % GMV dự kiến");
    expect(day14Steps(partial)[3].result).toBe("Một phần");
    expect(finalBox(measurement("final"))?.title).toBe("Một phần: 70 % GMV dự kiến");
  });

  it("D31.7: Đạt not clearly above both windows' noise reads Đạt · chưa chắc chắn", () => {
    for (const strength of ["likely", "noise"] as const) {
      const m = measurement("final", { verdict: { day14: "met", strength } });
      expect(measureHead(m)).toEqual({ headline: "Ngày 14: đạt mục tiêu", chip: { label: "Đạt · chưa chắc chắn", tone: "ok" } });
      expect(day14Steps(m)[3].result).toBe("Đạt · chưa chắc chắn");
      expect(finalBox(m)?.title).toMatch(/^Đạt · chưa chắc chắn: CTR /);
    }
    const clear = measurement("final", { verdict: { day14: "met", strength: "clear" } });
    expect(measureHead(clear).chip).toEqual({ label: "Đạt", tone: "ok" });
    expect(finalBox(clear)?.title).toMatch(/^Đạt: CTR /);
    // Một phần / Không đạt keep their words whatever the strength.
    expect(measureHead(measurement("final", { verdict: { day14: "partial", strength: "likely" } })).chip.label).toBe("Một phần");
    expect(measureHead(measurement("final", { verdict: { day14: "not_met", strength: "noise" } })).chip.label).toBe("Không đạt");
  });

  it("D31.7: the panel chip and the external-change note together", () => {
    renderMeasure(
      measurement("final", {
        verdict: { day14: "met", strength: "likely", affected_by_external_change: true },
        external_changes: [{ kind: "product_edit", fields: ["title"], occurred_at: "2026-10-12T03:00:00Z", source: "webhook_15" }],
      }),
      "d14",
    );
    expect(screen.getByTestId("measure-chip")).toHaveTextContent("Đạt · chưa chắc chắn");
    expect(screen.getByTestId("external-change")).toHaveTextContent("Bị ảnh hưởng bởi thay đổi khác");
  });

  it("external change lines; none without the fields", () => {
    const m = measurement("final", {
      verdict: { day14: "partial", affected_by_external_change: true },
      external_changes: [
        { kind: "promotion_create", fields: ["flash_sale"], occurred_at: "2026-10-14T03:00:00Z", source: "webhook_63" },
        { kind: "product_edit", fields: ["title"], occurred_at: "2026-10-12T03:00:00Z", source: "webhook_15" },
      ],
    });
    expect(externalChangeLines(m)).toEqual(["Tiêu đề sửa ngoài Juli · 12/10", "Flash sale bắt đầu · 14/10"]);
    expect(externalChangeLines(measurement("final", { verdict: { affected_by_external_change: true } }))).toEqual([]);
    expect(externalChangeLines(measurement("final"))).toBeNull();
    expect(
      externalChangeLines(measurement("final", { external_changes: [{ kind: "promotion_deactivate", fields: [], occurred_at: null }] })),
    ).toEqual(["Khuyến mãi kết thúc"]);
  });

  it("the panel shows the amber note and the verdict chip", async () => {
    renderMeasure(
      measurement("final", {
        verdict: { day14: "met", affected_by_external_change: true },
        external_changes: [{ kind: "product_edit", fields: ["title"], occurred_at: "2026-10-12T03:00:00Z", source: "webhook_15" }],
      }),
      "d14",
    );
    const note = screen.getByTestId("external-change");
    expect(note).toHaveTextContent("Bị ảnh hưởng bởi thay đổi khác");
    expect(note).toHaveTextContent("Tiêu đề sửa ngoài Juli · 12/10");
    expect(screen.getByTestId("measure-chip")).toHaveTextContent("Đạt");
  });

  it("the panel without the new fields has no note", () => {
    renderMeasure(measurement("day7"), "d7");
    expect(screen.queryByTestId("external-change")).toBeNull();
    expect(screen.getByTestId("measure-chip")).toHaveTextContent("Ngày 7 · trong khoảng");
  });
});

describe("P23 hold thresholds (D29.9)", () => {
  const unsetBands = (): ShopRules => rules({ stability_band: {}, band_metrics: ["ctr", "aov"] });

  it("band defaults from the API prefill the inputs (editable) and are saved as typed", async () => {
    const onSave = vi.fn(async () => undefined);
    const r = { ...unsetBands(), stability_band_defaults: { ctr: 8.5, aov: 4 } };
    expect(bandDefault(r, "ctr")).toBe(8.5);
    render(<RulesEditor onDelete={vi.fn()} onSave={onSave} rules={r} />);
    const ctr = within(screen.getByTestId("rule-stability_band-ctr")).getByRole("textbox");
    expect(ctr).toHaveValue("8,5");
    expect(within(screen.getByTestId("rule-stability_band-aov")).getByRole("textbox")).toHaveValue("4");
    expect(screen.getByText(/Juli gợi ý theo dao động của từng chỉ số/)).toBeInTheDocument();
    await userEvent.clear(ctr);
    await userEvent.type(ctr, "6");
    await userEvent.click(within(screen.getByTestId("rule-stability_band-ctr")).getByRole("button", { name: "Lưu" }));
    expect(onSave).toHaveBeenCalledWith("stability_band", 6, "seller", "ctr");
  });

  it("an unset band item carrying a value counts as the default", () => {
    const r = rules({ stability_band: { ctr: { value: 5, set_by: null, set_by_user_id: null, set_at: null } } });
    expect(bandDefault(r, "ctr")).toBe(5);
  });

  it("without defaults: empty inputs and no suggestion (V8: no fixed ±3 %)", () => {
    const r = unsetBands();
    expect(bandDefault(r, "ctr")).toBeNull();
    render(<RulesEditor onDelete={vi.fn()} onSave={vi.fn()} rules={r} />);
    const ctr = within(screen.getByTestId("rule-stability_band-ctr")).getByRole("textbox");
    expect(ctr).toHaveValue("");
    expect(ctr).toHaveAttribute("placeholder", "—");
    expect(screen.queryByText(/±3 %/)).toBeNull();
    expect(screen.queryByText(/Juli gợi ý/)).toBeNull();
  });
});

describe("P30 (D34.8): Kết quả nhóm", () => {
  const SENTENCE = "Nhóm 6 sản phẩm đổi ảnh bìa: lượt nhấp tăng khoảng 7 % so với các sản phẩm chưa đổi";

  it("shows the group sentence once the card carries one (desktop and phone)", () => {
    const view = cardView(item("1", { ...P23, group_result: SENTENCE }));
    expect(view.groupResult).toBe(SENTENCE);
    const { unmount } = renderCard(view);
    expect(screen.getByTestId("group-result")).toHaveTextContent(SENTENCE);
    expect(screen.getByText("Kết quả nhóm")).toBeInTheDocument();
    unmount();
    renderCard(view, true);
    expect(screen.getByTestId("group-result-mobile")).toHaveTextContent(SENTENCE);
  });

  it("shows nothing without a verdict", () => {
    renderCard(cardView(item("1", { ...P23, group_result: null })));
    expect(screen.queryByTestId("group-result")).toBeNull();
    expect(screen.queryByText("Kết quả nhóm")).toBeNull();
  });
});
