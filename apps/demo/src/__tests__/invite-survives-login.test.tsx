import { render, screen, waitFor } from "@testing-library/react";
import { useRouter } from "next/navigation";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AuthCallbackPage from "../app/auth/callback/page";
import { AcceptInvite } from "../components/accept-invite";
import { PENDING_INVITE_KEY, rememberPendingInvite, takePendingInvite } from "../lib/ops/invite-client";

vi.mock("next/navigation", () => ({ useRouter: vi.fn() }));
vi.mock("../lib/tiktok-registration", () => ({ reportTikTokRegistration: vi.fn(async () => undefined) }));

const replace = vi.fn();
const FAKE_INVITE = "tok-invite"; // a placeholder, not a real invite token

describe("lời mời qua bước đăng nhập (2026-11-06: an invited seller signed in and the invite was lost)", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
    window.history.replaceState(null, "", "/");
    replace.mockClear();
    vi.mocked(useRouter).mockReturnValue({ back: vi.fn(), forward: vi.fn(), prefetch: vi.fn(), push: vi.fn(), refresh: vi.fn(), replace });
  });

  it("opening the invite signed out remembers it for after sign-in", async () => {
    render(<AcceptInvite inviteToken={FAKE_INVITE} />);
    expect(await screen.findByText(/Đăng nhập bằng email được mời/)).toBeInTheDocument();
    expect(screen.getByText(/Sau khi bạn đã tham gia/)).toBeInTheDocument();
    expect(takePendingInvite()).toBe(FAKE_INVITE);
  });

  it("after sign-in the callback goes back to the invite and keeps it until Tham gia shop", async () => {
    rememberPendingInvite(FAKE_INVITE);
    window.location.hash = "#access_token=eyJ.a.b&expires_at=1791600000&expires_in=3600&refresh_token=r&token_type=bearer";
    render(<AuthCallbackPage />);
    await waitFor(() => expect(replace).toHaveBeenCalledWith(`/nhan-shop#${FAKE_INVITE}`));
    expect(window.localStorage.getItem(PENDING_INVITE_KEY)).toContain(FAKE_INVITE);
  });

  it("an expired remembered invite is ignored", () => {
    window.localStorage.setItem(PENDING_INVITE_KEY, JSON.stringify({ token: FAKE_INVITE, at: Date.now() - 8 * 86_400_000 }));
    expect(takePendingInvite()).toBeNull();
    expect(window.localStorage.getItem(PENDING_INVITE_KEY)).toBeNull();
  });
});
