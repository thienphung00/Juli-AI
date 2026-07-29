import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname, useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoShell } from "../components/demo-shell";
import { DemoStateProvider } from "../components/demo-state";
import { SettingsView } from "../components/settings-view";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

const replace = vi.fn();
const push = vi.fn();

function renderSettings() {
  return render(
    <DemoStateProvider>
      <SettingsView />
    </DemoStateProvider>,
  );
}

describe("Settings — visitor disabled placeholder", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/settings");
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
  it("keeps Settings nav destination discoverable with Cài đặt heading and aria-disabled tabs", () => {
    renderSettings();

    expect(screen.getByRole("heading", { name: "Cài đặt" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Mẫu quy trình" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("tab", { name: "Ngưỡng" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );
    expect(screen.getByRole("tablist", { name: "Phần cài đặt" })).toBeInTheDocument();
  });

  it("explains configuration requires Sign-in without editable workflow or threshold surfaces", () => {
    renderSettings();

    expect(
      screen.getByText(
        /Mẫu quy trình và ngưỡng yêu cầu Sign-in\. Bạn vẫn có thể khám phá toàn bộ Demo bằng dữ liệu mẫu\./,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByTestId(/^settings-workflow-row-/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Lưu/i })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Chỉnh sửa mặc định/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/không thay thế việc phê duyệt tại Quyết định/i),
    ).toBeInTheDocument();
  });

  it("routes disabled tab interaction through Sign-in stub feedback without navigation", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(
      <DemoShell>
        <SettingsView />
      </DemoShell>,
    );

    await user.click(screen.getByRole("tab", { name: "Ngưỡng" }));

    expect(
      screen.getByRole("status", { name: "Phản hồi Demo" }),
    ).toHaveTextContent("Sign-in sắp ra mắt");
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });
});
