import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSearchParams } from "next/navigation";
import type { ComponentProps } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../components/demo-state";
import { DemoShell } from "../components/demo-shell";
import { RecommendationsView } from "../components/recommendations-view";
import { recommendationFixtures } from "../lib/recommendations";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: vi.fn(),
  usePathname: vi.fn(() => "/decisions"),
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace,
  })),
}));

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

describe("Decisions — Recommendations", () => {
  beforeEach(() => {
    mockHighlight();
    localStorage.clear();
    push.mockClear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders Workflow 1 as the Priority Card first, followed by 2-9 in stable spec order", () => {
    renderView();

    const cards = screen.getAllByRole("article");

    expect(cards.map((card) => card.getAttribute("data-workflow-key"))).toEqual(
      recommendationFixtures.map((fixture) => fixture.workflowKey),
    );
    expect(within(cards[0]).getByText("★ Ưu tiên")).toBeInTheDocument();
    expect(within(cards[1]).queryByText("★ Ưu tiên")).not.toBeInTheDocument();
  });

  it("never re-ranks by expected impact — order stays 1..9 regardless of differing impact values", () => {
    renderView();

    const cards = screen.getAllByRole("article");
    const impactKinds = recommendationFixtures.map((fixture) =>
      fixture.expectedImpactLabel === "—" ? "dash" : "value",
    );

    // The fixtures intentionally mix "—" and formatted-VND/count impacts; a
    // ranking-by-impact implementation would reorder them. Confirm it doesn't.
    expect(impactKinds).toContain("dash");
    expect(impactKinds).toContain("value");
    expect(cards.map((card) => card.getAttribute("data-workflow-key"))).toEqual(
      recommendationFixtures.map((fixture) => fixture.workflowKey),
    );
  });

  it("does not invent a monetary impact for inventory replenishment without a real forecast", () => {
    const replenishment = recommendationFixtures.find(
      (fixture) =>
        fixture.workflowKey === "replenish_inventory_3", // gitleaks:allow — documented mock workflow key
    );

    expect(replenishment?.expectedImpactLabel).toBe("—");
  });

  it("shows title, signal, and one concise benefit-led reason on every card", () => {
    renderView();

    recommendationFixtures.forEach((fixture) => {
      const card = findCard(fixture.workflowKey) as HTMLElement;

      expect(
        within(card).getByRole("heading", { level: 3, name: fixture.title }),
      ).toBeInTheDocument();
      expect(card).toHaveTextContent(fixture.signal);
      expect(card).toHaveTextContent(fixture.sellerReason);
      expect(card).not.toHaveTextContent(fixture.confidenceLabel);
      expect(card).not.toHaveTextContent(fixture.capabilityLabel);
      expect(card.textContent).not.toContain("Tác động dự kiến:");
    });
  });

  it("routes list title links to the recommendation detail page", () => {
    renderView();

    const fixture = recommendationFixtures[0];
    const card = findCard(fixture.workflowKey) as HTMLElement;
    const titleLink = within(card).getByRole("link", { name: fixture.title });

    expect(titleLink).toHaveAttribute(
      "href",
      `/decisions/recommendations/${fixture.workflowKey}`,
    );
  });

  it("Expand reveals evidence, eligibility, known limits, and risks; collapsing hides them again", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[0];
    const card = findCard(fixture.workflowKey) as HTMLElement;
    const disclosure = within(card).getByRole("button", { name: "Mở rộng" });

    expect(disclosure).toHaveAttribute("aria-expanded", "false");
    expect(within(card).queryByText(fixture.evidence)).not.toBeInTheDocument();

    await user.click(disclosure);

    expect(disclosure).toHaveAttribute("aria-expanded", "true");
    expect(within(card).getByText(fixture.evidence)).toBeInTheDocument();
    expect(within(card).getByText(fixture.eligibility)).toBeInTheDocument();
    expect(within(card).getByText(fixture.knownLimits)).toBeInTheDocument();
    expect(within(card).getByText(fixture.risks)).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Thu gọn" }));

    expect(
      within(card).getByRole("button", { name: "Mở rộng" }),
    ).toHaveAttribute("aria-expanded", "false");
    expect(within(card).queryByText(fixture.evidence)).not.toBeInTheDocument();
  });

  it("reject and expand interactions behave with improved seller copy", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[1];
    const card = findCard(fixture.workflowKey) as HTMLElement;

    await user.click(within(card).getByRole("button", { name: "Mở rộng" }));
    expect(within(card).getByText(fixture.evidence)).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Từ chối" }));

    expect(findCard(fixture.workflowKey)).toBeUndefined();
    expect(screen.getByRole("status")).toHaveTextContent(
      `Đã từ chối đề xuất ${fixture.title}.`,
    );
  });

  it("removes a card immediately on Reject while leaving the rest unchanged", async () => {
    const user = userEvent.setup();
    renderView();

    const target = recommendationFixtures[2];
    const card = findCard(target.workflowKey) as HTMLElement;

    await user.click(within(card).getByRole("button", { name: "Từ chối" }));

    const remaining = screen.getAllByRole("article");
    expect(remaining).toHaveLength(recommendationFixtures.length - 1);
    expect(findCard(target.workflowKey)).toBeUndefined();
    expect(remaining.map((el) => el.getAttribute("data-workflow-key"))).toEqual(
      recommendationFixtures
        .filter((fixture) => fixture.workflowKey !== target.workflowKey)
        .map((fixture) => fixture.workflowKey),
    );
  });

  it("persists rejection until Manual Refresh instead of restoring it on remount", async () => {
    const user = userEvent.setup();
    const target = recommendationFixtures[2];
    const firstRender = renderView();
    const card = findCard(target.workflowKey) as HTMLElement;

    await user.click(within(card).getByRole("button", { name: "Từ chối" }));
    firstRender.unmount();
    renderView();

    await waitFor(() => {
      expect(findCard(target.workflowKey)).toBeUndefined();
    });
  });

  it("announces rejection and restores focus to the recommendations panel", async () => {
    const user = userEvent.setup();
    renderView();

    const target = recommendationFixtures[1];
    const card = findCard(target.workflowKey) as HTMLElement;

    await user.click(within(card).getByRole("button", { name: "Từ chối" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      `Đã từ chối đề xuất ${target.title}.`,
    );
    await waitFor(() => {
      expect(document.activeElement).toBe(
        screen.getByLabelText("Đề xuất", { selector: "div" }),
      );
    });
  });

  it("shows a truthful empty state that keeps navigation reachable after rejecting all nine", async () => {
    const user = userEvent.setup();
    renderView();

    for (const fixture of recommendationFixtures) {
      const card = findCard(fixture.workflowKey) as HTMLElement;
      await user.click(within(card).getByRole("button", { name: "Từ chối" }));
    }

    expect(screen.queryAllByRole("article")).toHaveLength(0);

    const empty = screen.getByRole("status", { name: "Đề xuất" });
    expect(empty).toHaveTextContent("Không có đề xuất nào cần xem xét");
    expect(empty).toHaveTextContent("chưa có tín hiệu nào cần bạn xem xét");

    const analyticsLink = screen.getByRole("link", { name: "Mở Phân tích" });
    expect(analyticsLink).toHaveAttribute("href", "/analytics");
  });

  it("renders Approve as disabled for workflows without a review shell, with an associated explanation", () => {
    renderView();

    const executableKeys = new Set([
      "create_hero_product_1",
      "optimize_product_2",
      "replenish_inventory_3", // gitleaks:allow — documented mock workflow key
      "clear_excess_4",
      "process_order_5",
      "create_activity_7a",
      "update_activity_7c",
      "delete_activity_7b",
      "prevent_cancellation_8a",
      "prevent_return_8b",
      "prevent_refund_8c",
    ]);

    recommendationFixtures
      .filter((fixture) => !executableKeys.has(fixture.workflowKey))
      .forEach((fixture) => {
        const card = findCard(fixture.workflowKey) as HTMLElement;
        const approveButton = within(card).getByRole("button", {
          name: "Phê duyệt",
        });

        expect(approveButton).toBeDisabled();

        const describedBy = approveButton.getAttribute("aria-describedby");
        expect(describedBy).toBeTruthy();

        const explanation = card.querySelector(`#${describedBy}`);
        expect(explanation).not.toBeNull();
        expect(explanation?.textContent ?? "").toMatch(/Phê duyệt/);
        expect((explanation?.textContent ?? "").length).toBeGreaterThan(20);
      });
  });

  it("enables Approve for Workflow 1 and workflows 7–9 and routes to the review page", async () => {
    const user = userEvent.setup();
    renderView();

    const executableFixtures = recommendationFixtures.filter((fixture) =>
      [
        "create_hero_product_1",
        "optimize_product_2",
        "replenish_inventory_3", // gitleaks:allow — documented mock workflow key
        "clear_excess_4",
        "process_order_5",
        "create_activity_7a",
        "update_activity_7c",
        "delete_activity_7b",
        "prevent_cancellation_8a",
        "prevent_return_8b",
        "prevent_refund_8c",
      ].includes(fixture.workflowKey),
    );

    for (const fixture of executableFixtures) {
      push.mockClear();
      const card = findCard(fixture.workflowKey) as HTMLElement;
      const approveButton = within(card).getByRole("button", {
        name: "Phê duyệt",
      });

      expect(approveButton).toBeEnabled();
      expect(approveButton).not.toHaveAttribute("aria-describedby");

      await user.click(approveButton);

      expect(push).toHaveBeenCalledWith(
        `/decisions/recommendations/${fixture.workflowKey}`,
      );
    }
  });

  it("renders a recoverable error state and retries without leaving Decisions", async () => {
    const user = userEvent.setup();
    renderView({ initialLoadState: "error" });

    expect(
      screen.getByRole("alert", { name: "Lỗi tải đề xuất" }),
    ).toHaveTextContent("Không thể tải đề xuất mẫu");

    await user.click(screen.getByRole("button", { name: "Thử lại" }));

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getAllByRole("article")).toHaveLength(
      recommendationFixtures.length,
    );
  });

  it("supplies active recommendation evidence and risks to contextual assistance", async () => {
    const target = recommendationFixtures[4];
    mockHighlight(`highlight=${target.workflowKey}`);

    render(
      <DemoShell>
        <RecommendationsView />
      </DemoShell>,
    );

    const assistance = screen.getByRole("complementary", {
      name: "Gợi ý từ Juli",
    });

    await waitFor(() => {
      expect(assistance).toHaveTextContent(target.title);
      expect(assistance).toHaveTextContent(target.evidence);
      expect(assistance).toHaveTextContent(target.risks);
    });
  });

  it("focuses and visibly marks the matching card for ?highlight=<workflow_key>", () => {
    const target = recommendationFixtures[4];
    mockHighlight(`highlight=${target.workflowKey}`);

    renderView();

    const card = findCard(target.workflowKey) as HTMLElement;

    expect(card).toBeTruthy();
    expect(document.activeElement).toBe(card);
    expect(within(card).getByText("Đang xem")).toBeInTheDocument();
  });

  it("respects prefers-reduced-motion by scrolling without smooth behavior", () => {
    const target = recommendationFixtures[4];
    mockHighlight(`highlight=${target.workflowKey}`);
    vi.mocked(window.matchMedia).mockReturnValue({
      addEventListener: vi.fn(),
      addListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      removeEventListener: vi.fn(),
      removeListener: vi.fn(),
    } as unknown as MediaQueryList);
    const scrollSpy = vi.spyOn(Element.prototype, "scrollIntoView");

    renderView();

    expect(scrollSpy).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
  });

  it("does not crash or wrongly highlight anything for a non-matching ?highlight= value", () => {
    mockHighlight("highlight=not_a_real_workflow_key");

    renderView();

    const cards = screen.getAllByRole("article");
    expect(cards).toHaveLength(recommendationFixtures.length);
    expect(screen.queryByText("Đang xem")).not.toBeInTheDocument();
    expect(document.activeElement).not.toBe(cards[0]);
  });

  it("supports keyboard-driven interaction for Reject via userEvent", async () => {
    const user = userEvent.setup();
    renderView();

    const target = recommendationFixtures[1];
    const card = findCard(target.workflowKey) as HTMLElement;
    const rejectButton = within(card).getByRole("button", { name: "Từ chối" });

    rejectButton.focus();
    expect(document.activeElement).toBe(rejectButton);

    await user.keyboard("{Enter}");

    expect(findCard(target.workflowKey)).toBeUndefined();
  });

  it("supports touch pointer interaction for Expand", async () => {
    const user = userEvent.setup();
    renderView();

    const firstCard = screen.getAllByRole("article")[0];
    const expand = within(firstCard).getByRole("button", { name: "Mở rộng" });

    await user.pointer([
      { keys: "[TouchA>]", target: expand },
      { keys: "[/TouchA]" },
    ]);

    expect(expand).toHaveAttribute("aria-expanded", "true");
  });

  it("makes no backend request or real write anywhere in the recommendations flow", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    renderView();

    const firstCard = screen.getAllByRole("article")[0];
    await user.click(within(firstCard).getByRole("button", { name: "Mở rộng" }));
    await user.click(within(firstCard).getByRole("button", { name: "Từ chối" }));

    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("tests empty, error, keyboard, touch, and reduced-motion states", async () => {
    const user = userEvent.setup();
    const firstRender = renderView();
    const keyboardTarget = recommendationFixtures[1];
    const keyboardCard = findCard(keyboardTarget.workflowKey) as HTMLElement;
    const rejectButton = within(keyboardCard).getByRole("button", {
      name: "Từ chối",
    });

    rejectButton.focus();
    await user.keyboard("{Enter}");

    const touchCard = screen.getAllByRole("article")[0];
    const expand = within(touchCard).getByRole("button", { name: "Mở rộng" });
    await user.pointer([
      { keys: "[TouchA>]", target: expand },
      { keys: "[/TouchA]" },
    ]);
    expect(expand).toHaveAttribute("aria-expanded", "true");

    for (const card of screen.getAllByRole("article")) {
      await user.click(within(card).getByRole("button", { name: "Từ chối" }));
    }
    expect(
      screen.getByRole("status", { name: "Đề xuất" }),
    ).toHaveTextContent("Không có đề xuất nào cần xem xét");
    firstRender.unmount();

    localStorage.clear();
    const errorRender = renderView({ initialLoadState: "error" });
    expect(
      screen.getByRole("alert", { name: "Lỗi tải đề xuất" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    errorRender.unmount();

    const reducedMotionTarget = recommendationFixtures[4];
    mockHighlight(`highlight=${reducedMotionTarget.workflowKey}`);
    vi.mocked(window.matchMedia).mockReturnValue({
      addEventListener: vi.fn(),
      addListener: vi.fn(),
      dispatchEvent: vi.fn(),
      matches: true,
      media: "(prefers-reduced-motion: reduce)",
      onchange: null,
      removeEventListener: vi.fn(),
      removeListener: vi.fn(),
    } as unknown as MediaQueryList);
    const scrollSpy = vi.spyOn(Element.prototype, "scrollIntoView");

    renderView();

    expect(scrollSpy).toHaveBeenCalledWith(
      expect.objectContaining({ behavior: "auto" }),
    );
  });

  describe("Header density — stat row", () => {
    it("renders a stat row directly under the header showing open recommendations and in-progress counts", () => {
      renderView();

      const statRow = screen.queryByRole("region", {
        name: /Tóm tắt quyết định/i,
      });
      expect(statRow).toBeInTheDocument();
    });

    it("displays open recommendations count (all fixtures minus rejected/approved)", () => {
      renderView();

      const allCount = recommendationFixtures.length;
      const statRow = screen.queryByRole("region", {
        name: /Tóm tắt quyết định/i,
      });

      expect(statRow?.textContent).toMatch(new RegExp(String(allCount)));
    });

    it("displays in-progress count (0 on fresh render)", () => {
      renderView();

      const statRow = screen.queryByRole("region", {
        name: /Tóm tắt quyết định/i,
      });
      expect(statRow?.textContent).toMatch("0");
    });

    it("updates open count after rejecting a recommendation", async () => {
      const user = userEvent.setup();
      renderView();

      const card = findCard(recommendationFixtures[0].workflowKey) as HTMLElement;
      await user.click(within(card).getByRole("button", { name: "Từ chối" }));

      const statRow = screen.queryByRole("region", {
        name: /Tóm tắt quyết định/i,
      });
      expect(statRow?.textContent).toMatch(
        new RegExp(String(recommendationFixtures.length - 1)),
      );
    });

    it("stat row contains no interactive elements (buttons or links)", () => {
      renderView();

      const statRow = screen.queryByRole("region", {
        name: /Tóm tắt quyết định/i,
      });
      expect(statRow).toBeInTheDocument();

      const buttons = statRow?.querySelectorAll("button");
      const links = statRow?.querySelectorAll("a");

      expect(buttons?.length ?? 0).toBe(0);
      expect(links?.length ?? 0).toBe(0);
    });

    it("stat row labels fit within 3-word budget per stat", () => {
      renderView();

      const statRow = screen.queryByRole("region", {
        name: /Tóm tắt quyết định/i,
      });
      const text = statRow?.textContent ?? "";

      // Labels should be concise: "Đề xuất mở" (2 words) and "Đang thực hiện" (2 words)
      const labels = text.split(/[\n\t]+/).filter((t) => t.trim().length > 0);
      expect(labels.some((l) => l.length <= 30)).toBe(true); // ~3 words
    });
  });

  describe("Layout density — intro paragraph removal", () => {
    it("does not render the standalone demo-intro paragraph", () => {
      renderView();

      const introParagraph = screen.queryByText(
        /Xem các đề xuất Juli phát hiện được/,
      );
      expect(introParagraph).not.toBeInTheDocument();
    });

    it("preserves kicker and title while removing intro", () => {
      renderView();

      expect(screen.getByText("Quyết định")).toBeInTheDocument();
      expect(
        screen.getByRole("heading", { name: "Việc cần bạn quyết định" }),
      ).toBeInTheDocument();
    });
  });

  describe("Sub-tab deep linking via ?tab= query param", () => {
    it("renders Recommendations tab active by default (/decisions)", () => {
      mockHighlight("");
      renderView();

      const recTab = screen.getByRole("button", { name: "Đề xuất" });
      expect(recTab).toHaveAttribute("aria-pressed", "true");
    });

    it("renders In Progress tab active when /decisions?tab=in-progress", () => {
      mockHighlight("tab=in-progress");
      renderView();

      const inProgressTab = screen.getByRole("button", {
        name: "Đang thực hiện",
      });
      expect(inProgressTab).toHaveAttribute("aria-pressed", "true");
    });

    it("renders Recommendations tab active when /decisions?tab=recommendations", () => {
      mockHighlight("tab=recommendations");
      renderView();

      const recTab = screen.getByRole("button", { name: "Đề xuất" });
      expect(recTab).toHaveAttribute("aria-pressed", "true");
    });

    it("falls back to Recommendations for unknown ?tab= values", () => {
      mockHighlight("tab=unknown_value");
      renderView();

      const recTab = screen.getByRole("button", { name: "Đề xuất" });
      expect(recTab).toHaveAttribute("aria-pressed", "true");
    });

    it("clicking Recommendations tab updates URL with ?tab=recommendations", async () => {
      const user = userEvent.setup();
      mockHighlight("tab=in-progress");
      replace.mockClear();
      renderView();

      const recTab = screen.getByRole("button", { name: "Đề xuất" });
      await user.click(recTab);

      expect(replace).toHaveBeenCalledWith(expect.stringContaining("tab="));
    });

    it("clicking In Progress tab updates URL with ?tab=in-progress", async () => {
      const user = userEvent.setup();
      mockHighlight("");
      replace.mockClear();
      renderView();

      const inProgressTab = screen.getByRole("button", {
        name: "Đang thực hiện",
      });
      await user.click(inProgressTab);

      expect(replace).toHaveBeenCalledWith(expect.stringContaining("tab="));
    });

    it("combines ?tab= with existing ?highlight= param", () => {
      const target = recommendationFixtures[4];
      mockHighlight(`tab=recommendations&highlight=${target.workflowKey}`);
      renderView();

      const recTab = screen.getByRole("button", { name: "Đề xuất" });
      expect(recTab).toHaveAttribute("aria-pressed", "true");
      expect(document.activeElement).toBe(findCard(target.workflowKey));
    });

    it("mutableState.decisionsView stays in sync with URL ?tab= param", async () => {
      const user = userEvent.setup();
      mockHighlight("tab=in-progress");
      const { unmount } = renderView();

      const inProgressTab = screen.getByRole("button", {
        name: "Đang thực hiện",
      });
      expect(inProgressTab).toHaveAttribute("aria-pressed", "true");

      unmount();
      mockHighlight("");
      renderView();

      const recTab = screen.getByRole("button", { name: "Đề xuất" });
      expect(recTab).toHaveAttribute("aria-pressed", "true");
    });
  });
});
