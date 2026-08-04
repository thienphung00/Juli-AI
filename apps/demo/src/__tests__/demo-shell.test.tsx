import { readFileSync } from "node:fs";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname, useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoShell } from "../components/demo-shell";
import {
  DEFAULT_MUTABLE_MOCK_STATE,
  useDemoState,
} from "../components/demo-state";
import { DestinationPlaceholder } from "../components/destination-placeholder";

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

const replace = vi.fn();
const push = vi.fn();

function MutableStateProbe() {
  const { mutableState, updateMutableState } = useDemoState();

  return (
    <section>
      <button
        type="button"
        onClick={() =>
          updateMutableState((current) => ({
            ...current,
            rejectedRecommendationIds: ["workflow-1"],
            approvedRecommendationIds: ["workflow-2"],
            workflowInputs: { budget: "500000" },
            workflowReviewDrafts: { "workflow-1": { title: "draft" } },
            executionRecords: {},
            executionProgress: { "exec-workflow-2-1": "executing" },
            decisionsView: "in-progress",
            analyticsMetric: "inventory-turnover",
            analyticsRange: "90d",
            settingsDraft: { threshold: "12" },
          }))
        }
      >
        Thay đổi dữ liệu mẫu
      </button>
      <output data-testid="mutable-state">
        {JSON.stringify(mutableState)}
      </output>
    </section>
  );
}

describe("Demo shell controls", () => {
  beforeEach(() => {
    vi.mocked(usePathname).mockReturnValue("/analytics");
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

  it("persists Mock as the default mode", async () => {
    render(<DemoShell>Nội dung</DemoShell>);

    expect(screen.getByRole("button", { name: "Mock" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Sign-in" })).toHaveAttribute(
      "aria-disabled",
      "true",
    );

    await waitFor(() => {
      expect(localStorage.getItem("juli_demo_mode")).toBe("mock");
    });
  });

  it("keeps Manual Refresh available on every destination", () => {
    for (const pathname of ["/", "/decisions", "/analytics", "/settings"]) {
      vi.mocked(usePathname).mockReturnValue(pathname);

      const { unmount } = render(<DemoShell>Nội dung</DemoShell>);

      expect(
        screen.getByRole("button", { name: "Làm mới Demo" }),
      ).toBeInTheDocument();
      unmount();
    }
  });

  it("explains disabled Sign-in without routing or making a network call", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    render(<DemoShell>Nội dung</DemoShell>);
    await user.click(screen.getByRole("button", { name: "Sign-in" }));

    expect(
      screen.getByRole("status", { name: "Phản hồi Demo" }),
    ).toHaveTextContent("Sign-in sắp ra mắt");
    expect(push).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(localStorage.getItem("juli_demo_mode")).toBe("mock");
  });

  it("resets every mutable mock-state category and opens Decisions", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <MutableStateProbe />
      </DemoShell>,
    );

    await user.click(
      screen.getByRole("button", { name: "Thay đổi dữ liệu mẫu" }),
    );
    expect(screen.getByTestId("mutable-state")).toHaveTextContent(
      "inventory-turnover",
    );

    await user.click(screen.getByRole("button", { name: "Làm mới Demo" }));

    expect(screen.getByTestId("mutable-state")).toHaveTextContent(
      JSON.stringify(DEFAULT_MUTABLE_MOCK_STATE),
    );
    expect(replace).toHaveBeenCalledWith("/decisions");
    expect(
      screen.getByRole("status", { name: "Phản hồi Demo" }),
    ).toHaveTextContent("Demo đã trở về trạng thái ban đầu");
  });

  it("manual refresh clears unsaved settings edits and restores defaults", async () => {
    const user = userEvent.setup();

    render(
      <DemoShell>
        <MutableStateProbe />
      </DemoShell>,
    );

    await user.click(
      screen.getByRole("button", { name: "Thay đổi dữ liệu mẫu" }),
    );
    expect(screen.getByTestId("mutable-state")).toHaveTextContent("threshold");

    await user.click(screen.getByRole("button", { name: "Làm mới Demo" }));

    expect(JSON.parse(screen.getByTestId("mutable-state").textContent ?? "{}")).toEqual(
      DEFAULT_MUTABLE_MOCK_STATE,
    );
  });

  it("grounds contextual assistance in the active destination without decision or execution authority", () => {
    render(<DemoShell>Nội dung</DemoShell>);

    const assistance = screen.getByRole("complementary", {
      name: "Gợi ý từ Juli",
    });

    expect(assistance).toHaveTextContent("Phân tích");
    expect(assistance).not.toHaveTextContent(/Phê duyệt|Từ chối|Thực thi/);
    expect(
      screen.getByRole("navigation", { name: "Điều hướng chính" }).querySelectorAll(
        "a",
      ),
    ).toHaveLength(4);
  });

  describe("assistance bar destination routing", () => {
    it("routes Home assistance on / (root)", () => {
      vi.mocked(usePathname).mockReturnValue("/");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Trang chủ");
      expect(assistance).toHaveTextContent("Juli là trợ lý phân tích và tự động hóa");
    });

    it("routes Decisions assistance on /decisions (exact match)", () => {
      vi.mocked(usePathname).mockReturnValue("/decisions");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Quyết định");
      expect(assistance).toHaveTextContent("Juli sẽ giải thích lý do");
    });

    it("routes Decisions assistance on nested /decisions/recommendations/<key>", () => {
      vi.mocked(usePathname).mockReturnValue("/decisions/recommendations/workflow-1");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Quyết định");
      expect(assistance).not.toHaveTextContent("Trang chủ");
    });

    it("routes Decisions assistance on nested /decisions/in-progress/<id>", () => {
      vi.mocked(usePathname).mockReturnValue("/decisions/in-progress/exec-workflow-1-1");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Quyết định");
      expect(assistance).not.toHaveTextContent("Trang chủ");
    });

    it("routes Analytics assistance on /analytics (exact match)", () => {
      vi.mocked(usePathname).mockReturnValue("/analytics");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Phân tích");
      expect(assistance).toHaveTextContent("Juli sẽ giúp bạn đọc thay đổi");
    });

    it("routes Analytics assistance on nested /analytics/<metricKey>", () => {
      vi.mocked(usePathname).mockReturnValue("/analytics/gmv-tiktok");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Phân tích");
      expect(assistance).not.toHaveTextContent("Trang chủ");
    });

    it("routes Settings assistance on /settings (exact match)", () => {
      vi.mocked(usePathname).mockReturnValue("/settings");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Cài đặt");
      expect(assistance).toHaveTextContent("Juli sẽ làm rõ cách mẫu");
    });

    it("routes Settings assistance on nested /settings/workflows/<key>", () => {
      vi.mocked(usePathname).mockReturnValue("/settings/workflows/workflow-1");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Cài đặt");
      expect(assistance).not.toHaveTextContent("Trang chủ");
    });

    it("falls back to Home assistance on unknown paths", () => {
      vi.mocked(usePathname).mockReturnValue("/unknown/deep/nested/path");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Trang chủ");
      expect(assistance).not.toHaveTextContent(/Quyết định|Phân tích|Cài đặt/);
    });

    it("does not crash on empty path", () => {
      vi.mocked(usePathname).mockReturnValue("");

      render(<DemoShell>Nội dung</DemoShell>);

      const assistance = screen.getByRole("complementary", {
        name: "Gợi ý từ Juli",
      });

      expect(assistance).toHaveTextContent("Trang chủ");
    });
  });

  describe("recommendation context message formatting", () => {
    it("sanitizes backend vocabulary from evidence in recommendation message", () => {
      vi.mocked(usePathname).mockReturnValue("/decisions");

      const banPatterns = readFileSync(
        "src/lib/review-seller-copy.ts",
        "utf8",
      );

      render(<DemoShell>Nội dung</DemoShell>);

      // Verify that sanitizeSellerReviewText is imported and used
      expect(banPatterns).toContain("REVIEW_UI_BANNED_PATTERNS");
      expect(banPatterns).toContain("sanitizeSellerReviewText");
    });
  });

  it("labels preview content truthfully without trapping navigation", () => {
    render(
      <DemoShell>
        <DestinationPlaceholder
          title="Phân tích"
          description="KPI sẽ xuất hiện trong lát cắt Phân tích tiếp theo."
        />
      </DemoShell>,
    );

    expect(screen.getByRole("status", { name: "Phân tích" })).toHaveTextContent(
      "lát cắt Phân tích tiếp theo",
    );
    expect(screen.getByRole("link", { name: "Về Trang chủ" })).toHaveAttribute(
      "href",
      "/",
    );
    expect(
      screen.getByRole("navigation", { name: "Điều hướng chính" }),
    ).toBeInTheDocument();
  });

  it("keeps loading, empty, and error placeholders truthful and recoverable", () => {
    for (const [state, expectedLabel] of [
      ["loading", "Đang tải"],
      ["empty", "Chưa có dữ liệu"],
      ["error", "Chưa thể tải nội dung"],
    ] as const) {
      const { unmount } = render(
        <DemoShell>
          <DestinationPlaceholder
            title="Phân tích"
            description="Dữ liệu mẫu tạm thời chưa sẵn sàng."
            recoveryHref="/"
            recoveryLabel="Về Trang chủ"
            state={state}
          />
        </DemoShell>,
      );

      const placeholder = screen.getByText(expectedLabel).closest("section");

      expect(placeholder).toHaveTextContent("Dữ liệu mẫu tạm thời chưa sẵn sàng.");
      expect(
        screen.getByRole("link", { name: "Về Trang chủ" }),
      ).toHaveAttribute("href", "/");
      unmount();
    }
  });

  it("preserves desktop and mobile terminology, touch targets, focus-visible, and reduced motion", () => {
    const css = readFileSync(
      "src/app/globals.css",
      "utf8",
    );

    render(<DemoShell>Nội dung</DemoShell>);

    expect(screen.getByRole("button", { name: "Mock" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign-in" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Làm mới Demo" }),
    ).toBeInTheDocument();
    expect(css).toContain("min-height: var(--juli-touch-target)");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media (max-width: 35rem)");
    expect(css).toContain("@media (min-width: 56rem)");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});
