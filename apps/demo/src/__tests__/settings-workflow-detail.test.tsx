import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useParams, useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { SettingsWorkflowDetail } from "../components/settings-workflow-detail";

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

describe("Settings — workflow detail visitor disabled", () => {
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
    push.mockClear();
    replace.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows Sign-in required placeholder instead of editable form", () => {
    renderDetail();

    expect(
      screen.getByText(
        /Chỉnh sửa mẫu quy trình yêu cầu Sign-in\. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu\./,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Lưu" })).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/Ngưỡng cảnh báo hết hàng/i),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("offers recovery link to Settings without unsaved-change dialog", async () => {
    const user = userEvent.setup();
    renderDetail();

    const backLink = screen.getByRole("link", { name: "Về Cài đặt" });
    expect(backLink).toHaveAttribute("href", "/settings");

    await user.click(backLink);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps unknown workflow recovery honest without editable fields", () => {
    vi.mocked(useParams).mockReturnValue({
      workflowKey: "unknown_workflow",
    });

    renderDetail();

    expect(screen.getByRole("status")).toHaveTextContent(
      /Mẫu quy trình không tồn tại/,
    );
    expect(screen.getByRole("link", { name: "Về Cài đặt" })).toHaveAttribute(
      "href",
      "/settings",
    );
    expect(screen.queryByRole("button", { name: "Lưu" })).not.toBeInTheDocument();
  });
});
