import { render, screen, waitFor } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AuthCallbackPage from "../app/auth/callback/page";
import { readAuthSession } from "../lib/supabase-auth";
import { reportTikTokRegistration } from "../lib/tiktok-registration";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(),
}));

vi.mock("../lib/tiktok-registration", () => ({
  reportTikTokRegistration: vi.fn(async () => undefined),
}));

const replace = vi.fn();

function setHash(hash: string) {
  window.location.hash = hash;
}

describe("Auth callback route", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
    replace.mockClear();
    vi.mocked(reportTikTokRegistration).mockClear();
    vi.mocked(useRouter).mockReturnValue({
      back: vi.fn(),
      forward: vi.fn(),
      prefetch: vi.fn(),
      push: vi.fn(),
      refresh: vi.fn(),
      replace,
    } as unknown as ReturnType<typeof useRouter>);
  });

  afterEach(() => {
    window.location.hash = "";
  });

  it("stores the real session and moves on to the connect-shop screen", async () => {
    setHash("#access_token=abc.def.ghi&refresh_token=r-1&expires_in=3600&token_type=bearer");

    render(<AuthCallbackPage />);

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith("/auth/connect-shop");
    });
    expect(readAuthSession()).toEqual({
      accessToken: "abc.def.ghi",
      refreshToken: "r-1",
      expiresIn: 3600,
      tokenType: "bearer",
    });
  });

  it("reports the sign-up to TikTok, with the session stored first", async () => {
    setHash("#access_token=abc.def.ghi&refresh_token=r-1&expires_in=3600&token_type=bearer");

    render(<AuthCallbackPage />);

    await waitFor(() => {
      expect(reportTikTokRegistration).toHaveBeenCalledWith("abc.def.ghi");
    });
    // The session is what the seller came for; the conversion report must not
    // be able to cost them it.
    expect(readAuthSession()).not.toBeNull();
  });

  it("reports nothing when the sign-in failed", async () => {
    setHash("#error=access_denied&error_description=User%20cancelled%20login");

    render(<AuthCallbackPage />);

    await screen.findByRole("alert");
    expect(reportTikTokRegistration).not.toHaveBeenCalled();
  });

  it("renders a real, announced error on a provider failure — never a silent fall-through", async () => {
    setHash("#error=access_denied&error_description=User%20cancelled%20login");

    render(<AuthCallbackPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/User cancelled login|không thể đăng nhập|Đăng nhập không thành công/i);
    expect(replace).not.toHaveBeenCalled();
    expect(readAuthSession()).toBeNull();
  });

  it("treats an empty callback as an honest error, not a fabricated success", async () => {
    setHash("");

    render(<AuthCallbackPage />);

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});
