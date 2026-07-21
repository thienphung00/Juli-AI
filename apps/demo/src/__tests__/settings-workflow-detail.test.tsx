import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useParams, useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { SettingsWorkflowDetail } from "../components/settings-workflow-detail";
import {
  resetSettingsSaveFailureForTest,
  setSettingsSaveFailureForTest,
} from "../lib/settings/save";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: vi.fn(),
  usePathname: vi.fn(() => "/settings/workflows/replenish_inventory_3"),
  useRouter: vi.fn(),
}));

function renderDetail() {
  return render(
    <DemoStateProvider>
      <SettingsWorkflowDetail />
    </DemoStateProvider>,
  );
}

describe("Settings — workflow detail editing", () => {
  beforeEach(() => {
    vi.mocked(useParams).mockReturnValue({
      workflowKey: "replenish_inventory_3", // gitleaks:allow
    });
    vi.mocked(useRouter).mockReturnValue({
      back: vi.fn(),
      forward: vi.fn(),
      prefetch: vi.fn(),
      push,
      refresh: vi.fn(),
      replace,
    });
    localStorage.clear();
    resetSettingsSaveFailureForTest();
    push.mockClear();
    replace.mockClear();
  });

  afterEach(() => {
    resetSettingsSaveFailureForTest();
    vi.restoreAllMocks();
  });

  it("validates editable defaults against allowed ranges before save", async () => {
    const user = userEvent.setup();
    renderDetail();

    const thresholdField = screen.getByLabelText(/Ngưỡng cảnh báo hết hàng/i);
    await user.clear(thresholdField);
    await user.type(thresholdField, "2");
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    expect(
      screen.getByRole("alert"),
    ).toHaveTextContent(/giá trị hợp lệ 3–30 ngày/i);
    expect(screen.queryByRole("status", { name: /Đã lưu/i })).not.toBeInTheDocument();
  });

  it("shows saving, saved, validation, and retry states while preserving intent", async () => {
    const user = userEvent.setup();
    renderDetail();

    const thresholdField = screen.getByLabelText(/Ngưỡng cảnh báo hết hàng/i);
    await user.clear(thresholdField);
    await user.type(thresholdField, "6");

    setSettingsSaveFailureForTest(true);
    await user.click(screen.getByRole("button", { name: "Lưu" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent(
        /Không thể lưu cài đặt/i,
      );
    });
    expect(thresholdField).toHaveValue("6");
    expect(screen.getByRole("button", { name: "Thử lại" })).toBeInTheDocument();

    resetSettingsSaveFailureForTest();
    await user.click(screen.getByRole("button", { name: "Thử lại" }));

    await waitFor(() => {
      expect(
        screen.getByRole("status", { name: "Xác nhận đã lưu" }),
      ).toHaveTextContent(/Nhập thêm hàng/);
    });
    expect(thresholdField).toHaveValue("6");
  });

  it("warns on unsaved navigation and supports Save or Discard", async () => {
    const user = userEvent.setup();
    renderDetail();

    const thresholdField = screen.getByLabelText(/Ngưỡng cảnh báo hết hàng/i);
    await user.clear(thresholdField);
    await user.type(thresholdField, "8");

    await user.click(screen.getByRole("link", { name: "Về Cài đặt" }));

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/Thay đổi chưa lưu/);

    await user.click(within(dialog).getByRole("button", { name: "Huỷ bỏ thay đổi" }));
    expect(thresholdField).toHaveValue("4");
  });

  it("keeps FBT and unresolved settings read-only without fake activation", () => {
    renderDetail();

    const fbtField = screen.getByLabelText(/FBT — nhập hàng/i);
    expect(fbtField).toHaveAttribute("readonly");
    expect(
      screen.getByText(/Chưa xác định — không có executor FBT/i),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("switch", { name: /Bật FBT/i }),
    ).not.toBeInTheDocument();
  });
});
