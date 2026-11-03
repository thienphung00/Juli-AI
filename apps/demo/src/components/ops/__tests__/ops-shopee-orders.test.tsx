import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { OpsApiError } from "../../../lib/ops/api";
import { CANARIES, KEY_HEX, PLAIN, RAW_ORDER_IDS } from "../../../lib/ops/orders/__tests__/fixtures";
import { buildXlsx } from "../../../lib/ops/orders/__tests__/xlsx-builder";
import { OpsShopeeOrders, failureText } from "../shopee/ops-shopee-orders";
import { ME, SHOP_ID } from "./fixtures";

/** P90 step 2: the Đơn hàng page, with a synthetic workbook whose buyer columns carry canaries. */

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("../ops-cost-banner", () => ({ OpsCostBanner: () => null }));

function fakeApi() {
  const uploads: string[] = [];
  return {
    uploads,
    api: {
      orderRefKey: vi.fn(async () => ({ order_ref_key: KEY_HEX, algorithm: "HMAC-SHA256", key_version: 1, expires_at: "2026-11-03T03:10:00Z" })),
      uploadOrderLines: vi.fn(async (_shopId: string, lines: readonly unknown[]) => {
        uploads.push(JSON.stringify(lines));
        return { lines: lines.length, duplicate: false };
      }),
    },
  };
}

const file = (bytes: Uint8Array) =>
  new File([bytes as BlobPart], "Order.all.20261001_20261031.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });

function choose(input: HTMLElement, f: File) {
  fireEvent.change(input, { target: { files: [f] } });
}

describe("OpsShopeeOrders", () => {
  it("reads the workbook in the browser, shows counts only, and posts hashed PII-free lines", async () => {
    const { api, uploads } = fakeApi();
    render(<OpsShopeeOrders api={api} me={ME} shopId={SHOP_ID} />);
    choose(screen.getByLabelText(/Chọn tệp đơn hàng/), file(PLAIN));

    const preview = await screen.findByTestId("orders-preview");
    expect(api.orderRefKey).toHaveBeenCalledWith(SHOP_ID);
    expect(within(preview).getByText("11").nextSibling?.textContent).toContain("dòng");
    expect(within(preview).getByText("9").nextSibling?.textContent).toContain("đơn");
    const table = screen.getByRole("table", { name: "Đơn theo trạng thái" });
    expect(within(table).getByText("Đã hủy").nextSibling?.textContent).toBe("1");

    // Nothing but counts is on the page: no canary, no raw order id, no key.
    for (const secret of [...CANARIES, ...RAW_ORDER_IDS, KEY_HEX]) expect(document.body.textContent).not.toContain(secret);
    expect(api.uploadOrderLines).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Tải lên 11 dòng/ }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toContain("Đã gửi 11 / 11 dòng"));
    expect(api.uploadOrderLines).toHaveBeenCalledTimes(2);
    const posted = uploads.join("\n");
    for (const secret of [...CANARIES, ...RAW_ORDER_IDS, KEY_HEX]) expect(posted).not.toContain(secret);
    expect(screen.queryByRole("button", { name: /Tải lên/ })).toBeNull();
  });

  it("names the unknown column and sends nothing when Shopee changed the export", async () => {
    const { api } = fakeApi();
    render(<OpsShopeeOrders api={api} me={ME} shopId={SHOP_ID} />);
    choose(screen.getByLabelText(/Chọn tệp đơn hàng/), file(buildXlsx([["Mã đơn hàng", "Email người mua"], ["X-1", "CANARY-mail@example.invalid"]])));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Email người mua");
    expect(alert.textContent).not.toContain("CANARY");
    expect(api.uploadOrderLines).not.toHaveBeenCalled();
  });

  it("shows a server refusal without echoing a value", async () => {
    const { api } = fakeApi();
    api.uploadOrderLines.mockRejectedValueOnce(new OpsApiError(403, "consent_required"));
    render(<OpsShopeeOrders api={api} me={ME} shopId={SHOP_ID} />);
    choose(screen.getByLabelText(/Chọn tệp đơn hàng/), file(PLAIN));
    fireEvent.click(await screen.findByRole("button", { name: /Tải lên/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("đồng ý");
  });

  it("gives a viewer no upload control", () => {
    const { api } = fakeApi();
    render(<OpsShopeeOrders api={api} me={{ ...ME, role: "viewer" }} shopId={SHOP_ID} />);
    expect(screen.queryByLabelText(/Chọn tệp đơn hàng/)).toBeNull();
    expect(screen.getByText(/Chỉ vai trò Vận hành/)).toBeTruthy();
  });

  it("words the failures", () => {
    expect(failureText(new OpsApiError(503, "order_ref_key_not_configured"))).toContain("khóa băm");
    expect(failureText(new OpsApiError(422, "invalid_rows"))).toContain("từ chối");
  });
});
