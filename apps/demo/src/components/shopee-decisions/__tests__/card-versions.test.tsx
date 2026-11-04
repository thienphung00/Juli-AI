import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { detailOf, fakeReco, summaryOf, titleCard, versionOf, versionedVoucher, voucherCardB } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardList, CardSummary } from "../../../lib/shopee-decisions/types";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

const slider = (name: string) => screen.getByRole("slider", { name }) as HTMLInputElement;

function queueList(cards: CardSummary[]): CardList {
  return { platform: "shopee", xep_theo: "diem", queue: "product", cards, counts: { family: {}, section: {}, total: cards.length } };
}

describe("CardVersions · nhiều phiên bản của một thay đổi", () => {
  it("shows the versions as columns next to 'Hôm nay' with their codes, V1 as Juli's pick and V3 flagged", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(versionedVoucher(), { code: "JC-2611-0007", product_id: "BEP-S5", product_queue: 1 }) }));
    const table = await screen.findByTestId("sv-table");
    expect(screen.getByTestId("sv-count")).toHaveTextContent("3 phiên bản của cùng một thay đổi");
    expect(within(table).getByText("Hôm nay")).toBeInTheDocument();
    expect(within(table).getByText("voucher hiện tại: 10.000đ cho đơn ≥ 200.000đ")).toBeInTheDocument();
    for (const n of [1, 2, 3]) expect(screen.getByTestId(`sv-ver-${n}`)).toHaveTextContent(`JC-2611-0007-V${n}`);
    expect(screen.getByTestId("sv-ver-1")).toHaveTextContent("Juli đề xuất");
    expect(screen.getByTestId("sv-ver-3")).toHaveTextContent("Chạm giá sàn");
    expect(screen.getByTestId("sv-ver-1")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("sv-floor-3")).toHaveTextContent("✕ Khách trả 175.000đ < sàn 181.979đ");
    expect(screen.getByTestId("sd-queue-line")).toHaveTextContent("#1 · Đang ở Quyết định");
    expect(screen.getByTestId("sd-code")).toHaveTextContent("JC-2611-0007");
    expect(screen.getByTestId("sd-selected")).toHaveTextContent("JC-2611-0007-V1");
  });

  it("choosing V2 approves V2: the button, the body and the outcome name it", async () => {
    const reco = fakeReco({ detail: detailOf(versionedVoucher(), { code: "JC-2611-0007", product_id: "BEP-S5", product_queue: 1 }) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByTestId("sv-ver-2"));
    expect(screen.getByTestId("sv-ver-2")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("sd-selected")).toHaveTextContent("JC-2611-0007-V2");
    fireEvent.click(screen.getByRole("button", { name: "Duyệt V2" }));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "approve")).toBe(true));
    expect(reco.calls.find((c) => c.name === "approve")!.args).toEqual(["card-voucher", { inputs: null, chosenVersion: 2, acknowledgeBreaches: false }]);
    const outcome = await screen.findByTestId("sd-outcome");
    expect(outcome).toHaveTextContent("Đã duyệt JC-2611-0007-V2. Các phiên bản còn lại đóng cùng thẻ.");
    expect(outcome).toHaveTextContent("kết quả đọc sau 14 ngày");
  });

  it("the what-if moves the selected version only and asks for that version", async () => {
    const card = versionedVoucher();
    const moved = { ...card, versions: [card.versions![0]!, versionOf(voucherCardB(), 2, "15.000đ cho đơn ≥ 200.000đ", { code: "JC-2611-0007-V2", inputs: { ...voucherCardB().inputs, min_spend: 250000 } }), card.versions![2]!] };
    const reco = fakeReco({ detail: detailOf(card, { code: "JC-2611-0007" }), whatif: moved });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByTestId("sv-ver-2"));
    expect(screen.getByText("Phép thử “nếu đổi” cho V2")).toBeInTheDocument();
    expect(screen.getByText("Chỉ V2 thay đổi, các phiên bản khác giữ nguyên.")).toBeInTheDocument();
    fireEvent.change(slider("Đơn tối thiểu"), { target: { value: "250000" } });
    await waitFor(() => expect(reco.calls.some((c) => c.name === "whatif")).toBe(true));
    expect(reco.calls.find((c) => c.name === "whatif")!.args).toEqual(["card-voucher", { min_spend: 250000 }, 2]);
    expect(await screen.findByText("Đã chỉnh so với đề xuất (whatif_adjusted)")).toBeInTheDocument();
    expect(screen.getByTestId("sv-ver-1")).toHaveTextContent("JC-2611-0007-V1");
    fireEvent.click(await screen.findByRole("button", { name: "Về mặc định" }));
    await waitFor(() => expect(screen.queryByText("Đã chỉnh so với đề xuất (whatif_adjusted)")).toBeNull());
  });

  it("a version that could not be priced is shown and cannot be chosen", async () => {
    const card = versionedVoucher();
    const refused = { ...versionOf(card, 4, "Mức giảm 5%"), status: "refused", refusal: "cost_or_fee_unknown", five_numbers: undefined, ranked: false };
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf({ ...card, versions: [...card.versions!, refused] }) }));
    const v4 = await screen.findByTestId("sv-ver-4");
    expect(v4).toBeDisabled();
    expect(v4).toHaveTextContent("Không tính được");
    expect(screen.getByTestId("sv-count")).toHaveTextContent("4 phiên bản");
  });

  it("'Tiếp theo cho sản phẩm này' names the next card and links to the product's queue", async () => {
    const card = versionedVoucher();
    const next = summaryOf({ ...versionedVoucher(), code: "JC-2611-0009", product_queue: 2 }, { id: "card-next", code: "JC-2611-0009", product_queue: 2, title: "Combo Găng tay cao su A × 2 + Túi rác sinh học B" });
    const me = summaryOf(card, { code: "JC-2611-0007", product_queue: 1 });
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(card, { code: "JC-2611-0007", product_id: "BEP-S5", product_queue: 1 }), list: queueList([me, next]) }));
    const strip = await screen.findByTestId("sd-next");
    await waitFor(() => expect(strip).toHaveTextContent("JC-2611-0009"));
    expect(strip).toHaveTextContent("Combo Găng tay cao su A × 2 + Túi rác sinh học B · còn 1 thẻ xếp hàng");
    expect(within(strip).getByRole("link", { name: "Xem cả hàng đợi ›" })).toHaveAttribute("href", "/san-pham/BEP-S5?tab=dx&from=card&card=card-voucher");
  });

  it("a card further back says it comes up after the cards before it close", async () => {
    const card = titleCard();
    const top = summaryOf(versionedVoucher(), { code: "JC-2611-0007", product_queue: 1 });
    const me = summaryOf(card, { code: "JC-2611-0011", product_queue: 4 });
    renderReco(<CardPage from={null} id="card-title" />, fakeReco({ detail: detailOf(card, { code: "JC-2611-0011", product_id: "BEP-S5", product_queue: 4 }), list: queueList([top, me]) }));
    const strip = await screen.findByTestId("sd-next");
    await waitFor(() => expect(strip).toHaveTextContent("JC-2611-0007"));
    expect(strip).toHaveTextContent("đang ở Quyết định; thẻ này lên sau khi 3 thẻ trước đóng");
    expect(screen.getByTestId("sd-queue-line")).toHaveTextContent("#4 · Xếp hàng");
  });

  it("'Sản phẩm đang đo: còn N ngày' on a card of a product being measured; approving is still offered", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(versionedVoucher(), { code: "JC-2611-0007", product_measuring: { until: "2026-11-14", change_set: null } }) }));
    expect(await screen.findByTestId("sd-measuring")).toHaveTextContent("Sản phẩm đang đo: còn 3 ngày");
    expect(screen.getByRole("button", { name: "Duyệt V1" })).toBeEnabled();
  });

  it("an acknowledged breach is a chip on the card", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(versionedVoucher(), { status: "approved", chosen_version: 3, acknowledged_breaches: { at: "2026-11-04T03:15:00", breaches: [{ type: "floor" }] } }) }));
    expect(await screen.findByTestId("sd-ack-card")).toHaveTextContent("Đã xác nhận vượt giá sàn · 04/11/2026 10:15");
    expect(screen.getByTestId("sv-ver-3")).toHaveAttribute("aria-checked", "true");
    expect(screen.getByTestId("sv-ver-1")).toBeDisabled();
  });

  it("the plan button is there only when the host has a plan", async () => {
    const plan: string[] = [];
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(versionedVoucher()) }), { plan: { addCard: async (id, v) => void plan.push(`${id}:${v}`) } });
    fireEvent.click(await screen.findByTestId("sv-ver-2"));
    fireEvent.click(screen.getByRole("button", { name: "Thêm V2 vào kế hoạch" }));
    expect(plan).toEqual(["card-voucher:2"]);
  });

  it("opens on the version named in the link (?v=2)", async () => {
    renderReco(<CardPage from={null} id="card-voucher" version={2} />, fakeReco({ detail: detailOf(versionedVoucher()) }));
    await screen.findByTestId("sv-table");
    expect(screen.getByTestId("sv-ver-2")).toHaveAttribute("aria-checked", "true");
  });
});

describe("tiêu đề · giới hạn 100 ký tự", () => {
  const title = (n: number) => "G".repeat(n);

  it("counts as the person types, recomputes up to 100 and sends nothing above", async () => {
    const reco = fakeReco({ detail: detailOf(titleCard(), { code: "JC-2611-0011", product_queue: 4 }), whatif: titleCard() });
    renderReco(<CardPage from={null} id="card-title" />, reco);
    const box = (await screen.findByRole("textbox", { name: /Tiêu đề trên Shopee/ })) as HTMLTextAreaElement;
    expect(screen.getByTestId("sv-title-count")).toHaveTextContent("97/100");
    fireEvent.change(box, { target: { value: title(90) } });
    await waitFor(() => expect(reco.calls.some((c) => c.name === "whatif")).toBe(true));
    expect(reco.calls.find((c) => c.name === "whatif")!.args).toEqual(["card-title", { title: title(90) }, 1]);
    expect(screen.getByTestId("sv-title-count")).toHaveTextContent("90/100");
    expect(screen.getByText("Còn 10 ký tự.")).toBeInTheDocument();
    const before = reco.calls.filter((c) => c.name === "whatif").length;
    fireEvent.change(box, { target: { value: title(104) } });
    expect(screen.getByTestId("sv-title-count")).toHaveTextContent("104/100");
    expect(screen.getByText("Quá 4 ký tự. Phần vượt không được lưu và Duyệt bị khoá.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Duyệt V1" })).toBeDisabled();
    expect(screen.getByTestId("sd-approve-hint")).toHaveTextContent("Rút bớt 4 ký tự để duyệt.");
    await new Promise((r) => setTimeout(r, 400));
    expect(reco.calls.filter((c) => c.name === "whatif")).toHaveLength(before);
  });
});
