import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoLanding } from "../components/demo-landing";
import * as authCopy from "../lib/auth-screen-copy";
import { ENTRY_MODE_STORAGE_KEY } from "../lib/entry-mode";
import { buildGoogleAuthorizeUrl } from "../lib/supabase-auth";
import * as trialCopy from "../lib/trial-signup-copy";

/**
 * `/` signed out (P34-F, D44.5; spec `fasttrack/design/p34/Auth.dc.html`):
 * the auth screen, or the sample demo once chosen. Supersedes the two-door
 * landing's tests (#1319, #1905, #1907, AC-9.1, D43): every behaviour they
 * pinned is still pinned here, against the new structure and copy.
 *
 * `buildGoogleAuthorizeUrl` is mocked (the seam), never NEXT_PUBLIC_SUPABASE_*
 * — see the #1905 note this file used to carry: mutating process.env cannot
 * force the unconfigured branch once CI has real secrets.
 */
const SUPABASE_ORIGIN_AUTHORIZE_URL =
  "https://placeholder-project-ref.supabase.co/auth/v1/authorize?provider=google&redirect_to=http%3A%2F%2Flocalhost%2Fauth%2Fcallback&apikey=anon-key-for-tests";

vi.mock("../lib/supabase-auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/supabase-auth")>()),
  buildGoogleAuthorizeUrl: vi.fn(),
  GOOGLE_SIGN_IN_UNAVAILABLE_COPY: "Đăng nhập với Google chưa sẵn sàng trong môi trường này.",
}));

const mockedBuildGoogleAuthorizeUrl = vi.mocked(buildGoogleAuthorizeUrl);

const SAMPLE_ENTRY = "Xem thử với dữ liệu mẫu, không cần tài khoản →";
const MATRIX = "Ma trận 5 luồng truy cập";
const PARTNER_TOP = "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác";

beforeEach(() => {
  window.sessionStorage.clear();
  // The entry read uses window.location.search (not useSearchParams — that
  // would force a Suspense boundary around the prerendered landing), so tests
  // drive the real URL. Reset it to a bare `/` between tests.
  window.history.replaceState(null, "", "/");
  mockedBuildGoogleAuthorizeUrl.mockReturnValue(SUPABASE_ORIGIN_AUTHORIZE_URL);
});

afterEach(() => {
  vi.clearAllMocks();
});

async function googleLink(name: RegExp | string = "Tiếp tục với Google") {
  return waitFor(() => {
    const link = screen.getByRole("link", { name });
    expect(link).toHaveAttribute("href");
    return link;
  });
}

describe("auth screen — hierarchy (D44.5)", () => {
  it("has one h1, Google first, then the 'hoặc dùng email' rule, the email field and its outline button", async () => {
    render(<DemoLanding />);
    const google = await googleLink();

    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByText("Chưa có tài khoản? Juli tự tạo cho bạn ở bước này.")).toBeInTheDocument();
    expect(screen.getByText("hoặc dùng email")).toBeInTheDocument();
    const email = screen.getByLabelText("Email");
    expect(email).toHaveAttribute("type", "email");
    expect(email).toHaveAttribute("autocomplete", "email");
    const send = screen.getByRole("button", { name: "Gửi mã đăng nhập" });
    // Document order: Google → email field → send.
    expect(google.compareDocumentPosition(email) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(email.compareDocumentPosition(send) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("D47.6: the partner entry sits at the top of the column, before the h1, secondary to Google, to /auth/email#doi-tac", async () => {
    render(<DemoLanding />);
    const google = await googleLink();

    const top = screen.getByRole("link", { name: PARTNER_TOP });
    const heading = screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" });
    // No partner form on `/` → a real link to the page that carries it.
    expect(top).toHaveAttribute("href", "/auth/email#doi-tac");
    // Document order: top entry → h1 → Google; inside the sign-in column.
    expect(top.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(heading.compareDocumentPosition(google) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(within(screen.getByRole("main")).getByRole("link", { name: PARTNER_TOP })).toBe(top);
    // Secondary: not a filled button; the footer link stays.
    expect(top).not.toHaveClass("auth-btn--ink");
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Tài khoản đối tác" })).toBeInTheDocument();
    // Focus order is pinned in "keyboard order" below.
  });

  it("Tiếp tục với Google is the ONLY filled (ink) button on the screen", async () => {
    const { container } = render(<DemoLanding />);
    const google = await googleLink();

    const filled = container.querySelectorAll(".auth-btn--ink");
    expect(filled).toHaveLength(1);
    expect(filled[0]).toBe(google);
    expect(screen.getByRole("button", { name: "Gửi mã đăng nhập" })).toHaveClass("auth-btn--outline");
  });

  it("the Google button is a real link to the Supabase authorize endpoint, not a disabled stub", async () => {
    render(<DemoLanding />);
    const link = await googleLink();

    expect(link).toHaveAttribute("href", expect.stringContaining("placeholder-project-ref.supabase.co/auth/v1/authorize"));
    expect(link).toHaveAttribute("href", expect.stringContaining("provider=google"));
    expect(link.getAttribute("aria-disabled")).toBeNull();
  });

  it("links the terms and the privacy policy in the consent line", () => {
    render(<DemoLanding />);

    const note = screen.getByTestId("legal-consent-note");
    expect(note).toHaveTextContent("Bằng việc tiếp tục, bạn đồng ý với Điều khoản dịch vụ và Chính sách bảo mật của Juli.");
    expect(within(note).getByRole("link", { name: "Chính sách bảo mật" })).toHaveAttribute("href", "https://app-juli.com/privacy");
    expect(within(note).getByRole("link", { name: "Điều khoản dịch vụ" })).toHaveAttribute("href", "https://app-juli.com/terms");
  });

  it("the footer: Tài khoản đối tác (to /auth/email#doi-tac), Điều khoản, Chính sách bảo mật, ©", () => {
    render(<DemoLanding />);

    const footer = screen.getByRole("contentinfo");
    expect(within(footer).getByRole("link", { name: "Tài khoản đối tác" })).toHaveAttribute("href", "/auth/email#doi-tac");
    expect(within(footer).getByRole("link", { name: "Điều khoản" })).toHaveAttribute("href", "https://app-juli.com/terms");
    expect(within(footer).getByRole("link", { name: "Chính sách bảo mật" })).toHaveAttribute("href", "https://app-juli.com/privacy");
    expect(footer).toHaveTextContent("© 2026 Công ty TNHH Công Nghệ Juli AI");
  });

  it("the desktop panel: product shot captioned Ví dụ thẻ đề xuất and three proof lines", () => {
    render(<DemoLanding />);

    const panel = screen.getByRole("complementary", { name: "Juli làm gì" });
    expect(within(panel).getByRole("img", { name: "Thẻ đề xuất của Juli: Mặt nạ đất sét 100g, CTOR 5,4 % lên 5,9 %" })).toBeInTheDocument();
    expect(within(panel).getByText("Ví dụ thẻ đề xuất")).toBeInTheDocument();
    expect(within(panel).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Kết nối chính thức qua TikTok Shop Open API",
      "Chỉ thực hiện khi bạn duyệt",
      "Miễn phí 3 tháng",
    ]);
  });

  it("never issues a fetch merely by rendering", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<DemoLanding />);
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("keyboard order: logo, the partner entry (D47.6), Google, email", async () => {
    const user = userEvent.setup();
    render(<DemoLanding />);
    await googleLink();

    await user.tab();
    expect(screen.getByRole("link", { name: /Juli AI/ })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: PARTNER_TOP })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("link", { name: "Tiếp tục với Google" })).toHaveFocus();
    await user.tab();
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });
});

describe("auth screen — the sample demo entry", () => {
  it("is a text-link button under the column; clicking it reveals the sample Home with no navigation and no fetch", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    render(<DemoLanding />);

    const entry = screen.getByRole("button", { name: SAMPLE_ENTRY });
    expect(entry).toHaveClass("auth-link");
    await user.click(entry);

    expect(screen.getByRole("region", { name: MATRIX })).toBeInTheDocument();
    expect(screen.getByTestId("mock-data-notice")).toBeInTheDocument();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem(ENTRY_MODE_STORAGE_KEY)).toBe("replay");
    fetchSpy.mockRestore();
  });

  it("skips straight to the sample Home on a later render within the same session", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");
    render(<DemoLanding />);

    expect(await screen.findByRole("region", { name: MATRIX })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: SAMPLE_ENTRY })).not.toBeInTheDocument();
  });

  // Issue #1907: `/?entry=door` is the explicit escape from the stored choice.
  it("renders the auth screen at /?entry=door even with the sample stored", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");
    window.history.replaceState(null, "", "/?entry=door");
    render(<DemoLanding />);

    await googleLink();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.getByRole("button", { name: SAMPLE_ENTRY })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: MATRIX })).not.toBeInTheDocument();
  });
});

describe("auth screen — Supabase not configured (#1905)", () => {
  it("renders an honest, non-broken Google button and visible copy explaining it", async () => {
    mockedBuildGoogleAuthorizeUrl.mockReturnValue(null);
    render(<DemoLanding />);

    expect(await screen.findByText("Đăng nhập với Google chưa sẵn sàng trong môi trường này.")).toBeVisible();
    expect(screen.getByRole("link", { name: /Tiếp tục với Google/ })).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByText("Đăng nhập bằng email chưa sẵn sàng trong môi trường này.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Gửi mã đăng nhập" })).toBeDisabled();
  });

  it("never shows the unavailable copy once configured", async () => {
    render(<DemoLanding />);
    await googleLink();
    expect(screen.queryByText("Đăng nhập với Google chưa sẵn sàng trong môi trường này.")).not.toBeInTheDocument();
  });
});

describe("auth screen — trial variant (/?dang-ky=dung-thu, D43 additions)", () => {
  it("same layout, copy only: heading, no-card line, Đăng ký bằng Google, Gửi mã đăng ký, Đã có tài khoản? Đăng nhập", async () => {
    window.history.replaceState(null, "", "/?dang-ky=dung-thu");
    const { container } = render(<DemoLanding />);

    expect(await screen.findByRole("heading", { level: 1, name: "Dùng thử Juli miễn phí 3 tháng" })).toBeInTheDocument();
    expect(screen.getByText("Không cần thẻ thanh toán. Sau 3 tháng, từ 500.000đ/tháng.")).toBeInTheDocument();
    const google = await googleLink("Đăng ký bằng Google");
    expect(google).toHaveAttribute("href", expect.stringContaining("provider=google"));
    expect(screen.getByRole("button", { name: "Gửi mã đăng ký" })).toBeInTheDocument();
    expect(screen.getByText("Đã có tài khoản?")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Đăng nhập" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Đăng nhập vào Juli" })).toBeNull();
    // Same layout: one filled button, the sample entry, the partner link.
    expect(container.querySelectorAll(".auth-btn--ink")).toHaveLength(1);
    expect(screen.getByRole("button", { name: SAMPLE_ENTRY })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Tài khoản đối tác" })).toHaveAttribute("href", "/auth/email#doi-tac");
    // D47.6: the top partner entry too, still above the heading.
    const top = screen.getByRole("link", { name: PARTNER_TOP });
    expect(top).toHaveAttribute("href", "/auth/email#doi-tac");
    expect(
      top.compareDocumentPosition(screen.getByRole("heading", { level: 1 })) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("shows the auth screen even when the sample is stored, like ?entry=door", async () => {
    window.sessionStorage.setItem(ENTRY_MODE_STORAGE_KEY, "replay");
    window.history.replaceState(null, "", "/?dang-ky=dung-thu");
    render(<DemoLanding />);

    expect(await screen.findByRole("heading", { level: 1, name: "Dùng thử Juli miễn phí 3 tháng" })).toBeInTheDocument();
  });

  it("Mới dùng Juli? Dùng thử miễn phí 3 tháng ↔ Đã có tài khoản? Đăng nhập swaps the copy in place and the URL", async () => {
    const user = userEvent.setup();
    render(<DemoLanding />);
    await googleLink();

    expect(screen.getByText("Mới dùng Juli?")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Dùng thử miễn phí 3 tháng" }));
    expect(screen.getByRole("heading", { level: 1, name: "Dùng thử Juli miễn phí 3 tháng" })).toBeInTheDocument();
    expect(window.location.search).toBe("?dang-ky=dung-thu");

    await user.click(screen.getByRole("link", { name: "Đăng nhập" }));
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })).toBeInTheDocument();
    expect(window.location.search).toBe("?entry=door");
  });

  it("keeps the plain sign-in without the query", () => {
    render(<DemoLanding />);
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })).toBeInTheDocument();
    expect(screen.queryByText(/Dùng thử Juli miễn phí/)).toBeNull();
  });
});

describe("auth screen copy is in dictionary.md", () => {
  const dictionary = readFileSync(join(__dirname, "..", "..", "..", "..", "dictionary.md"), "utf8");

  it("every string in auth-screen-copy.ts and trial-signup-copy.ts", () => {
    const strings = [...Object.values(authCopy), ...Object.values(trialCopy)].flatMap((value) =>
      typeof value === "string" ? [value] : Array.isArray(value) ? (value as string[]) : [],
    );
    const skip = new Set(["https://app-juli.com", authCopy.AUTH_PARTNER_HREF, "dang-ky", "dung-thu"]);
    expect(strings.length).toBeGreaterThan(30);
    for (const text of strings) {
      if (skip.has(text)) continue;
      expect(dictionary, text).toContain(text);
    }
  });

  it("the templated strings too", () => {
    expect(dictionary).toContain("Gửi mã sau {n} giây");
    expect(dictionary).toContain("Gửi lại mã sau {n} giây");
  });
});
