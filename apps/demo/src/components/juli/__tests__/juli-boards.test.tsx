import { readFileSync } from "node:fs";
import { join } from "node:path";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { JuliAgentEvent } from "@juli/contracts";

import * as F from "../../../lib/juli/fixtures";
import { createMockJuliClient } from "../../../lib/juli/mock-client";
import type { ChatMessage } from "../../../lib/juli/use-juli-chat";
import { JuliApiError, type JuliClient } from "../../../lib/juli/client";
import { MessagePair, type AnswerActions } from "../answer";
import { JuliChat } from "../juli-chat";

function actions(over: Partial<AnswerActions> = {}): AnswerActions {
  return {
    platform: "shopee",
    templates: F.TEMPLATES,
    readOnly: false,
    cardStates: {},
    onSendCard: vi.fn(),
    onDismissCard: vi.fn(),
    onChoose: vi.fn(),
    onOther: vi.fn(),
    onTemplate: vi.fn(),
    onMore: vi.fn(),
    onRetry: vi.fn(),
    onAskAgain: vi.fn(),
    ...over,
  };
}
function pair(events: readonly JuliAgentEvent[], over: Partial<ChatMessage> = {}, a: AnswerActions = actions()) {
  const message: ChatMessage = { id: "m1", question: "Câu hỏi mẫu", events, status: "done", reconnecting: false, ...over };
  return { a, ...render(<MessagePair message={message} isLast actions={a} />) };
}

describe("board 2 running (U3)", () => {
  it("shows the restated first line, done steps, one status line and the streamed text", () => {
    pair(F.RUNNING, { status: "running" });
    const text = document.querySelector(".juli-answer")!.textContent!;
    expect(text.indexOf("Đang tìm hiểu: vì sao")).toBeLessThan(text.indexOf("Đang kiểm tra dữ liệu"));
    expect(screen.getByText("Đang kiểm tra dữ liệu")).toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Đang tìm nguyên nhân");
    expect(screen.getByText(/Phần lớn mức giảm nằm ở/)).toBeInTheDocument();
  });
  it("before the restated line only 'Đang tìm hiểu' shows", () => {
    pair([{ type: "status", data: { key: "thinking", text_vi: "Đang tìm hiểu" } }], { status: "running" });
    expect(screen.getByText("Đang tìm hiểu")).toBeInTheDocument();
  });
});

describe("restated line", () => {
  it("is prefixed when the backend text lacks it", () => {
    pair([{ type: "restated", data: { text_vi: "vì sao GMV giảm" } }, { type: "done", data: { stop_reasons: [] } }]);
    expect(screen.getByText("Đang tìm hiểu: vì sao GMV giảm")).toBeInTheDocument();
  });
  it("is not doubled when it has it", () => {
    pair([{ type: "restated", data: { text_vi: "Đang tìm hiểu: x" } }, { type: "done", data: { stop_reasons: [] } }]);
    expect(screen.getByText("Đang tìm hiểu: x")).toBeInTheDocument();
  });
});

describe("board 3 explanation + card (U1, U6)", () => {
  it("renders the path row with links, four versions, ★ preselected, buttons", async () => {
    const { a } = pair(F.EXPLANATION_CARD);
    const path = screen.getByRole("navigation", { name: "Đường phân tích" });
    const links = within(path).getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/phan-tich"));
    expect(links[2]).toHaveAttribute("href", "/san-pham/1001");
    const radios = screen.getAllByRole("radio");
    expect(radios).toHaveLength(4);
    expect(radios[1]).toBeChecked();
    expect(radios[3]).not.toBeChecked(); // unestimable never preselected
    expect(screen.getByText("Chưa đủ dữ liệu")).toBeInTheDocument();
    await userEvent.click(radios[2]!);
    await userEvent.click(screen.getByRole("button", { name: "Gửi vào Đề xuất" }));
    expect(a.onSendCard).toHaveBeenCalledWith("draft-1", "14.000đ từ 290.000đ");
    await userEvent.click(screen.getByRole("button", { name: "Bỏ qua" }));
    expect(a.onDismissCard).toHaveBeenCalledWith("draft-1");
  });
  it("colours every direction value and never by colour alone (U2)", () => {
    pair(F.EXPLANATION_CARD);
    const up = screen.getByText("+111.104đ");
    expect(up).toHaveClass("juli-up");
    expect(up).toHaveAttribute("data-dir", "up");
    const down = screen.getByText("−665đ");
    expect(down).toHaveClass("juli-down");
    expect(screen.getByText("▼ 39,8%")).toHaveClass("juli-down");
    const margins = document.querySelectorAll('[data-col="margin"] .juli-down');
    expect(margins.length).toBeGreaterThan(0);
    expect(document.querySelector('[data-col="margin"] .juli-up')).not.toBeNull(); // 16,1% → 16,4%
  });
  it("selecting a version is by label with a 44 px class and the unestimable row can be chosen", async () => {
    pair(F.EXPLANATION_CARD);
    await userEvent.click(screen.getAllByRole("radio")[3]!);
    expect(screen.getAllByRole("radio")[3]).toBeChecked();
  });
  it("read-only shop shows the block without the button (U11d)", () => {
    pair(F.EXPLANATION_CARD, {}, actions({ readOnly: true }));
    expect(screen.queryByRole("button", { name: "Gửi vào Đề xuất" })).toBeNull();
    expect(screen.getByRole("radiogroup", { name: "Phương án" })).toBeInTheDocument();
  });
  it("text_replace answer shows only the rewrite", () => {
    pair(F.EXPLANATION_REPLACED);
    expect(screen.queryByText("Đoạn nháp sẽ bị thay.")).toBeNull();
    expect(screen.getByText(/chủ yếu ở Thẻ sản phẩm\./)).toBeInTheDocument();
  });
});

describe("board 4 sent / no card (U6b, U6e)", () => {
  it("sent state names the JC code and links to Quyết định", () => {
    pair(F.EXPLANATION_CARD, {}, actions({ cardStates: { "draft-1": { phase: "sent", code: "JC-2611-0042" } } }));
    expect(screen.getByText("Đã gửi", { selector: "b" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem trong Quyết định" })).toHaveAttribute("href", expect.stringContaining("JC-2611-0042"));
    expect(screen.queryByRole("button", { name: "Gửi vào Đề xuất" })).toBeNull();
  });
  it("the no-card line links the existing card", () => {
    pair(F.NO_CARD_EXISTING);
    expect(screen.getByText(/Đã có thẻ JC-2611-0031 đang làm việc này/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Xem" })).toHaveAttribute("href", expect.stringContaining("JC-2611-0031"));
  });
  it("the plain no-card line has no link", () => {
    pair(F.NO_CARD_PLAIN);
    expect(screen.getByText(/Chưa có đề xuất/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("board 5 data answers (U4a)", () => {
  it("number + change chip + window + freshness", () => {
    pair(F.DATA_METRIC);
    expect(screen.getByText("47 đơn")).toBeInTheDocument();
    expect(screen.getByText("▼ 43,4%")).toHaveClass("juli-down");
    expect(screen.getByText(/01\/11–18\/11 so với/)).toBeInTheDocument();
    expect(screen.getByText("Số liệu đến hết 18/11")).toBeInTheDocument();
  });
  it("top list with links", () => {
    pair(F.DATA_TOP);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(screen.getByRole("link", { name: "Sản phẩm mẫu A" })).toHaveAttribute("href", "/san-pham/1001");
  });
  it("daily bars with tap values and a table view", async () => {
    pair(F.DATA_DAILY);
    expect(screen.getByText("Cao nhất 17/11 · 907.200đ")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "13/11: 371.952đ" }));
    expect(screen.getByText("13/11 · 371.952đ")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Xem bảng" }));
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(8);
    expect(within(table).getAllByText("thiếu dữ liệu")).toHaveLength(2);
  });
  it("channel table marks missing data", () => {
    pair(F.DATA_CHANNEL);
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.getByText("thiếu dữ liệu")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dịch vụ hiển thị Sản phẩm" })).toHaveAttribute("href", "/quang-cao");
  });
});

describe("board 6 stop labels + multi-intent (U4c, U4d)", () => {
  it.each([
    [F.LABEL_NOISE, "Không phát hiện gì bất thường", "Mức thường thấy: 2,46%–3,82%"],
    [F.LABEL_UNEXPLAINED, "Chưa rõ nguyên nhân", "Trong kỳ: 2 sản phẩm sắp hết hàng"],
    [F.LABEL_STALE, "Dữ liệu đến 18/11", null],
    [F.LABEL_MISSING, "Thiếu dữ liệu", null],
  ])("label %#", (events, label, detail) => {
    pair(events);
    expect(screen.getByText(label)).toBeInTheDocument();
    if (detail) expect(screen.getByText(detail)).toBeInTheDocument();
  });
  it("multi-intent blocks and the Xem tiếp button", async () => {
    const { a } = pair(F.MULTI_INTENT);
    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["GMV", "Đơn hàng", "CTR"]);
    await userEvent.click(screen.getByRole("button", { name: "Xem tiếp: CTOR" }));
    expect(a.onMore).toHaveBeenCalledWith("CTOR tuần này so với tuần trước");
  });
});

describe("board 7 choices (U5)", () => {
  it("needs_choice: option buttons + Khác…", async () => {
    const { a } = pair(F.CHOICE_METRIC);
    await userEvent.click(screen.getByRole("button", { name: "CTR" }));
    expect(a.onChoose).toHaveBeenCalledWith("metric", { label_vi: "CTR", value: "ctr" }, "Câu hỏi mẫu");
    await userEvent.click(screen.getByRole("button", { name: "Khác…" }));
    expect(a.onOther).toHaveBeenCalled();
  });
  it("window and product choices render their options", () => {
    pair(F.CHOICE_WINDOW);
    expect(screen.getByRole("button", { name: "01/11–18/11 so với 01/10–18/10" })).toBeInTheDocument();
  });
  it("product choice stacks vertically", () => {
    pair(F.CHOICE_PRODUCT);
    expect(document.querySelector(".juli-opts--stack")).not.toBeNull();
  });
  it("Jev outage (needs_choice item template) renders the template buttons", async () => {
    const { a } = pair([
      { type: "needs_choice", data: { item: "template", question_vi: "Bạn muốn xem gì?", options: F.TEMPLATES.map((t) => ({ label_vi: t.key, value: t.key })), pending: {} } },
      { type: "done", data: { stop_reasons: [] } },
    ]);
    const group = screen.getByRole("group", { name: "Mẫu câu hỏi" });
    expect(within(group).getAllByRole("button")).toHaveLength(5);
    expect(screen.queryByRole("button", { name: "Khác…" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Giảm chi phí" }));
    expect(a.onTemplate).toHaveBeenCalledWith({ key: "reduce_cost", label_vi: "Giảm chi phí" });
  });

  it("unsupported: fixed line + 5 templates, no platform switch", async () => {
    const { a } = pair(F.UNSUPPORTED);
    expect(screen.getByText("Juli chưa hỗ trợ câu hỏi này")).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Mẫu câu hỏi" })).getAllByRole("button")).toHaveLength(5);
    await userEvent.click(screen.getByRole("button", { name: "Giảm chi phí" }));
    expect(a.onTemplate).toHaveBeenCalledWith({ key: "reduce_cost", label_vi: "Giảm chi phí" });
  });
  it("other-platform question offers the switch", async () => {
    const onSwitchPlatform = vi.fn();
    pair(F.UNSUPPORTED_OTHER_PLATFORM, {}, actions({ onSwitchPlatform }));
    await userEvent.click(screen.getByRole("button", { name: "Chuyển sang shop TikTok" }));
    expect(onSwitchPlatform).toHaveBeenCalledWith("tiktok");
  });
  it("choices are disabled once a later message exists", () => {
    const message: ChatMessage = { id: "m", question: "q", events: F.CHOICE_METRIC, status: "done", reconnecting: false };
    render(<MessagePair message={message} isLast={false} actions={actions()} />);
    expect(screen.getByRole("button", { name: "CTR" })).toBeDisabled();
  });
});

describe("board 8 answer-level system states (U3e, U11e, U11f)", () => {
  it("error shows the fixed line and Thử lại", async () => {
    const { a } = pair(F.ERROR_FAILED, { status: "failed" });
    expect(screen.getByText("Juli đang gặp sự cố, thử lại sau")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(a.onRetry).toHaveBeenCalled();
  });
  it("reconnecting keeps the text and shows the status", () => {
    pair(F.RUNNING, { status: "running", reconnecting: true });
    expect(screen.getByText("Đang kết nối lại…")).toBeInTheDocument();
    expect(screen.getByText(/Phần lớn mức giảm/)).toBeInTheDocument();
  });
  it("stopped shows Đã dừng", () => {
    pair(F.RUNNING, { status: "stopped" });
    expect(screen.getByText("Đã dừng")).toBeInTheDocument();
  });
});

describe("board 9 history answer (U8c)", () => {
  it("a saved answer shows its data date and Hỏi lại với số liệu mới, sent card keeps its link", async () => {
    const a = actions();
    pair(F.NO_CARD_PLAIN, { status: "saved", dataUntilVi: "Số liệu đến 15/11" }, a);
    expect(screen.getByText("Số liệu đến 15/11")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Hỏi lại với số liệu mới" }));
    expect(a.onAskAgain).toHaveBeenCalledWith("m1");
  });
  it("saved answer with a sent card shows the sent line", () => {
    pair(F.EXPLANATION_CARD, { status: "saved", sentCardCode: "JC-2611-0031" });
    expect(screen.getByRole("link", { name: "Xem trong Quyết định" })).toHaveAttribute("href", expect.stringContaining("JC-2611-0031"));
  });
});

describe("board 10 TikTok before W3 (U12)", () => {
  it("Thiếu dữ liệu + report line + no TikTok card", () => {
    pair(F.TIKTOK_MISSING, {}, actions({ platform: "tiktok" }));
    expect(screen.getByText("Thiếu dữ liệu")).toBeInTheDocument();
    expect(screen.getByText(/Báo cáo ngày 18\/11/)).toBeInTheDocument();
    expect(screen.getByText("Chưa có đề xuất cho TikTok")).toBeInTheDocument();
  });
});

describe("whole page flows (mock client)", () => {
  beforeEach(() => window.sessionStorage.clear());

  const props = { platform: "shopee" as const, templates: F.TEMPLATES, shopKey: "t" };

  it("board 1 empty: heading, five tiles, input", () => {
    render(<JuliChat client={createMockJuliClient()} {...props} />);
    expect(screen.getByRole("heading", { name: "Bạn muốn cải thiện chỉ số nào?" })).toBeInTheDocument();
    expect(within(screen.getByRole("group", { name: "Mẫu câu hỏi" })).getAllByRole("button")).toHaveLength(5);
    expect(screen.getByRole("textbox", { name: "Hỏi Juli về shop của bạn" })).toHaveAttribute("placeholder", "Hỏi Juli về shop của bạn…");
  });

  it("a template runs the answer, then templates stay as a row under the input (U2c) and the card sends", async () => {
    const client = createMockJuliClient();
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Cải thiện tỷ lệ chuyển đổi/ }));
    await screen.findByRole("button", { name: "Gửi vào Đề xuất" });
    expect(screen.getAllByText("Cải thiện tỷ lệ chuyển đổi").length).toBeGreaterThan(0);
    expect(within(screen.getByRole("group", { name: "Mẫu câu hỏi" })).getAllByRole("button")).toHaveLength(5);
    await userEvent.click(screen.getByRole("button", { name: "Gửi vào Đề xuất" }));
    await screen.findByText("Đã gửi", { selector: "b" });
    expect(client.calls.sendCard).toEqual([["draft-1", "8.000đ từ 150.000đ"]]);
  });

  it("running: send disabled, templates hidden, Dừng works and writes nothing", async () => {
    const client = createMockJuliClient({ delayMs: 20 });
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Cải thiện GMV/ }));
    const stop = await screen.findByRole("button", { name: "Dừng" });
    expect(screen.getByRole("button", { name: "Gửi" })).toBeDisabled();
    expect(screen.queryByRole("group", { name: "Mẫu câu hỏi" })).toBeNull();
    expect(screen.getByRole("textbox")).toHaveAttribute("placeholder", "Bạn có thể gõ câu tiếp theo…");
    await userEvent.click(stop);
    expect(await screen.findByText("Đã dừng")).toBeInTheDocument();
    expect(client.calls.sendCard).toHaveLength(0);
    await waitFor(() => expect(client.calls.cancel.length).toBe(1));
  });

  it("free text goes to unsupported with the five templates", async () => {
    render(<JuliChat client={createMockJuliClient()} {...props} />);
    await userEvent.type(screen.getByRole("textbox"), "đối thủ bán bao nhiêu{enter}");
    expect(await screen.findByText("Juli chưa hỗ trợ câu hỏi này")).toBeInTheDocument();
  });

  it("dismiss writes nothing and collapses the block", async () => {
    const client = createMockJuliClient();
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Cải thiện GMV/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Bỏ qua" }));
    expect(await screen.findByText("Đã bỏ qua")).toBeInTheDocument();
    expect(client.calls.dismissCard).toEqual(["draft-1"]);
  });

  it("limit (429) disables the input and hides templates (U11c)", async () => {
    const client: JuliClient = { ...createMockJuliClient(), ask: vi.fn().mockRejectedValue(new JuliApiError(429, "2026-11-20T08:40:00Z")) };
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Giảm chi phí/ }));
    expect(await screen.findByText(/Bạn đã hỏi nhiều trong giờ này, thử lại sau \d{2}:\d{2}/)).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.queryByRole("group", { name: "Mẫu câu hỏi" })).toBeNull();
  });

  it("a 422 juli_card_refused shows the no-card line", async () => {
    const client: JuliClient = { ...createMockJuliClient(), sendCard: vi.fn().mockRejectedValue(new JuliApiError(422, undefined, "juli_card_refused")) };
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Cải thiện GMV/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Gửi vào Đề xuất" }));
    expect(await screen.findByText("Juli chưa tạo được thẻ này")).toBeInTheDocument();
  });

  it("shop_state.read_only from GET /templates hides the send button", async () => {
    const client = createMockJuliClient({ readOnly: true });
    render(<JuliChat client={client} platform="shopee" shopKey="ro" />);
    await userEvent.click(await screen.findByRole("button", { name: /Cải thiện GMV/ }));
    await screen.findByRole("radiogroup", { name: "Phương án" });
    expect(screen.queryByRole("button", { name: "Gửi vào Đề xuất" })).toBeNull();
  });

  it("403 on card send flips the card block to read-only", async () => {
    const client: JuliClient = { ...createMockJuliClient(), sendCard: vi.fn().mockRejectedValue(new JuliApiError(403)) };
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Cải thiện GMV/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Gửi vào Đề xuất" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Gửi vào Đề xuất" })).toBeNull());
  });

  it("ask 403 -> read-only state, ask 409 -> busy line, ask 422 -> templates; none offers Thử lại", async () => {
    for (const [status, code, text] of [
      [403, undefined, "Shop chỉ xem"],
      [409, "juli_busy", "Juli đang trả lời câu trước"],
      [422, "juli_ask_invalid", "Juli chưa hiểu câu hỏi này"],
    ] as const) {
      window.sessionStorage.clear();
      const client: JuliClient = { ...createMockJuliClient(), ask: vi.fn().mockRejectedValue(new JuliApiError(status, undefined, code)) };
      const { unmount } = render(<JuliChat client={client} {...props} />);
      await userEvent.click(screen.getByRole("button", { name: /Giảm chi phí/ }));
      expect(await screen.findByText(text)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
      if (status === 422) expect(within(screen.getAllByRole("group", { name: "Mẫu câu hỏi" })[0]!).getAllByRole("button").length).toBeGreaterThanOrEqual(5);
      unmount();
    }
  });

  it("ask 403 makes later cards read-only", async () => {
    const mock = createMockJuliClient();
    const client: JuliClient = { ...mock, ask: vi.fn().mockRejectedValueOnce(new JuliApiError(403)).mockImplementation(mock.ask) };
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Giảm chi phí/ }));
    await screen.findByText("Shop chỉ xem");
    await userEvent.click(screen.getAllByRole("button", { name: /Cải thiện GMV/ }).at(-1)!);
    await screen.findByRole("radiogroup", { name: "Phương án" });
    expect(screen.queryByRole("button", { name: "Gửi vào Đề xuất" })).toBeNull();
  });

  it("429 without a time shows the generic busy line", async () => {
    const client: JuliClient = { ...createMockJuliClient(), ask: vi.fn().mockRejectedValue(new JuliApiError(429)) };
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Giảm chi phí/ }));
    expect(await screen.findByText("Juli đang bận, thử lại sau")).toBeInTheDocument();
  });

  it("a stream 429 shows the limit line and is not retried", async () => {
    const mock = createMockJuliClient();
    const client: JuliClient = {
      ...mock,
      stream: (_id, handlers) => {
        queueMicrotask(() => handlers.onClose?.("limited", { retryAt: "2026-11-20T08:40:00Z" }));
        return { abort: () => undefined };
      },
    };
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: /Giảm chi phí/ }));
    expect(await screen.findByText(/Bạn đã hỏi nhiều trong giờ này, thử lại sau \d{2}:\d{2}/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Thử lại" })).toBeNull();
  });

  it("history asks for the current platform and shows a bare dd/mm as Số liệu đến dd/mm", async () => {
    const mock = createMockJuliClient({
      history: [{ id: "c1", title: "Giảm chi phí", messages: [{ id: "x1", question: "Giảm chi phí", events: F.NO_CARD_PLAIN, created_at: "2026-11-12T03:00:00Z", data_until_vi: "15/11" }] }],
    });
    const spy = vi.spyOn(mock, "conversations");
    render(<JuliChat client={mock} platform="tiktok" templates={F.TEMPLATES} shopKey="p" />);
    await waitFor(() => expect(spy).toHaveBeenCalledWith("tiktok"));
    await userEvent.click(screen.getByRole("button", { name: "Lịch sử" }));
    const panel = await screen.findByRole("complementary", { name: "Lịch sử" });
    await userEvent.click(await within(panel).findByRole("button", { name: /Giảm chi phí/ }));
    expect(await screen.findByText("Số liệu đến 15/11")).toBeInTheDocument();
  });

  it("stale line (U11b) and backfilling (U11g)", () => {
    const { unmount } = render(<JuliChat client={createMockJuliClient()} {...props} staleUntil="15/11" />);
    expect(screen.getByText("Dữ liệu đến 15/11")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Kết nối dữ liệu" })).toBeInTheDocument();
    unmount();
    render(<JuliChat client={createMockJuliClient()} {...props} backfilling />);
    expect(screen.getByText("Juli đang lấy dữ liệu shop, thử lại sau")).toBeInTheDocument();
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.queryByRole("group", { name: "Mẫu câu hỏi" })).toBeNull();
  });

  it("history lists the shop's conversations newest first and reopens one (U8)", async () => {
    const client = createMockJuliClient({
      history: [
        { id: "c1", title: "Giảm chi phí", messages: [{ id: "x1", question: "Giảm chi phí", events: F.NO_CARD_PLAIN, created_at: "2026-11-12T03:00:00Z", data_until_vi: "Số liệu đến 12/11" }] },
        { id: "c2", title: "Vì sao GMV thay đổi?", messages: [{ id: "x2", question: "Vì sao GMV thay đổi?", events: F.NO_CARD_PLAIN, created_at: "2026-11-16T03:00:00Z", data_until_vi: "Số liệu đến 15/11" }] },
      ],
    });
    render(<JuliChat client={client} {...props} />);
    await userEvent.click(screen.getByRole("button", { name: "Lịch sử" }));
    const history = await screen.findByRole("complementary", { name: "Lịch sử" });
    await waitFor(() => expect(within(history).getAllByRole("button", { name: /Giảm chi phí|Vì sao GMV/ })).toHaveLength(2));
    const items = within(history).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("Vì sao GMV thay đổi?");
    await userEvent.click(within(history).getByRole("button", { name: /Giảm chi phí/ }));
    expect(await screen.findByText("Số liệu đến 12/11")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Hỏi lại với số liệu mới" })).toBeInTheDocument();
  });
});

describe("U2 / mobile contract (static)", () => {
  const css = readFileSync(join(__dirname, "../../../app/juli/juli.css"), "utf8");
  const source = (name: string) => readFileSync(join(__dirname, "..", name), "utf8");

  it("DS direction colours and 44 px targets are in the stylesheet", () => {
    expect(css).toContain("--juli-up: #15803d");
    expect(css).toContain("--juli-down: #b42318");
    for (const cls of [".juli-btn", ".juli-opt", ".juli-chip", ".juli-send", ".juli-stop", ".juli-pill", ".juli-history__item"]) {
      const block = css.slice(css.indexOf(`${cls} {`));
      expect(block.slice(0, 400), cls).toMatch(/(min-)?(height|width): 44px/);
    }
  });
  it("mobile rules: swipeable templates, vertical path, stacked versions, history sheet", () => {
    const mobile = css.slice(css.indexOf("@media (max-width: 767px)"));
    expect(mobile).toContain("overflow-x: auto");
    expect(mobile).toMatch(/\.juli-path ol \{ flex-direction: column/);
    expect(mobile).toContain(".juli-ver-head { display: none; }");
    expect(mobile).toMatch(/\.juli-history \{[^}]*position: fixed[^}]*bottom: 0/);
    expect(mobile).toContain("min-height: 48px");
  });
  it("uses DS v7 tokens: no hex colours but the two direction colours", () => {
    const hex = css.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    expect([...new Set(hex)].sort()).toEqual(["#15803d", "#b42318"]);
    expect(css).not.toMatch(/var\(--juli-[a-z-]+,/); // no fallbacks where a token exists
    expect(css).toContain("var(--juli-border)");
    expect(css).toContain("var(--juli-surface)");
  });
  it("no captions or 'ước tính' anywhere in the Juli UI sources", () => {
    for (const f of ["answer.tsx", "answer-parts.tsx", "card-block.tsx", "composer.tsx", "history.tsx", "juli-chat.tsx", "delta.tsx"]) {
      expect(source(f).toLowerCase()).not.toContain("ước tính");
      expect(source(f).toLowerCase()).not.toContain("minh hoạ");
    }
    expect(JSON.stringify(F).toLowerCase()).not.toContain("ước tính");
  });
  it("no hard-coded source keys in the UI (labels come from the payload)", () => {
    for (const f of ["answer.tsx", "answer-parts.tsx"]) {
      expect(source(f)).not.toMatch(/product_card|shop_page|"video"|shopee_ads/);
    }
  });
});
