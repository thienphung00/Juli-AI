import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PickerProduct } from "../../../lib/shopee-decisions/builder-api";
import { initialForms } from "../../../lib/shopee-decisions/builder-p92";
import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { JOURNEY_EXECUTED, JOURNEY_VERIFIED, detailOf, fakeReco, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardDetail } from "../../../lib/shopee-decisions/types";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import type { FillJobRow } from "../../planned-changes/listing-extras";
import { AffiliatePanel, DescPanel } from "../builder-p92/panels-listing";
import { CardPage } from "../card-page";
import { renderReco } from "./harness";

/** batch-1118g t3: revert fill (F3.1), read-back polling (F3.2), current values (E20/E50), captured voucher (F2.3). Synthetic data. */

const job = (over: Partial<FillJobRow> = {}): FillJobRow => ({
  id: "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f",
  kind: "title",
  version: 1,
  group_code: null,
  status: "queued",
  target: { item_id: "1001" },
  captured_ref: null,
  error: null,
  open_path: "/portal/product/1001",
  payload: { mode: "revert" },
  ...over,
});
const answer = (jobs: FillJobRow[]) => vi.fn(async () => new Response(JSON.stringify({ data: { enabled: true, jobs } }), { status: 200 }));
const executed = (p: Partial<CardDetail> = {}) => detailOf(voucherCard(), { status: "executed", journey: JOURNEY_VERIFIED, ...p });
const withRevert = <T extends object>(reco: T): T & { revertFill: () => Promise<unknown> } => Object.assign(reco, { revertFill: vi.fn(async () => ({ card_id: "card-voucher", jobs: [job()], ready: false })) });

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});
afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("F3.1 · Hoàn tác bằng Connector", () => {
  it("'Mở và điền' queues the revert fill and lists its jobs; 'Đã hoàn tác' stays off until ready", async () => {
    const f = answer([]);
    vi.stubGlobal("fetch", f);
    const reco = withRevert(fakeReco({ detail: executed() }));
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    expect(screen.getByTestId("sd-reverted-confirm")).toBeDisabled();
    fireEvent.click(screen.getByTestId("sd-revert-fill"));
    await waitFor(() => expect(reco.revertFill).toHaveBeenCalledWith("card-voucher"));
  });

  it("shows the revert jobs with progress and a link that hands the job to the Connector", async () => {
    vi.stubGlobal("fetch", answer([job()]));
    renderReco(<CardPage from={null} id="card-voucher" />, withRevert(fakeReco({ detail: executed({ revert: { jobs: [job()], ready: false } }) })));
    const list = await screen.findByTestId("sd-fill-jobs");
    expect(list).toHaveTextContent("Hoàn tác · Tên sản phẩm");
    expect(list).toHaveTextContent("Chờ mở trang");
    expect(screen.getByTestId("sd-revert-open")).toHaveAttribute("href", "https://banhang.shopee.vn/portal/product/1001#juli-fill=6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f");
    expect(screen.getByTestId("sd-reverted-confirm")).toBeDisabled();
  });

  it("'Đã hoàn tác' is enabled when the API says ready and sends no manual flag", async () => {
    vi.stubGlobal("fetch", answer([job({ status: "saved" })]));
    const reco = withRevert(fakeReco({ detail: executed({ revert: { jobs: [job({ status: "saved" })], ready: true } }) }));
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    const ok = await screen.findByTestId("sd-reverted-confirm");
    await waitFor(() => expect(ok).toBeEnabled());
    fireEvent.click(ok);
    await waitFor(() => expect(reco.calls.find((c) => c.name === "reverted")?.args).toEqual(["card-voucher"]));
  });

  it("'Đã hoàn tác thủ công' sends {manual: true}; a 409 revert_not_confirmed shows inline", async () => {
    vi.stubGlobal("fetch", answer([]));
    const failing = withRevert(fakeReco({ detail: executed() }, { reverted: new ShopeeApiError(409, "revert_not_confirmed", "Chưa đọc lại được giá trị cũ") }));
    renderReco(<CardPage from={null} id="card-voucher" />, failing);
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    fireEvent.click(screen.getByTestId("sd-reverted-manual"));
    await waitFor(() => expect(failing.calls.find((c) => c.name === "reverted")?.args).toEqual(["card-voucher", { manual: true }]));
    expect(await screen.findByRole("alert")).toHaveTextContent("Chưa đọc lại được giá trị cũ");
  });
});

describe("F3.2 · Khớp / Không khớp without a reload", () => {
  it("polls the fill jobs every 15 s while a read-back job is open and re-reads the card when it closes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const open = job({ id: "aaaaaaaa-1d2b-4c5d-8e7f-0a1b2c3d4e5f", kind: "readback", payload: { mode: "readback" }, status: "queued" });
    const f = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ data: { enabled: true, jobs: [open] } }), { status: 200 })).mockResolvedValue(new Response(JSON.stringify({ data: { enabled: true, jobs: [{ ...open, status: "captured" }] } }), { status: 200 }));
    vi.stubGlobal("fetch", f);
    const reco = fakeReco({ detail: executed({ journey: JOURNEY_EXECUTED }) });
    renderReco(<CardPage from={null} id="card-voucher" />, reco);
    await screen.findByTestId("sd-readback");
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    const detailCalls = () => reco.calls.filter((c) => c.name === "detail").length;
    const before = detailCalls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15_100);
    });
    await waitFor(() => expect(f.mock.calls.length).toBeGreaterThanOrEqual(2));
    await waitFor(() => expect(detailCalls()).toBeGreaterThan(before));
  });
});

describe("E20 / E50 · Hiện tại", () => {
  const ctxOf = (extra: Partial<PickerProduct>) => ({ product: { item_id: "1001", name: "Sản phẩm thử", ...extra } as unknown as PickerProduct, variations: [], products: [], api: {}, outcome: null }) as never;
  it("shows the current first line and commission when the API sends them, nothing otherwise", () => {
    const f = initialForms();
    const { rerender } = render(<DescPanel ctx={ctxOf({ current_first_line: "Dòng đầu hiện có" })} form={f.description_first_line} set={() => undefined} />);
    expect(screen.getByTestId("p2-desc-current")).toHaveTextContent("Hiện tại: Dòng đầu hiện có");
    rerender(<DescPanel ctx={ctxOf({ current_first_line: null })} form={f.description_first_line} set={() => undefined} />);
    expect(screen.queryByTestId("p2-desc-current")).toBeNull();
    const aff = render(<AffiliatePanel ctx={ctxOf({ current_commission_pct: 7.5 })} form={f.affiliate} set={() => undefined} />);
    expect(within(aff.container).getByTestId("p2-aff-current")).toHaveTextContent("Hiện tại: 7.5%");
    aff.rerender(<AffiliatePanel ctx={ctxOf({})} form={f.affiliate} set={() => undefined} />);
    expect(screen.queryByTestId("p2-aff-current")).toBeNull();
  });
});

describe("F2.3 · mã voucher đã lấy", () => {
  it("an approved voucher card whose voucher job was captured needs no typed code", async () => {
    vi.stubGlobal("fetch", answer([job({ kind: "voucher", payload: null, status: "captured", captured_ref: "88001" })]));
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(voucherCard(), { status: "approved" }) }));
    expect(await screen.findByTestId("sd-voucher-captured")).toHaveTextContent("88001");
    expect(screen.queryByLabelText(/Mã voucher trên Seller Centre/)).toBeNull();
    expect(screen.getByRole("button", { name: "Đã làm" })).toBeEnabled();
  });
  it("a revert job's captured ref is not mistaken for the voucher id", async () => {
    vi.stubGlobal("fetch", answer([job({ kind: "voucher", status: "captured", captured_ref: "77" })]));
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(voucherCard(), { status: "approved" }) }));
    await screen.findByLabelText(/Mã voucher trên Seller Centre/);
    expect(screen.getByRole("button", { name: "Đã làm" })).toBeDisabled();
  });
});
