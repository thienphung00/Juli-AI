/**
 * Proven against the captured scenario (#1311's output) walking every
 * stage, never a hand-built event -- same discipline as
 * `reduce-run-view.test.ts` and `stage-events.test.ts`.
 */

import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentEvent } from "@juli/contracts";

import { reduceRunView } from "../../lib/run-surface/reduce-run-view";
import { RunStageCanvas } from "../run-stage-canvas";

const SCENARIO_PATH = path.resolve(
  __dirname,
  "../../../../../tests/fixtures/golden_scenarios/optimize_product_confirm_pause.json",
);

interface Scenario {
  readonly events: AgentEvent[];
  readonly continuations: Record<string, AgentEvent[]>;
}

function loadScenario(): Scenario {
  return JSON.parse(readFileSync(SCENARIO_PATH, "utf8")) as Scenario;
}

const scenario = loadScenario();
const approved: AgentEvent[] = [...scenario.events, ...scenario.continuations.approve];

const PRODUCT_NAME = "Áo thun cotton nam";

describe("RunStageCanvas -- product snapshot stage", () => {
  it("shows the bound product name -- the seller sees which listing before any confirmation", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="thong-tin-san-pham"
        view={view}
      />,
    );

    expect(screen.getByText(PRODUCT_NAME)).toBeInTheDocument();
  });

  it("shows the get_product_information tool's seller-facing label, never the raw tool name", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="thong-tin-san-pham"
        view={view}
      />,
    );

    expect(screen.getByText("Xem thông tin sản phẩm")).toBeInTheDocument();
    expect(screen.queryByText(/get_product_information/)).not.toBeInTheDocument();
  });
});

describe("RunStageCanvas -- SEO stage (never entered by this scenario)", () => {
  it("renders the honest empty state, not invented keyword content", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="seo"
        view={view}
      />,
    );

    expect(
      screen.getByText("Không có bước phân tích từ khoá SEO trong luồng này."),
    ).toBeInTheDocument();
  });
});

describe("RunStageCanvas -- Đề xuất stage (the paused decision request)", () => {
  it("renders the proposed change and the expiry countdown, driven by the reducer's decisionRequest", () => {
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={new Date("2026-08-28T09:32:13.308159Z").getTime()} // 1h before expires_at
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="de-xuat"
        view={view}
      />,
    );

    // The option card's headline value AND its before/after diff caption
    // both carry the proposed title (PUI-DESIGN.md §3 mockup repeats the
    // value the same way) -- at least one occurrence is the assertion.
    expect(screen.getAllByText("Tiêu đề đã tối ưu").length).toBeGreaterThan(0);
    expect(screen.getByText(/Đề xuất còn hiệu lực/)).toBeInTheDocument();
    expect(screen.queryByText(/update_product_listing/)).not.toBeInTheDocument();
  });
});

describe("RunStageCanvas -- Cập nhật stage", () => {
  it("shows the selected option as a header, sourced from the historical approval_required event", () => {
    const view = reduceRunView(approved);
    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="cap-nhat"
        view={view}
      />,
    );

    expect(screen.getAllByText("Cập nhật thông tin sản phẩm").length).toBeGreaterThan(0);
    expect(screen.getByText("Tiêu đề đã tối ưu")).toBeInTheDocument();
  });

  it("still shows the header even though the reducer's decisionRequest is already cleared (run finished)", () => {
    const view = reduceRunView(approved);
    expect(view.decisionRequest).toBeUndefined();

    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="cap-nhat"
        view={view}
      />,
    );

    expect(screen.getByText("Tiêu đề đã tối ưu")).toBeInTheDocument();
  });
});

describe("RunStageCanvas -- Hoàn tất stage", () => {
  it("shows the honest completed outcome, never a raw stop_reason", () => {
    const view = reduceRunView(approved);
    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="hoan-tat"
        view={view}
      />,
    );

    expect(screen.getByText("Juli đã hoàn tất và áp dụng thay đổi được phê duyệt.")).toBeInTheDocument();
    expect(screen.queryByText(/final_response/)).not.toBeInTheDocument();
  });

  it("distinguishes completed-after-decline from a plain completion -- no state dressed as another", () => {
    const declined = [...scenario.events, ...scenario.continuations.decline];
    const view = reduceRunView(declined);
    render(
      <RunStageCanvas
        events={declined}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId="hoan-tat"
        view={view}
      />,
    );

    expect(screen.getByText("Bạn đã chọn không thay đổi giá")).toBeInTheDocument();
  });
});

describe("RunStageCanvas -- no leaked internals, across every stage", () => {
  const stageIds = [
    "phan-tich",
    "thong-tin-san-pham",
    "seo",
    "de-xuat",
    "cap-nhat",
    "hoan-tat",
  ] as const;

  it.each(stageIds)("renders %s with no tool name, workflow key, or raw stop_reason", (stageId) => {
    const view = reduceRunView(approved);
    render(
      <RunStageCanvas
        events={approved}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1"
        stageId={stageId}
        view={view}
      />,
    );

    const text = document.body.textContent ?? "";
    expect(text).not.toMatch(/get_product_information/);
    expect(text).not.toMatch(/update_product_listing/);
    expect(text).not.toMatch(/optimize_product_2/);
    expect(text).not.toMatch(/final_response/);
    expect(text).not.toMatch(/tool_call_id/);
  });
});
