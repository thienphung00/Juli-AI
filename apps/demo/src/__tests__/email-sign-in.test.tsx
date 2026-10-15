import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthScreen } from "../components/auth/auth-screen";
import { maskEmail } from "../lib/auth-screen-copy";
import { AUTH_SESSION_STORAGE_KEY, readAuthSession } from "../lib/supabase-auth";
import { reportTikTokRegistration } from "../lib/tiktok-registration";

vi.mock("../lib/tiktok-registration", () => ({
  reportTikTokRegistration: vi.fn(async () => undefined),
}));

/**
 * Email sign-in (AC-9.1) on the P34-F auth screen: email → "Gửi mã đăng nhập"
 * → the OTP view (6 boxes, masked address) → signed in. Behaviour pinned
 * before P34 is kept: 60 s resend cooldown, Vietnamese errors (format,
 * wrong/expired code, rate limit, network), the code never echoed, and the
 * session stored exactly as the Google callback stores it. Supabase is
 * stubbed at `fetch`.
 */

const ORIGINAL_ENV = { ...process.env };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

const SESSION_BODY = {
  access_token: "eyJ.email.sig",
  token_type: "bearer",
  expires_in: 3600,
  refresh_token: "r-email-1",
};

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://placeholder-project-ref.supabase.co";
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key-for-tests";
  window.sessionStorage.clear();
  window.localStorage.clear();
  window.history.replaceState(null, "", "/");
  vi.mocked(reportTikTokRegistration).mockClear();
  fetchSpy = vi.spyOn(globalThis, "fetch");
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
  fetchSpy.mockRestore();
  vi.useRealTimers();
});

function routeSupabase(handlers: { otp?: () => Response; verify?: () => Response }) {
  fetchSpy.mockImplementation(async (input: RequestInfo | URL) => {
    const path = new URL(String(input)).pathname;
    if (path === "/auth/v1/otp") return (handlers.otp ?? (() => json(200, {})))();
    if (path === "/auth/v1/verify") return (handlers.verify ?? (() => json(200, SESSION_BODY)))();
    throw new Error(`unexpected ${path}`);
  });
}

function renderScreen(onSignedIn: ReturnType<typeof vi.fn> = vi.fn(), trial = false) {
  return render(
    <AuthScreen onEnterSample={vi.fn()} onSignedIn={onSignedIn} onTrialChange={vi.fn()} trial={trial} />,
  );
}

async function sendCodeTo(user: ReturnType<typeof userEvent.setup>, email: string, label = "Gửi mã đăng nhập") {
  const send = await screen.findByRole("button", { name: label });
  await waitFor(() => expect(send).toBeEnabled());
  await user.type(screen.getByLabelText("Email"), email);
  await user.click(send);
}

async function sendCodeWithFakeTimers(email = "ban@shopcuaban.vn") {
  await act(async () => {
    vi.advanceTimersByTime(10);
  });
  fireEvent.change(screen.getByLabelText("Email"), { target: { value: email } });
  fireEvent.click(screen.getByRole("button", { name: "Gửi mã đăng nhập" }));
  await screen.findByRole("heading", { name: "Nhập mã 6 chữ số" });
}

function boxes() {
  return [1, 2, 3, 4, 5, 6].map((n) => screen.getByLabelText(`Số ${n}`) as HTMLInputElement);
}

function pasteInto(target: HTMLElement, text: string) {
  fireEvent.paste(target, { clipboardData: { getData: () => text } });
}

describe("email OTP on the auth screen", () => {
  it("shows a Vietnamese format error with an icon (role=alert) and sends nothing for a malformed email", async () => {
    const user = userEvent.setup();
    renderScreen();

    await sendCodeTo(user, "chushop");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Email chưa đúng định dạng");
    expect(alert.querySelector("svg")).not.toBeNull();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("the send button shows a loading state while the request is in flight", async () => {
    const user = userEvent.setup();
    let release: (response: Response) => void = () => undefined;
    fetchSpy.mockImplementation(() => new Promise<Response>((resolve) => (release = resolve)));
    renderScreen();

    await sendCodeTo(user, "ban@shopcuaban.vn");

    const pending = await screen.findByRole("button", { name: "Đang gửi mã…" });
    expect(pending).toBeDisabled();
    expect(pending).toHaveAttribute("aria-busy", "true");
    await act(async () => release(json(200, {})));
    expect(await screen.findByRole("heading", { level: 1, name: "Nhập mã 6 chữ số" })).toBeInTheDocument();
  });

  it("sends the code, then the OTP view: masked address, 6 boxes (one-time-code, numeric), resend locked 60 s", async () => {
    const user = userEvent.setup();
    routeSupabase({});
    renderScreen();

    await sendCodeTo(user, "chushop@vi-du.vn");

    expect(await screen.findByRole("heading", { level: 1, name: "Nhập mã 6 chữ số" })).toBeInTheDocument();
    expect(screen.getByText("ch***@vi-du.vn")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("chushop@vi-du.vn");
    const all = boxes();
    expect(all[0]).toHaveAttribute("autocomplete", "one-time-code");
    for (const box of all) expect(box).toHaveAttribute("inputmode", "numeric");
    expect(all[0]).toHaveFocus();
    expect(screen.getByRole("group", { name: "Mã đăng nhập" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gửi lại mã sau 60 giây" })).toBeDisabled();
    // Google is gone from this view: "Xác nhận" is its one filled button.
    expect(screen.queryByRole("link", { name: "Tiếp tục với Google" })).toBeNull();
    expect(document.querySelectorAll(".auth-btn--ink")).toHaveLength(1);
    const [url] = fetchSpy.mock.calls[0] as [string];
    expect(new URL(url).searchParams.get("redirect_to")).toBe(`${window.location.origin}/auth/callback`);
  });

  it("pasting the code into any box fills all six and submits it", async () => {
    const user = userEvent.setup();
    const onSignedIn = vi.fn();
    routeSupabase({});
    renderScreen(onSignedIn);
    await sendCodeTo(user, "ban@shopcuaban.vn");
    await screen.findByRole("heading", { name: "Nhập mã 6 chữ số" });

    // Into box 3, with the usual space in the middle: still fills from box 1.
    pasteInto(boxes()[2], "123 456");

    expect(boxes().map((b) => b.value)).toEqual(["1", "2", "3", "4", "5", "6"]);
    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    const verifyCall = (fetchSpy.mock.calls as unknown as [string, RequestInit][]).find(([u]) =>
      u.includes("/auth/v1/verify"),
    ) as [string, RequestInit];
    expect(JSON.parse(verifyCall[1].body as string)).toEqual({ type: "email", email: "ban@shopcuaban.vn", token: "123456" });
  });

  it("typing digit by digit moves focus, Backspace steps back, the sixth digit auto-submits", async () => {
    const user = userEvent.setup();
    const onSignedIn = vi.fn();
    routeSupabase({});
    renderScreen(onSignedIn);
    await sendCodeTo(user, "ban@shopcuaban.vn");
    await screen.findByRole("heading", { name: "Nhập mã 6 chữ số" });

    await user.keyboard("12");
    expect(boxes()[2]).toHaveFocus();
    await user.keyboard("{Backspace}");
    expect(boxes()[1]).toHaveFocus();
    expect(boxes()[1]).toHaveValue("");
    await user.keyboard("23456");

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
  });

  it("re-enables Gửi lại mã when the cooldown ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routeSupabase({});
    renderScreen();
    await sendCodeWithFakeTimers();

    for (let i = 0; i < 61; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }

    const resend = screen.getByRole("button", { name: "Gửi lại mã" });
    expect(resend).toBeEnabled();
    fireEvent.click(resend);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
  });

  it("a wrong or expired code: alert with icon, boxes cleared, 'Gửi mã mới' once resend is allowed, code never echoed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routeSupabase({
      verify: () => json(403, { error_code: "otp_expired", msg: "Token has expired or is invalid" }),
    });
    renderScreen();
    await sendCodeWithFakeTimers();

    pasteInto(boxes()[0], "987654");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Mã không đúng hoặc đã hết hạn");
    expect(alert.querySelector("svg")).not.toBeNull();
    expect(boxes().map((b) => b.value).join("")).toBe("");
    expect(document.body.textContent).not.toContain("987654");
    expect(readAuthSession()).toBeNull();
    expect(screen.queryByRole("button", { name: "Gửi mã mới" })).toBeNull();
    for (let i = 0; i < 61; i += 1) {
      await act(async () => {
        vi.advanceTimersByTime(1000);
      });
    }
    fireEvent.click(screen.getByRole("button", { name: "Gửi mã mới" }));
    await waitFor(() =>
      expect((fetchSpy.mock.calls as unknown as [string][]).filter(([u]) => u.includes("/auth/v1/otp"))).toHaveLength(2),
    );
  });

  it("a rate-limited send says so in Vietnamese and locks the send button for the wait GoTrue names", async () => {
    const user = userEvent.setup();
    routeSupabase({
      otp: () =>
        json(429, {
          error_code: "over_email_send_rate_limit",
          msg: "For security purposes, you can only request this after 37 seconds.",
        }),
    });
    renderScreen();

    await sendCodeTo(user, "ban@shopcuaban.vn");

    expect(await screen.findByRole("alert")).toHaveTextContent("Bạn đã yêu cầu quá nhiều lần");
    expect(screen.getByRole("button", { name: "Gửi mã sau 37 giây" })).toBeDisabled();
  });

  it("a network failure says so", async () => {
    const user = userEvent.setup();
    fetchSpy.mockRejectedValue(new TypeError("Failed to fetch"));
    renderScreen();

    await sendCodeTo(user, "ban@shopcuaban.vn");

    expect(await screen.findByRole("alert")).toHaveTextContent("Không kết nối được tới máy chủ đăng nhập");
  });

  it("a right code stores the session in the Google path's shape and key, then hands over", async () => {
    const user = userEvent.setup();
    const onSignedIn = vi.fn();
    routeSupabase({});
    renderScreen(onSignedIn);
    await sendCodeTo(user, "ban@shopcuaban.vn");
    await screen.findByRole("heading", { name: "Nhập mã 6 chữ số" });
    pasteInto(boxes()[0], "123456");

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    const session = { accessToken: "eyJ.email.sig", refreshToken: "r-email-1", expiresIn: 3600, tokenType: "bearer" };
    expect(onSignedIn).toHaveBeenCalledWith(session);
    expect(JSON.parse(window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY) as string)).toEqual(session);
  });

  it("by default reports the sign-up and full-loads the connect-shop screen", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign });
    routeSupabase({});
    render(<AuthScreen onEnterSample={vi.fn()} onTrialChange={vi.fn()} trial={false} />);
    await sendCodeTo(user, "ban@shopcuaban.vn");
    await screen.findByRole("heading", { name: "Nhập mã 6 chữ số" });
    pasteInto(boxes()[0], "123456");

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/auth/connect-shop"));
    expect(reportTikTokRegistration).toHaveBeenCalledWith("eyJ.email.sig");
    vi.restoreAllMocks();
  });

  it("← Đổi email goes back to the email step with the address kept and focused", async () => {
    const user = userEvent.setup();
    routeSupabase({});
    renderScreen();
    await sendCodeTo(user, "ban@shopcuaban.vn");

    await user.click(await screen.findByRole("button", { name: "← Đổi email" }));

    expect(screen.getByLabelText("Email")).toHaveValue("ban@shopcuaban.vn");
    expect(screen.getByLabelText("Email")).toHaveFocus();
  });

  it("trial variant: 'Gửi mã đăng ký', then Mã đăng ký and 'Xác nhận và tạo tài khoản'", async () => {
    const user = userEvent.setup();
    routeSupabase({});
    renderScreen(vi.fn(), true);
    await sendCodeTo(user, "ban@shopcuaban.vn", "Gửi mã đăng ký");

    expect(await screen.findByText("Dùng thử miễn phí 3 tháng")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Mã đăng ký" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Xác nhận và tạo tài khoản" })).toBeInTheDocument();
  });
});

describe("maskEmail", () => {
  it("keeps two characters of the local part, one when it is short", () => {
    expect(maskEmail("chushop@vi-du.vn")).toBe("ch***@vi-du.vn");
    expect(maskEmail("ab@x.vn")).toBe("a***@x.vn");
    expect(maskEmail("not-an-email")).toBe("not-an-email");
  });
});
