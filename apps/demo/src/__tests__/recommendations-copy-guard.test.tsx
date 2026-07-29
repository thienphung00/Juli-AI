import { render, screen, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useSearchParams } from "next/navigation";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { RecommendationsView } from "../components/recommendations-view";
import { recommendationFixtures } from "../lib/recommendations";

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(),
  usePathname: vi.fn(() => "/decisions"),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push: vi.fn(),
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
}));

const BANNED_COPY = [
  "Có thể thực thi qua FBS",
  /Độ tin cậy:\s*(Cao|Trung bình|Thấp)/,
] as const;

const BANNED_JARGON = [/tool_name/, /feature_id/, /\bwebhook\b/i, /\bendpoint\b/i] as const;

function mockHighlight(query = "") {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(query) as unknown as ReturnType<typeof useSearchParams>,
  );
}

function renderView(
  props: ComponentProps<typeof RecommendationsView> = {},
) {
  return render(
    <DemoStateProvider>
      <RecommendationsView {...props} />
    </DemoStateProvider>,
  );
}

function findCard(workflowKey: string) {
  return screen
    .getAllByRole("article")
    .find((card) => card.getAttribute("data-workflow-key") === workflowKey);
}

function recommendationsPanelText() {
  const panel = screen.getByLabelText("Đề xuất", { selector: "div" });
  return panel.textContent ?? "";
}

describe("Recommendations — copy guard", () => {
  beforeEach(() => {
    mockHighlight();
    localStorage.clear();
  });

  it("does not render banned FBS or confidence strings in the recommendations panel", () => {
    renderView();

    const text = recommendationsPanelText();

    for (const banned of BANNED_COPY) {
      if (typeof banned === "string") {
        expect(text).not.toContain(banned);
      } else {
        expect(text).not.toMatch(banned);
      }
    }
  });

  it("does not render backend jargon patterns on recommendation card surfaces", () => {
    renderView();

    for (const fixture of recommendationFixtures) {
      const card = findCard(fixture.workflowKey) as HTMLElement;
      const surfaceText = card.textContent ?? "";

      for (const pattern of BANNED_JARGON) {
        expect(surfaceText).not.toMatch(pattern);
      }
    }
  });

  it("shows signal and one concise reason per card without confidence or capability badges", () => {
    renderView();

    recommendationFixtures.forEach((fixture) => {
      const card = findCard(fixture.workflowKey) as HTMLElement;

      expect(
        within(card).getByRole("heading", { level: 3, name: fixture.title }),
      ).toBeInTheDocument();
      expect(within(card).getByText(fixture.signal)).toBeInTheDocument();
      expect(within(card).getByText(fixture.reasoning)).toBeInTheDocument();
      expect(
        within(card).queryByText(fixture.confidenceLabel),
      ).not.toBeInTheDocument();
      expect(
        within(card).queryByText(fixture.capabilityLabel),
      ).not.toBeInTheDocument();
      expect(card.textContent).not.toContain("Tác động dự kiến:");
    });
  });

  it("leaves In Progress routes and components untouched by Recommendations changes", () => {
    const panelSource = readFileSync(
      join(process.cwd(), "src/components/recommendations-panel.tsx"),
      "utf8",
    );
    expect(panelSource).not.toMatch(/in-progress/i);
    expect(screen.queryByTestId("in-progress-panel")).not.toBeInTheDocument();
  });
});
