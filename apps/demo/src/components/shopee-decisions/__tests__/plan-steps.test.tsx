import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PlanApi, PlanResponse, PlanStep } from "../../../lib/shopee-decisions/plan-types";
import { PlanSteps, productsWithSteps } from "../plan-steps";

const step = (i: number, key: string, label: string, card: string, over: Partial<PlanStep> = {}): PlanStep => ({
  index: i, step: key, step_label: label, card_id: card, code: `JC-2611-000${i}`, title: `${label} thử`, change_kind: "x", version_label: null,
  margin_pct_before: 31.2, margin_pct_after: 27.9, dprofit_step_p50: -120000, dprofit_total_p50: -120000, dprofit_total_certain: -150000, dgmv_total_p50: 900000, cost_month_total: 150000, floor_ok: true, ...over,
});

function planOf(items: PlanStep[]): PlanResponse {
  return {
    plan: null,
    cards: [{ card_id: "c-ads" }, { card_id: "c-disc" }, { card_id: "c-vou" }, { card_id: "c-solo" }] as unknown as PlanResponse["cards"],
    windows: null,
    change_sets: [],
    aggregate: {
      as_of: "2026-11-05", n_cards: 4, today: { as_of: "x", gmv_30d: 1, orders_30d: 1, aov: 1, margin_pct: 30 }, cards: [],
      products: [
        { product_id: "P1", name: "Găng tay A", cards: [], codes: [], steps: { order: ["price", "giam_gia", "voucher", "combo", "ads"], custom_order: false, items, total: { margin_pct_before: 31.2, margin_pct_after: 24, dprofit_p50: 310000, dprofit_certain: -80000, dgmv_p50: 2400000 } } },
        { product_id: "P2", name: "Túi B", cards: [], codes: [], steps: { order: [], custom_order: false, items: [step(1, "ads", "Quảng cáo", "c-solo")], total: { margin_pct_before: null, margin_pct_after: null, dprofit_p50: null, dprofit_certain: null, dgmv_p50: null } } },
      ],
      steps_summary: { shop: { dprofit_p50: 310000, dprofit_certain: -80000, margin_pct_after: 24, products: 2 } },
    } as unknown as PlanResponse["aggregate"],
  };
}

const items = [
  step(1, "giam_gia", "Giảm giá", "c-disc"),
  step(2, "voucher", "Voucher", "c-vou", { margin_pct_before: 27.9, margin_pct_after: null, dprofit_step_p50: null, dprofit_total_p50: null, floor_ok: false }),
  step(3, "ads", "Quảng cáo", "c-ads", { margin_pct_before: null, margin_pct_after: 24, dprofit_step_p50: 430000, dprofit_total_p50: 310000 }),
];

function api(): PlanApi {
  return { move: vi.fn(async () => planOf(items)), remove: vi.fn(async () => planOf(items)) } as unknown as PlanApi;
}

describe("Kế hoạch: từng bước (P92 B-10)", () => {
  it("only products with at least two cards get the step table", () => {
    expect(productsWithSteps(planOf(items)).map((p) => p.product_id)).toEqual(["P1"]);
    expect(render(<PlanSteps api={api()} busy={false} done={false} onAct={async () => undefined} plan={{ ...planOf(items), aggregate: null }} />).container).toBeEmptyDOMElement();
  });

  it("shows margin and Δ profit after each step, '—' for null, the total and the shop totals", () => {
    render(<PlanSteps api={api()} busy={false} done={false} onAct={async () => undefined} plan={planOf(items)} />);
    const first = screen.getByTestId("kh-step-c-disc");
    expect(first).toHaveTextContent("31,2% → 27,9%");
    expect(first.querySelector("[data-testid=kh-step-dstep]")).toHaveTextContent("−120.000đ");
    const second = screen.getByTestId("kh-step-c-vou");
    expect(second).toHaveTextContent("27,9% → —");
    expect(second.querySelector("[data-testid=kh-step-dtotal]")).toHaveTextContent("—");
    expect(second).toHaveTextContent("Chạm giá sàn");
    expect(screen.getByTestId("kh-steps-total-p50")).toHaveTextContent("+310.000đ");
    expect(screen.getByTestId("kh-steps-total-p50")).toHaveTextContent("chắc chắn −80.000đ");
    expect(screen.getByTestId("kh-steps-shop")).toHaveTextContent("Cả shop (2 sản phẩm)");
    expect(screen.getByTestId("kh-steps-shop")).toHaveTextContent("+310.000đ");
    expect(screen.queryByTestId("kh-steps-P2")).toBeNull();
  });

  it("Lên / Xuống call move with the neighbour's plan position; the ends are disabled; Bỏ removes", () => {
    const a = api();
    const onAct = vi.fn(async (call: () => Promise<PlanResponse>) => void (await call()));
    render(<PlanSteps api={a} busy={false} done={false} onAct={onAct} plan={planOf(items)} />);
    expect(screen.getByRole("button", { name: "Lên: Giảm giá" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Xuống: Quảng cáo" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Xuống: Giảm giá" }));
    expect(a.move).toHaveBeenCalledWith("c-disc", 3); // c-vou is 3rd in the plan list
    fireEvent.click(screen.getByRole("button", { name: "Lên: Quảng cáo" }));
    expect(a.move).toHaveBeenCalledWith("c-ads", 3);
    fireEvent.click(screen.getByRole("button", { name: "Bỏ: Voucher" }));
    expect(a.remove).toHaveBeenCalledWith("c-vou");
  });

  it("a confirmed plan shows the steps read-only", () => {
    render(<PlanSteps api={api()} busy={false} done onAct={async () => undefined} plan={planOf(items)} />);
    expect(screen.queryByRole("button", { name: /Lên:/ })).toBeNull();
  });
});
