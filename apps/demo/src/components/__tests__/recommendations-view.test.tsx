import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { useSearchParams } from "next/navigation";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DemoStateProvider } from "../demo-state";
import { RecommendationsView } from "../recommendations-view";
import { recommendationFixtures } from "../../lib/recommendations";

/**
 * Issue #1916 — the Optimize Product card designed as a before/after a
 * seller can read (v3 draft, owner decision 2026-09-14).
 *
 * The list card is horizontal: subject on the left of the header, workflow
 * category on the right, `Ưu tiên` on the first card only, and a preview
 * block carrying the change itself — so "Phê duyệt" is an informed click,
 * not a navigation. "Xem thêm" opens the detail BESIDE the list (never an
 * overlay or a modal — owner direction, stated twice), hides itself while
 * open, and "← Quay lại" restores the grid.
 */

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

function mockSearch(query = "") {
  vi.mocked(useSearchParams).mockReturnValue(
    new URLSearchParams(query) as unknown as ReturnType<typeof useSearchParams>,
  );
}

function renderView(props: ComponentProps<typeof RecommendationsView> = {}) {
  return render(
    <DemoStateProvider>
      <RecommendationsView {...props} />
    </DemoStateProvider>,
  );
}

function findCard(workflowKey: string): HTMLElement {
  const card = screen
    .getAllByRole("article")
    .find((node) => node.getAttribute("data-workflow-key") === workflowKey);
  if (!card) throw new Error(`Card not found: ${workflowKey}`);
  return card;
}

describe("Recommendation card — v3 anatomy (issue #1916)", () => {
  beforeEach(() => {
    mockSearch();
    localStorage.clear();
    sessionStorage.clear();
    push.mockClear();
    replace.mockClear();
  });

  it("reads subject on the left and workflow category on the right of every header", () => {
    renderView();

    for (const fixture of recommendationFixtures) {
      const card = findCard(fixture.workflowKey);

      // The subject — what the decision is about — is the card's heading.
      expect(
        within(card).getByRole("heading", { level: 3, name: fixture.subject }),
      ).toBeInTheDocument();

      // The workflow category names which workflow will run.
      const category = card.querySelector(
        ".juli-recommendation-card__category",
      );
      expect(category).not.toBeNull();
      expect(category).toHaveTextContent(fixture.title);
    }
  });

  it("marks Ưu tiên on the first card only", () => {
    renderView();

    const cards = screen.getAllByRole("article");
    expect(within(cards[0]).getByText("★ Ưu tiên")).toBeInTheDocument();
    for (const card of cards.slice(1)) {
      expect(within(card).queryByText("★ Ưu tiên")).not.toBeInTheDocument();
    }
  });

  it("carries a preview block naming the fields that will change, so approving is an informed click", () => {
    renderView();

    for (const fixture of recommendationFixtures) {
      const card = findCard(fixture.workflowKey);
      const preview = within(card).getByTestId("recommendation-preview");

      expect(fixture.previewRows.length).toBeGreaterThan(0);
      for (const row of fixture.previewRows) {
        expect(within(preview).getByText(row.label)).toBeInTheDocument();
        expect(within(preview).getByText(row.change)).toBeInTheDocument();
      }

      // At least one row states an actual change (never a card of only keeps).
      expect(fixture.previewRows.some((row) => row.kind === "change")).toBe(
        true,
      );
    }
  });

  it("offers exactly the three actions of the draft: Phê duyệt, Từ chối, Xem thêm", () => {
    renderView();

    const card = findCard(recommendationFixtures[0].workflowKey);
    expect(
      within(card).getByRole("button", { name: "Phê duyệt" }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Từ chối" }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Xem thêm" }),
    ).toBeInTheDocument();
    // The old in-card accordion is gone from this surface.
    expect(
      within(card).queryByRole("button", { name: "Mở rộng" }),
    ).not.toBeInTheDocument();
  });
});

describe("Xem thêm — the detail opens beside the list, never over it (issue #1916)", () => {
  beforeEach(() => {
    mockSearch();
    localStorage.clear();
    sessionStorage.clear();
    push.mockClear();
  });

  it("opens the detail beside the list: the split narrows, no dialog, no overlay", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[1];
    const card = findCard(fixture.workflowKey);

    const split = screen.getByTestId("decisions-split");
    expect(split).toHaveAttribute("data-detail-open", "false");

    await user.click(within(card).getByRole("button", { name: "Xem thêm" }));

    // Same region, side by side — never an overlay or a modal.
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.querySelector("[aria-modal]")).toBeNull();
    expect(split).toHaveAttribute("data-detail-open", "true");

    const detail = screen.getByRole("region", { name: "Chi tiết đề xuất" });
    expect(split.contains(detail)).toBe(true);
    expect(split.contains(card)).toBe(true);

    // The detail carries the full grounding for this recommendation.
    expect(within(detail).getByText(fixture.signal)).toBeInTheDocument();
    expect(within(detail).getByText(fixture.evidence)).toBeInTheDocument();
    expect(within(detail).getByText(fixture.eligibility)).toBeInTheDocument();
    expect(within(detail).getByText(fixture.knownLimits)).toBeInTheDocument();
    expect(within(detail).getByText(fixture.risks)).toBeInTheDocument();
  });

  it("hides Xem thêm on the open card while Phê duyệt and Từ chối stay", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[1];
    const card = findCard(fixture.workflowKey);

    await user.click(within(card).getByRole("button", { name: "Xem thêm" }));

    expect(
      within(card).queryByRole("button", { name: "Xem thêm" }),
    ).not.toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Phê duyệt" }),
    ).toBeInTheDocument();
    expect(
      within(card).getByRole("button", { name: "Từ chối" }),
    ).toBeInTheDocument();
  });

  it("moves focus into the detail on open, and Quay lại restores the grid and the card's focus", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[2];
    const card = findCard(fixture.workflowKey);

    await user.click(within(card).getByRole("button", { name: "Xem thêm" }));

    const detail = screen.getByRole("region", { name: "Chi tiết đề xuất" });
    await waitFor(() => expect(document.activeElement).toBe(detail));

    await user.click(within(detail).getByRole("button", { name: "Quay lại" }));

    expect(
      screen.queryByRole("region", { name: "Chi tiết đề xuất" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("decisions-split")).toHaveAttribute(
      "data-detail-open",
      "false",
    );
    expect(
      within(card).getByRole("button", { name: "Xem thêm" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(document.activeElement).toBe(card));
  });

  it("closes the detail when its card is rejected", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[3];
    const card = findCard(fixture.workflowKey);

    await user.click(within(card).getByRole("button", { name: "Xem thêm" }));
    expect(
      screen.getByRole("region", { name: "Chi tiết đề xuất" }),
    ).toBeInTheDocument();

    await user.click(within(card).getByRole("button", { name: "Từ chối" }));

    expect(
      screen.queryByRole("region", { name: "Chi tiết đề xuất" }),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("decisions-split")).toHaveAttribute(
      "data-detail-open",
      "false",
    );
  });

  it("keeps the list card's Phê duyệt as a navigation to the review route — the consent gate is untouched", async () => {
    const user = userEvent.setup();
    renderView();

    const fixture = recommendationFixtures[1];
    const card = findCard(fixture.workflowKey);
    await user.click(within(card).getByRole("button", { name: "Xem thêm" }));

    // With the detail open, approving still only navigates — nothing executes.
    await user.click(within(card).getByRole("button", { name: "Phê duyệt" }));
    expect(push).toHaveBeenCalledWith(
      `/decisions/recommendations/${fixture.workflowKey}`,
    );
  });
});

describe("Dictionary coverage for the new card strings (ADR-028)", () => {
  it("keys every new user-visible string in dictionary.md", () => {
    const dictionary = readFileSync(
      join(process.cwd(), "..", "..", "dictionary.md"),
      "utf8",
    );

    for (const term of ["Xem thêm", "Quay lại", "Chi tiết đề xuất"]) {
      expect(dictionary).toContain(term);
    }
  });
});
