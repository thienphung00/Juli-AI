import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import type { BuilderEvaluation, BuilderVersion, GroupResult, OutcomeTarget } from "../../../lib/shopee-decisions/builder-api";
import { groupedPlan } from "../../../lib/shopee-decisions/__tests__/plan-fixtures";
import { FLOOR_WARNING, P_GLOVE, P_SPONGE, P_ZIP, evaluation, fakeBuilder, type FakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { BuilderP92View } from "../builder-p92";
import { renderReco } from "./harness";

configure({ asyncUtilTimeout: 4000 });

const names: Record<string, string> = { [P_ZIP]: "Túi zip thực phẩm D", [P_GLOVE]: "Găng tay cao su A", [P_SPONGE]: "Miếng rửa chén C" };

/** The server's answer for a many-target version: a total and a row per target (the glove breaks its floor). */
function manyTargets(versions: readonly BuilderVersion[]): BuilderEvaluation {
  return evaluation(versions.length, (i) => {
    const v = versions[i]!;
    const ids = (v["targets"] ?? v["campaign_keys"] ?? []) as string[];
    if (ids.length === 0) return {};
    const targets: OutcomeTarget[] = ids.map((id) => ({
      id,
      kind: v.kind === "ads" ? "campaign" : "item",
      name: names[id] ?? id,
      ok: true,
      dgmv_p50: -10_000,
      dprofit_p50: -5_000,
      cost_month: 10_000,
      breach: id === P_GLOVE,
      breaches: id === P_GLOVE ? [FLOOR_WARNING] : [],
    }));
    return { targets, targets_mode: "sum", fill: { mode: v.kind === "affiliate" ? "bulk" : "per_target", targets: ids.length }, breach: targets.some((t) => t.breach), warnings: targets.some((t) => t.breach) ? [FLOOR_WARNING] : [] };
  });
}

function open(builder: FakeBuilder) {
  return renderReco(<BuilderP92View from="quyet-dinh" productId={null} />, fakeReco(), { builder });
}

const evals = (b: FakeBuilder) => b.calls.filter((c) => c.name === "evaluate").map((c) => (c.args[0] as Record<string, unknown>[])[0]!);
function chooseKind(key: string) {
  if (!screen.queryByTestId("p2-kinds")) fireEvent.click(screen.getByRole("button", { name: "Đổi chiến lược" }));
  fireEvent.click(screen.getByTestId(`p2-kind-${key}`));
  fireEvent.click(screen.getByTestId("p2-knext"));
}

async function toKind(kind: string) {
  fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
  await waitFor(() => expect(screen.getByTestId("p2-vnext")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-vnext"));
  await screen.findByTestId("p2-kinds");
  chooseKind(kind);
}

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia unless a test defines it
  delete window.matchMedia;
});

describe("P97 D85.13 · một thẻ, nhiều đối tượng", () => {
  it("one % for many products: the picker fills the target list, the result shows a row per target", async () => {
    const b = fakeBuilder({ evaluate: manyTargets });
    open(b);
    await toKind("product_discount");
    fireEvent.click(await screen.findByRole("button", { name: "Nhiều sản phẩm cùng một mức giảm" }));
    fireEvent.change(screen.getByRole("textbox", { name: "% GIẢM cho tất cả" }), { target: { value: "12" } });
    const picker = within(screen.getByTestId("p2-targets"));
    fireEvent.click(picker.getByRole("checkbox", { name: /Chọn Găng tay cao su A/ }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ kind: "product_discount", discount_pct: 12, targets: [P_ZIP, P_GLOVE] }));
    expect(evals(b).at(-1)!["variations"]).toBeUndefined();
    const rows = await screen.findByTestId("p2-trows");
    expect(within(rows).getByTestId(`p2-trow-${P_GLOVE}`)).toHaveTextContent("Chạm giá sàn");
    expect(within(rows).getByTestId(`p2-trow-${P_ZIP}`)).not.toHaveTextContent("Chạm giá sàn");
    expect(screen.getByTestId("p2-fill-mode")).toHaveTextContent("2 lượt điền, mỗi đối tượng một lượt");
  });

  it("unticking the target that breaks the floor evaluates the card again without it", async () => {
    const b = fakeBuilder({ evaluate: manyTargets });
    open(b);
    await toKind("product_discount");
    fireEvent.click(await screen.findByRole("button", { name: "Nhiều sản phẩm cùng một mức giảm" }));
    fireEvent.click(within(screen.getByTestId("p2-targets")).getByRole("checkbox", { name: /Chọn Găng tay cao su A/ }));
    const row = await screen.findByTestId(`p2-trow-${P_GLOVE}`);
    fireEvent.click(within(row).getByRole("checkbox", { name: /Áp dụng cho Găng tay cao su A/ }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ targets: [P_ZIP] }));
    await waitFor(() => expect(screen.queryByTestId(`p2-trow-${P_GLOVE}`)).toBeNull());
    expect(within(screen.getByTestId("p2-sel")).queryByText(/Găng tay cao su A/)).toBeNull();
  });

  it("affiliate commission over many products fills in one bulk pass", async () => {
    const b = fakeBuilder({ evaluate: manyTargets });
    open(b);
    await toKind("affiliate");
    fireEvent.click(await screen.findByRole("button", { name: "Nhiều sản phẩm cùng một mức hoa hồng" }));
    fireEvent.click(within(screen.getByTestId("p2-targets")).getByRole("checkbox", { name: /Chọn Miếng rửa chén C/ }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ kind: "affiliate", targets: [P_ZIP, P_SPONGE] }));
    expect(await screen.findByTestId("p2-fill-mode")).toHaveTextContent("một lượt bằng chỉnh sửa hàng loạt");
  });

  it("a product voucher sends its product list", async () => {
    const b = fakeBuilder();
    open(b);
    await toKind("voucher");
    fireEvent.click(await screen.findByRole("radio", { name: "Voucher sản phẩm" }));
    fireEvent.click(screen.getByLabelText(/Áp cho nhiều sản phẩm/));
    fireEvent.click(within(screen.getByTestId("p2-targets")).getByRole("checkbox", { name: /Chọn Găng tay cao su A/ }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ kind: "voucher", scope: "product", item_ids: [P_ZIP, P_GLOVE] }));
  });
});

describe("P97 D85.17 · quảng cáo theo form của Shopee", () => {
  it("a budget below ₫100.000 stops with Shopee's wording and sends nothing", async () => {
    const b = fakeBuilder();
    open(b);
    await toKind("ads");
    await screen.findByRole("option", { name: /GMV Max/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Chiến dịch" }), { target: { value: "c1" } });
    fireEvent.change(screen.getByRole("textbox", { name: "Ngân sách mới mỗi ngày" }), { target: { value: "22000" } });
    expect(await screen.findByText("Ngân sách tối thiểu: ₫100.000")).toBeInTheDocument();
    expect(evals(b)).toHaveLength(0);
    fireEvent.change(screen.getByRole("textbox", { name: "Ngân sách mới mỗi ngày" }), { target: { value: "100000" } });
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ kind: "ads", lever: "budget", campaign_key: "c1", daily_budget: 100_000 }));
  });

  it("an unlimited budget is sent as unlimited; ROAS presets and the system mode are Shopee's", async () => {
    const b = fakeBuilder();
    open(b);
    await toKind("ads");
    await screen.findByRole("option", { name: /GMV Max/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Chiến dịch" }), { target: { value: "c1" } });
    fireEvent.click(screen.getByRole("button", { name: "Không giới hạn" }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ lever: "budget", unlimited: true }));
    expect(evals(b).at(-1)!["daily_budget"]).toBeUndefined();
    fireEvent.click(screen.getByRole("tab", { name: "ROAS mục tiêu" }));
    const presets = within(await screen.findByTestId("p2-roas-presets"));
    expect(presets.getAllByRole("button").map((x) => x.textContent)).toEqual(["2,5", "3,5", "4,5"]);
    fireEvent.click(presets.getByRole("button", { name: "3,5" }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ lever: "roas", roas_mode: "custom", roas_target: 3.5 }));
    fireEvent.click(screen.getByRole("button", { name: "Hệ thống tối ưu" }));
    await waitFor(() => expect(evals(b).at(-1)).toMatchObject({ lever: "roas", roas_mode: "system" }));
    expect(evals(b).at(-1)!["roas_target"]).toBeUndefined();
  });

  it("shows the server's ROAS warnings and has no keyword lever", async () => {
    const warn = (msg: string, type: string) => ({ type, message: msg });
    const b = fakeBuilder({
      evaluate: (v) => evaluation(v.length, () => ({ warnings: [warn("Vui lòng đặt ≤ 3.5 (gợi ý của Shopee): ROAS mục tiêu càng cao, quảng cáo càng ít được hiển thị.", "ads_roas_above_hint"), warn("Chiến dịch này đã đổi ROAS trong 7 ngày qua. Đổi từ 2 lần trong một tuần thì tuần đó mất hỗ trợ hiệu suất của Shopee.", "ads_roas_second_change")] })),
    });
    open(b);
    await toKind("ads");
    expect(screen.queryByRole("button", { name: /Từ khoá và giá thầu/ })).toBeNull();
    await screen.findByRole("option", { name: /GMV Max/ });
    fireEvent.change(screen.getByRole("combobox", { name: "Chiến dịch" }), { target: { value: "c1" } });
    fireEvent.click(screen.getByRole("tab", { name: "ROAS mục tiêu" }));
    fireEvent.change(await screen.findByRole("textbox", { name: "ROAS mục tiêu mới" }), { target: { value: "5" } });
    expect(await screen.findByText(/Vui lòng đặt ≤ 3.5/)).toBeInTheDocument();
  });
});


async function addVoucher(value: string) {
  chooseKind("voucher");
  fireEvent.change(await screen.findByRole("textbox", { name: "Giá trị" }), { target: { value } });
  await waitFor(() => expect(screen.getByTestId("p2-add")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-add"));
  await waitFor(() => expect(screen.getByTestId("p3-next")).toBeEnabled());
}
