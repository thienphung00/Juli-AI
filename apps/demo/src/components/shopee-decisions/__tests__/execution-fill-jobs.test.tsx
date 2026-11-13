import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SHEET_VOUCHER, detailOf, fakeReco, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import type { FillJobRow } from "../../planned-changes/listing-extras";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

/** P97 D85.6: the execution panel shows the Connector's fill jobs as a checklist and the captured id. Synthetic data. */

const job = (over: Partial<FillJobRow> = {}): FillJobRow => ({
  id: "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f",
  kind: "voucher",
  version: 1,
  group_code: null,
  status: "queued",
  target: { product_ids: [] },
  captured_ref: null,
  error: null,
  open_path: "/portal/marketing/vouchers/new?usecase=1",
  ...over,
});

const answer = (jobs: FillJobRow[], enabled = true) => vi.fn(async () => new Response(JSON.stringify({ data: { enabled, jobs } }), { status: 200 }));
const approved = () => detailOf(voucherCard(), { status: "approved" });

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});
afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("Connector điền sẵn · danh sách trang", () => {
  it("lists each page with its status and a button that opens it for the Connector (only the job id in the address)", async () => {
    const f = answer([job(), job({ id: "7f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f", kind: "ads_edit", target: { campaign_id: "160675212" }, group_code: "A", open_path: "/portal/marketing/pas/product/manual/160675212" })]);
    vi.stubGlobal("fetch", f);
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    const list = await screen.findByTestId("sd-fill-jobs");
    expect(f).toHaveBeenCalledWith("/v1/demo/shopee/fill-jobs?card_id=card-voucher", expect.objectContaining({ headers: expect.objectContaining({ Authorization: "Bearer t" }) }));
    expect(within(list).getByTestId("sd-fill-count")).toHaveTextContent("0/2 trang đã xong");
    const first = within(list).getByTestId("sd-fill-job-6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(first).toHaveTextContent("Tạo voucher");
    expect(first).toHaveTextContent("Chờ mở trang");
    expect(within(first).getByTestId("sd-fill-open")).toHaveAttribute("href", "https://banhang.shopee.vn/portal/marketing/vouchers/new?usecase=1#juli-fill=6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(within(first).getByTestId("sd-fill-open")).toHaveAttribute("target", "_blank");
    const second = within(list).getByTestId("sd-fill-job-7f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(second).toHaveTextContent("Sửa quảng cáo · chiến dịch 160675212 · Nhóm A");
    expect(list).toHaveTextContent("Juli không bấm thay bạn");
  });

  it("a finished job has no open button and shows what the Connector captured; the voucher id need not be typed", async () => {
    vi.stubGlobal("fetch", answer([job({ status: "captured", captured_ref: "88001" })]));
    const reco = fakeReco({ detail: approved() });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    const row = await screen.findByTestId("sd-fill-job-6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(row).toHaveTextContent("Xong");
    expect(within(row).getByTestId("sd-fill-captured")).toHaveTextContent("Mã voucher: 88001");
    expect(within(row).queryByTestId("sd-fill-open")).toBeNull();
    expect(screen.getByTestId("sd-fill-count")).toHaveTextContent("1/1 trang đã xong");
    expect(screen.getByTestId("sd-voucher-captured")).toHaveTextContent("88001");
    expect(screen.queryByLabelText(/Mã voucher trên Seller Centre/)).toBeNull();
    const done = screen.getByRole("button", { name: "Đã làm" });
    expect(done).toBeEnabled();
    fireEvent.click(done);
    await waitFor(() => expect(reco.calls.find((c) => c.name === "executed")?.args).toEqual(["card-voucher", { voucherId: null }]));
  });

  it("without a captured id the voucher id is still typed by hand", async () => {
    vi.stubGlobal("fetch", answer([job({ status: "filled" })]));
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    await screen.findByTestId("sd-fill-jobs");
    expect(screen.getByRole("button", { name: "Đã làm" })).toBeDisabled();
    expect(screen.getByLabelText(/Mã voucher trên Seller Centre/)).toBeInTheDocument();
    expect(screen.getByTestId("sd-fill-job-6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f")).toHaveTextContent("Đã điền, chờ bạn lưu");
  });

  it("says why a job failed, in words", async () => {
    vi.stubGlobal("fetch", answer([job({ kind: "ads_edit", status: "failed", error: "budget_below_minimum", target: { campaign_id: "1" }, open_path: null })]));
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    expect(await screen.findByTestId("sd-fill-error")).toHaveTextContent("thấp hơn mức tối thiểu ₫100.000");
    expect(screen.queryByTestId("sd-fill-open")).toBeNull();
  });

  it("shows nothing when the server switch is off, there are no jobs, or the card is not approved", async () => {
    const off = answer([job()], false);
    vi.stubGlobal("fetch", off);
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: approved() }));
    await waitFor(() => expect(off).toHaveBeenCalled());
    expect(screen.queryByTestId("sd-fill-jobs")).toBeNull();
    expect(screen.getByLabelText(/Mã voucher trên Seller Centre/)).toBeInTheDocument();
  });

  it("asks nothing for a card that is not approved or has no fill kind", async () => {
    const f = answer([job()]);
    vi.stubGlobal("fetch", f);
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(voucherCard({ change_kind: "add_on", family: "combo" }), { status: "approved" }) }));
    await screen.findByTestId("sd-execution");
    expect(f).not.toHaveBeenCalled();
    expect(SHEET_VOUCHER).toBeDefined();
  });

  it("lists a combo job like any other page, and says why a legacy basket was not filled", async () => {
    const id = "8f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f";
    vi.stubGlobal(
      "fetch",
      answer([
        job({ kind: "combo", target: { product_ids: ["1001", "1003"] }, open_path: "/portal/marketing/bundle/new" }),
        job({ id, kind: "combo", status: "failed", error: "Combo kiểu cũ — tạo lại theo mức ưu đãi của Shopee", open_path: null }),
      ]),
    );
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(voucherCard({ change_kind: "bundle_deal", family: "combo" }), { status: "approved" }) }));
    const first = await screen.findByTestId("sd-fill-job-6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(first).toHaveTextContent("Tạo Combo Khuyến Mãi · 2 sản phẩm");
    expect(within(first).getByTestId("sd-fill-open")).toHaveAttribute("href", "https://banhang.shopee.vn/portal/marketing/bundle/new#juli-fill=6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(within(screen.getByTestId(`sd-fill-job-${id}`)).getByTestId("sd-fill-error")).toHaveTextContent("Combo kiểu cũ");
  });
});
