import { readFileSync } from "node:fs";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { usePathname, useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoShell } from "../components/demo-shell";
import {
  DEFAULT_MUTABLE_MOCK_STATE,
  useDemoState,
} from "../components/demo-state";
import { DestinationPlaceholder } from "../components/destination-placeholder";
import { shopInitials, shopSubline } from "../components/app-shell/shop-header";
import { buildGoogleAuthorizeUrl } from "../lib/supabase-auth";

/**
 * The app shell (AC-8.5, ADR-109 decisions 1, 7, 8). Replaces the Phase 2.6
 * shell's header controls, assistance aside and bottom-nav-everywhere: the
 * video's rail + shop header, with Đăng nhập / Làm mới Demo / Cài đặt moved
 * into the shop-avatar menu.
 */

vi.mock("next/navigation", () => ({
  usePathname: vi.fn(),
  useRouter: vi.fn(),
}));

// Mock the seam directly rather than the NEXT_PUBLIC_SUPABASE_* variables
// (#1905). Worded without the env-object property prefix on purpose: the
// issue-397 demo workspace contract greps demo source for that pattern.
const SUPABASE_ORIGIN_AUTHORIZE_URL =
  "https://placeholder-project-ref.supabase.co/auth/v1/authorize?provider=google&redirect_to=http%3A%2F%2Flocalhost%2Fauth%2Fcallback&apikey=anon-key-for-tests";

vi.mock("../lib/supabase-auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/supabase-auth")>()),
  buildGoogleAuthorizeUrl: vi.fn(),
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY:
    "Đăng nhập với Google chưa sẵn sàng trong môi trường này.",
}));

const mockedBuildGoogleAuthorizeUrl = vi.mocked(buildGoogleAuthorizeUrl);

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

function mockRouter() {
  vi.mocked(useRouter).mockReturnValue({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace,
  });
}

async function openShopMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: /^Menu shop/ }));
}

function signIn(shopName = "Shop Thật") {
  window.sessionStorage.setItem(
    "juli_demo_auth_session",
    JSON.stringify({ accessToken: "token-1", tokenType: "bearer" }),
  );
  window.sessionStorage.setItem(
    "juli_demo_active_shop",
    JSON.stringify({ id: "shop-1", name: shopName }),
  );
}

beforeEach(() => {
  vi.mocked(usePathname).mockReturnValue("/analytics");
  mockRouter();
  localStorage.clear();
  window.sessionStorage.clear();
  push.mockClear();
  replace.mockClear();
  mockedBuildGoogleAuthorizeUrl.mockReturnValue(SUPABASE_ORIGIN_AUTHORIZE_URL);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("App shell — rail, header, slot", () => {
  it("renders the rail nav, the shop header and the page in the main slot", async () => {
    render(<DemoShell>Nội dung trang</DemoShell>);

    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
    expect(screen.getByTestId("shop-header")).toBeInTheDocument();
    expect(screen.getByRole("main")).toHaveTextContent("Nội dung trang");
  });

  it("anonymous: names the sample shop, flags it as Bản minh họa, and shows its update time — not 'Juli đang chạy'", async () => {
    render(<DemoShell>Nội dung</DemoShell>);
    const header = screen.getByTestId("shop-header");

    await waitFor(() => expect(header).toHaveTextContent("Cửa hàng Mẫu Hoa Mai"));
    expect(header).toHaveTextContent("Bản minh họa");
    expect(header).toHaveTextContent("TikTok Shop");
    expect(header).toHaveTextContent("Dữ liệu mẫu · cập nhật 01:15");
    expect(header).not.toHaveTextContent("Juli đang chạy");
    expect(within(header).getByRole("button", { name: /^Menu shop/ })).toHaveTextContent("CH");
  });

  it("signed in: 'Juli đang chạy · cập nhật HH:MM' comes from the report's built_at", async () => {
    signIn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          as_of: "2026-10-07",
          built_at: "2026-10-08T02:00:00+07:00",
          ranking: "60d",
          report: { shop_name: "Shop Thật", channels: [], windows: {} },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );

    render(<DemoShell>Nội dung</DemoShell>);
    const header = screen.getByTestId("shop-header");

    await waitFor(() => expect(header).toHaveTextContent("Juli đang chạy · cập nhật 02:00"));
    expect(header).toHaveTextContent("Shop Thật");
    expect(header).not.toHaveTextContent("Bản minh họa");
  });

  it("signed in without a report: omits the update time rather than inventing one", async () => {
    signIn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 404 }));

    render(<DemoShell>Nội dung</DemoShell>);
    const header = screen.getByTestId("shop-header");

    await waitFor(() => expect(header).toHaveTextContent("Shop Thật"));
    expect(header).not.toHaveTextContent("cập nhật");
  });

  it("has no five-stage stepper in the global header (ADR-109 decision 8)", async () => {
    render(<DemoShell>Nội dung</DemoShell>);
    const header = screen.getByTestId("shop-header");
    await waitFor(() => expect(header).toHaveTextContent("Cửa hàng Mẫu Hoa Mai"));

    for (const stage of ["Đề xuất", "Duyệt", "Thực thi", "Đo lường"]) {
      expect(header).not.toHaveTextContent(stage);
    }
  });

  it("contains no developer vocabulary — the literal string 'Mock' never appears", () => {
    const { container } = render(<DemoShell>Nội dung</DemoShell>);
    expect(container.textContent).not.toContain("Mock");
  });

  it("initials and subline helpers", () => {
    expect(shopInitials("Mây Lam Skin")).toBe("ML");
    expect(shopInitials("đồ gốm")).toBe("ĐG");
    expect(shopInitials("")).toBe("J");
    expect(shopSubline({})).toBe("TikTok Shop");
    expect(shopSubline({ industry: "Mỹ phẩm", skuCount: 1200 })).toBe("TikTok Shop · Mỹ phẩm · 1.200 SKU");
  });
});

describe("Shop-avatar menu", () => {
  it("is closed until the avatar is pressed, and Escape closes it", async () => {
    const user = userEvent.setup();
    render(<DemoShell>Nội dung</DemoShell>);

    const avatar = await screen.findByRole("button", { name: /^Menu shop/ });
    expect(avatar).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "Cài đặt" })).toBeNull();

    await user.click(avatar);
    expect(avatar).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("link", { name: "Cài đặt" })).toHaveAttribute("href", "/settings");

    await user.keyboard("{Escape}");
    expect(avatar).toHaveAttribute("aria-expanded", "false");
    expect(avatar).toHaveFocus();
  });

  it("anonymous: holds Cài đặt, a real Đăng nhập link to Supabase Auth (#1907) and Làm mới Demo", async () => {
    const user = userEvent.setup();
    window.sessionStorage.setItem("juli_demo_entry_mode", "replay");
    render(<DemoShell>Nội dung</DemoShell>);
    await openShopMenu(user);

    const signInLink = await screen.findByRole("link", { name: "Đăng nhập với Google" });
    expect(new URL(signInLink.getAttribute("href") as string).origin).toBe(
      "https://placeholder-project-ref.supabase.co",
    );
    expect(signInLink).not.toHaveAttribute("aria-disabled");
    expect(screen.getByRole("button", { name: "Làm mới Demo" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Đăng xuất" })).toBeNull();
  });

  it("anonymous without Supabase env: the same honest disabled Đăng nhập as the landing door", async () => {
    const user = userEvent.setup();
    mockedBuildGoogleAuthorizeUrl.mockReturnValue(null);
    render(<DemoShell>Nội dung</DemoShell>);
    await openShopMenu(user);

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Đăng nhập với Google" })).toHaveAttribute("aria-disabled", "true");
    });
    expect(
      screen.getByTitle("Đăng nhập với Google chưa sẵn sàng trong môi trường này."),
    ).toBeInTheDocument();
  });

  it("signed in: holds Cài đặt, Đổi shop and Đăng xuất; sign-out clears the session and shop", async () => {
    const user = userEvent.setup();
    signIn();
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 404 }));
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({
      ...window.location,
      assign,
      origin: "http://localhost",
    });

    render(<DemoShell>Nội dung</DemoShell>);
    await waitFor(() => expect(screen.getByTestId("shop-header")).toHaveTextContent("Shop Thật"));
    await openShopMenu(user);

    expect(screen.getByRole("link", { name: "Cài đặt" })).toHaveAttribute("href", "/settings");
    expect(screen.getByRole("link", { name: "Đổi shop" })).toHaveAttribute("href", "/auth/connect-shop");
    expect(screen.queryByRole("button", { name: "Làm mới Demo" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(window.sessionStorage.getItem("juli_demo_auth_session")).toBeNull();
    expect(window.sessionStorage.getItem("juli_demo_active_shop")).toBeNull();
    expect(assign).toHaveBeenCalledWith("/?entry=door");
  });

  it("Làm mới Demo resets every mutable mock-state category, opens Decisions and announces it", async () => {
    const user = userEvent.setup();
    render(
      <DemoShell>
        <MutableStateProbe />
      </DemoShell>,
    );

    await user.click(screen.getByRole("button", { name: "Thay đổi dữ liệu mẫu" }));
    expect(screen.getByTestId("mutable-state")).toHaveTextContent("inventory-turnover");

    await openShopMenu(user);
    await user.click(screen.getByRole("button", { name: "Làm mới Demo" }));

    expect(JSON.parse(screen.getByTestId("mutable-state").textContent ?? "{}")).toEqual(
      DEFAULT_MUTABLE_MOCK_STATE,
    );
    expect(replace).toHaveBeenCalledWith("/decisions");
    expect(screen.getByRole("status", { name: "Phản hồi Demo" })).toHaveTextContent(
      "Demo đã trở về trạng thái ban đầu",
    );
  });
});

describe("Placeholders inside the shell", () => {
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
    expect(screen.getByRole("link", { name: "Về Trang chủ" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
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
      expect(screen.getByRole("link", { name: "Về Trang chủ" })).toHaveAttribute("href", "/");
      unmount();
    }
  });

  it("the stylesheet keeps the rail ↔ bottom-bar switch at 768px, touch targets, focus-visible and reduced motion", () => {
    const css = readFileSync("src/app/globals.css", "utf8");

    expect(css).toContain("@media (min-width: 768px)");
    expect(css).toContain("min-height: var(--juli-touch-target)");
    expect(css).toContain(":focus-visible");
    expect(css).toContain("@media (max-width: 35rem)");
    expect(css).toContain("@media (min-width: 56rem)");
    expect(css).toContain("@media (prefers-reduced-motion: reduce)");
  });
});

describe("Run route framing (#1910) — the run owns the region right of the rail", () => {
  const RUN_PATH = "/decisions/in-progress/00000000-0000-0000-0000-00000000b453";

  it("sheds the shop header and the feedback region on the run route", () => {
    vi.mocked(usePathname).mockReturnValue(RUN_PATH);
    const { container } = render(<DemoShell>Nội dung luồng</DemoShell>);

    expect(container.querySelector(".shop-header")).toBeNull();
    expect(screen.queryByRole("status", { name: "Phản hồi Demo" })).toBeNull();
    expect(screen.getByText("Nội dung luồng")).toBeInTheDocument();
  });

  it("KEEPS the nav rail on the run route — owner amendment 2026-09-14; removing it would strand the seller", () => {
    vi.mocked(usePathname).mockReturnValue(RUN_PATH);
    render(<DemoShell>Nội dung luồng</DemoShell>);

    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
  });

  it("keeps the full shell on a legacy mock execution detail and on every destination", () => {
    for (const pathname of [
      "/decisions/in-progress/exec-optimize-1",
      "/",
      "/decisions",
      "/analytics",
      "/settings",
    ]) {
      vi.mocked(usePathname).mockReturnValue(pathname);
      const { container, unmount } = render(<DemoShell>Nội dung</DemoShell>);

      expect(container.querySelector(".shop-header"), `header missing on ${pathname}`).not.toBeNull();
      expect(container.querySelector(".app-nav"), `nav missing on ${pathname}`).not.toBeNull();
      unmount();
    }
  });
});
