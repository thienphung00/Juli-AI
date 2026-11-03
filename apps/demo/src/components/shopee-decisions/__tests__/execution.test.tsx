import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JOURNEY_EXECUTED, JOURNEY_VERIFIED, SHEET_VOUCHER, detailOf, fakeReco, voucherCard, megaCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardDetail, Card } from "../../../lib/shopee-decisions/types";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

const writeText = vi.fn(async () => undefined);
beforeEach(() => {
  writeText.mockClear();
  Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
});
afterEach(() => vi.restoreAllMocks());

const approved = (card: Card = voucherCard(), p: Partial<CardDetail> = {}) => detailOf(card, { status: "approved", ...p });
const executed = (journey: CardDetail["journey"], p: Partial<CardDetail> = {}) => detailOf(voucherCard(), { status: "executed", journey, ...p });

describe("thực hiện có hỗ trợ · bảng thao tác", () => {
  it("shows the page, each field with its exact before -> after, the time window and the save hint", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    const sheet = await screen.findByTestId("sd-sheet");
    expect(within(sheet).getByTestId("sd-page")).toHaveTextContent("Marketing › Voucher của tôi");
    const step1 = within(sheet).getByTestId("sd-step-1");
    expect(step1).toHaveTextContent("Giá trị giảm (VND)");
    expect(step1).toHaveTextContent("10.000đ");
    expect(step1).toHaveTextContent("15.000đ");
    expect(within(sheet).getByTestId("sd-step-2")).toHaveTextContent("299.000đ");
    expect(within(sheet).getByTestId("sd-time-window")).toHaveTextContent("khi bạn bấm lưu · chạy 30 ngày");
    expect(sheet).toHaveTextContent("Juli không bấm thay bạn");
  });

  it("copy buttons put the exact value on the clipboard", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    const sheet = await screen.findByTestId("sd-sheet");
    fireEvent.click(within(sheet).getByRole("button", { name: "Sao chép Đơn tối thiểu" }));
    expect(writeText).toHaveBeenCalledWith("299000");
    expect(await within(sheet).findByText("Đã sao chép")).toBeInTheDocument();
    fireEvent.click(within(sheet).getByRole("button", { name: "Sao chép Giá trị giảm (VND)" }));
    expect(writeText).toHaveBeenLastCalledWith("15000");
  });

  it("opens the Seller Centre page in a new tab; an unverified link is marked", async () => {
    const sheet = { ...SHEET_VOUCHER, page: { ...SHEET_VOUCHER.page, verified: false } };
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved(voucherCard({ execution_sheet: sheet })) }));
    const link = await screen.findByRole("link", { name: "Mở trang để sửa" });
    expect(link).toHaveAttribute("href", "https://banhang.shopee.vn/portal/marketing/vouchers/list");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText("đường dẫn chưa kiểm")).toBeInTheDocument();
  });

  it("a verified link carries no warning; a page with no link says where to go", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    await screen.findByTestId("sd-sheet");
    expect(screen.queryByText("đường dẫn chưa kiểm")).toBeNull();
    const none = { ...SHEET_VOUCHER, page: { ...SHEET_VOUCHER.page, verified: false, deep_link: null, path: null } };
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved(voucherCard({ execution_sheet: none })) }));
    await waitFor(() => expect(screen.getAllByTestId("sd-sheet")).toHaveLength(2));
    expect(screen.getByText(/Chưa có đường dẫn trực tiếp/)).toBeInTheDocument();
  });

  it("'Đã làm' needs the voucher id of a voucher, then calls the executed endpoint", async () => {
    const reco = fakeReco({ detail: approved() });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    const done = await screen.findByRole("button", { name: "Đã làm" });
    expect(done).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Mã voucher trên Seller Centre/), { target: { value: " 998877 " } });
    expect(done).toBeEnabled();
    fireEvent.click(done);
    await waitFor(() => expect(reco.calls.some((c) => c.name === "executed")).toBe(true));
    expect(reco.calls.find((c) => c.name === "executed")!.args).toEqual(["card-voucher", { voucherId: "998877" }]);
    expect(await screen.findByTestId("sd-outcome")).toHaveTextContent("Đã ghi nhận “Đã làm”");
  });

  it("a non-voucher card is marked done without an id", async () => {
    const card = voucherCard({ family: "ads", change_kind: "ads_budget", execution_sheet: { ...SHEET_VOUCHER, changes: [{ change_kind: "daily_budget", target: { campaign_id: "c1" }, expected: { daily_budget: 400000 } }] } });
    const reco = fakeReco({ detail: approved(card) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Đã làm" }));
    await waitFor(() => expect(reco.calls.find((c) => c.name === "executed")?.args).toEqual(["card-voucher", { voucherId: null }]));
  });

  it("read-only view: 'Đã làm' is locked", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }), { readOnly: true });
    expect(await screen.findByRole("button", { name: "Đã làm" })).toBeDisabled();
  });

  it("uses the sheet of the values the seller approved, not the proposal's", async () => {
    const final = { ...SHEET_VOUCHER, steps: [{ order: 1, field: "Đơn tối thiểu", before: 200000, after: 250000, unit: "VND", copy: "250000" }] };
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved(voucherCard(), { approved_with: { inputs: { min_spend: 250000 }, execution_sheet: final } }) }));
    const sheet = await screen.findByTestId("sd-sheet");
    expect(within(sheet).getByTestId("sd-step-1")).toHaveTextContent("250.000đ");
    expect(within(sheet).queryByTestId("sd-step-2")).toBeNull();
  });

  it("recomputes the sheet from the approved inputs when the API does not send it", async () => {
    const final = voucherCard({ execution_sheet: { ...SHEET_VOUCHER, steps: [{ order: 1, field: "Đơn tối thiểu", before: 200000, after: 250000, unit: "VND", copy: "250000" }] } });
    const reco = fakeReco({ detail: approved(voucherCard(), { approved_with: { inputs: { min_spend: 250000 } } }), whatif: final });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    await waitFor(() => expect(within(screen.getByTestId("sd-sheet")).getByTestId("sd-step-1")).toHaveTextContent("250.000đ"));
    expect(reco.calls.find((c) => c.name === "whatif")!.args).toEqual(["card-voucher", { min_spend: 250000 }]);
  });

  it("'Hoàn tác' shows the reverse sheet", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: executed(JOURNEY_VERIFIED) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    const reverse = await screen.findByTestId("sd-revert-sheet");
    expect(within(reverse).getByTestId("sd-step-1")).toHaveTextContent("15.000đ");
    expect(within(reverse).getByTestId("sd-step-1")).toHaveTextContent("10.000đ");
    fireEvent.click(within(reverse).getAllByRole("button", { name: /Sao chép/ })[0]!);
    expect(writeText).toHaveBeenCalledWith("10000");
  });
});

describe("xác minh và đo lường", () => {
  it("Chờ xác minh right after 'Đã làm'", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: executed(JOURNEY_EXECUTED) }));
    const rb = await screen.findByTestId("sd-readback");
    expect(rb).toHaveTextContent("Chờ xác minh");
    expect(rb).toHaveTextContent("sau 48 giờ sẽ báo cho Ops");
    expect(screen.getByTestId("sd-countdown")).toHaveTextContent("Kết quả sau 14 ngày · đồng hồ chạy khi thay đổi được xác minh");
    expect(screen.queryByRole("button", { name: "Đã làm" })).toBeNull();
  });

  it("Đã xác minh with the observed value and time, and the 14-day countdown", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: executed(JOURNEY_VERIFIED) }));
    const rb = await screen.findByTestId("sd-readback");
    expect(rb).toHaveTextContent("Đã xác minh");
    expect(rb).toHaveTextContent("discount_amount: 15.000, min_spend: 299.000");
    expect(rb).toHaveTextContent("lúc 05/11 08:00");
    expect(screen.getByTestId("sd-countdown")).toHaveTextContent("Còn 7 ngày (ngày 8/14)");
  });

  it("Không khớp and Chưa thấy", async () => {
    const mismatch = [...JOURNEY_EXECUTED, { event: "mismatch", at: "2026-11-06T03:00:00", reason_code: null, payload: { observed: 14000 } }];
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: executed(mismatch) }));
    expect(await screen.findByTestId("sd-readback")).toHaveTextContent("Không khớp");
    expect(screen.getByTestId("sd-readback")).toHaveTextContent("Giá trị đọc được: 14.000");
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: executed([...JOURNEY_EXECUTED, { event: "not_seen", at: "2026-11-06T03:00:00", reason_code: null }]) }));
    await waitFor(() => expect(screen.getAllByTestId("sd-readback")).toHaveLength(2));
    expect(screen.getAllByTestId("sd-readback")[1]).toHaveTextContent("Chưa thấy");
  });

  it("'khó kết luận' when the plan has no 14/28-day window", async () => {
    const card = voucherCard({ measurement_plan: { metric: "aov", planned_days: null, label: "khó kết luận" } });
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(card, { status: "executed", journey: JOURNEY_VERIFIED }) }));
    expect(await screen.findByTestId("sd-countdown")).toHaveTextContent("khó kết luận");
  });

  it("shows the T+7 and final readings when they exist", async () => {
    const journey = [
      ...JOURNEY_VERIFIED,
      { event: "impact_preliminary", at: "2026-11-12T00:00:00", reason_code: null, payload: { impact_pct: 3.2, confidence: "Thấp" } },
      { event: "impact_final", at: "2026-11-19T00:00:00", reason_code: null, payload: { impact_pct: -1.5, confidence: "Trung bình" } },
    ];
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: executed(journey) }));
    expect(await screen.findByTestId("sd-reading-t7")).toHaveTextContent("Ngày 7: +3,2% · độ tin cậy Thấp");
    expect(screen.getByTestId("sd-reading-final")).toHaveTextContent("Kết quả cuối: −1,5%");
  });

  it("a mega sale card in execution lists each child with its own page link", async () => {
    renderReco(<CardPage from={null} id="card-mega" />, fakeReco({ detail: detailOf(megaCard(), { status: "approved" }) }));
    const sheet = await screen.findByTestId("sd-sheet");
    expect(within(sheet).getByTestId("sd-step-3")).toHaveTextContent("Marketing › Quảng cáo Shopee");
    expect(within(sheet).getByTestId("sd-step-3")).toHaveTextContent("đường dẫn chưa kiểm");
  });
});
