import { configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { P_ZIP, fakeBuilder, type FakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { fakeReco, summaryOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { BuilderP98Api } from "../../../lib/shopee-decisions/builder-p98-api";
import type { ExecutionCard, ExecutionStates } from "../../../lib/shopee-decisions/types";
import { DecisionsView } from "../decisions-view";
import { RecoHostProvider } from "../../../lib/shopee-decisions/context";
import { Row, ThucHienView } from "../thuc-hien";
import { hostOf, params, renderReco } from "./harness";

/**
 * UI grill 2026-11-16 (owner), S2's part: G2 tool tabs keep their work, G3 defaults are placeholders,
 * G9 a new DVHT campaign is set up inside Từng phương án, G10 the "Tự tạo" tag, G14 the voucher code on
 * a Thực hiện row. Synthetic data only.
 */

configure({ asyncUtilTimeout: 4000 });

const p98 = { combo: vi.fn(), kol: vi.fn(), ads: vi.fn() } as unknown as BuilderP98Api;
const calls = (b: FakeBuilder, name: string) => b.calls.filter((c) => c.name === name);

async function toKinds() {
  fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
  await waitFor(() => expect(screen.getByTestId("p2-vnext")).toBeEnabled());
  fireEvent.click(screen.getByTestId("p2-vnext"));
  await screen.findByTestId("p2-kinds");
}

function chooseKind(key: string) {
  fireEvent.click(screen.getByTestId(`p2-kind-${key}`));
  fireEvent.click(screen.getByTestId("p2-knext"));
}

describe("G2 · a tool tab keeps its work", () => {
  it("Từng phương án is where the seller left it after a look at Combo nhiều SKU", async () => {
    renderReco(<DecisionsView params={params("tu-tao=1")} />, fakeReco(), { builder: fakeBuilder(), p98 });
    await toKinds();
    chooseKind("voucher");
    await screen.findByTestId("p2-panel-voucher");
    fireEvent.click(screen.getByTestId("p98-mode-combo"));
    expect(screen.getByTestId("p98-pane-single")).not.toBeVisible();
    fireEvent.click(screen.getByTestId("p98-mode-single"));
    expect(screen.getByTestId("p98-pane-single")).toBeVisible();
    expect(screen.getByTestId("p2-panel-voucher")).toBeInTheDocument(); // still on step ③, voucher
  });
});

describe("G3 · defaults are placeholders", () => {
  it("an empty field shows its default in grey; typing replaces it; left blank it still counts", async () => {
    const builder = fakeBuilder();
    renderReco(<DecisionsView params={params("tu-tao=1")} />, fakeReco(), { builder, p98 });
    await toKinds();
    chooseKind("affiliate");
    const field = await screen.findByRole("textbox", { name: "Hoa hồng mới" });
    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("placeholder", "10");
    await waitFor(() => expect(calls(builder, "evaluate").at(-1)?.args[0]).toMatchObject([{ kind: "affiliate", commission_pct: 10 }]));
    fireEvent.change(field, { target: { value: "15" } });
    await waitFor(() => expect(calls(builder, "evaluate").at(-1)?.args[0]).toMatchObject([{ kind: "affiliate", commission_pct: 15 }]));
  });
});

describe("G9 · a new DVHT campaign inside Từng phương án", () => {
  it("'+ Tạo chiến dịch mới' opens the setup in step ③ with the product already chosen", async () => {
    renderReco(<DecisionsView params={params("tu-tao=1")} />, fakeReco(), { builder: fakeBuilder(), p98 });
    await toKinds();
    chooseKind("ads");
    const select = await screen.findByRole("combobox", { name: "Chiến dịch" });
    await screen.findByRole("option", { name: "+ Tạo chiến dịch mới" });
    fireEvent.change(select, { target: { value: "__new__" } });
    const pane = await screen.findByTestId("p2-panel-ads-new");
    expect(screen.getByTestId("p98-pane-single")).toBeVisible(); // no jump to the DVHT tab
    const chosen = within(pane).getByRole("button", { name: "Túi zip thực phẩm D" });
    expect(chosen.className).toContain("sb-pill--on");
    expect(within(pane).getByLabelText("Ngân sách mỗi ngày 1 (đ)")).toHaveAttribute("placeholder", "100000");
    fireEvent.click(within(pane).getByRole("button", { name: "‹ Chiến dịch đang chạy" }));
    expect(await screen.findByTestId("p2-panel-ads")).toBeInTheDocument();
  });
});

describe("G10 · the seller's own cards are tagged", () => {
  it("a card made in Tự tạo carries 'Tự tạo' in the Đề xuất list; Juli's do not", async () => {
    const mine = summaryOf(voucherCard(), { origin: "manual" });
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: { cards: [mine], counts: {} } as never }));
    const card = await screen.findByTestId("sq-card-card-voucher");
    expect(within(card).getByText("Tự tạo")).toBeInTheDocument();
  });
});

const row = (over: Partial<ExecutionCard>): ExecutionCard => ({
  card_id: "v",
  code: "JC-2611-0009",
  title: "Voucher đơn tối thiểu",
  family: "voucher",
  family_label: "Voucher",
  change_kind: "min_spend_voucher",
  product_id: "P1",
  state: "da_dien",
  completed: 3,
  bad: null,
  fields: { filled: 3, total: 3 },
  jobs: { total: 1, filled: 1, saved: 1, failed: 0 },
  noun: "voucher",
  not_seen: false,
  mismatch: null,
  executed_at: null,
  verified_at: null,
  measure_start: null,
  measure_days: null,
  open_job: null,
  ...over,
});

const states = (cards: ExecutionCard[]): ExecutionStates => ({
  platform: "shopee",
  connector: { version: "0.3.20", last_check_at: "2026-11-16T09:05:00", connected: true, seller_centre_open: true },
  cards,
  counts: {},
});

describe("G14 · the voucher code on a Thực hiện row", () => {
  it("asks for the Seller Centre code beside Đã làm and sends it", async () => {
    const reco = fakeReco({ execution: states([row({})]) });
    renderReco(<ThucHienView />, reco);
    const code = await screen.findByTestId("sd-th-code-v");
    const done = within(screen.getByTestId("sd-th-v")).getByRole("button", { name: "Đã làm" });
    expect(done).toBeDisabled();
    fireEvent.change(code, { target: { value: "88001" } });
    fireEvent.click(done);
    await waitFor(() => expect(reco.calls.find((c) => c.name === "executed")?.args).toEqual(["v", { voucherId: "88001" }]));
  });

  it("is pre-filled with the code the Connector picked up; a title card has no code field", async () => {
    renderReco(<ThucHienView />, fakeReco({ execution: states([row({ captured_voucher_id: "77002" }), row({ card_id: "t", change_kind: "title", family: "listing" })]) }));
    expect(await screen.findByTestId("sd-th-code-v")).toHaveValue("77002");
    expect(screen.queryByTestId("sd-th-code-t")).toBeNull();
  });
});

describe("G14 · a code captured after the row is shown", () => {
  it("fills the field when a later refresh brings it, and keeps what the seller typed", async () => {
    const host = hostOf(fakeReco());
    const at = (c: ExecutionCard) => (
      <RecoHostProvider host={host}>
        <Row c={c} name={null} onDone={() => undefined} readOnly={false} sample={false} />
      </RecoHostProvider>
    );
    const { rerender } = render(at(row({})));
    expect(await screen.findByTestId("sd-th-code-v")).toHaveValue("");
    rerender(at(row({ captured_voucher_id: "77003" })));
    expect(screen.getByTestId("sd-th-code-v")).toHaveValue("77003");
    fireEvent.change(screen.getByTestId("sd-th-code-v"), { target: { value: "99" } });
    rerender(at(row({ captured_voucher_id: "77004" })));
    expect(screen.getByTestId("sd-th-code-v")).toHaveValue("99");
  });
});

describe("F2 · a Đề xuất card on stale data", () => {
  it("shows where the data stops instead of Δ lợi nhuận, and no per-day line", async () => {
    const old = summaryOf(voucherCard(), { data_stale: { dataset: "orders", through: "2026-11-12" } });
    renderReco(<DecisionsView params={params()} />, fakeReco({ list: { cards: [old], counts: {} } as never }));
    const card = await screen.findByTestId("sq-card-card-voucher");
    expect(within(card).getByTestId("dx-dprofit")).toHaveTextContent("Đơn hàng đến 12/11");
    expect(within(card).queryByTestId("dx-perday")).toBeNull();
  });
});
