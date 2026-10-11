import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AUTH_SESSION_STORAGE_KEY } from "../../lib/supabase-auth";
import { AcceptInvite } from "../accept-invite";

beforeEach(() => {
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify({ accessToken: "t", tokenType: "bearer" }));
});

describe("Nhận shop (P9-B, D25.7)", () => {
  it("previews and accepts in JSON bodies, asking about the team's access", async () => {
    const fetchImpl = vi.fn(async (url: string) =>
      url.endsWith("/preview")
        ? new Response(JSON.stringify({ data: { shop_name: "Mỹ phẩm Thảo Nhi", keep_ops_access_asked: true, expires_at: "x" } }), { status: 200 })
        : new Response(JSON.stringify({ data: { shop_id: "s1", kept_ops_access: false } }), { status: 200 }),
    );
    render(<AcceptInvite fetchImpl={fetchImpl as unknown as typeof fetch} inviteToken="tok-123456789012345678901" />);
    expect(await screen.findByText(/Mỹ phẩm Thảo Nhi/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: "Nhận shop" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Shop đã về tài khoản của bạn."));
    const calls = fetchImpl.mock.calls as unknown as [string, RequestInit][];
    expect(calls.map(([u]) => u)).toEqual(["/v1/shop-invites/preview", "/v1/shop-invites/accept"]);
    expect(calls.every(([u]) => !u.includes("tok-"))).toBe(true);
    expect(JSON.parse(String(calls[1][1].body))).toEqual({ token: "tok-123456789012345678901", keep_ops_access: false });
  });

  it("explains a wrong account", async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ detail: "wrong_account" }), { status: 403 }));
    render(<AcceptInvite fetchImpl={fetchImpl as unknown as typeof fetch} inviteToken="tok-123456789012345678901" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("đăng nhập bằng email khác");
  });
});
