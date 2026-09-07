import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ConnectShopPage from "../app/auth/connect-shop/page";
import { clearAuthSession, storeAuthSession } from "../lib/supabase-auth";

const VALID_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  "eyJzdWIiOiJ1MSIsImVtYWlsIjoic2VsbGVyQGV4YW1wbGUuY29tIn0." +
  "sig";

describe("Connect-shop route", () => {
  beforeEach(() => {
    clearAuthSession();
  });

  it("sends a visitor with no stored session back to the landing, honestly", async () => {
    render(<ConnectShopPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/chưa đăng nhập/i);
    expect(screen.getByRole("link", { name: /trang chào mừng|đăng nhập/i })).toHaveAttribute(
      "href",
      "/",
    );
  });

  it("renders the connect-shop screen for a real signed-in session", async () => {
    storeAuthSession({
      accessToken: VALID_JWT,
      refreshToken: "r-1",
      expiresIn: 3600,
      tokenType: "bearer",
    });

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => [],
    } as Response);

    render(<ConnectShopPage />);

    expect(
      await screen.findByRole("heading", { name: "Kết nối TikTok Shop" }),
    ).toBeInTheDocument();

    const [, init] = fetchSpy.mock.calls[0] as [string, RequestInit];
    expect((init.headers as Record<string, string>).Authorization).toBe(
      `Bearer ${VALID_JWT}`,
    );
    fetchSpy.mockRestore();
  });
});
