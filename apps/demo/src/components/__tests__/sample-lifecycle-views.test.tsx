import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resolveTab } from "../../lib/quyet-dinh/copy";
import { SAMPLE_PROPOSAL_VALIDITY_MS, createSampleQdClients, type SampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import { SAMPLE_MAIN_CARD, SAMPLE_MANUAL_CARD } from "../../lib/quyet-dinh/sample-data";
import { sampleReport } from "../../lib/phan-tich/sample-data";
import type { QueryState } from "../../lib/phan-tich/model";
import { resetReviewerSample, reviewerSampleClients } from "../../lib/reviewer/sample-store";
import { PhanTichView } from "../phan-tich/phan-tich-view";
import { loadSampleDecisions, loadSampleRanking } from "../phan-tich/sample-phan-tich";
import { resolveMeasureTab, type QdQuery } from "../quyet-dinh/quyet-dinh-view";
import { SampleQuyetDinh } from "../quyet-dinh/sample-quyet-dinh";

/**
 * P37 (D47.2): the sample screens follow the store's card lifecycle — a run
 * that fails puts its card back to "Chờ duyệt", 7 untouched days read "Hết
 * hạn", a declined consent reads "Đã từ chối" — and Phân tích reads the same
 * tab-wide store Quyết định changes. Still no request at all.
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const A = { token: "sample", shopId: "sample-shop" };

function queryOf(href: string): QdQuery {
  const params = new URLSearchParams(href.split("?")[1] ?? "");
  return {
    tab: resolveTab(params.get("tab")),
    run: params.get("run"),
    rulesOpen: params.get("quy-tac") === "1",
    measureTab: resolveMeasureTab(params.get("moc")),
  };
}

function Harness({ clients, initial = "/decisions" }: { clients?: SampleQdClients; initial?: string }) {
  const [href, setHref] = useState(initial);
  return <SampleQuyetDinh clients={clients} onNavigate={setHref} query={queryOf(href)} />;
}

const cardOf = (name: string) => screen.getAllByTestId("recommendation-card").find((card) => card.textContent?.includes(name))!;
const statusOf = (name: string) => within(cardOf(name)).getByTestId("card-status");

let fetchSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("no network in the sample"));
  resetReviewerSample({ stepMs: 0 });
});
afterEach(() => {
  expect(fetchSpy).not.toHaveBeenCalled();
  fetchSpy.mockRestore();
});

describe("Quyết định follows the sample lifecycle", () => {
  it("Duyệt → Đang thực hiện; the run fails → back to Chờ duyệt with Duyệt", async () => {
    const clients = createSampleQdClients({ stepMs: 0 });
    render(<Harness clients={clients} />);
    await waitFor(() => expect(cardOf(SAMPLE_MAIN_CARD.name)).toBeDefined());
    await userEvent.click(within(cardOf(SAMPLE_MAIN_CARD.name)).getByRole("button", { name: "Duyệt" }));
    await waitFor(() => expect(statusOf(SAMPLE_MAIN_CARD.name)).toHaveTextContent("Đang thực hiện"));
    const run = clients.snapshotRuns().find((entry) => entry.product_name === SAMPLE_MAIN_CARD.name)!;
    act(() => {
      clients.failRun(run.id);
    });
    await waitFor(() => expect(statusOf(SAMPLE_MAIN_CARD.name)).toHaveTextContent("Chờ duyệt"));
    expect(within(cardOf(SAMPLE_MAIN_CARD.name)).getByRole("button", { name: "Duyệt" })).toBeInTheDocument();
  });

  it("7 days untouched → Hết hạn, with no Duyệt", async () => {
    const clients = createSampleQdClients({ stepMs: 0 });
    render(<Harness clients={clients} />);
    await waitFor(() => expect(statusOf(SAMPLE_MAIN_CARD.name)).toHaveTextContent("Chờ duyệt"));
    act(() => {
      clients.advanceTime(SAMPLE_PROPOSAL_VALIDITY_MS);
    });
    await waitFor(() => expect(statusOf(SAMPLE_MAIN_CARD.name)).toHaveTextContent("Hết hạn"));
    expect(within(cardOf(SAMPLE_MAIN_CARD.name)).queryByRole("button", { name: "Duyệt" })).toBeNull();
  });

  it("Không thực hiện at the consent → the card reads Đã từ chối on Đề xuất", async () => {
    const clients = createSampleQdClients({ stepMs: 0 });
    render(<Harness clients={clients} />);
    await waitFor(() => expect(cardOf(SAMPLE_MAIN_CARD.name)).toBeDefined());
    await userEvent.click(within(cardOf(SAMPLE_MAIN_CARD.name)).getByRole("button", { name: "Duyệt" }));
    await userEvent.click(await screen.findByRole("link", { name: "Xem tiến độ ›" }));
    await screen.findByTestId("consent-block");
    await userEvent.click(screen.getByRole("button", { name: "Không thực hiện" }));
    const dialog = screen.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    await userEvent.click(within(dialog).getByRole("radio", { name: "Văn phong chưa phù hợp" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Đồng ý" }));
    await screen.findByTestId("reason-done");
    expect(clients.cardStatus(SAMPLE_MAIN_CARD.id)).toBe("rejected");
    await userEvent.click(screen.getByRole("tab", { name: "Đề xuất" }));
    await waitFor(() => expect(statusOf(SAMPLE_MAIN_CARD.name)).toHaveTextContent("Đã từ chối"));
  });

  it("Seller Center: after Tôi đã áp dụng the card stays Đang thực hiện (no recorded write)", async () => {
    const clients = createSampleQdClients({ stepMs: 0 });
    render(<Harness clients={clients} />);
    await waitFor(() => expect(cardOf(SAMPLE_MANUAL_CARD.name)).toBeDefined());
    await userEvent.click(within(cardOf(SAMPLE_MANUAL_CARD.name)).getByRole("button", { name: "Duyệt" }));
    await userEvent.click(await screen.findByRole("link", { name: "Xem tiến độ ›" }));
    const guide = await screen.findByTestId("seller-guide");
    for (const box of within(guide).getAllByRole("checkbox")) await userEvent.click(box);
    await userEvent.click(within(guide).getByRole("button", { name: "Tôi đã áp dụng" }));
    await waitFor(() => expect(screen.getByTestId("run-timeline")).toHaveTextContent("Tìm thấy: Giảm giá sản phẩm"));
    await userEvent.click(screen.getByRole("tab", { name: "Đề xuất" }));
    await waitFor(() => expect(statusOf(SAMPLE_MANUAL_CARD.name)).toHaveTextContent("Đang thực hiện"));
    expect(clients.cardStatus(SAMPLE_MANUAL_CARD.id)).toBe("running");
  });
});

describe("one sample store for the tab", () => {
  it("the signed-out Quyết định writes to the store Phân tích reads", async () => {
    render(<Harness />);
    await waitFor(() => expect(cardOf(SAMPLE_MAIN_CARD.name)).toBeDefined());
    await userEvent.click(within(cardOf(SAMPLE_MAIN_CARD.name)).getByRole("button", { name: "Duyệt" }));
    await waitFor(() => expect(reviewerSampleClients().cardStatus(SAMPLE_MAIN_CARD.id)).toBe("running"));
    expect((await loadSampleDecisions()).map((item) => item.id)).not.toContain(SAMPLE_MAIN_CARD.id);
  });

  it("Phân tích's Xem N đề xuất counts only the store's cards still on the desk", async () => {
    const query: QueryState = { tab: null, stream: null, metric: null, huong: null, row: null };
    const view = () => (
      <PhanTichView loadDecisions={loadSampleDecisions} loadRanking={loadSampleRanking} query={query} report={sampleReport()} sample />
    );
    const first = render(view());
    expect(await screen.findByRole("link", { name: "Xem 3 đề xuất ›" })).toBeInTheDocument();
    first.unmount();
    await reviewerSampleClients().reject(A, SAMPLE_MAIN_CARD.id, { reason_code: "other" });
    render(view());
    expect(await screen.findByRole("link", { name: "Xem 2 đề xuất ›" })).toBeInTheDocument();
  });
});
