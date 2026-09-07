import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ConnectShopView } from "../components/connect-shop-view";
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

  it("states honestly, with no control implying a working merchant exchange, when the seller has zero connected shops", async () => {
    const loadShops = vi.fn().mockResolvedValue([]);

    render(<ConnectShopView loadShops={loadShops} session={session} />);

    await waitFor(() => {
      expect(screen.getByText(/chưa kết nối/i)).toBeInTheDocument();
    });

    const cta = screen.queryByTestId("connect-tiktok-shop-cta");
    if (cta) {
      expect(cta).toHaveAttribute("aria-disabled", "true");
    }
    expect(
      screen.getByText(/đang được hoàn thiện|chưa được kết nối|chưa hoạt động/i),
    ).toBeInTheDocument();
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
