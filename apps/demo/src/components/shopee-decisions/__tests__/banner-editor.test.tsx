import { cleanup, configure, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { bannerContext, fakeBuilder, P_ZIP, type FakeBuilder } from "../../../lib/shopee-decisions/__tests__/builder-fixtures";
import { detailOf, fakeReco, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { BannerSpec } from "../../../lib/shopee-decisions/banner";
import { BannerEditor } from "../banner-editor";
import { BuilderP92View } from "../builder-p92";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

/**
 * P100 S2-E (owner, 2026-11-15): Ảnh bìa follows the design
 * (https://claude.ai/artifact/4SuySBPc5VbTQFU1SMK1wx): 1 Chọn mẫu → 2 Loại ngày → 3 Thêm banner →
 * 4 Kiểm tra → 5 Tải ảnh, over the real cover, values from the card or listing. Synthetic data.
 */

configure({ asyncUtilTimeout: 4000 });
afterEach(cleanup);

const calls = (b: FakeBuilder, name: string) => b.calls.filter((c) => c.name === name);
const next = () => fireEvent.click(screen.getByTestId("bn-next"));

async function toStep3(builder: FakeBuilder, cardId: string | null = "card-v") {
  render(<BannerEditor api={builder} cardId={cardId} itemId={P_ZIP} />);
  await screen.findByTestId("bn-step-1");
  expect(screen.getByTestId("bn-next")).toBeDisabled(); // a template first
  fireEvent.click(screen.getByRole("button", { name: /Nổi bật/ }));
  next();
  expect(screen.getByTestId("bn-next")).toBeDisabled(); // then the day mode
  fireEvent.click(screen.getByRole("button", { name: /Ngày thường/ }));
  next();
  return screen.findByTestId("bn-step-3");
}

describe("BannerEditor", () => {
  it("steps in order; the voucher banner comes filled from the card, over the real cover", async () => {
    const builder = fakeBuilder({ banner: bannerContext() });
    await toStep3(builder);
    expect(calls(builder, "banner")[0].args).toEqual([P_ZIP, "card-v"]);
    expect(screen.getByTestId("bn-cover").querySelector("img")?.getAttribute("src")).toBe("/sample-shop/hn-tdr.svg");
    expect(screen.queryByTestId("bn-add-mega")).toBeNull(); // the Mega Sale strip only on Mega Sale
    fireEvent.click(screen.getByTestId("bn-add-voucher"));
    expect(screen.getByTestId("bn-box-voucher")).toHaveTextContent("Voucher giảm 10K");
    expect(screen.getByTestId("bn-box-voucher")).toHaveTextContent("Đơn từ 200K");
    expect(screen.getByTestId("bn-add-voucher")).toBeDisabled(); // one per kind
    const item = screen.getByTestId("bn-item-voucher");
    expect(within(item).getByRole("button", { name: "Giữa phải" })).toHaveAttribute("aria-pressed", "true");
    expect(within(item).queryByRole("button", { name: /trái/ })).toBeNull(); // bottom-left never
    fireEvent.change(within(item).getByRole("textbox", { name: "Giảm (đ)" }), { target: { value: "15.000" } });
    expect(screen.getByTestId("bn-box-voucher")).toHaveTextContent("Voucher giảm 15K");
    expect(screen.getByTestId("bn-summary")).toHaveTextContent("Mẫu Nổi bật · Ngày thường · 1/3 banner");
  });

  it("Kiểm tra finds the overlap and Áp dụng moves the second banner; then the card stores the banner", async () => {
    const builder = fakeBuilder({ banner: bannerContext() });
    await toStep3(builder);
    fireEvent.click(screen.getByTestId("bn-add-voucher"));
    fireEvent.click(screen.getByTestId("bn-add-combo"));
    fireEvent.click(within(screen.getByTestId("bn-item-combo")).getByRole("button", { name: "Giữa phải" }));
    next();
    const overlap = await screen.findByTestId("bn-check-overlap");
    expect(overlap).toHaveTextContent("Hai banner chồng nhau: Voucher + Combo");
    fireEvent.click(within(overlap).getByRole("button", { name: "Áp dụng" }));
    expect(screen.queryByTestId("bn-check-overlap")).toBeNull();
    next();
    await screen.findByTestId("bn-step-5");
    fireEvent.click(screen.getByTestId("bn-save"));
    await waitFor(() => expect(calls(builder, "saveBanner")).toHaveLength(1));
    const body = calls(builder, "saveBanner")[0].args[0] as { itemId: string; cardId: string; spec: BannerSpec };
    expect(body).toMatchObject({ itemId: P_ZIP, cardId: "card-v", spec: { template: "noi_bat", day_mode: "ngay_thuong", size_px: 1200 } });
    expect(body.spec.banners.map((b) => [b.kind, b.position])).toEqual([
      ["voucher", "middle_right"],
      ["combo", "bottom_right"],
    ]);
    expect(body.spec.banners[0].sources.value).toEqual({ card_id: "card-v", field: "change.after.value" });
    expect(await screen.findByRole("button", { name: "Đã lưu vào thẻ" })).toBeInTheDocument();
  });

  it("a card's stored banner opens at step 3; Mega Sale offers the strip and asks for it", async () => {
    const stored: BannerSpec = {
      template: "toi_gian",
      day_mode: "ngay_thuong",
      size_px: 1200,
      banners: [{ shape: "the", kind: "quy_cach", values: { text: "500ml" }, sources: {}, position: "bottom_right", colour: "#2F6B4F", size: "S" }],
      checks: [],
      check_call_id: null,
    };
    const builder = fakeBuilder({ banner: bannerContext({ stored: { spec: stored, source: "seeded", created_at: null } }) });
    render(<BannerEditor api={builder} cardId="card-c" itemId={P_ZIP} />);
    await screen.findByTestId("bn-step-3");
    expect(screen.getByTestId("bn-box-quy_cach")).toHaveTextContent("500ml");
    fireEvent.click(screen.getByRole("button", { name: /Loại ngày/ }));
    fireEvent.click(screen.getByRole("button", { name: /Mega Sale/ }));
    fireEvent.click(screen.getByRole("button", { name: /Kiểm tra$/ }));
    expect(await screen.findByTestId("bn-check-missing_strip")).toHaveTextContent("Mega Sale chưa có dải tên sale");
  });

  it("without the seller's banner routes (Ops) the editor is not shown", () => {
    const { container } = render(<BannerEditor api={fakeBuilder()} itemId={P_ZIP} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("Tự tạo › Ảnh bìa", () => {
  it("is the banner editor, and the version sent carries the banner spec", async () => {
    const builder = fakeBuilder({ banner: bannerContext() });
    renderReco(<BuilderP92View from="quyet-dinh" productId={null} />, fakeReco(), { builder });
    fireEvent.click(await screen.findByTestId(`p2-prod-${P_ZIP}`));
    await waitFor(() => expect(screen.getByTestId("p2-vnext")).toBeEnabled());
    fireEvent.click(screen.getByTestId("p2-vnext"));
    fireEvent.click(await screen.findByTestId("p2-kind-cover_image"));
    fireEvent.click(screen.getByTestId("p2-knext"));
    const panel = await screen.findByTestId("p2-panel-cover");
    expect(within(panel).queryByTestId("p2-cover-draft")).toBeNull(); // no AI overlay button
    await within(panel).findByTestId("bn-step-1");
    fireEvent.click(within(panel).getByRole("button", { name: /Tối giản/ }));
    fireEvent.click(within(panel).getByTestId("bn-next"));
    fireEvent.click(within(panel).getByRole("button", { name: /Ngày thường/ }));
    fireEvent.click(within(panel).getByTestId("bn-next"));
    fireEvent.click(await within(panel).findByTestId("bn-add-unit"));
    fireEvent.change(within(panel).getByRole("textbox", { name: "Số đơn vị" }), { target: { value: "3" } });
    await waitFor(() => {
      const v = calls(builder, "evaluate").at(-1)?.args[0] as Record<string, unknown>[] | undefined;
      expect(v?.[0]).toMatchObject({ kind: "cover_image", item_id: P_ZIP, banner: { template: "toi_gian", banners: [{ kind: "unit", values: { price: 59_000, qty: 3 } }] } });
    });
  });
});

describe("the card's banner", () => {
  it("a voucher card opens the editor on itself; a host without the banner routes shows nothing", async () => {
    const card = voucherCard();
    const id = card.id ?? "card-voucher";
    const builder = fakeBuilder({ banner: bannerContext() });
    renderReco(<CardPage from={null} id={id} />, fakeReco({ detail: detailOf(card) }), { builder });
    const section = await screen.findByTestId("bn-card");
    fireEvent.click(within(section).getByTestId("bn-card-open"));
    await within(section).findByTestId("bn-step-1");
    expect(calls(builder, "banner")[0].args).toEqual([card.scope.product_ids[0], id]);
    cleanup();
    renderReco(<CardPage from={null} id={id} />, fakeReco({ detail: detailOf(card) }), { builder: fakeBuilder() });
    await screen.findByText(card.title);
    expect(screen.queryByTestId("bn-card")).toBeNull();
  });
});
