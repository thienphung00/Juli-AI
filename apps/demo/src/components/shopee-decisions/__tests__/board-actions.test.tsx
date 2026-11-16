import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import type { BoardApi, ExternalPreview } from "../../../lib/shopee-decisions/board";
import { DEMO_RECO_BASE, createRecoApi, opsRecoBase } from "../../../lib/shopee-decisions/client";
import { BoardActions } from "../board-actions";

/** Thực hiện board sync (owner 2026-11-16): reset with one confirm, xlsx import preview → Nhập. Synthetic data. */

const preview = (over: Partial<ExternalPreview> = {}): ExternalPreview => ({
  file_hash: "h1",
  token: "tok-12345678",
  missing_columns: [],
  counts: { rows: 2, cards: 1, create: 1, exists: 0, skipped: 1 },
  rows: [{ row: 2, ref: "NG-01", category: "Voucher", items: ["P1"], shop_wide: false, status: "done", status_label: "Đã làm", started_on: "2026-11-01", run_days: 7, forecast_as_of: null, skipped: false, reason: null, reason_label: null, cards: [{ ref: "NG-01", change_kind: "title", action: "create" }] }],
  skipped: [{ row: 3, ref: "NG-02", category: "", items: [], shop_wide: false, status: "unknown", status_label: "", started_on: null, run_days: null, forecast_as_of: null, skipped: true, reason: "no_product", reason_label: "Không có sản phẩm", cards: [] }],
  ...over,
});

const fakeBoard = (over: Partial<BoardApi> = {}): BoardApi => ({
  reset: vi.fn().mockResolvedValue({ withdrawn: 4, by_status: {}, card_ids: [], codes: [], reason_code: "reset", at: "2026-11-16T10:00:00" }),
  previewImport: vi.fn().mockResolvedValue(preview()),
  commitImport: vi.fn().mockResolvedValue({ file_hash: "h1", created: 1, exists: 0, refused: 0, skipped: 1, executed: 1, cards: [] }),
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
    expect(await screen.findByRole("alert")).toHaveTextContent("Chỉ chủ shop làm được việc này.");
    expect(document.body.textContent).not.toContain("board_owner_only");
  });
});

describe("Thực hiện · Nhập thẻ đã làm ngoài Juli", () => {
  it("previews the rows and the skipped ones with their reason, then Nhập sends the same file with the token", async () => {
    const board = fakeBoard();
    const changed = vi.fn();
    render(<BoardActions board={board} onChanged={changed} />);
    fireEvent.click(screen.getByRole("button", { name: "Nhập thẻ đã làm ngoài Juli" }));
    fireEvent.change(screen.getByTestId("sd-board-file"), { target: { files: [xlsx()] } });
    const row = await screen.findByTestId("sd-board-row-2");
    expect(row).toHaveTextContent("NG-01");
    expect(row).toHaveTextContent("Tiêu đề");
    expect(row).toHaveTextContent("Đã làm");
    expect(row).toHaveTextContent("01/11");
    expect(screen.getByTestId("sd-board-skip-3")).toHaveTextContent("Bỏ qua: Không có sản phẩm");
    const b64 = (board.previewImport as ReturnType<typeof vi.fn>).mock.calls[0]![0] as string;
    expect(b64).toBe(btoa(String.fromCharCode(80, 75, 3, 4)));
    fireEvent.click(screen.getByTestId("sd-board-commit"));
    await waitFor(() => expect(board.commitImport).toHaveBeenCalledWith(b64, "tok-12345678"));
    expect(await screen.findByTestId("sd-board-done")).toHaveTextContent("Đã nhập 1 thẻ");
    expect(changed).toHaveBeenCalled();
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
