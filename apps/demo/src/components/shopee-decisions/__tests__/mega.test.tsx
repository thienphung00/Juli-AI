import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { detailOf, fakeReco, megaCard, megaChildren } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { Card } from "../../../lib/shopee-decisions/types";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

const without = (ids: readonly string[]): Card => {
  const kids = megaChildren().filter((c) => !ids.includes(c.child_id));
  return megaCard({
    title: `Mega sale 11/11 — ${kids.length} thay đổi, một ngân sách, một lần duyệt`,
    children: kids,
    certain: { ...megaCard().certain, total_discount: 1_800_000, by_lever: [{ lever: "khuyen_mai", lines: 50, discount: 1_800_000 }] },
  });
};

describe("thẻ mega sale", () => {
  it("lists the children, the day-by-day schedule, the totals and the per-SKU floor table", async () => {
    renderReco(<CardPage from={null} id="card-mega" />, fakeReco({ detail: detailOf(megaCard()) }));
    const kids = await screen.findByTestId("sd-mega-children");
    expect(within(kids).getAllByRole("listitem").filter((li) => li.getAttribute("data-testid")?.startsWith("sd-child-")).map((li) => li.getAttribute("data-testid"))).toEqual(["sd-child-child-1", "sd-child-child-2", "sd-child-child-3"]);
    const schedule = screen.getByTestId("sd-mega-schedule");
    expect(within(screen.getByTestId("sd-day-2026-11-11")).getByText("11/11")).toBeInTheDocument();
    expect(schedule).toHaveTextContent("Bật lúc 00:00 · Giảm giá sản phẩm");
    expect(screen.getByTestId("sd-day-2026-11-12")).toHaveTextContent("Tắt lúc 00:00 · Voucher đơn tối thiểu");
    const totals = screen.getByTestId("sd-mega-totals");
    expect(totals).toHaveTextContent("2.400.000đ");
    expect(totals).toHaveTextContent("Khuyến mãi");
    const table = screen.getByTestId("sd-mega-skus");
    expect(within(screen.getByTestId("sd-sku-BEP-S5-CB")).getByText("Trên giá sàn")).toBeInTheDocument();
    expect(within(screen.getByTestId("sd-sku-BEP-S5-LX")).getByText("Dưới giá sàn")).toBeInTheDocument();
    expect(table).toHaveTextContent("121.176đ");
    expect(screen.getByTestId("sd-mega-cap")).toHaveTextContent("Chi 1.300.000đ/ngày, trong trần 1.500.000đ");
  });

  it("removing a child recomputes the whole card and the approval carries the removal", async () => {
    const reco = fakeReco({ detail: detailOf(megaCard()), whatif: (inputs) => (Array.isArray(inputs["remove"]) && inputs["remove"].includes("child-3") ? without(["child-3"]) : megaCard()) });
    renderReco(<CardPage from={null} id="card-mega" />, reco);
    await screen.findByTestId("sd-mega-children");
    fireEvent.click(screen.getByRole("button", { name: "Bỏ Đổi ngân sách ngày" }));
    await waitFor(() => expect(screen.queryByTestId("sd-child-child-3")).toBeNull());
    expect(reco.calls.find((c) => c.name === "whatif")!.args).toEqual(["card-mega", { remove: ["child-3"] }, 1]);
    expect(screen.getByTestId("sd-mega-removed")).toHaveTextContent("Đã bỏ 1 thay đổi");
    expect(screen.getByTestId("sd-mega-totals")).toHaveTextContent("1.800.000đ");
    fireEvent.click(screen.getByRole("button", { name: /^Duyệt V1$/ }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "approve")).toBe(true));
    expect(reco.calls.find((c) => c.name === "approve")!.args).toEqual(["card-mega", { inputs: { remove: ["child-3"] }, chosenVersion: 1, acknowledgeBreaches: false }]);
  });

  it("the last child cannot be taken out, and an approved mega card is not editable", async () => {
    const first = renderReco(<CardPage from={null} id="card-mega" />, fakeReco({ detail: detailOf(megaCard({ children: [megaChildren()[0]!] })) }));
    await screen.findByTestId("sd-mega-children");
    expect(screen.getByRole("button", { name: "Bỏ Giảm giá sản phẩm" })).toBeDisabled();
    first.unmount();
    renderReco(<CardPage from={null} id="card-mega" />, fakeReco({ detail: detailOf(megaCard(), { status: "approved" }) }));
    await screen.findByTestId("sd-mega");
    expect(screen.queryByRole("button", { name: /^Bỏ (Giảm|Voucher|Đổi)/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Duyệt V1$/ })).toBeNull();
  });

  it("one budget cap for the whole campaign: changing it recomputes", async () => {
    const reco = fakeReco({ detail: detailOf(megaCard()), whatif: (inputs) => megaCard({ inputs: { budget_cap_per_day: inputs["budget_cap_per_day"] as number }, certain: { ...megaCard().certain, spend: { ...megaCard().certain.spend!, cap_per_day: 1_000_000, over_budget: true } } }) });
    renderReco(<CardPage from={null} id="card-mega" />, reco);
    const cap = (await screen.findByLabelText("Trần chi / ngày cho cả chiến dịch")) as HTMLInputElement;
    expect(cap.value).toBe("1500000");
    fireEvent.change(cap, { target: { value: "1000000" } });
    await waitFor(() => expect(screen.getByTestId("sd-mega-cap")).toHaveTextContent("vượt trần 1.000.000đ"));
    expect(reco.calls.find((c) => c.name === "whatif")!.args[1]).toEqual({ budget_cap_per_day: 1000000 });
  });
});
