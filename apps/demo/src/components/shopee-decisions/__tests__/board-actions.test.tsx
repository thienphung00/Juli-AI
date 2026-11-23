import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import type { BoardApi, ExternalCommit, ExternalPreview, ImportJob } from "../../../lib/shopee-decisions/board";
import { DEMO_RECO_BASE, createRecoApi, opsRecoBase } from "../../../lib/shopee-decisions/client";
import { BoardActions } from "../board-actions";

/** Thực hiện board sync (owner 2026-11-16): reset with one confirm, xlsx import preview → Nhập. Synthetic data. */

const preview = (over: Partial<ExternalPreview> = {}): ExternalPreview => ({
  file_hash: "h1",
  token: "preview-token",
  missing_columns: [],
  counts: { rows: 2, cards: 1, create: 1, exists: 0, skipped: 1 },
  rows: [{ row: 2, ref: "NG-01", category: "Voucher", items: ["P1"], shop_wide: false, status: "done", status_label: "Đã làm", started_on: "2026-11-01", run_days: 7, forecast_as_of: null, skipped: false, reason: null, reason_label: null, cards: [{ ref: "NG-01", change_kind: "title", action: "create" }] }],
  skipped: [{ row: 3, ref: "NG-02", category: "", items: [], shop_wide: false, status: "unknown", status_label: "", started_on: null, run_days: null, forecast_as_of: null, skipped: true, reason: "no_product", reason_label: "Không có sản phẩm", cards: [] }],
  ...over,
});

const commit = (over: Partial<ExternalCommit> = {}): ExternalCommit => ({
  file_hash: "h1",
  created: 1,
  exists: 1,
  refused: 1,
  skipped: 0,
  executed: 1,
  cards: [
    { ref: "NG-01", row: 2, change_kind: "title", status: "done", run_days: 7, action: "created" },
    { ref: "NG-02", row: 3, change_kind: "title", status: "done", run_days: 7, action: "exists", reason: "exists" },
    { ref: "NG-03", row: 4, change_kind: "title", status: "done", run_days: 7, action: "refused", reason: "build_failed", message: "Thiếu giá vốn" },
  ],
  ...over,
});

const job = (status: ImportJob["status"], result: ExternalCommit | null, error: ImportJob["error"] = null): ImportJob => ({ job_id: "j1", status, result, error });

const fakeBoard = (over: Partial<BoardApi> = {}): BoardApi => ({
  reset: vi.fn().mockResolvedValue({ withdrawn: 4, by_status: {}, card_ids: [], codes: [], reason_code: "reset", at: "2026-11-16T10:00:00" }),
  previewImport: vi.fn().mockResolvedValue(preview()),
  commitImport: vi.fn().mockResolvedValue(job("running", null)),
  importStatus: vi.fn().mockResolvedValue(null),
  ...over,
});

const xlsx = () => new File([new Uint8Array([80, 75, 3, 4])], "ngoai-juli.xlsx");

describe("Thực hiện · Xoá bảng", () => {
  it("asks once, then withdraws every open card and refreshes the board", async () => {
    const board = fakeBoard();
    const changed = vi.fn();
    render(<BoardActions board={board} onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Xoá bảng" }));
    expect(screen.getByText("Xoá toàn bộ thẻ trên bảng Thực hiện?")).toBeInTheDocument();
    expect(board.reset).not.toHaveBeenCalled();
    fireEvent.click(within(screen.getByTestId("sd-board-reset")).getByRole("button", { name: "Xoá" }));
    await waitFor(() => expect(screen.getByTestId("sd-board-done")).toHaveTextContent("Đã xoá 4 thẻ"));
    expect(changed).toHaveBeenCalled();
  });

  it("a non-owner gets the refusal in words, never the code", async () => {
    const board = fakeBoard({ reset: vi.fn().mockRejectedValue(new ShopeeApiError(403, "board_owner_only", "board_owner_only")) });
    render(<BoardActions board={board} onChanged={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Xoá bảng" }));
    fireEvent.click(within(screen.getByTestId("sd-board-reset")).getByRole("button", { name: "Xoá" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Chỉ chủ shop hoặc thành viên của shop làm được việc này.");
    expect(document.body.textContent).not.toContain("board_owner_only");
  });
});

describe("Thực hiện · Nhập thẻ đã làm ngoài Juli", () => {
  it("previews the rows and the skipped ones with their reason, then Nhập sends the same file with the token", async () => {
    const board = fakeBoard();
    const changed = vi.fn();
    render(<BoardActions board={board} onChanged={changed} pollMs={5} />);
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    fireEvent.change(screen.getByTestId("sd-board-file"), { target: { files: [xlsx()] } });
    const row = await screen.findByTestId("sd-board-row-2");
    expect(row).toHaveTextContent("NG-01");
    expect(row).toHaveTextContent("Tên sản phẩm");
    expect(row).toHaveTextContent("Đã làm");
    expect(row).toHaveTextContent("01/11");
    expect(screen.getByTestId("sd-board-skip-3")).toHaveTextContent("Bỏ qua: Không có sản phẩm");
    const b64 = (board.previewImport as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
    expect(b64).toBe(btoa(String.fromCharCode(80, 75, 3, 4)));
    fireEvent.click(screen.getByTestId("sd-board-commit"));
    await waitFor(() => expect(board.commitImport).toHaveBeenCalledWith(b64, "preview-token"));
    expect(await screen.findByTestId("sd-board-running")).toHaveTextContent("Đang nhập…");
  });

  it("missing columns are named and nothing can be imported", async () => {
    render(<BoardActions board={fakeBoard({ previewImport: vi.fn().mockResolvedValue(preview({ missing_columns: ["Mã", "Trạng thái"] })) })} onChanged={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    fireEvent.change(screen.getByTestId("sd-board-file"), { target: { files: [xlsx()] } });
    expect(await screen.findByTestId("sd-board-missing")).toHaveTextContent("Thiếu cột: Mã, Trạng thái");
    expect(screen.getByTestId("sd-board-commit")).toBeDisabled();
  });
});

describe("board client", () => {
  it("posts to /v1/demo/shopee/board with the shop and unwraps data; Ops has no board", async () => {
    const f = vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: { withdrawn: 2 } }), { status: 200 }));
    const api = createRecoApi({ base: DEMO_RECO_BASE, token: "t", shopId: "s1", fetchImpl: f });
    expect((await api.board!.reset()).withdrawn).toBe(2);
    const [url, init] = f.mock.calls[0]!;
    expect(url).toBe("/v1/demo/shopee/board/reset");
    expect(JSON.parse(init.body)).toEqual({ confirm: true });
    expect(init.headers["X-Shop-Id"]).toBe("s1");
    expect(createRecoApi({ base: opsRecoBase("s1"), token: "t" }).board).toBeUndefined();
  });
});

describe("Thực hiện · Nhập: background job (F6.2)", () => {
  it("shows Đang nhập… while it runs, then the per-row result with the refused reason", async () => {
    const importStatus = vi.fn().mockResolvedValueOnce(null).mockResolvedValueOnce(job("running", null)).mockResolvedValue(job("done", commit()));
    const board = fakeBoard({ importStatus });
    const changed = vi.fn();
    render(<BoardActions board={board} onChanged={changed} pollMs={5} />);
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    fireEvent.change(screen.getByTestId("sd-board-file"), { target: { files: [xlsx()] } });
    await screen.findByTestId("sd-board-row-2");
    fireEvent.click(screen.getByTestId("sd-board-commit"));
    expect(await screen.findByTestId("sd-board-running")).toBeInTheDocument();
    expect(await screen.findByTestId("sd-board-done")).toHaveTextContent("Đã nhập 1 thẻ · 1 đã có · 1 không nhập được");
    expect(screen.queryByTestId("sd-board-running")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    expect(screen.getByTestId("sd-board-result-NG-03-title")).toHaveTextContent("Không nhập được: Thiếu giá vốn");
    expect(screen.getByTestId("sd-board-result-NG-02-title")).toHaveTextContent("Đã có");
    expect(screen.getByTestId("sd-board-result-NG-01-title")).toHaveTextContent("Đã tạo");
    expect(changed).toHaveBeenCalled();
  });

  it("after a reload the last import is read again from the server", async () => {
    render(<BoardActions board={fakeBoard({ importStatus: vi.fn().mockResolvedValue(job("done", commit())) })} onChanged={() => undefined} />);
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    expect(await screen.findByTestId("sd-board-result-NG-03-title")).toHaveTextContent("Thiếu giá vốn");
  });

  it("a failed job is told in words", async () => {
    render(<BoardActions board={fakeBoard({ importStatus: vi.fn().mockResolvedValue(job("failed", null, { code: "external_file_changed" })) })} onChanged={() => undefined} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("File đã đổi sau khi xem trước.");
  });
});

describe("Thực hiện · the board refetch keeps the panels open (F6.1)", () => {
  it("Xoá bảng confirm and the import preview survive a refetch of the card list", async () => {
    const { ThucHienView } = await import("../thuc-hien");
    const { RecoHostProvider } = await import("../../../lib/shopee-decisions/context");
    const { fakeReco } = await import("../../../lib/shopee-decisions/__tests__/fixtures");
    const { hostOf } = await import("./harness");
    const card = { card_id: "a", code: "JC-1", title: "T", family: "listing", family_label: "Listing", change_kind: "title", product_id: "P1", state: "cho_dien", completed: 1, bad: null, fields: { filled: 0, total: 0 }, jobs: { total: 0, filled: 0, saved: 0, failed: 0 }, noun: "x", not_seen: false, mismatch: null, executed_at: null, verified_at: null, measure_start: null, measure_days: null, open_job: null };
    const data = { platform: "shopee", connector: { version: "0.3.18", last_check_at: null, connected: true, seller_centre_open: false }, cards: [card], counts: {} };
    let calls = 0;
    const reco = {
      ...fakeReco({ execution: data as never }),
      board: fakeBoard(),
      executionStates: vi.fn(async () => {
        calls += 1;
        await new Promise((r) => setTimeout(r, 30));
        return data as never;
      }),
      reconcile: vi.fn().mockResolvedValue({ requested: true }),
    };
    render(
      <RecoHostProvider host={hostOf(reco as never)}>
        <ThucHienView />
      </RecoHostProvider>,
    );
    await screen.findByTestId("sd-board");
    fireEvent.click(screen.getByRole("button", { name: "Xoá bảng" }));
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    fireEvent.change(screen.getByTestId("sd-board-file"), { target: { files: [xlsx()] } });
    await screen.findByTestId("sd-board-row-2");
    const before = calls;
    fireEvent.click(screen.getByRole("button", { name: "Đối chiếu ngay" }));
    await waitFor(() => expect(calls).toBeGreaterThan(before));
    // while the refetch is pending and after it lands, the preview is still there
    expect(screen.getByTestId("sd-board-row-2")).toBeInTheDocument();
    await new Promise((r) => setTimeout(r, 80));
    expect(screen.getByTestId("sd-board-row-2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Xoá bảng" }));
    expect(screen.getByTestId("sd-board-reset")).toBeInTheDocument();
  });
});
