import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createSampleQdClients, type SampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import {
  SAMPLE_APPLIED_CARD,
  SAMPLE_CARDS,
  SAMPLE_MAIN_CARD,
  SAMPLE_MANUAL_CARD,
  SAMPLE_PHOTO_CARD,
  executorOf,
} from "../../lib/quyet-dinh/sample-data";
import { cardView } from "../../lib/quyet-dinh/card-model";
import { resolveTab } from "../../lib/quyet-dinh/copy";
import { resolveMeasureTab, type QdQuery } from "../quyet-dinh/quyet-dinh-view";
import { SampleQuyetDinh } from "../quyet-dinh/sample-quyet-dinh";

/**
 * P11: the signed-out Quyết định is the P10 design ("Bản minh họa") over
 * in-memory sample clients — same card, Đang thực hiện timeline and Đo
 * lường as the signed-in door; every action changes local state only and no
 * request is issued (ADR-094 d.1).
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

function queryOf(href: string): QdQuery {
  const params = new URLSearchParams(href.split("?")[1] ?? "");
  return {
    tab: resolveTab(params.get("tab")),
    run: params.get("run"),
    rulesOpen: params.get("quy-tac") === "1",
    measureTab: resolveMeasureTab(params.get("moc")),
  };
}

function Harness({ clients, initial }: { clients: SampleQdClients; initial: string }) {
  const [href, setHref] = useState(initial);
  return <SampleQuyetDinh clients={clients} onNavigate={setHref} query={queryOf(href)} />;
}

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network in the sample"));
});
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

function renderSample(initial = "/decisions") {
  const clients = createSampleQdClients({ stepMs: 0 });
  render(<Harness clients={clients} initial={initial} />);
  return clients;
}

const cardOf = (name: string) => screen.getAllByTestId("recommendation-card").find((card) => card.textContent?.includes(name))!;

describe("sample fixtures — P10 contract shapes", () => {
  it("cover every executor type and read through the real card model", () => {
    expect(new Set(SAMPLE_CARDS.map(executorOf))).toEqual(new Set(["juli", "juli_with_photo", "seller_center"]));
    return createSampleQdClients({ stepMs: 0 })
      .fetchDecisions({ token: "x", shopId: "y" })
      .then((items) => {
        const main = cardView(items.find((item) => item.id === SAMPLE_MAIN_CARD.id)! as never);
        expect(main.sku).toBe("SM-012");
        expect(main.title).toBe("Son môi số 12");
        expect(main.executor).toBe("juli");
      });
  });
});

describe("signed-out Quyết định (Bản minh họa)", () => {
  it("Đề xuất shows the P10 cards with the sample notice; Xem thêm expands in place", async () => {
    renderSample();
    await waitFor(() => expect(screen.getAllByTestId("recommendation-card").length).toBeGreaterThanOrEqual(4));
    expect(screen.getByTestId("mock-data-notice")).toHaveTextContent("Dữ liệu mẫu · Cửa hàng Mẫu Hoa Mai là shop minh họa");
    const main = cardOf("Son môi số 12");
    expect(main).toHaveTextContent("SKU · SM-012");
    expect(main).toHaveTextContent("5,4 %");
    expect(main).toHaveTextContent("5,9 %");
    expect(main).toHaveTextContent("+2,1 tr ₫/tháng");
    expect(within(main).getByTestId("card-status")).toHaveTextContent("Chờ duyệt");
    expect(cardOf(SAMPLE_PHOTO_CARD.name)).toHaveTextContent(`SKU · ${SAMPLE_PHOTO_CARD.sku}`);
    expect(cardOf(SAMPLE_MANUAL_CARD.name)).toHaveTextContent(`SKU · ${SAMPLE_MANUAL_CARD.sku}`);
    expect(within(cardOf(SAMPLE_APPLIED_CARD.name)).getByTestId("card-status")).toHaveTextContent("Đã áp dụng");
    await userEvent.click(within(main).getByRole("button", { name: /Xem thêm/ }));
    expect(main).toHaveTextContent("Lý do đầy đủ");
    expect(main).toHaveTextContent("TikTok báo mã chẩn đoán: “Mô tả quá ngắn”.");
  });

  it("Phê duyệt creates a local run; Từ chối needs one reason and only changes local state", async () => {
    const clients = renderSample();
    await waitFor(() => expect(cardOf("Son môi số 12")).toBeDefined());
    const main = cardOf("Son môi số 12");
    await userEvent.click(within(main).getByRole("button", { name: "Phê duyệt" }));
    await waitFor(() => expect(within(main).getByTestId("card-status")).toHaveTextContent("Đang thực hiện"));
    expect(within(main).getByRole("link", { name: "Xem tiến độ ›" })).toBeInTheDocument();
    expect(clients.snapshotRuns().find((run) => run.product_name === "Son môi số 12")?.status).toBe("waiting_approval");

    const photo = cardOf(SAMPLE_PHOTO_CARD.name);
    await userEvent.click(within(photo).getByRole("button", { name: "Từ chối" }));
    const dialog = screen.getByRole("dialog", { name: "Từ chối thẻ này?" });
    expect(within(dialog).getByRole("button", { name: "Từ chối thẻ" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("radio", { name: "Lý do hoặc số liệu chưa thuyết phục" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Từ chối thẻ" }));
    await waitFor(() => expect(within(photo).getByTestId("card-status")).toHaveTextContent("Đã từ chối"));
    // a0382006: the completion message names the picked reason and what Juli learns from it.
    const done = within(photo).getByTestId("reason-done");
    expect(done).toHaveTextContent("Hoàn thành · đã từ chối thẻ");
    expect(done).toHaveTextContent("Lý do bạn chọnLý do hoặc số liệu chưa thuyết phục");
    expect(done).toHaveTextContent("Lý do giúp Juli đưa ra đề xuất tốt hơn: Juli chỉ đề xuất khi số liệu đủ rõ và giải thích kỹ hơn.");
  });

  it("Không thực hiện and Hoàn tác end on the completion message with the picked reason", async () => {
    renderSample();
    await waitFor(() => expect(cardOf("Son môi số 12")).toBeDefined());
    await userEvent.click(within(cardOf("Son môi số 12")).getByRole("button", { name: "Phê duyệt" }));
    await userEvent.click(await screen.findByRole("link", { name: "Xem tiến độ ›" }));
    await screen.findByTestId("consent-block");
    await userEvent.click(screen.getByRole("button", { name: "Không thực hiện" }));
    const skip = screen.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    expect(skip).toHaveTextContent("Khi đồng ý, gợi ý sẽ không quay lại");
    expect(skip).not.toHaveTextContent("Lý do giúp Juli");
    await userEvent.click(within(skip).getByRole("radio", { name: "Văn phong chưa phù hợp" }));
    await userEvent.click(within(skip).getByRole("button", { name: "Đồng ý" }));
    const declined = await screen.findByTestId("reason-done");
    expect(declined).toHaveTextContent("Hoàn thành · không thực hiện thay đổi");
    expect(declined).toHaveTextContent("Juli soạn theo văn phong gần với nội dung hiện tại của bạn hơn.");
  });

  it("Hoàn tác: no hint in the dialog; the finished revert shows the reason box", async () => {
    renderSample("/decisions?tab=dang-thuc-hien&run=sample-run-tn-021");
    await userEvent.click(await screen.findByRole("button", { name: "Hoàn tác" }));
    const dialog = screen.getByRole("dialog", { name: "Hoàn tác thay đổi này?" });
    expect(dialog).not.toHaveTextContent("Lý do giúp Juli");
    await userEvent.click(within(dialog).getByRole("radio", { name: "Khách phản hồi không tốt" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Bắt đầu hoàn tác" }));
    const consent = await screen.findByTestId("consent-block");
    await userEvent.click(consent.querySelector(".qv-option") as HTMLElement);
    await userEvent.click(within(consent).getByRole("button", { name: "Xác nhận khôi phục" }));
    const done = await screen.findByTestId("reason-done", {}, { timeout: 3000 });
    expect(done).toHaveTextContent("Hoàn tác hoàn thành · đã khôi phục nội dung cũ");
    expect(done).toHaveTextContent("Lý do bạn chọnKhách phản hồi không tốt");
    expect(done).toHaveTextContent("Lý do giúp Juli đưa ra đề xuất tốt hơn: Juli đọc thêm đánh giá và tin nhắn của khách trước khi soạn.");
    expect(done).toHaveTextContent('được ghi là "Đã hoàn tác"');
  });

  it("Đang thực hiện: the consent → Xác nhận plays the write and TikTok's review to the end", async () => {
    const clients = renderSample();
    await waitFor(() => expect(cardOf("Son môi số 12")).toBeDefined());
    await userEvent.click(within(cardOf("Son môi số 12")).getByRole("button", { name: "Phê duyệt" }));
    await userEvent.click(await screen.findByRole("link", { name: "Xem tiến độ ›" }));
    const consent = await screen.findByTestId("consent-block");
    expect(screen.getByTestId("run-timeline")).toBeInTheDocument();
    await userEvent.click(within(consent).getByRole("button", { name: "✎ Sửa nội dung trước khi áp dụng" }));
    const title = screen.getByLabelText("Tiêu đề (bạn sửa)");
    await userEvent.clear(title);
    await userEvent.type(title, "Son môi lì số 12 — màu đỏ ruby");
    await userEvent.click(screen.getByRole("button", { name: "Lưu bản sửa" }));
    await userEvent.click(within(consent).getByRole("button", { name: "Xác nhận thay đổi này" }));
    await waitFor(() => expect(screen.getByTestId("run-timeline")).toHaveTextContent("Phiên bản mới đã được duyệt"));
    expect(screen.getByTestId("run-timeline")).toHaveTextContent("theo bản bạn sửa");
    const run = clients.snapshotRuns().find((item) => item.product_name === "Son môi số 12")!;
    const changes = await clients.fetchChanges({ token: "", shopId: "" }, run.id);
    expect(changes.changes.find((change) => change.field === "title")?.after).toBe("Son môi lì số 12 — màu đỏ ruby");
  });

  it("cover image: the upload passes the checks locally and reaches the consent", async () => {
    renderSample();
    await waitFor(() => expect(cardOf(SAMPLE_PHOTO_CARD.name)).toBeDefined());
    await userEvent.click(within(cardOf(SAMPLE_PHOTO_CARD.name)).getByRole("button", { name: "Phê duyệt" }));
    await userEvent.click(await screen.findByRole("link", { name: "Xem tiến độ ›" }));
    await screen.findByTestId("photo-request");
    await act(async () => {
      await userEvent.upload(screen.getByTestId("photo-input") as HTMLInputElement, new File(["png"], "a.png", { type: "image/png" }));
    });
    expect(await screen.findByTestId("consent-block")).toBeInTheDocument();
    expect(screen.getByTestId("run-timeline")).toHaveTextContent("1:1 · 1200 × 1200 px · nền trắng · sản phẩm 78 % khung");
  });

  it("Seller Center: the checklist gates Tôi đã áp dụng; Juli then finds the promotion", async () => {
    renderSample();
    await waitFor(() => expect(cardOf(SAMPLE_MANUAL_CARD.name)).toBeDefined());
    await userEvent.click(within(cardOf(SAMPLE_MANUAL_CARD.name)).getByRole("button", { name: "Phê duyệt" }));
    await userEvent.click(await screen.findByRole("link", { name: "Xem tiến độ ›" }));
    const guide = await screen.findByTestId("seller-guide");
    await waitFor(() => expect(guide).toHaveTextContent("Làm theo 4 bước trên Seller Center"));
    const applied = within(guide).getByRole("button", { name: "Tôi đã áp dụng" });
    for (const box of within(guide).getAllByRole("checkbox")) await userEvent.click(box);
    expect(applied).toBeEnabled();
    await userEvent.click(applied);
    await waitFor(() => expect(screen.getByTestId("run-timeline")).toHaveTextContent("Tìm thấy: Giảm giá sản phẩm"));
  });

  it("Đo lường shows the sample's measured run (day 7, within the band)", async () => {
    renderSample("/decisions?tab=do-luong");
    const panel = await screen.findByTestId("measure-panel");
    await waitFor(() => expect(panel).toHaveTextContent(SAMPLE_APPLIED_CARD.name));
    expect(screen.getByRole("tab", { name: "Ngày 7 · kiểm tra" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByTestId("measure-target")).toContainHTML("9.613 – 10.207");
  });
});
