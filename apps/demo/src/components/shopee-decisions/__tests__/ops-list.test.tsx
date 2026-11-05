import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ShopeeApiError } from "../../../lib/shopee-analytics/client";
import { fakeReco, summaryOf, versionOf, voucherCard } from "../../../lib/shopee-decisions/__tests__/fixtures";
import type { CardByCode, CardList, CardSummary, Family } from "../../../lib/shopee-decisions/types";
import { DecisionsView } from "../decisions-view";
import { params, renderReco } from "./harness";

function mk(id: string, code: string, queue: number | null, over: Partial<CardSummary> = {}, family: Family = "voucher", label = "Voucher"): CardSummary {
  const card = voucherCard({ id, code, product_queue: queue, family, family_label: label, title: `Thẻ ${code}`, versions: [versionOf(voucherCard(), 1, "Mặc định", { code: `${code}-V1` }), versionOf(voucherCard(), 2, "Hai", { code: `${code}-V2` })] });
  return summaryOf(card, { code, product_queue: queue, sent_at: "2026-11-04T00:10:00Z", product_id: "GT-A", ...over });
}

const cards: CardSummary[] = [
  mk("a", "JC-2611-0007", 1),
  mk("b", "JC-2611-0015", 3, { origin: "manual", status: "draft" }, "combo", "Combo"),
  mk("c", "JC-2611-0003", 1, { status: "planned", product_id: "TR-B" }, "promotion", "Khuyến mãi"),
  mk("d", "JC-2610-0031", null, { status: "executed", plan_code: "KH-2610-007" }, "promotion", "Khuyến mãi"),
  mk("e", "JC-2610-0008", null, { status: "rejected", product_id: "TR-B" }),
];

const list: CardList = { platform: "shopee", xep_theo: "diem", queue: "all", cards, counts: { family: {}, section: {}, total: cards.length } };
const products = async () => [
  { id: "GT-A", name: "Găng tay cao su A" },
  { id: "TR-B", name: "Túi rác sinh học B" },
];

function open(reco = fakeReco({ list })) {
  renderReco(<DecisionsView params={params()} />, reco, { staff: true, products, href: (v) => `/ops/shops/s1/shopee/de-xuat?${new URLSearchParams(Object.entries({ ...(v.the ? { the: v.the } : {}), ...(v.builder ? { "tu-tao": "1", from: v.from ?? "" } : {}) }))}` });
  return reco;
}

describe("Ops · Danh sách đề xuất", () => {
  it("Gỡ thẻ on an open card asks in the page (reason select), then withdraws with the reason", async () => {
    const reco = open();
    await screen.findByTestId("ops-row-JC-2611-0007");
    expect(screen.queryByTestId("ops-withdraw-JC-2610-0031")).toBeNull(); // executed: nothing to take off
    expect(screen.queryByTestId("ops-withdraw-JC-2610-0008")).toBeNull(); // dismissed already
    fireEvent.click(screen.getByTestId("ops-withdraw-JC-2611-0007"));
    expect(await screen.findByTestId("sd-withdraw-dialog")).toBeInTheDocument();
    expect(reco.calls.filter((c) => c.name === "withdraw")).toHaveLength(0);
    fireEvent.change(screen.getByTestId("sd-withdraw-reason"), { target: { value: "duplicate" } });
    fireEvent.click(screen.getByTestId("sd-withdraw-confirm"));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "withdraw")).toBe(true));
    const call = reco.calls.find((c) => c.name === "withdraw")!;
    expect(call.args[0]).toBe("a");
    expect(call.args[1]).toMatchObject({ reasonCode: "duplicate" });
    expect(await screen.findByTestId("ops-withdraw-flash")).toHaveTextContent("Đã gỡ 1 thẻ");
  });

  it("bulk: select open cards (planned and manual too), Gỡ N thẻ, one request with the reason", async () => {
    const reco = open();
    await screen.findByTestId("ops-row-JC-2611-0007");
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn thẻ JC-2611-0007" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn thẻ JC-2611-0003" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Chọn thẻ JC-2611-0015" }));
    expect(screen.queryByRole("checkbox", { name: "Chọn thẻ JC-2610-0031" })).toBeNull();
    fireEvent.click(screen.getByTestId("ops-bulk-withdraw"));
    expect(await screen.findByRole("dialog")).toHaveTextContent("Gỡ 3 thẻ đã chọn?");
    fireEvent.click(screen.getByTestId("sd-withdraw-confirm"));
    await waitFor(() => expect(reco.calls.some((c) => c.name === "withdrawMany")).toBe(true));
    const call = reco.calls.find((c) => c.name === "withdrawMany")!;
    expect([...(call.args[0] as string[])].sort()).toEqual(["a", "b", "c"]);
    expect(call.args[1]).toMatchObject({ reasonCode: "not_fit" });
  });

  it("one row per card with its code, product, family, source, queue, versions, plan code, status", async () => {
    open();
    const row = await screen.findByTestId("ops-row-JC-2611-0007");
    await waitFor(() => expect(row).toHaveTextContent("Găng tay cao su A"));
    const cells = within(row).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[1]).toBe("JC-2611-0007");
    expect(cells[3]).toBe("Voucher");
    expect(cells[4]).toBe("Juli");
    expect(cells[5]).toBe("#1");
    expect(cells[6]).toBe("2 (V1 mặc định)");
    expect(cells[7]).toBe("—");
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Chọn", "Mã thẻ", "Sản phẩm · thay đổi", "Họ", "Nguồn", "Hàng đợi", "Phiên bản", "Mã kế hoạch", "Trạng thái", "Tạo lúc", "Thao tác"]);
    expect(within(screen.getByTestId("ops-row-JC-2611-0015")).getByText("Thủ công")).toBeInTheDocument();
    expect(screen.getByTestId("ops-row-JC-2611-0003")).toHaveTextContent("Nháp, chưa có mã");
    expect(screen.getByTestId("ops-row-JC-2610-0031")).toHaveTextContent("KH-2610-007");
    expect(within(screen.getByTestId("ops-row-JC-2611-0007")).getByRole("link", { name: "JC-2611-0007" })).toHaveAttribute("href", "/ops/shops/s1/shopee/de-xuat?the=a");
  });

  it("has the status filters and a code search, and no export button", async () => {
    open();
    await screen.findByTestId("ops-row-JC-2611-0007");
    for (const name of ["Tất cả", "Chờ duyệt", "Trong kế hoạch", "Đang đo", "Đã đo xong", "Đã bỏ qua"]) expect(screen.getByRole("button", { name })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Trong kế hoạch" }));
    expect(screen.getAllByTestId(/^ops-row-/)).toHaveLength(1);
    expect(screen.getByTestId("ops-row-JC-2611-0003")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Đã bỏ qua" }));
    expect(screen.getByTestId("ops-row-JC-2610-0008")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Tất cả" }));
    fireEvent.change(screen.getByPlaceholderText("JC-2611-0007"), { target: { value: "2611-0015" } });
    expect(screen.getAllByTestId(/^ops-row-/)).toHaveLength(1);
    fireEvent.change(screen.getByPlaceholderText("JC-2611-0007"), { target: { value: "JC-9999" } });
    expect(screen.getByTestId("ops-empty")).toHaveTextContent("Không có thẻ khớp mã hoặc trạng thái này.");
    expect(screen.queryByRole("button", { name: /Excel|Export|Xuất file/i })).toBeNull();
    expect(screen.getByText(/Mã thẻ không bao giờ dùng lại trong cùng shop/)).toBeInTheDocument();
  });

  it("'+ Tạo phương án thủ công' opens the builder", async () => {
    open();
    expect(await screen.findByTestId("ops-builder-link")).toHaveAttribute("href", "/ops/shops/s1/shopee/de-xuat?tu-tao=1&from=product");
    expect(screen.getByRole("heading", { name: "Danh sách đề xuất" })).toBeInTheDocument();
  });

  it("a whole code is looked up by code: versions, chosen version, inputs and history", async () => {
    const byCode: CardByCode = {
      code: "JC-2611-0007",
      id: "a",
      status: "approved",
      family: "voucher",
      change_kind: "min_spend_voucher",
      title: "Voucher cho đơn từ 299.000đ",
      product_id: "GT-A",
      product_queue: 1,
      created_at: "2026-11-04T00:10:00",
      sent_at: null,
      supersedes_code: "JC-2610-0002",
      versions: [
        { version: 1, code: "JC-2611-0007-V1", label: "Mặc định", status: "ok", ranked: true },
        { version: 2, code: "JC-2611-0007-V2", label: "Hai", status: "floor_breach", ranked: false },
      ],
      chosen_version: 2,
      chosen_version_code: "JC-2611-0007-V2",
      inputs: { default: { value: 15000 }, chosen: { value: 20000 }, approved: { value: 20000 } },
      change: { before: { value: 10000 }, after: { value: 20000 } },
      status_history: [{ event: "proposed", at: "2026-11-04T00:10:00" }, { event: "accepted", at: "2026-11-04T03:00:00", actor: "seller" }],
      verification: { state: "pending" },
    };
    const reco = open(fakeReco({ list, byCode }));
    await screen.findByTestId("ops-row-JC-2611-0007");
    fireEvent.change(screen.getByPlaceholderText("JC-2611-0007"), { target: { value: "jc-2611-0007" } });
    const lookup = await screen.findByTestId("ops-lookup");
    expect(reco.calls.find((c) => c.name === "byCode")!.args).toEqual(["JC-2611-0007"]);
    expect(lookup).toHaveTextContent("Tra thẻ theo mã · JC-2611-0007");
    expect(lookup).toHaveTextContent("thay thẻ JC-2610-0002");
    expect(lookup).toHaveTextContent("JC-2611-0007-V2 · Hai · Chạm giá sàn · đã chọn");
    expect(screen.getByTestId("ops-lookup-inputs")).toHaveTextContent('mặc định {"value":15000} · đã chọn {"value":20000} · đã duyệt {"value":20000}');
    expect(lookup).toHaveTextContent("accepted · seller");
  });

  it("an unknown code is said", async () => {
    open(fakeReco({ list }, { byCode: new ShopeeApiError(404, "reco_card_not_found", "reco_card_not_found") }));
    await screen.findByTestId("ops-row-JC-2611-0007");
    fireEvent.change(screen.getByPlaceholderText("JC-2611-0007"), { target: { value: "JC-2611-0999" } });
    expect(await screen.findByTestId("ops-lookup-error")).toHaveTextContent("Không tìm thấy thẻ JC-2611-0999");
  });

  it("keeps the staff bar (generate, publish, re-run)", async () => {
    open();
    expect(await screen.findByTestId("sd-staffbar")).toBeInTheDocument();
  });
});
