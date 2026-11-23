import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JOURNEY_VERIFIED, detailOf, fakeReco, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import { jobDiffLines, jobHref, jobWord, markDoneBody, type CardJob } from "../../../lib/shopee-decisions/card-job";
import { KINDS_92, SERVER_KIND_NAMES, buildVersion, initialForms } from "../../../lib/shopee-decisions/builder-p92";
import { kindLabel } from "../../../lib/shopee-decisions/model";
import type { ExecutionCard, ExecutionStates } from "../../../lib/shopee-decisions/types";
import { AUTH_SESSION_STORAGE_KEY } from "../../../lib/supabase-auth";
import { CardPage } from "../card-page";
import { ThucHienView } from "../thuc-hien";
import { renderReco } from "./harness";

/** batch-1123-a2 Track L: Shopee names, open-a-job links (K3), Thực hiện step words and Đã làm (K4), combo defaults. Synthetic data only. */

const JOB_ID = "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f";
const job = (over: Partial<CardJob> = {}): CardJob => ({
  job_id: JOB_ID,
  role: "forward",
  kind: "combo",
  status: "opened",
  status_label: "Chờ điền",
  open_path: "/portal/marketing/bundle/new",
  filled: 2,
  total: 8,
  readback: null,
  ...over,
});

const row = (over: Partial<ExecutionCard>): ExecutionCard => ({
  card_id: "c1",
  code: "JC-2611-0301",
  title: "Combo mua 2 giảm 5%",
  family: "combo",
  family_label: "Combo Khuyến Mãi",
  change_kind: "combo_multi",
  product_id: "P1",
  state: "cho_dien",
  completed: 1,
  bad: null,
  fields: { filled: 0, total: 8 },
  jobs: { total: 1, filled: 0, saved: 0, failed: 0 },
  noun: "combo",
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
  connector: { version: "0.3.32", last_check_at: "2026-11-23T09:05:00", connected: true, seller_centre_open: true },
  cards,
  counts: {},
});

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ data: { enabled: true, jobs: [] } }), { status: 200 })));
});
afterEach(() => {
  window.localStorage.clear();
  vi.unstubAllGlobals();
});

describe("L-A6 · Shopee names", () => {
  it("the builder strategy list and the server names use Shopee's words", () => {
    const names = KINDS_92.map((k) => k.name);
    expect(names).toContain("Mã Giảm Giá");
    expect(names).toContain("Mua Kèm Deal Sốc");
    expect(names).toContain("Flash Sale Của Shop");
    expect(names).not.toContain("Voucher");
    expect(names).not.toContain("Deal Sốc");
    expect(names).not.toContain("Giá bán + Flash sale");
    expect(SERVER_KIND_NAMES["voucher"]).toBe("Mã Giảm Giá");
  });

  it("no raw kind id renders in the import result: every import kind has a Vietnamese name", () => {
    expect(kindLabel({ change_kind: "ads_roas_target" })).toBe("Dịch vụ hiển thị · ROAS mục tiêu");
    expect(kindLabel({ change_kind: "ads_remove_product" })).toBe("Dịch vụ hiển thị · Xoá sản phẩm khỏi chiến dịch");
    expect(kindLabel({ change_kind: "affiliate_commission" })).toBe("Tiếp thị liên kết · Hoa hồng");
    expect(kindLabel({ change_kind: "affiliate_target_campaign" })).toBe("Tiếp thị liên kết · Chiến dịch mục tiêu");
    expect(kindLabel({ change_kind: "voucher" })).toBe("Mã Giảm Giá");
    for (const k of ["ads_roas_target", "ads_remove_product", "affiliate_commission", "affiliate_target_campaign"]) expect(kindLabel({ change_kind: k })).not.toMatch(/_/);
  });
});

describe("K3/K4 adapter", () => {
  it("the open link is the job's own page with only its id in the hash", () => {
    expect(jobHref(job())).toBe(`https://banhang.shopee.vn/portal/marketing/bundle/new#juli-fill=${JOB_ID}`);
    expect(jobHref(job({ open_path: null }))).toBeNull();
    expect(jobHref(null)).toBeNull();
  });

  it("status words come from the backend label, else the K4 mapping; a read-back says Khớp / Lệch", () => {
    expect(jobWord(job({ status_label: "Đã lưu · chờ xác minh", status: "saved" }))).toBe("Đã lưu · chờ xác minh");
    expect(jobWord(job({ status_label: null, status: "queued" }))).toBe("Chờ điền");
    expect(jobWord(job({ status_label: null, status: "filled" }))).toBe("Đã điền · chờ bạn lưu");
    expect(jobWord(job({ status_label: null, status: "saved" }))).toBe("Đã lưu · chờ xác minh");
    expect(jobWord(job({ readback: { result: "match", diffs: [] } }))).toBe("Khớp");
    const bad = job({ readback: { result: "mismatch", diffs: [{ field: "start", label_vi: "Bắt đầu", card_value: "01/03", seen_value: "03/01" }] } });
    expect(jobWord(bad)).toBe("Lệch");
    expect(jobDiffLines(bad)).toEqual(["Bắt đầu: Seller Centre 03/01 · thẻ 01/03"]);
  });

  it("a typed value goes as `id` when it is digits, else as `code`; nothing typed sends nothing", () => {
    expect(markDoneBody(" 528996878602285 ")).toEqual({ id: "528996878602285" });
    expect(markDoneBody("ORYVGD2OW")).toEqual({ code: "ORYVGD2OW" });
    expect(markDoneBody("  ")).toEqual({});
  });
});

describe("L-E118 · Thực hiện step and Đã làm", () => {
  it("a combo the Connector filled 2/8 shows Chờ điền 2/8, opens its job and has a Đã làm box", async () => {
    const reco = fakeReco({ execution: states([row({ job: job(), can_mark_done: true })]) });
    renderReco(<ThucHienView />, reco);
    const r = await screen.findByTestId("sd-th-c1");
    expect(within(r).getByTestId("sd-th-state-c1")).toHaveTextContent("Chờ điền");
    expect(within(r).getByTestId("sd-th-detail-c1")).toHaveTextContent("2/8 đã điền");
    expect(within(r).getByRole("link", { name: "Mở Seller Centre" })).toHaveAttribute("href", `https://banhang.shopee.vn/portal/marketing/bundle/new#juli-fill=${JOB_ID}`);
    expect(within(r).getByRole("link", { name: "Mở Seller Centre" })).toHaveAttribute("target", "_blank");
    const box = within(r).getByTestId("sd-th-code-c1");
    const done = within(r).getByRole("button", { name: "Đã làm" });
    expect(done).toBeEnabled();
    fireEvent.change(box, { target: { value: "528996878602285" } });
    fireEvent.click(done);
    await waitFor(() => expect(reco.calls.find((c) => c.name === "executed")?.args).toEqual(["c1", { id: "528996878602285" }]));
  });

  it("Đã làm without a typed value sends nothing; a typed code is sent as a code", async () => {
    const reco = fakeReco({ execution: states([row({ job: job({ status: "saved", status_label: "Đã lưu · chờ xác minh" }), can_mark_done: true, state: "da_dien", completed: 3 })]) });
    renderReco(<ThucHienView />, reco);
    const r = await screen.findByTestId("sd-th-c1");
    expect(within(r).getByTestId("sd-th-state-c1")).toHaveTextContent("Đã lưu · chờ xác minh");
    fireEvent.click(within(r).getByRole("button", { name: "Đã làm" }));
    await waitFor(() => expect(reco.calls.find((c) => c.name === "executed")?.args).toEqual(["c1", {}]));
  });

  it("the card's can_mark_done=false hides Đã làm", async () => {
    renderReco(<ThucHienView />, fakeReco({ execution: states([row({ job: job(), can_mark_done: false })]) }));
    const r = await screen.findByTestId("sd-th-c1");
    expect(within(r).queryByRole("button", { name: "Đã làm" })).toBeNull();
  });

  it("a read-back mismatch lists the differing fields", async () => {
    const bad = job({ status: "captured", readback: { result: "mismatch", diffs: [{ field: "start", label_vi: "Ngày bắt đầu", card_value: "01/03/2027", seen_value: "03/01/2027" }] } });
    renderReco(<ThucHienView />, fakeReco({ execution: states([row({ state: "lech", completed: 3, bad: 3, job: bad })]) }));
    expect(await screen.findByTestId("sd-th-detail-c1")).toHaveTextContent("Ngày bắt đầu: Seller Centre 03/01/2027 · thẻ 01/03/2027");
  });

  it("an undo job shows as Hoàn tác with its own word and opens the revert page", async () => {
    const revert = job({ role: "revert", kind: "combo_end", status: "filled", status_label: "Đã điền · chờ bạn lưu", open_path: "/portal/marketing/bundle/list" });
    renderReco(<ThucHienView />, fakeReco({ execution: states([row({ state: "khop", completed: 4, job: revert })]) }));
    const r = await screen.findByTestId("sd-th-c1");
    expect(within(r).getByTestId("sd-th-state-c1")).toHaveTextContent("Hoàn tác · Đã điền · chờ bạn lưu");
    expect(within(r).getByRole("link", { name: "Mở Seller Centre" })).toHaveAttribute("href", `https://banhang.shopee.vn/portal/marketing/bundle/list#juli-fill=${JOB_ID}`);
  });
});

describe("L-E114 · the card detail opens the job's page", () => {
  it("Hoàn tác: Mở và điền and the page button open the revert job's page, never the create page", async () => {
    const revert = job({ role: "revert", kind: "voucher_end", status: "queued", open_path: "/portal/marketing/vouchers/list" });
    const detail = detailOf(voucherCard(), { status: "executed", journey: JOURNEY_VERIFIED, job: revert });
    const reco = fakeReco({ detail });
    renderReco(<CardPage from={null} id="card-voucher" />, { ...reco, revertFill: async () => ({ card_id: "card-voucher", jobs: [], ready: false }) });
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    const want = `https://banhang.shopee.vn/portal/marketing/vouchers/list#juli-fill=${JOB_ID}`;
    expect(await screen.findByTestId("sd-revert-open")).toHaveAttribute("href", want);
    expect(screen.getByTestId("sd-revert-open")).toHaveAttribute("target", "_blank");
    expect(within(screen.getByTestId("sd-revert-sheet")).getByTestId("sd-page-open")).toHaveAttribute("href", want);
    expect(document.body.innerHTML).not.toContain("vouchers/new");
  });

  it("Hoàn tác with no revert job yet: the sheet shows no 'Mở trang' to the forward page", async () => {
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail: detailOf(voucherCard(), { status: "executed", journey: JOURNEY_VERIFIED }) }));
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    const reverse = await screen.findByTestId("sd-revert-sheet");
    expect(within(reverse).queryByTestId("sd-page-open")).toBeNull();
  });

  it("Mở và điền with no revert job yet queues it and opens the new job's page in a new tab", async () => {
    const tab = { location: { href: "" }, close: vi.fn(), opener: {} };
    vi.stubGlobal("open", vi.fn(() => tab));
    const queued = { id: JOB_ID, kind: "voucher_end", version: 1, group_code: null, status: "queued", target: {}, captured_ref: null, error: null, open_path: "/portal/marketing/vouchers/list", payload: { mode: "revert" } };
    const revertFill = vi.fn(async () => ({ card_id: "card-voucher", jobs: [queued], ready: false }));
    const reco = fakeReco({ detail: detailOf(voucherCard(), { status: "executed", journey: JOURNEY_VERIFIED }) });
    renderReco(<CardPage from={null} id="card-voucher" />, { ...reco, revertFill } as never);
    fireEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    fireEvent.click(await screen.findByTestId("sd-revert-fill"));
    await waitFor(() => expect(tab.location.href).toBe(`https://banhang.shopee.vn/portal/marketing/vouchers/list#juli-fill=${JOB_ID}`));
    expect(tab.close).not.toHaveBeenCalled();
  });

  it("an approved card with a forward job: Mở và điền opens that job", async () => {
    const detail = detailOf(voucherCard(), { status: "approved", job: job({ kind: "voucher", open_path: "/portal/marketing/vouchers/new?usecase=1" }) });
    renderReco(<CardPage from={null} id="card-voucher" />, fakeReco({ detail }));
    expect(await screen.findByTestId("sd-page-open")).toHaveAttribute("href", `https://banhang.shopee.vn/portal/marketing/vouchers/new?usecase=1#juli-fill=${JOB_ID}`);
  });
});

describe("L-E117 · combo builder defaults and HH:mm", () => {
  it("the combo type is preselected (Giảm giá theo %) and a version builds from the defaults", () => {
    const f = initialForms();
    expect(f.combo.dtype).toBe("pct");
    const built = buildVersion("combo", { ...f, combo: { ...f.combo, dtype: "" as never, items: ["1001", "1002"] } }, { product: { item_id: "1001" } } as never);
    expect(built.problem ?? "").not.toMatch(/Loại/);
  });
});
