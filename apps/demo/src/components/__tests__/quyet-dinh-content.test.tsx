import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { cardView } from "../../lib/quyet-dinh/card-model";
import { resolveTab } from "../../lib/quyet-dinh/copy";
import { CONTENT_GROUP_KEY, contentGroupTitle, groupDecisions, isContentCard } from "../../lib/quyet-dinh/grouping";
import type { ContentRunDetail, QdRun } from "../../lib/quyet-dinh/p10-types";
import { createSampleQdClients, type SampleQdClients } from "../../lib/quyet-dinh/sample-clients";
import {
  SAMPLE_CONTENT_LIVE,
  SAMPLE_CONTENT_VIDEO,
  SAMPLE_MAIN_CARD,
  sampleContentDecision,
  sampleContentDetail,
  sampleDecision,
} from "../../lib/quyet-dinh/sample-data";
import { buildRunTimeline } from "../../lib/quyet-dinh/timeline";
import { ContentRunPanel, contentChip, contentPhase, contentSteps, copyText } from "../quyet-dinh/content-run-panel";
import { resolveMeasureTab, type QdQuery } from "../quyet-dinh/quyet-dinh-view";
import { SampleQuyetDinh } from "../quyet-dinh/sample-quyet-dinh";

/**
 * P14-E "Juli soạn · bạn làm" (`fasttrack/contracts/p14-content-cards.md`,
 * `ContentCards.dc.html`, `ContentRun.dc.html`): the content card, its group,
 * the content run panel, and the signed-out sample flow (no network, no model).
 */

vi.mock("next/navigation", () => ({
  usePathname: () => "/decisions",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

const NOW = Date.parse("2026-10-10T02:00:00Z");

describe("content card model", () => {
  it("reads the contract's content block into the card view", () => {
    const view = cardView(sampleContentDecision(SAMPLE_CONTENT_VIDEO, NOW));
    expect(view.executor).toBe("juli_drafts");
    expect(view.sku).toBe("MN-015");
    expect(view.meta).toMatch(/^Tối ưu nội dung · Video · Cập nhật /);
    expect(view.kpiLabel).toBe("CTR - Video của người bán");
    expect(view.kpiCurrent).toBe("1,9 %");
    expect(view.kpiTarget).toBe("3,2 %");
    expect(view.gmvPerMonth).toBe("+1,7 tr ₫/tháng");
    expect(view.content).toEqual({
      kind: "video",
      actionLabel: "Kịch bản video mới",
      chip: "Juli soạn · bạn làm",
      willDraft:
        "Hook 3 giây và 2 phương án mở đầu\nKịch bản 25–35 giây theo cảnh, sản phẩm xuất hiện trước giây 3\nLời kêu gọi bấm giỏ, gợi ý hashtag và nhạc đang lên",
      measure: "CTR trên các video mới gắn MN-015 trong 7 và 14 ngày, so với video cũ.",
    });
    expect(cardView(sampleDecision(SAMPLE_MAIN_CARD, NOW)).content).toBeNull();
  });

  it("groups content cards on their own, after the product groups", () => {
    const items = [
      sampleDecision(SAMPLE_MAIN_CARD, NOW),
      sampleContentDecision(SAMPLE_CONTENT_VIDEO, NOW),
      sampleContentDecision(SAMPLE_CONTENT_LIVE, NOW),
    ];
    expect(items.map(isContentCard)).toEqual([false, true, true]);
    const groups = groupDecisions(items);
    const content = groups.find((group) => group.key === CONTENT_GROUP_KEY)!;
    expect(content.title).toBe("2 thẻ nội dung: Juli soạn, bạn quay hoặc LIVE");
    expect(contentGroupTitle(1)).toBe("1 thẻ nội dung: Juli soạn, bạn quay hoặc LIVE");
    expect(content.content).toBe(true);
    expect(content.cards.map((card) => card.id)).toEqual([SAMPLE_CONTENT_VIDEO.id, SAMPLE_CONTENT_LIVE.id]);
    expect(content.gmvPerMonth).toBe(2_600_000);
    expect(groups[0].content).toBeUndefined();
  });
});

// -- the run panel ------------------------------------------------------------------------

function run(over: Partial<QdRun> = {}): QdRun {
  return {
    id: "run-c",
    status: "waiting_external",
    stop_reason: null,
    product_name: "Mặt nạ đất sét 100g",
    created_at: "2026-10-10T02:00:00Z",
    completed_at: null,
    running_seconds_elapsed: 3,
    latest_narration: null,
    decision_summary: null,
    awaiting: "content_choice",
    ...over,
  } as QdRun;
}

const AT = ["2026-10-10T02:01:00Z", "2026-10-10T02:01:20Z", "2026-10-10T02:02:00Z"];

function detail(over: Partial<ContentRunDetail> = {}, stage: ContentRunDetail["stage"] = "choice", version: 1 | 2 = 1): ContentRunDetail {
  return {
    ...sampleContentDetail(SAMPLE_CONTENT_VIDEO, {
      stage,
      version,
      chosenVersion: null,
      edited: false,
      stepAt: [AT[0], AT[1], AT[2], null, null, null],
    }),
    ...over,
  };
}

function renderPanel(d: ContentRunDetail, r: QdRun = run(), handlers: Partial<Parameters<typeof ContentRunPanel>[0]> = {}) {
  const timeline = buildRunTimeline([], { kind: "content" });
  const phase = contentPhase(r, d, timeline, false);
  const props = {
    run: r,
    card: null,
    detail: d,
    timeline,
    phase,
    chip: contentChip(phase, r.stop_reason),
    reconnecting: false,
    measureHref: "/decisions?tab=do-luong",
    onOpenMeasure: vi.fn(),
    onUse: vi.fn().mockResolvedValue(undefined),
    onRedraft: vi.fn().mockResolvedValue(undefined),
    onPublished: vi.fn().mockResolvedValue(undefined),
    onDecline: vi.fn().mockResolvedValue(undefined),
    ...handlers,
  };
  render(<ContentRunPanel {...props} />);
  return props;
}

describe("ContentRunPanel (ContentRun.dc.html)", () => {
  it("choice: six steps, the script and its checks; Dùng sends the version and only the edited blocks", async () => {
    const props = renderPanel(detail());
    expect(screen.getByTestId("run-chip")).toHaveTextContent("Đang chờ bạn");
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("MN-015 · Mặt nạ đất sét 100g · kịch bản video");
    expect(screen.getByTestId("run-detail")).toHaveTextContent("Juli soạn · bạn làm");
    const steps = within(screen.getByTestId("content-steps")).getAllByRole("listitem");
    expect(steps).toHaveLength(6);
    expect(steps.map((step) => step.getAttribute("data-state"))).toEqual(["done", "done", "done", "current", "todo", "todo"]);
    expect(steps[0]).toHaveTextContent("✓Đọc số liệu video và sản phẩm3 video gắn MN-015 · CTR 1,9 % · giỏ hàng xuất hiện giây 20");
    expect(steps[0]).toHaveTextContent("09:01");
    expect(steps[3]).toHaveTextContent("4Bạn xem, sửa và chọnĐang chờ bạn");
    expect(steps[4]).not.toHaveTextContent("Đang chờ bạn");

    const script = screen.getByTestId("content-script");
    expect(script).toHaveTextContent("Kịch bản video 25–35 giây");
    expect(script).toHaveTextContent("Bản 1 · bạn sửa trực tiếp được");
    expect(script).toHaveTextContent("Đã kiểm tra: không có từ cấm, giữ từ bảo vệ của bạn, đúng thông tin sản phẩm, trong trần giảm giá.");
    const hook = screen.getByRole("textbox", { name: "Hook (0–3 giây)" });
    expect(hook).toHaveValue('"Lỗ chân lông to sau 1 tuần dùng cái này…" · cận mặt trước khi đắp');
    await userEvent.clear(hook);
    await userEvent.type(hook, "Hook mới");
    await userEvent.click(screen.getByRole("button", { name: "Dùng kịch bản này" }));
    expect(props.onUse).toHaveBeenCalledWith(1, { hook: "Hook mới" });
  });

  it("Dùng without edits sends no blocks; Soạn lại is disabled after bản 2", async () => {
    const props = renderPanel(detail({}, "choice", 2));
    expect(screen.getByTestId("content-script")).toHaveTextContent("Bản 2 · bạn sửa trực tiếp được");
    expect(screen.getByRole("button", { name: "Soạn lại" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Dùng kịch bản này" }));
    expect(props.onUse).toHaveBeenCalledWith(2, null);
  });

  it("Soạn lại asks for bản 2; Sao chép copies the plain text", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const d = detail();
    const props = renderPanel(d);
    await userEvent.click(screen.getByRole("button", { name: "Soạn lại" }));
    expect(props.onRedraft).toHaveBeenCalledTimes(1);
    await userEvent.click(screen.getByRole("button", { name: "Sao chép" }));
    expect(writeText).toHaveBeenCalledWith(d.script!.plain_text);
    expect(await screen.findByRole("button", { name: "Đã sao chép" })).toBeInTheDocument();
    expect(copyText(d.script!, { hook: "X" })).toContain("Hook (0–3 giây)\nX");
  });

  it("publish: the blue wait box; the done button reports the video", async () => {
    const d = detail({ wait: sampleContentDetail(SAMPLE_CONTENT_VIDEO, { stage: "publish", version: 1, chosenVersion: 1, edited: false, stepAt: [AT[0], AT[1], AT[2], AT[2], null, null] }).wait }, "publish");
    const props = renderPanel(d, run({ awaiting: "content_publish" }));
    const wait = screen.getByTestId("content-wait");
    expect(wait).toHaveTextContent("Đang chờ bạn đăng video");
    expect(wait).toHaveTextContent("Hoặc để Juli tự nhận ra khi có video mới gắn MN-015.");
    expect(screen.queryByTestId("content-script")).toBeNull();
    await userEvent.click(within(wait).getByRole("button", { name: "Tôi đã đăng video" }));
    expect(props.onPublished).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /Hoàn tác/ })).toBeNull();
  });

  it("measuring: the green box links to Đo lường; the chip says Đang đo", () => {
    const d = sampleContentDetail(SAMPLE_CONTENT_VIDEO, {
      stage: "measuring",
      version: 1,
      chosenVersion: 1,
      edited: false,
      stepAt: [AT[0], AT[1], AT[2], AT[2], AT[2], null],
    });
    renderPanel(d, run({ status: "completed", stop_reason: "final_response", awaiting: null }));
    expect(screen.getByTestId("run-chip")).toHaveTextContent("Đang đo");
    const box = screen.getByTestId("content-measuring");
    expect(box).toHaveTextContent("Đang đo kết quả");
    expect(box).toHaveTextContent('Video mới "7 ngày mặt nạ đất sét" đăng 12/10.');
    expect(within(box).getByRole("link", { name: "Xem ở Đo lường ›" })).toHaveAttribute("href", "/decisions?tab=do-luong");
    expect(contentSteps(d, "measuring").map((step) => step.state)).toEqual(["done", "done", "done", "done", "done", "current"]);
  });

  it("Không thực hiện opens the reason dialog and ends on the completion message", async () => {
    const onDecline = vi.fn().mockResolvedValue(undefined);
    const props = renderPanel(detail(), run(), { onDecline });
    await userEvent.click(screen.getByRole("button", { name: "Không thực hiện" }));
    const dialog = screen.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    await userEvent.click(within(dialog).getByRole("radio", { name: "Văn phong chưa phù hợp" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Đồng ý" }));
    expect(props.onDecline).toHaveBeenCalledWith(expect.objectContaining({ reason_code: "tone" }));
  });
});

// -- the signed-out sample ------------------------------------------------------------------

function queryOf(href: string): QdQuery {
  const params = new URLSearchParams(href.split("?")[1] ?? "");
  return {
    tab: resolveTab(params.get("tab")),
    run: params.get("run"),
    rulesOpen: params.get("quy-tac") === "1",
    measureTab: resolveMeasureTab(params.get("moc")),
  };
}

function Harness({ clients }: { clients: SampleQdClients }) {
  const [href, setHref] = useState("/decisions");
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

const contentGroup = () =>
  screen.getAllByTestId("decision-group").find((group) => group.getAttribute("data-group-key") === CONTENT_GROUP_KEY)!;
const contentCard = (name: string) =>
  within(contentGroup())
    .getAllByTestId("recommendation-card")
    .find((card) => card.textContent?.includes(name))!;

describe("signed-out sample — content cards", () => {
  it("shows both content cards with the drafts chip, no batch button; Xem thêm shows Juli sẽ soạn", async () => {
    render(<Harness clients={createSampleQdClients({ stepMs: 0 })} />);
    await waitFor(() => expect(contentGroup()).toBeDefined());
    const group = contentGroup();
    expect(group).toHaveTextContent("2 thẻ nội dung: Juli soạn, bạn quay hoặc LIVE");
    expect(within(group).queryByRole("button", { name: /^Duyệt/ })).toBeNull();
    const video = contentCard("Mặt nạ đất sét 100g");
    expect(video).toHaveTextContent("SKU · MN-015");
    expect(video).toHaveTextContent("Tối ưu nội dung · Video");
    expect(video).toHaveTextContent("CTR - Video của người bán");
    expect(within(video).getByTestId("drafts-chip")).toHaveTextContent("Juli soạn · bạn làm");
    expect(within(contentCard("Son môi số 12")).getByTestId("drafts-chip")).toHaveTextContent("Juli soạn · bạn làm");
    await userEvent.click(within(video).getByRole("button", { name: "Xem thêm" }));
    expect(video).toHaveTextContent("Juli sẽ soạn");
    expect(video).toHaveTextContent("Đo kết quả");
    expect(within(video).getByRole("button", { name: "Thu gọn" })).toBeInTheDocument();
  });

  it("video: Phê duyệt → bản 1 → Soạn lại → bản 2 → Dùng → wait → Tôi đã đăng → Đang đo", async () => {
    const clients = createSampleQdClients({ stepMs: 0 });
    render(<Harness clients={clients} />);
    await waitFor(() => expect(contentGroup()).toBeDefined());
    const video = contentCard("Mặt nạ đất sét 100g");
    await userEvent.click(within(video).getByRole("button", { name: "Phê duyệt" }));
    await userEvent.click(await within(video).findByRole("link", { name: "Xem tiến độ ›" }));
    const script = await screen.findByTestId("content-script");
    expect(script).toHaveTextContent("Bản 1 · bạn sửa trực tiếp được");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Juli đã soạn kịch bản video, bạn quay và đăng");
    await userEvent.click(within(script).getByRole("button", { name: "Soạn lại" }));
    await waitFor(() => expect(screen.getByTestId("content-script")).toHaveTextContent("Bản 2 · bạn sửa trực tiếp được"));
    expect(screen.getByRole("textbox", { name: "Hook (0–3 giây)" })).toHaveValue('"Mình thử mặt nạ 69k này 7 ngày liền" · cầm sản phẩm lên khung hình');
    await userEvent.click(screen.getByRole("button", { name: "Dùng kịch bản này" }));
    const wait = await screen.findByTestId("content-wait");
    expect(wait).toHaveTextContent("Đang chờ bạn đăng video");
    await userEvent.click(within(wait).getByRole("button", { name: "Tôi đã đăng video" }));
    expect(await screen.findByTestId("content-measuring")).toHaveTextContent("Đang đo kết quả");
    const runItem = clients.snapshotRuns().find((item) => item.decision_id === SAMPLE_CONTENT_VIDEO.id)!;
    expect(runItem.status).toBe("completed");
    const changes = await clients.fetchChanges({ token: "", shopId: "" }, runItem.id);
    expect(changes.revert.available).toBe(false);
    const measurement = await clients.fetchMeasurement({ token: "", shopId: "" }, runItem.id);
    expect(measurement?.target.label).toBe("CTR - Video của người bán");
  });

  it("LIVE: Không thực hiện at the script ends the run with the picked reason", async () => {
    const clients = createSampleQdClients({ stepMs: 0 });
    render(<Harness clients={clients} />);
    await waitFor(() => expect(contentGroup()).toBeDefined());
    const live = contentCard("Son môi số 12");
    await userEvent.click(within(live).getByRole("button", { name: "Phê duyệt" }));
    await userEvent.click(await within(live).findByRole("link", { name: "Xem tiến độ ›" }));
    const script = await screen.findByTestId("content-script");
    expect(script).toHaveTextContent("Kịch bản host cho SM-012 + thứ tự giỏ");
    await userEvent.click(within(script).getByRole("button", { name: "Không thực hiện" }));
    const dialog = screen.getByRole("dialog", { name: "Không thực hiện thay đổi này?" });
    await userEvent.click(within(dialog).getByRole("radio", { name: "Văn phong chưa phù hợp" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Đồng ý" }));
    expect(await screen.findByTestId("reason-done")).toHaveTextContent("Hoàn thành · không thực hiện thay đổi");
    expect(screen.getByTestId("run-chip")).toHaveTextContent("Không thay đổi");
    const runItem = clients.snapshotRuns().find((item) => item.decision_id === SAMPLE_CONTENT_LIVE.id)!;
    expect(runItem.stop_reason).toBe("cancelled_by_seller");
  });
});
