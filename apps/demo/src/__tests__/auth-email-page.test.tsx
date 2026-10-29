import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import EmailSignInPage from "../app/auth/email/page";
import { ENTRY_MODE_STORAGE_KEY } from "../lib/entry-mode";
import { buildGoogleAuthorizeUrl } from "../lib/supabase-auth";

/**
 * `/auth/email` (P34-F, D44.5): the same auth screen, email focused, and the
 * only page carrying the partner password form — a view of its own, opened
 * from the pill above the heading (D47.6) or the footer "Tài khoản đối tác",
 * replacing the column, with
 * "← Quay lại". The shell's reviewer denial (`?doi-tac=<reason>#doi-tac`)
 * lands straight in that view with the reason shown.
 */

vi.mock("../lib/supabase-auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/supabase-auth")>()),
  buildGoogleAuthorizeUrl: vi.fn(),
}));

beforeEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/auth/email");
  vi.mocked(buildGoogleAuthorizeUrl).mockReturnValue("https://ref.supabase.co/auth/v1/authorize?provider=google");
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("/auth/email — the auth screen with the partner view", () => {
  it("opens on the seller column with the email field focused", async () => {
    render(<EmailSignInPage />);
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Email")).toHaveFocus());
  });

  it("Tài khoản đối tác swaps the column for the partner form; ← Quay lại swaps it back", async () => {
    const user = userEvent.setup();
    const { container } = render(<EmailSignInPage />);

    await user.click(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Tài khoản đối tác" }));

    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập bằng mật khẩu" })).toHaveFocus();
    expect(screen.getByRole("form", { name: "Đăng nhập bằng mật khẩu" })).toBeInTheDocument();
    expect(screen.getByLabelText("Mật khẩu")).toHaveAttribute("autocomplete", "current-password");
    // The seller column is gone, not stacked under it.
    expect(screen.queryByRole("link", { name: "Tiếp tục với Google" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Đăng nhập bằng email" })).toBeNull();
    // The dark submit is the view's one filled button.
    const filled = container.querySelectorAll(".auth-btn--ink");
    expect(filled).toHaveLength(1);
    expect(filled[0]).toHaveTextContent("Đăng nhập");
    expect(window.location.hash).toBe("#doi-tac");

    await user.click(screen.getByRole("button", { name: "← Quay lại đăng nhập cho người bán" }));

    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Mật khẩu")).toBeNull();
    expect(window.location.hash).toBe("");
  });

  it("the sample entry shows on the plain door, and is gone once the partner door has been opened", async () => {
    const user = userEvent.setup();
    render(<EmailSignInPage />);
    expect(screen.getByRole("button", { name: /Xem thử với dữ liệu mẫu/ })).toBeInTheDocument();

    await user.click(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Tài khoản đối tác" }));
    expect(screen.queryByRole("button", { name: /dữ liệu mẫu/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "← Quay lại đăng nhập cho người bán" }));
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /dữ liệu mẫu/ })).toBeNull();
  });

  it("D47.6: the top entry (above the h1) opens the same in-page partner view as the footer link", async () => {
    const user = userEvent.setup();
    render(<EmailSignInPage />);

    const top = screen.getByRole("link", { name: "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác" });
    const heading = screen.getByRole("heading", { level: 1, name: "Đăng nhập vào Juli" });
    expect(top.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    // The partner form is on this page → an in-page link, like the footer's.
    expect(top).toHaveAttribute("href", "#doi-tac");
    expect(within(screen.getByRole("contentinfo")).getByRole("link", { name: "Tài khoản đối tác" })).toHaveAttribute(
      "href",
      "#doi-tac",
    );

    await user.click(top);

    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập bằng mật khẩu" })).toHaveFocus();
    expect(screen.getByLabelText("Mật khẩu")).toBeInTheDocument();
    expect(window.location.hash).toBe("#doi-tac");
    // The partner view does not repeat the entry.
    expect(screen.queryByRole("link", { name: "Đối tác thẩm định? Đăng nhập bằng tài khoản đối tác" })).toBeNull();
  });

  it("#doi-tac opens the partner view directly", async () => {
    window.history.replaceState(null, "", "/auth/email#doi-tac");
    render(<EmailSignInPage />);
    expect(await screen.findByRole("heading", { level: 1, name: "Đăng nhập bằng mật khẩu" })).toBeInTheDocument();
  });

  it("the shell's denial lands in the partner view with the reason as an alert", async () => {
    window.history.replaceState(null, "", "/auth/email?doi-tac=expired#doi-tac");
    render(<EmailSignInPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Tài khoản đối tác này đã hết hạn. Vui lòng liên hệ Juli để gia hạn.");
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập bằng mật khẩu" })).toBeInTheDocument();
  });

  it("the sample entry stores the choice and goes to /", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign });
    render(<EmailSignInPage />);

    await user.click(screen.getByRole("button", { name: "Xem thử với dữ liệu mẫu, không cần tài khoản →" }));

    expect(window.sessionStorage.getItem(ENTRY_MODE_STORAGE_KEY)).toBe("replay");
    expect(assign).toHaveBeenCalledWith("/");
  });
});
