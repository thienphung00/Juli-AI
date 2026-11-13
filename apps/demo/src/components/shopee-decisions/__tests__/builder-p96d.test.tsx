import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { P_ZIP, evaluation, fakeBuilder, type FakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { BuilderP92View } from "../builder-p92";
import { renderReco } from "./harness";

/** P96d (owner report 2026-11-06): the compare table names each version's type and inputs and marks what differs. */

configure({ asyncUtilTimeout: 4000 });

const calls = (b: FakeBuilder, name: string) => b.calls.filter((c) => c.name === name);
const lastVersions = (b: FakeBuilder, name: string) => calls(b, name).at(-1)!.args[0] as Record<string, unknown>[];

async function addVoucher(builder: FakeBuilder, value: string, min: string) {
  fireEvent.click(screen.getByTestId("p2-kind-voucher"));
  fireEvent.click(screen.getByTestId("p2-knext"));
  fireEvent.change(await screen.findByRole("textbox", { name: "Giá trị" }), { target: { value } });
  fireEvent.change(screen.getByRole("textbox", { name: "Đơn tối thiểu" }), { target: { value: min } });
  await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "voucher", value: Number(value), min_spend: Number(min) }));
  await waitFor(() => expect(screen.getByTestId("p2-add")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-add"));
  await screen.findByTestId("p2-kinds");
}

describe("P96d · compare names the versions", () => {
  it("headers say 'Voucher sản phẩm', a Thông số row lists the inputs and marks those that differ from P1, the losing best says 'lỗ ít nhất'", async () => {
    const losing = (i: number) => ({ delta: { ...evaluation(1).versions[0]!.delta!, profit: { low: -30_000, p50: -20_000 + i * 5_000, high: -9_000 } } });
    const builder = fakeBuilder({ compare: (v) => evaluation(v.length, losing) });
    renderReco(<BuilderP92View from="quyet-dinh" productId={null} />, fakeReco(), { builder });
    fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
    await waitFor(() => expect(screen.getByTestId("p2-vnext")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-vnext"));
    await screen.findByTestId("p2-kinds");
    await addVoucher(builder, "5000", "100000");
    await addVoucher(builder, "10000", "100000");
    fireEvent.click(screen.getByTestId("p2-open-compare"));
    await screen.findByTestId("p2-cmp-table");

    const head1 = screen.getByTestId("p2-head-1");
    expect(head1).toHaveTextContent("Voucher sản phẩm");
    const facts = screen.getByTestId("p2-row-facts");
    expect(within(screen.getByTestId("p2-facts-1")).getByText("5.000đ")).not.toHaveClass("p2-cmp__diff");
    expect(within(screen.getByTestId("p2-facts-2")).getByText("10.000đ")).toHaveClass("p2-cmp__diff");
    expect(within(screen.getByTestId("p2-facts-2")).getByText("100.000đ")).not.toHaveClass("p2-cmp__diff");
    expect(facts).toHaveTextContent("Túi zip thực phẩm D");
    expect(screen.getByTestId("p2-head-2")).toHaveTextContent("lỗ ít nhất");
    expect(screen.queryByText("lợi nhuận tốt nhất")).toBeNull();
  });
});
