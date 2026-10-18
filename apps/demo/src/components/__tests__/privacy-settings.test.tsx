import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { adMeasurement, resetAdMeasurement } from "../../lib/privacy/ad-measurement";
import type { PrivacyState } from "../../lib/privacy/legal";
import {
  DELETE_DIALOG_BODY,
  DELETE_DIALOG_TITLE,
  PRIVACY_SWITCHES,
  PrivacySettings,
  SAVE_ERROR_TEXT,
  deletionPendingText,
  type PrivacyIo,
} from "../privacy-settings";

const BASE: PrivacyState = {
  marketing_opt_out: false,
  ad_measurement_opt_out: false,
  case_study_opt_in: false,
  terms_date_accepted: "2026-10-18",
  terms_accepted_at: "2026-10-18T03:00:00Z",
  liability_clause_accepted_at: "2026-10-18T03:00:00Z",
  current_terms_date: "2026-10-18",
  needs_terms_acceptance: false,
  deletion_scheduled_for: null,
};

function makeIo(overrides: Partial<PrivacyIo> = {}, initial: PrivacyState = BASE) {
  let current = initial;
  const io = {
    fetchPrivacy: vi.fn(async () => current),
    updatePrivacy: vi.fn(async (_token: string, patch: Partial<PrivacyState>) => {
      current = { ...current, ...patch };
      return current;
    }),
    fetchExport: vi.fn(async () => ({ blob: new Blob(["{}"]), filename: "juli-du-lieu-2026-10-18.json" })),
    requestDeletion: vi.fn(async () => {
      current = { ...current, deletion_scheduled_for: "2026-11-17T03:00:00Z" };
      return current;
    }),
    cancelDeletion: vi.fn(async () => {
      current = { ...current, deletion_scheduled_for: null };
      return current;
    }),
    saveFile: vi.fn(),
    ...overrides,
  };
  return io;
}

beforeEach(() => {
  resetAdMeasurement();
});

describe("Cài đặt → Quyền riêng tư (P50, D60.6)", () => {
  it("shows the three switches from the seller's saved choices", async () => {
    render(<PrivacySettings io={makeIo({}, { ...BASE, case_study_opt_in: true })} token="tok" />);

    for (const item of PRIVACY_SWITCHES) {
      expect(await screen.findByRole("switch", { name: item.label })).toBeInTheDocument();
    }
    expect(screen.getByRole("switch", { name: "Không nhận email tiếp thị" })).toHaveAttribute("aria-checked", "false");
    expect(screen.getByRole("switch", { name: "Cho phép Juli nêu tên shop làm ví dụ khách hàng" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("saves one switch with PATCH, optimistically", async () => {
    const user = userEvent.setup();
    let release: (value: PrivacyState) => void = () => undefined;
    const io = makeIo({
      updatePrivacy: vi.fn(() => new Promise<PrivacyState>((resolve) => (release = resolve))),
    });
    render(<PrivacySettings io={io} token="tok" />);
    const control = await screen.findByRole("switch", { name: "Không nhận email tiếp thị" });

    await user.click(control);

    expect(control).toHaveAttribute("aria-checked", "true");
    expect(io.updatePrivacy).toHaveBeenCalledWith("tok", { marketing_opt_out: true });
    release({ ...BASE, marketing_opt_out: true });
    await waitFor(() => expect(control).toBeEnabled());
    expect(control).toHaveAttribute("aria-checked", "true");
  });

  it("rolls the switch back and says so when saving fails", async () => {
    const user = userEvent.setup();
    const io = makeIo({ updatePrivacy: vi.fn(async () => Promise.reject(new Error("503"))) });
    render(<PrivacySettings io={io} token="tok" />);
    const control = await screen.findByRole("switch", { name: "Cho phép Juli nêu tên shop làm ví dụ khách hàng" });

    await user.click(control);

    expect(await screen.findByRole("alert")).toHaveTextContent(SAVE_ERROR_TEXT);
    expect(control).toHaveAttribute("aria-checked", "false");
  });

  it("stops ad measurement in this browser the moment the seller opts out", async () => {
    const user = userEvent.setup();
    render(<PrivacySettings io={makeIo()} token="tok" />);

    await user.click(await screen.findByRole("switch", { name: "Không đo lường quảng cáo" }));

    expect(adMeasurement()).toBe("blocked");
  });

  it("downloads the export as a file", async () => {
    const user = userEvent.setup();
    const io = makeIo();
    render(<PrivacySettings io={io} token="tok" />);

    await user.click(await screen.findByRole("button", { name: "Tải dữ liệu của tôi" }));

    await waitFor(() => expect(io.saveFile).toHaveBeenCalledWith(expect.objectContaining({ filename: "juli-du-lieu-2026-10-18.json" })));
  });

  it("explains deletion in a dialog before asking, then shows the date and the cancel button", async () => {
    const user = userEvent.setup();
    const io = makeIo();
    render(<PrivacySettings io={io} token="tok" />);

    await user.click(await screen.findByRole("button", { name: "Xoá tài khoản" }));
    const dialog = screen.getByRole("dialog", { name: DELETE_DIALOG_TITLE });
    for (const line of DELETE_DIALOG_BODY) expect(dialog).toHaveTextContent(line);
    expect(dialog).toHaveTextContent("30 ngày");
    expect(dialog).toHaveTextContent("Hoá đơn được giữ 10 năm theo luật kế toán.");
    expect(io.requestDeletion).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Xoá tài khoản" }));

    expect(await screen.findByTestId("deletion-pending")).toHaveTextContent(
      deletionPendingText("2026-11-17T03:00:00Z"),
    );
    expect(screen.getByTestId("deletion-pending")).toHaveTextContent("17/11/2026");
    expect(screen.queryByRole("dialog")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Huỷ yêu cầu xoá" }));
    await waitFor(() => expect(screen.queryByTestId("deletion-pending")).toBeNull());
    expect(io.cancelDeletion).toHaveBeenCalledWith("tok");
  });

  it("closes the dialog with Quay lại without asking", async () => {
    const user = userEvent.setup();
    const io = makeIo();
    render(<PrivacySettings io={io} token="tok" />);

    await user.click(await screen.findByRole("button", { name: "Xoá tài khoản" }));
    await user.click(screen.getByRole("button", { name: "Quay lại" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(io.requestDeletion).not.toHaveBeenCalled();
  });

  it("gives the contact e-mail and both legal pages", async () => {
    render(<PrivacySettings io={makeIo()} token="tok" />);

    expect(await screen.findByRole("link", { name: "lienhe@app-juli.com" })).toHaveAttribute(
      "href",
      "mailto:lienhe@app-juli.com",
    );
    expect(screen.getByRole("link", { name: "Chính sách bảo mật" })).toHaveAttribute("href", "https://app-juli.com/privacy");
    expect(screen.getByRole("link", { name: "Điều khoản dịch vụ" })).toHaveAttribute("href", "https://app-juli.com/terms");
  });

  it("uses no em dash in any visible copy (D44.4)", async () => {
    const { container } = render(<PrivacySettings io={makeIo()} token="tok" />);
    await screen.findByRole("switch", { name: "Không nhận email tiếp thị" });
    expect(container.textContent).not.toContain("—");
    expect(DELETE_DIALOG_BODY.join(" ")).not.toContain("—");
  });
});
