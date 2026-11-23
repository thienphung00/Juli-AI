import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { type FillJobRow, FillJobsChecklist, fillStatusLabel } from "../listing-extras";

/** batch-1123-a E109: a save no reader confirms shows the server's note, never "Đã lưu" / "Xong". */

const job = (over: Partial<FillJobRow>): FillJobRow => ({
  id: "6f1c9a3e-1d2b-4c5d-8e7f-0a1b2c3d4e5f",
  kind: "deal_end",
  version: 1,
  group_code: null,
  status: "saved",
  target: {},
  captured_ref: null,
  error: null,
  open_path: null,
  payload: { mode: "revert" },
  ...over,
});
const NOTE = "Đã lưu trên Shopee · chưa đọc lại";

describe("fill job status chip", () => {
  it("an unread save (status_note present) shows the note, not Đã lưu / Xong", () => {
    expect(fillStatusLabel(job({ status_note: NOTE }))).toBe(NOTE);
    expect(fillStatusLabel(job({ status: "captured", status_note: NOTE }))).toBe(NOTE);
    render(<FillJobsChecklist enabled jobs={[job({ status_note: NOTE })]} />);
    expect(screen.getByTestId("sd-fill-jobs")).toHaveTextContent(NOTE);
    expect(screen.getByTestId("sd-fill-jobs")).not.toHaveTextContent(/Đã lưu$|Xong/);
  });

  it("a save a reader confirms (no note) keeps Đã lưu / Xong; an open job keeps its label", () => {
    expect(fillStatusLabel(job({ kind: "voucher", status: "captured", status_note: null }))).toBe("Xong");
    expect(fillStatusLabel(job({ kind: "voucher", status: "saved" }))).toBe("Đã lưu");
    expect(fillStatusLabel(job({ status: "filled", status_note: NOTE }))).toBe("Đã điền · chờ bạn lưu");
  });
});
