import { configure, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { P_ZIP, evaluation, fakeBuilder, type FakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { fakeReco } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { BuilderP92View } from "../builder-p92";
import { renderReco } from "./harness";

/** P96d: step 4 names each version by its label. */

configure({ asyncUtilTimeout: 4000 });

const calls = (b: FakeBuilder, name: string) => b.calls.filter((c) => c.name === name);
const lastVersions = (b: FakeBuilder, name: string) => calls(b, name).at(-1)!.args[0] as Record<string, unknown>[];
function chooseKind(key: string) {
  if (!screen.queryByTestId("p2-kinds")) fireEvent.click(screen.getByRole("button", { name: "Đổi chiến lược" }));
  fireEvent.click(screen.getByTestId(`p2-kind-${key}`));
  fireEvent.click(screen.getByTestId("p2-knext"));
}

async function addVoucher(builder: FakeBuilder, value: string, min: string) {
  chooseKind("voucher");
  fireEvent.change(await screen.findByRole("textbox", { name: "Giá trị" }), { target: { value } });
  fireEvent.change(screen.getByRole("textbox", { name: "Đơn tối thiểu" }), { target: { value: min } });
  await waitFor(() => expect(lastVersions(builder, "evaluate")[0]).toMatchObject({ kind: "voucher", value: Number(value), min_spend: Number(min) }));
  await waitFor(() => expect(screen.getByTestId("p2-add")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-add"));
  await waitFor(() => expect(screen.getByTestId("p3-next")).toBeEnabled());
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
    fireEvent.click(screen.getByTestId("p3-next"));
    await screen.findByTestId("p4-table");
    expect(screen.getByTestId("p4-bar-1")).toHaveTextContent("P1 · 5k / 100k");
    expect(screen.getByTestId("p4-bar-2")).toHaveTextContent("P2 · 10k / 100k");
    expect(screen.getAllByTestId(/^p4-row-/)).toHaveLength(2);
  });
});
