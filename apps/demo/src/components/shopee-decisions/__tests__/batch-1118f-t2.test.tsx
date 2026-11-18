import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FILLABLE_CHANGE_KINDS } from "../../../lib/shopee-decisions/model";
import { JOURNEY_VERIFIED, detailOf, fakeReco, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { ExecutionCard, ExecutionStates } from "../../../lib/shopee-decisions/types";
import { CardPage } from "../card-page";
import { ThucHienView } from "../thuc-hien";
import { renderReco } from "./harness";

const exec = (over: Partial<ExecutionCard>): ExecutionCard => ({
  card_id: "c1", code: null, title: "Thẻ thử", family: "listing", family_label: "Listing", change_kind: "title", product_id: "P1",
  state: "cho_dien", completed: 1, bad: null, fields: { filled: 0, total: 1 }, jobs: { total: 1, filled: 0, saved: 0, failed: 0 }, noun: "tiêu đề", not_seen: false, mismatch: null,
  executed_at: null, verified_at: null, measure_start: null, measure_days: null, open_job: null, ...over,
});
const states = (cards: ExecutionCard[]): ExecutionStates => ({ platform: "shopee", connector: { version: "0.3.22", last_check_at: null, connected: true, seller_centre_open: true }, cards, counts: {} });

describe("F1.4 · hoàn tác and Đã lưu", () => {
  it("toast after Hoàn tác says Đã ghi nhận hoàn tác, never Đã làm", async () => {
    const detail = detailOf(voucherCard(), { status: "executed", journey: JOURNEY_VERIFIED });
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail }));
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    fireEvent.click(await screen.findByTestId("sd-reverted-confirm"));
    const toast = await screen.findByTestId("sd-outcome");
    expect(toast).toHaveTextContent("Đã ghi nhận hoàn tác");
    expect(toast).not.toHaveTextContent("Đã làm");
  });

  it("a reverted card's header chip says Đã hoàn tác, not Đã làm", async () => {
    const detail = { ...detailOf(voucherCard(), { status: "executed", journey: JOURNEY_VERIFIED }), reverted: { by: "user:u1", at: "2026-11-17T09:30:00" } };
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail }));
    await screen.findByTestId("sd-reverted");
    expect(screen.getAllByText("Đã hoàn tác").length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText("Đã làm")).toBeNull();
  });

  it("once Bạn lưu is done the chip says Đã lưu · chờ xác minh", async () => {
    renderReco(<ThucHienView />, fakeReco({ execution: states([exec({ card_id: "a", state: "da_dien", completed: 3, executed_at: "2026-11-18T03:00:00Z" }), exec({ card_id: "b", state: "da_dien", completed: 2 })]) }));
    expect(await screen.findByTestId("sd-th-state-a")).toHaveTextContent("Đã lưu · chờ xác minh");
    expect(screen.getByTestId("sd-th-state-a")).not.toHaveTextContent("chờ bạn lưu");
    expect(screen.getByTestId("sd-th-state-b")).toHaveTextContent("Đã điền · chờ bạn lưu");
  });
});

describe("F1.5 · non-fillable kinds", () => {
  it("exposes the fillable kinds", () => {
    expect(FILLABLE_CHANGE_KINDS).toContain("combo_multi");
    expect(FILLABLE_CHANGE_KINDS).toHaveLength(9);
  });

  it("a non-fillable card shows the line and a working Mở trang link, no disabled button", async () => {
    const detail = detailOf(voucherCard());
    const withLink = { ...detail, card: { ...detail.card, execution_sheet: { ...detail.card.execution_sheet, page: { ...detail.card.execution_sheet.page, deep_link: "https://seller.shopee.vn/portal/marketing/vouchers" } } } };
    renderReco(<ThucHienView />, fakeReco({ detail: withLink, execution: states([exec({ card_id: "n", change_kind: "cover_image" })]) }));
    const box = await screen.findByTestId("sd-th-manual-n");
    expect(box).toHaveTextContent("Connector chưa điền loại thẻ này — làm theo bảng thao tác");
    await waitFor(() => expect(within(box).getByRole("link", { name: "Mở trang" })).toHaveAttribute("href", "https://seller.shopee.vn/portal/marketing/vouchers"));
    expect(screen.queryByRole("button", { name: "Mở Seller Centre" })).toBeNull();
  });

  it("a fillable card keeps its button/link", async () => {
    renderReco(<ThucHienView />, fakeReco({ execution: states([exec({ card_id: "f", change_kind: "title" })]) }));
    const row = await screen.findByTestId("sd-th-f");
    expect(within(row).getByRole("button", { name: "Mở Seller Centre" })).toBeDisabled();
    expect(screen.queryByTestId("sd-th-manual-f")).toBeNull();
  });
});

describe("F1.9 · dates and errors", () => {
  it("the header date is the card's own time in VN (a card made 18/11 at 22:55Z shows 19/11)", async () => {
    const detail = detailOf(voucherCard(), { computed_at: "2026-11-18T08:55:00Z" });
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail }));
    expect(await screen.findByTestId("sd-queue-line")).toHaveTextContent("cập nhật 18/11/2026");
    expect(screen.getByTestId("sd-queue-line")).not.toHaveTextContent("02/11/2026");
  });

  it("a failed Đã làm on the Thực hiện list shows the error", async () => {
    const reco = fakeReco({ execution: states([exec({ card_id: "e", state: "da_dien", completed: 2 })]) }, { executed: new Error("Máy chủ lỗi 500") });
    renderReco(<ThucHienView />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Đã làm" }));
    expect(await screen.findByTestId("sd-th-error-e")).toHaveTextContent("Máy chủ lỗi 500");
  });
});
