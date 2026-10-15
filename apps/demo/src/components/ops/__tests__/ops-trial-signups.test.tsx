import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import type { TrialSignup, TrialSignupsPage } from "../../../lib/ops/types";
import { auditWhat } from "../audit-text";
import { resetCostSystemCache } from "../ops-cost-banner";
import { OpsHeader } from "../ops-shell";
import { OpsTrialSignups, zaloHref } from "../ops-trial-signups";
import { ME } from "./fixtures";

/** P33-F (D43) — the Ops tab "Đăng ký dùng thử". */

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }), usePathname: () => "/ops" }));

const VIEWER = { ...ME, role: "viewer" as const, role_label: "Xem" };
const OPERATOR = { ...ME, role: "operator" as const, role_label: "Vận hành" };

const ROW: TrialSignup = {
  id: "11111111-1111-4111-8111-111111111111",
  created_at: "2026-10-15T03:20:00",
  full_name: "Nguyễn Thị Lan",
  phone: "0912345678",
  email: "lan@example.vn",
  shop: "tiktok.com/@lanshop",
  role: "seller",
  role_label: "Nhà bán",
  note: "Mỹ phẩm, 300 đơn/ngày",
  source: { utm_source: "tiktok", utm_campaign: "q4" },
  status: "new",
  status_label: "Mới",
  handled_by: null,
  handled_at: null,
};

const PAGE: TrialSignupsPage = {
  data: [ROW],
  counts: { new: 1, contacted: 2, converted: 0, spam: 0 },
  statuses: [
    { value: "new", label: "Mới" },
    { value: "contacted", label: "Đã liên hệ" },
    { value: "converted", label: "Đã kết nối shop" },
    { value: "spam", label: "Spam" },
  ],
};

function api() {
  return {
    trialSignups: vi.fn(async () => PAGE),
    setTrialSignupStatus: vi.fn(async () => ({ data: { ...ROW, status: "contacted" as const } })),
  };
}

beforeEach(() => {
  window.localStorage.clear();
  resetCostSystemCache();
});

afterEach(() => {
  resetCostSystemCache();
});

describe("Ops · Đăng ký dùng thử", () => {
  it("is in the main nav", () => {
    render(<OpsHeader active="signups" me={ME} />);
    const nav = screen.getByRole("navigation", { name: "Ops" });
    expect(within(nav).getByText("Đăng ký dùng thử")).toHaveAttribute("aria-current", "page");
  });

  it("lists sign-ups with contact links, source and counts", async () => {
    const a = api();
    render(<OpsTrialSignups api={a} me={OPERATOR} />);
    const row = await screen.findByTestId("signup-row");
    expect(row).toHaveTextContent("Nguyễn Thị Lan");
    expect(row).toHaveTextContent("Nhà bán");
    expect(within(row).getByText("0912345678")).toHaveAttribute("href", "tel:0912345678");
    expect(within(row).getByText("Nhắn Zalo")).toHaveAttribute("href", zaloHref("0912345678"));
    expect(within(row).getByText("lan@example.vn")).toHaveAttribute("href", "mailto:lan@example.vn");
    expect(row).toHaveTextContent("Nguồn: tiktok / q4");
    expect(screen.getByRole("button", { name: "Tất cả · 3" })).toHaveAttribute("aria-pressed", "true");
    expect(a.trialSignups).toHaveBeenCalledWith(null);
  });

  it("filters by status", async () => {
    const a = api();
    render(<OpsTrialSignups api={a} me={OPERATOR} />);
    await screen.findByTestId("signup-row");
    fireEvent.click(screen.getByRole("button", { name: "Đã liên hệ · 2" }));
    await waitFor(() => expect(a.trialSignups).toHaveBeenLastCalledWith("contacted"));
  });

  it("Vận hành changes the status (one audited call) and reloads", async () => {
    const a = api();
    render(<OpsTrialSignups api={a} me={OPERATOR} />);
    await screen.findByTestId("signup-row");
    fireEvent.change(screen.getByLabelText("Trạng thái của Nguyễn Thị Lan"), { target: { value: "contacted" } });
    await waitFor(() => expect(a.setTrialSignupStatus).toHaveBeenCalledWith(ROW.id, "contacted"));
    expect(await screen.findByText(/Mới → Đã liên hệ · ghi 1 dòng nhật ký/)).toBeInTheDocument();
    await waitFor(() => expect(a.trialSignups).toHaveBeenCalledTimes(2));
  });

  it("Xem sees no status control and the API's 403 as 'cần quyền Vận hành'", async () => {
    const a = {
      trialSignups: vi.fn(async () => {
        throw new OpsApiError(403, "Role too low");
      }),
      setTrialSignupStatus: vi.fn(),
    };
    render(<OpsTrialSignups api={a} me={VIEWER} />);
    expect(await screen.findByText(/Cần quyền Vận hành/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(a.setTrialSignupStatus).not.toHaveBeenCalled();
  });

  it("reads the audit row as a sentence (Nhật ký)", () => {
    expect(
      auditWhat({
        id: "a",
        at: "2026-10-15T03:20:00",
        actor_email: "thien.phung@app-juli.com",
        shop_id: null,
        action: "trial_signup_status",
        kind: "config",
        merged_count: 1,
        before: { status: "new" },
        after: { status: "converted" },
      }),
    ).toBe("Đăng ký dùng thử: Mới → Đã kết nối shop");
  });
});
