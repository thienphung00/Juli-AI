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

import { RUN_OPTION_FIELD_FALLBACK } from "../../lib/run-surface/option-diff";
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

// Derived from the captured approval, never restated. This was a hardcoded
// "2026-08-28T09:32:13Z", which #1862's deterministic re-capture (2026-01-01)
// turned into an instant AFTER the expiry it was meant to precede.
const NOW_BEFORE_EXPIRY = (() => {
  const approval = scenario.events.find((e) => e.event_type === "workflow.approval_required");
  const expiresAt = (approval?.payload as { expires_at?: string } | undefined)?.expires_at;
  if (!expiresAt) {
    throw new Error("fixture has no workflow.approval_required expires_at");
  }
  return new Date(expiresAt).getTime() - 60 * 60 * 1000;
})();

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
        nowMs={NOW_BEFORE_EXPIRY} // derived from the fixture, 1h before expires_at
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

describe("RunStageCanvas -- Cập nhật stage renders no raw payload key (issue #1908)", () => {
  // The captured scenario's proposed_change carries only `title`. The
  // production defect (#1908) leaked `attach_staged_image` and
  // `description` -- so the approval event is SHALLOW-MUTATED (never
  // invented from scratch, same discipline as option-picker.test.tsx's
  // N=1 mutations) to carry the production payload shape.
  const productionShapedEvents: AgentEvent[] = approved.map((event) =>
    event.event_type === "workflow.approval_required"
      ? ({
          ...event,
          payload: {
            ...event.payload,
            proposed_change: {
              title: "Tiêu đề đã tối ưu",
              description: "Mô tả đã tối ưu cho sản phẩm này.",
              attach_staged_image: true,
            },
          },
        } as AgentEvent)
      : event,
  );

  it("renders every proposed-change key through describeOptionField -- attach_staged_image appears nowhere", () => {
    const view = reduceRunView(productionShapedEvents);
    render(
      <RunStageCanvas
        events={productionShapedEvents}
        isTerminal={true}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1908"
        stageId="cap-nhat"
        view={view}
      />,
    );

    const text = document.body.textContent ?? "";
    expect(text).not.toContain("attach_staged_image");
    // The known key renders its seller label; the unknown keys render the
    // generic fallback -- one <dt> per proposed field, none of them raw.
    expect(screen.getByText("Tiêu đề")).toBeInTheDocument();
    expect(screen.getAllByText(RUN_OPTION_FIELD_FALLBACK).length).toBe(2);
    expect(text).not.toMatch(/[a-z]+_[a-z]+/);
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

describe("RunStageCanvas -- panel composition (issue #1914)", () => {
  it("the tabpanel composes juli-run-panel WITH juli-run-panel--raised -- raised alone sets only fill", () => {
    // `.juli-run-panel--raised` (packages/theme/run-surface-tokens.css)
    // declares fill facets only; the border, radius, shadow and colour
    // live on `.juli-run-panel`. Applying the modifier without the base
    // is how the stage canvas shipped borderless -- exactly what
    // in-progress-panel.tsx already composes correctly at its three call
    // sites.
    const view = reduceRunView(scenario.events);
    render(
      <RunStageCanvas
        events={scenario.events}
        isTerminal={false}
        nowMs={1000}
        productName={PRODUCT_NAME}
        runId="run-1914"
        stageId="phan-tich"
        view={view}
      />,
    );

    const panel = screen.getByRole("tabpanel");
    expect(panel.classList.contains("juli-run-panel--raised")).toBe(true);
    expect(panel.classList.contains("juli-run-panel")).toBe(true);
  });
});
