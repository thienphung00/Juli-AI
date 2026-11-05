import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { ShopMember } from "../../../lib/ops/types";
import { OpsShopSettings } from "../ops-shop-settings";
import { ME, SETTINGS, SHOP_ID } from "./fixtures";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

const MEMBERS: ShopMember[] = [
  { user_id: "u-1", email: "an@gmai…@…", added_at: "2026-11-01T03:00:00", added_via: "invite", implicit: false },
  { user_id: "u-2", email: "binh@g…@…", added_at: "2026-11-03T03:00:00", added_via: "invite", implicit: false },
];

const api = (members: ShopMember[] = MEMBERS) => ({
  settings: vi.fn(async () => ({ ...SETTINGS, members })),
  putSettings: vi.fn(async () => ({ settings: SETTINGS.settings })),
  resetSettings: vi.fn(async () => ({ settings: SETTINGS.settings })),
  invite: vi.fn(async () => ({ data: {} as never, email_sent: true, accept_url: null })),
  removeMember: vi.fn(async (_shop: string, userId: string) => ({ data: { user_id: userId, email: null, removed: true } })),
});

describe("Thành viên shop (P93)", () => {
  it("lists the members and invites one more person per link", async () => {
    const a = api();
    render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
    const team = await screen.findByTestId("ops-shop-team");
    expect(within(team).getByRole("heading", { name: "Thành viên shop" })).toBeInTheDocument();
    const rows = within(team).getAllByTestId("ops-member-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("an@gmai…@…");
    expect(rows[0]).toHaveTextContent("Tham gia");
    fireEvent.change(within(team).getByLabelText("Email của seller"), { target: { value: "chi@gmail.com" } });
    fireEvent.click(within(team).getByRole("button", { name: "Mời thêm" }));
    await waitFor(() => expect(a.invite).toHaveBeenCalledWith(SHOP_ID, "chi@gmail.com", true));
    expect(await within(team).findByText("Đã gửi email mời.")).toBeInTheDocument();
  });

  it("asks in the page before removing, never with window.confirm, and removes on confirm", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const a = api();
    render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
    const team = await screen.findByTestId("ops-shop-team");
    fireEvent.click(within(team).getByRole("button", { name: "Gỡ binh@g…@…" }));
    const dialog = screen.getByRole("dialog", { name: /Gỡ binh@g…@… khỏi/ });
    expect(a.removeMember).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("Người này mất quyền vào shop ngay");
    fireEvent.click(within(dialog).getByRole("button", { name: "Gỡ khỏi shop" }));
    await waitFor(() => expect(a.removeMember).toHaveBeenCalledWith(SHOP_ID, "u-2"));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(confirm).not.toHaveBeenCalled();
    confirm.mockRestore();
  });

  it("Quay lại closes the dialog without removing anyone", async () => {
    const a = api();
    render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
    const team = await screen.findByTestId("ops-shop-team");
    fireEvent.click(within(team).getByRole("button", { name: "Gỡ an@gmai…@…" }));
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Quay lại" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(a.removeMember).not.toHaveBeenCalled();
  });

  it("shows pending invites, an empty team with Mời seller, and no buttons for a Xem role", async () => {
    const pending = { id: "i1", email: "den@gmai…@…", keep_ops_access: true, expires_at: "2026-11-12T00:00:00", created_at: null, accepted_at: null, seller_kept_ops_access: null, revoked_at: null };
    const a = { ...api([]), settings: vi.fn(async () => ({ ...SETTINGS, members: [], invites: [pending] })) };
    const { unmount } = render(<OpsShopSettings api={a} me={ME} shopId={SHOP_ID} />);
    const team = await screen.findByTestId("ops-shop-team");
    expect(within(team).getByText("Chưa có thành viên nào.")).toBeInTheDocument();
    expect(within(team).getByTestId("ops-pending-invite")).toHaveTextContent("den@gmai…@…");
    expect(within(team).getByRole("button", { name: "Mời seller" })).toBeInTheDocument();
    unmount();

    render(<OpsShopSettings api={api()} me={{ ...ME, role: "viewer", role_label: "Xem" }} shopId={SHOP_ID} />);
    const viewerTeam = await screen.findByTestId("ops-shop-team");
    expect(within(viewerTeam).getAllByTestId("ops-member-row")).toHaveLength(2);
    expect(within(viewerTeam).queryByRole("button", { name: /Gỡ/ })).toBeNull();
    expect(within(viewerTeam).queryByRole("button", { name: /Mời/ })).toBeNull();
  });

  it("lets Vận hành invite on a contract shop whose owner has no e-mail", async () => {
    const contract = { ...SETTINGS, members: [], invites: [], shop: { ...SETTINGS.shop, owner_email: null, owned_by_team: false } };
    const a = { ...api([]), settings: vi.fn(async () => contract) };
    render(<OpsShopSettings api={a} me={{ ...ME, role: "operator", role_label: "Vận hành" }} shopId={SHOP_ID} />);
    const team = await screen.findByTestId("ops-shop-team");
    expect(within(team).getByText("Chưa có thành viên.")).toBeInTheDocument();
    expect(within(team).queryByText(/—/)).toBeNull();
    fireEvent.change(within(team).getByLabelText("Email của seller"), { target: { value: "ory@gmail.com" } });
    fireEvent.click(within(team).getByRole("button", { name: "Mời seller" }));
    await waitFor(() => expect(a.invite).toHaveBeenCalledWith(SHOP_ID, "ory@gmail.com", true));
  });
});
