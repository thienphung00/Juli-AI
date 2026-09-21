import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConnectShopView } from "../components/connect-shop-view";
import { readActiveShop } from "../lib/shop-session";
import { ShopsFetchError } from "../lib/shops-client";

const VALID_JWT =
  "eyJhbGciOiJIUzI1NiJ9." +
  "eyJzdWIiOiJ1MSIsImVtYWlsIjoic2VsbGVyQGV4YW1wbGUuY29tIn0." +
  "sig";

const session = {
  accessToken: VALID_JWT,
  refreshToken: "r-1",
  expiresIn: 3600,
  tokenType: "bearer",
};

describe("ConnectShopView", () => {
  it("shows an honest loading state while the shop list is in flight", () => {
    render(
      <ConnectShopView
        loadShops={() => new Promise(() => {})}
        session={session}
      />,
    );

    expect(
      screen.getByRole("status", { name: "Đang kiểm tra tài khoản" }),
    ).toBeInTheDocument();
  });

  it("greets the signed-in user by the email decoded from their real session, and every call it makes carries a bearer token", async () => {
    const loadShops = vi.fn().mockResolvedValue([]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText(/seller@example\.com/)).toBeInTheDocument();
    });

    expect(loadShops).toHaveBeenCalledWith(VALID_JWT);
  });

  it("offers a LIVE connect control to a seller with zero connected shops (issue #1970)", async () => {
    // Until #1970 this control was `aria-disabled` with an `onClick` that called
    // preventDefault, beside a disclaimer saying it did nothing — honest, but it
    // meant a signed-in seller could not connect a shop at all. The route it now
    // calls, `GET /v1/auth/tiktok/start`, returned 404 in production.
    const loadShops = vi.fn().mockResolvedValue([]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText(/chưa kết nối/i)).toBeInTheDocument();
    });

    const cta = screen.getByTestId("connect-tiktok-shop-cta");
    expect(cta).not.toHaveAttribute("aria-disabled");
    expect(cta).toBeEnabled();
  });

  it("sends the seller to the authorize URL the SERVER signed, never one it built itself (issue #1970)", async () => {
    const user = userEvent.setup();
    const authorizeUrl =
      "https://services.tiktokshop.com/open/authorize?app_key=k&state=signed.sig";
    const startConnect = vi
      .fn()
      .mockResolvedValue({ authorize_url: authorizeUrl, state_expires_in: 600 });
    const navigate = vi.fn();

    render(
      <ConnectShopView
        loadShops={vi.fn().mockResolvedValue([])}
        navigate={navigate}
        session={session}
        startConnect={startConnect}
      />,
    );

    await user.click(await screen.findByTestId("connect-tiktok-shop-cta"));

    // The bearer token is what proves who is connecting; the signed state the
    // backend mints from it is what binds the shop to them.
    expect(startConnect).toHaveBeenCalledWith(VALID_JWT);
    await waitFor(() => {
      expect(navigate).toHaveBeenCalledWith(authorizeUrl);
    });
  });

  it("keeps the seller on the page with an honest retry when the start call fails (issue #1970)", async () => {
    const user = userEvent.setup();
    const navigate = vi.fn();

    render(
      <ConnectShopView
        loadShops={vi.fn().mockResolvedValue([])}
        navigate={navigate}
        session={session}
        startConnect={vi.fn().mockRejectedValue(new Error("503"))}
      />,
    );

    await user.click(await screen.findByTestId("connect-tiktok-shop-cta"));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Không thể bắt đầu kết nối TikTok/i,
    );
    // Never a client-built fallback URL: only a server-signed state is bindable.
    expect(navigate).not.toHaveBeenCalled();
    expect(screen.getByTestId("connect-tiktok-shop-cta")).toBeEnabled();
  });

  it("shows the single connected shop without implying any further live wiring", async () => {
    const loadShops = vi.fn().mockResolvedValue([
      { id: "shop-1", shop_name: "Cửa hàng của Lan", tiktok_shop_id: "tt-1", is_active: true },
    ]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText("Cửa hàng của Lan")).toBeInTheDocument();
    });
  });

  it("lets a seller with more than one shop tell which shop they are acting as", async () => {
    const user = userEvent.setup();
    const loadShops = vi.fn().mockResolvedValue([
      { id: "shop-1", shop_name: "Cửa hàng của Lan", tiktok_shop_id: "tt-1", is_active: true },
      { id: "shop-2", shop_name: "Shop Minh Anh", tiktok_shop_id: "tt-2", is_active: true },
    ]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText("Shop Minh Anh")).toBeInTheDocument();
    });

    const picker = screen.getByRole("radiogroup", { name: /shop/i });
    const options = within(picker).getAllByRole("radio");
    expect(options).toHaveLength(2);
    expect(options[0]).toBeChecked();

    await user.click(options[1]);

    expect(document.querySelector(".connect-shop__active-shop")).toHaveTextContent(
      "Bạn đang thao tác trên: Shop Minh Anh",
    );
  });

  it("persists the default (first) shop as the acting shop the moment the list loads (issue #1909)", async () => {
    const loadShops = vi.fn().mockResolvedValue([
      { id: "shop-1", shop_name: "Cửa hàng của Lan", tiktok_shop_id: "tt-1", is_active: true },
      { id: "shop-2", shop_name: "Shop Minh Anh", tiktok_shop_id: "tt-2", is_active: true },
    ]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText("Shop Minh Anh")).toBeInTheDocument();
    });

    expect(readActiveShop()).toEqual({ id: "shop-1", name: "Cửa hàng của Lan" });
  });

  it("persists the newly selected shop so signed-in surfaces send its id as X-Shop-Id (issue #1909)", async () => {
    const user = userEvent.setup();
    const loadShops = vi.fn().mockResolvedValue([
      { id: "shop-1", shop_name: "Cửa hàng của Lan", tiktok_shop_id: "tt-1", is_active: true },
      { id: "shop-2", shop_name: "Shop Minh Anh", tiktok_shop_id: "tt-2", is_active: true },
    ]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText("Shop Minh Anh")).toBeInTheDocument();
    });

    const picker = screen.getByRole("radiogroup", { name: /shop/i });
    await user.click(within(picker).getAllByRole("radio")[1]);

    expect(readActiveShop()).toEqual({ id: "shop-2", name: "Shop Minh Anh" });
  });

  it("offers a real path onward to Decisions once a shop is selected (issue #1909)", async () => {
    const loadShops = vi.fn().mockResolvedValue([
      { id: "shop-1", shop_name: "Cửa hàng của Lan", tiktok_shop_id: "tt-1", is_active: true },
    ]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByRole("link", { name: "Đi tới Hành động" })).toHaveAttribute(
        "href",
        "/decisions",
      );
    });
  });

  it("renders the documented 401 known gap honestly, never a silent fixture fallback", async () => {
    const loadShops = vi
      .fn()
      .mockRejectedValue(new ShopsFetchError(401, "User not found"));

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/401/);
    expect(alert).not.toHaveTextContent(/Cửa hàng của Lan/);
  });

  it("renders a network-failure error honestly rather than a fixture", async () => {
    const loadShops = vi.fn().mockRejectedValue(new TypeError("network down"));

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toBeInTheDocument();
  });
});
