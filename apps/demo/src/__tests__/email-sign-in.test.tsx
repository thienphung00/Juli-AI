import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EmailSignIn } from "../components/email-sign-in";
import { AUTH_SESSION_STORAGE_KEY, readAuthSession } from "../lib/supabase-auth";
import { reportTikTokRegistration } from "../lib/tiktok-registration";

vi.mock("../lib/tiktok-registration", () => ({
  reportTikTokRegistration: vi.fn(async () => undefined),
}));

/**
 * AC-9.1 UI states: email → "Gửi mã" → code → signed in, with the 60 s
 * resend cooldown, Vietnamese errors (format, wrong/expired code, rate
 * limit), and the session stored exactly as the Google callback stores it.
 * Supabase is stubbed at `fetch`.
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

async function sendCodeTo(user: ReturnType<typeof userEvent.setup>, email: string) {
  await user.type(screen.getByLabelText("Email"), email);
  await user.click(screen.getByRole("button", { name: "Gửi mã" }));
}

describe("EmailSignIn", () => {
  it("shows a Vietnamese format error and sends nothing for a malformed email", async () => {
    const user = userEvent.setup();
    render(<EmailSignIn onSignedIn={vi.fn()} />);

    await sendCodeTo(user, "chushop");

    expect(await screen.findByRole("alert")).toHaveTextContent("Email chưa đúng định dạng");
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("sends the code, then asks for it with the address named and resend locked for 60 s", async () => {
    const user = userEvent.setup();
    routeSupabase({});
    render(<EmailSignIn onSignedIn={vi.fn()} />);

    await sendCodeTo(user, "ban@shopcuaban.vn");

    expect(await screen.findByRole("status")).toHaveTextContent("Đã gửi mã 6 chữ số tới ban@shopcuaban.vn");
    expect(screen.getByLabelText("Mã đăng nhập (6 chữ số)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gửi lại mã sau 60 giây" })).toBeDisabled();
    const [url] = fetchSpy.mock.calls[0] as [string];
    expect(new URL(url).searchParams.get("redirect_to")).toBe(`${window.location.origin}/auth/callback`);
  });

  it("re-enables Gửi lại mã when the cooldown ends", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    routeSupabase({});
    render(<EmailSignIn onSignedIn={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "ban@shopcuaban.vn" } });
    fireEvent.click(screen.getByRole("button", { name: "Gửi mã" }));
    await screen.findByRole("button", { name: /Gửi lại mã sau/ });

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

  it("a wrong or expired code shows the Vietnamese error, clears the field and never echoes the code", async () => {
    const user = userEvent.setup();
    routeSupabase({
      verify: () => json(403, { error_code: "otp_expired", msg: "Token has expired or is invalid" }),
    });
    render(<EmailSignIn onSignedIn={vi.fn()} />);
    await sendCodeTo(user, "ban@shopcuaban.vn");

    await user.type(await screen.findByLabelText("Mã đăng nhập (6 chữ số)"), "987654");
    await user.click(screen.getByRole("button", { name: "Xác nhận" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Mã không đúng hoặc đã hết hạn");
    expect(screen.getByLabelText("Mã đăng nhập (6 chữ số)")).toHaveValue("");
    expect(document.body.textContent).not.toContain("987654");
    expect(readAuthSession()).toBeNull();
  });

  it("a rate-limited send says so in Vietnamese and locks Gửi mã for the wait GoTrue names", async () => {
    const user = userEvent.setup();
    routeSupabase({
      otp: () =>
        json(429, {
          error_code: "over_email_send_rate_limit",
          msg: "For security purposes, you can only request this after 37 seconds.",
        }),
    });
    render(<EmailSignIn onSignedIn={vi.fn()} />);

    await sendCodeTo(user, "ban@shopcuaban.vn");

    expect(await screen.findByRole("alert")).toHaveTextContent("Bạn đã yêu cầu quá nhiều lần");
    expect(screen.getByRole("button", { name: "Gửi mã sau 37 giây" })).toBeDisabled();
  });

  it("a right code stores the session in the Google path's shape and key, then hands over", async () => {
    const user = userEvent.setup();
    const onSignedIn = vi.fn();
    routeSupabase({});
    render(<EmailSignIn onSignedIn={onSignedIn} />);
    await sendCodeTo(user, "ban@shopcuaban.vn");

    await user.type(await screen.findByLabelText("Mã đăng nhập (6 chữ số)"), "123 456");
    await user.click(screen.getByRole("button", { name: "Xác nhận" }));

    await waitFor(() => expect(onSignedIn).toHaveBeenCalledTimes(1));
    const session = {
      accessToken: "eyJ.email.sig",
      refreshToken: "r-email-1",
      expiresIn: 3600,
      tokenType: "bearer",
    };
    expect(onSignedIn).toHaveBeenCalledWith(session);
    expect(JSON.parse(window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY) as string)).toEqual(session);
    const verifyCall = (fetchSpy.mock.calls as unknown as [string, RequestInit][]).find(([url]) =>
      url.includes("/auth/v1/verify"),
    ) as [string, RequestInit];
    expect(JSON.parse(verifyCall[1].body as string)).toEqual({ type: "email", email: "ban@shopcuaban.vn", token: "123456" });
  });

  it("by default reports the sign-up and full-loads the connect-shop screen", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.spyOn(window, "location", "get").mockReturnValue({ ...window.location, assign });
    routeSupabase({});
    render(<EmailSignIn />);
    await sendCodeTo(user, "ban@shopcuaban.vn");
    await user.type(await screen.findByLabelText("Mã đăng nhập (6 chữ số)"), "123456");
    await user.click(screen.getByRole("button", { name: "Xác nhận" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/auth/connect-shop"));
    expect(reportTikTokRegistration).toHaveBeenCalledWith("eyJ.email.sig");
    vi.restoreAllMocks();
  });

  it("Dùng email khác goes back to the email step", async () => {
    const user = userEvent.setup();
    routeSupabase({});
    render(<EmailSignIn onSignedIn={vi.fn()} />);
    await sendCodeTo(user, "ban@shopcuaban.vn");

    await user.click(await screen.findByRole("button", { name: "Dùng email khác" }));

    expect(screen.getByLabelText("Email")).toHaveValue("ban@shopcuaban.vn");
  });
});
