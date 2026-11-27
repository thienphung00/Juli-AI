/**
 * Owner #110: the Chat answer lays out the reading rules the backend applies (readable.py):
 * the lead sentence first and no "Đang tìm hiểu" header, one period line on top (never per card),
 * at most three number tiles each with one comparison line, lists as right-aligned tables, no box
 * for an empty list, next steps as buttons. Several answer types: one figure, three figures, a list,
 * a why answer, a several-question answer, an answer saved before #110.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { JuliAgentEvent, JuliEventMap, JuliEventType } from "@juli/contracts";

import { reduceAnswer } from "../../../lib/juli/reduce";
import * as F from "../../../lib/juli/fixtures";
import type { ChatMessage } from "../../../lib/juli/use-juli-chat";
import { MessagePair, type AnswerActions } from "../answer";

function e<K extends JuliEventType>(type: K, data: JuliEventMap[K]): JuliAgentEvent {
  return { type, data } as JuliAgentEvent;
}

const META = e("meta", { window_vi: "01/11–24/11 so với 01/10–24/10", fresh_vi: "Số liệu đến hết 24/11", sale_vi: "Ngày sale: 11/11, 15/11" });
const tile = (title: string, value: string, compare?: string) =>
  e("data_answer", {
    kind: "metric_total",
    title_vi: title,
    value,
    window_vi: "01/11–24/11 so với 01/10–24/10",
    fresh_vi: "Số liệu đến hết 24/11",
    sale_vi: "Ngày sale: 11/11, 15/11",
    delta: { dir: "flat", text_vi: "Kỳ trước chưa đủ dữ liệu" },
    ...(compare ? { compare_vi: compare } : {}),
  });

const VOUCHERS: readonly JuliAgentEvent[] = [
  e("restated", { text_vi: "Đang tìm hiểu: phân tích voucher tháng 11" }),
  META,
  e("lead", { text_vi: "Đơn dùng voucher là 34." }),
  tile("Đơn dùng voucher", "34", "Kỳ trước chưa đủ dữ liệu"),
  tile("GMV đơn dùng voucher", "3.638.700đ", "Kỳ trước chưa đủ dữ liệu"),
  tile("Chi phí voucher (Ưu đãi)", "49.000đ"),
  e("data_answer", {
    kind: "top_products",
    title_vi: "Voucher đã chạy",
    window_vi: "01/11–24/11",
    fresh_vi: "Số liệu đến hết 24/11",
    rows: [{ label_vi: "Giảm 20K đơn 300K", value_vi: "20.000đ", detail_vi: "09/11–12/11" }],
  }),
  e("data_answer", { kind: "top_products", title_vi: "Theo mã", window_vi: "x", fresh_vi: "y", rows: [], empty: true }),
  e("text_replace", { text: "Đang tìm hiểu: phân tích voucher tháng 11\nShop tự chịu phần voucher; phần còn lại Shopee chịu." }),
  e("more", { items: [{ label_vi: "Theo sản phẩm", text: "Đơn dùng voucher theo sản phẩm 01/11–24/11" }] }),
  e("done", { stop_reasons: ["data_answer"] }),
];

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
function pair(events: readonly JuliAgentEvent[], a: AnswerActions = actions()) {
  const message: ChatMessage = { id: "m1", question: "Câu hỏi", events, status: "done", reconnecting: false };
  return render(<MessagePair message={message} isLast actions={a} />);
}

describe("#110 reading rules in the Chat answer", () => {
  it("1: the lead comes first and no 'Đang tìm hiểu' header stays once answered", () => {
    const { container } = pair(VOUCHERS);
    expect(screen.queryByText(/Đang tìm hiểu/)).toBeNull();
    const lead = screen.getByText("Đơn dùng voucher là 34.");
    expect(lead).toHaveClass("juli-lead");
    const text = container.querySelector(".juli-answer")!.textContent!;
    expect(text.indexOf("Đơn dùng voucher là 34.")).toBeLessThan(text.indexOf("Shop tự chịu"));
  });

  it("2: period, data day and sale days once, on top, never under each card", () => {
    const { container } = pair(VOUCHERS);
    expect(screen.getAllByText("Số liệu đến hết 24/11")).toHaveLength(1);
    expect(screen.getAllByText("Ngày sale: 11/11, 15/11")).toHaveLength(1);
    expect(container.querySelectorAll(".juli-fresh")).toHaveLength(0);
    const first = container.querySelector(".juli-answer")!.firstElementChild!;
    expect(first).toHaveClass("juli-meta");
  });

  it("4 + 5: three tiles, each a label, a value and one comparison line", () => {
    pair(VOUCHERS);
    const tiles = within(screen.getByRole("group", { name: "Số liệu chính" })).getAllByRole("region");
    expect(tiles).toHaveLength(3);
    expect(within(tiles[0]!).getByText("Đơn dùng voucher")).toBeInTheDocument();
    expect(within(tiles[0]!).getByText("34")).toBeInTheDocument();
    expect(within(tiles[0]!).getByText("Kỳ trước chưa đủ dữ liệu")).toBeInTheDocument();
    expect(screen.queryByText(/%/)).toBeNull();
  });

  it("6 + 7: a list is a right-aligned table; an empty list draws no box", () => {
    pair(VOUCHERS);
    const tables = screen.getAllByRole("table");
    expect(tables).toHaveLength(1);
    expect(within(tables[0]!).getByText("20.000đ")).toHaveClass("juli-right");
    expect(screen.queryByText("Theo mã")).toBeNull();
  });

  it("8: next steps are buttons", async () => {
    const a = actions();
    pair(VOUCHERS, a);
    await userEvent.click(screen.getByRole("button", { name: "Theo sản phẩm" }));
    expect(a.onMore).toHaveBeenCalledWith("Đơn dùng voucher theo sản phẩm 01/11–24/11");
  });

  it("a why answer: lead, then the path; the streamed header line never shows", () => {
    const why: readonly JuliAgentEvent[] = [
      e("restated", { text_vi: "Đang tìm hiểu: vì sao đơn giảm" }),
      e("text_delta", { text: "Đang tìm hiểu: vì sao" }),
      e("text_delta", { text: " đơn giảm\nĐơn giảm vì Video kém." }),
      META,
      e("lead", { text_vi: "Đơn hàng là 12, ▼ 55,6% so với kỳ trước." }),
      ...F.EXPLANATION_CARD.filter((x) => x.type === "path"),
      e("done", { stop_reasons: ["explained"] }),
    ];
    pair(why);
    expect(screen.getByText("Đơn giảm vì Video kém.")).toBeInTheDocument();
    expect(screen.queryByText(/Đang tìm hiểu/)).toBeNull();
    expect(screen.getByText("Đơn hàng là 12, ▼ 55,6% so với kỳ trước.")).toBeInTheDocument();
  });

  it("several questions on one period: one line; a block on another period shows its own", () => {
    const other = e("meta", { window_vi: "28/09–04/10 so với 21/09–27/09", fresh_vi: "Số liệu đến hết 24/11" });
    const v = reduceAnswer([
      e("intent_block", { index: 1, total: 3, title_vi: "Câu 1/3" }),
      META,
      tile("Chi phí quảng cáo", "210.000đ"),
      e("intent_block", { index: 2, total: 3, title_vi: "Câu 2/3" }),
      META,
      tile("ROAS", "3,10"),
      e("intent_block", { index: 3, total: 3, title_vi: "Câu 3/3" }),
      other,
      tile("GMV", "1.000đ"),
    ]);
    expect(v.meta?.window_vi).toBe("01/11–24/11 so với 01/10–24/10");
    expect(v.blocks.map((b) => b.meta?.window_vi ?? null)).toEqual([null, null, "28/09–04/10 so với 21/09–27/09"]);
  });

  it("an answer saved before #110 still gets one top line from its first figure", () => {
    const { container } = pair(F.DATA_METRIC);
    expect(container.querySelector(".juli-meta")).not.toBeNull();
    expect(screen.getAllByText("Số liệu đến hết 18/11")).toHaveLength(1);
  });
});

describe("#113 the period question", () => {
  it("five period buttons; 'Khoảng khác' focuses the input instead of choosing", async () => {
    const a = actions();
    pair(
      [
        e("needs_choice", {
          item: "window",
          question_vi: "Bạn muốn so sánh khoảng thời gian nào?",
          options: [
            { label_vi: "7 ngày qua", value: "last_7d_vs_prev_7d" },
            { label_vi: "30 ngày qua", value: "last_30d_vs_prev_30d" },
            { label_vi: "Tháng này", value: "mtd_vs_same_days_last_month" },
            { label_vi: "Tháng trước", value: "last_month_vs_month_before" },
            { label_vi: "Khoảng khác", value: "other" },
          ],
          pending: {},
        }),
        e("done", { stop_reasons: ["needs_choice"] }),
      ],
      a,
    );
    const group = screen.getByRole("group", { name: "Bạn muốn so sánh khoảng thời gian nào?" });
    expect(within(group).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "7 ngày qua",
      "30 ngày qua",
      "Tháng này",
      "Tháng trước",
      "Khoảng khác",
    ]);
    await userEvent.click(screen.getByRole("button", { name: "Khoảng khác" }));
    expect(a.onOther).toHaveBeenCalled();
    expect(a.onChoose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "7 ngày qua" }));
    expect(a.onChoose).toHaveBeenCalledWith("window", { label_vi: "7 ngày qua", value: "last_7d_vs_prev_7d" }, "Câu hỏi");
  });
});
