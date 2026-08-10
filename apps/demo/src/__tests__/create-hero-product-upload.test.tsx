import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RecommendationReview } from "../components/recommendation-review";
import { CREATE_HERO_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { getCreateHeroProductPlanReview } from "../lib/workflows/create-hero-product/plan";
import { REVIEW_UI_BANNED_PATTERNS } from "../lib/review-seller-copy";
import {
  confirmApproveThroughGate,
  makeValidPngFile,
  selectUploadFile,
} from "./review-test-helpers";

/**
 * The upload exception, driven from the actual review route (#909).
 *
 * The original defect shipped because `FileUploadField` had green isolation
 * tests and nothing asserted it was reachable from a route — every review
 * route returned `input[type=file]` count 0. These tests render
 * `RecommendationReview` for `create_hero_product_1`, the public entry
 * point, and assert the resting card carries both uploads, blocks approval
 * until the required one is supplied, and never claims to be a security
 * gate (ADR-055 items 12 and 20).
 */

const IMAGE_ONLY_ACCEPT = "image/jpeg,image/png,image/webp,image/gif";

const push = vi.fn();
const mockStartExecution = vi.fn(
  (workflowKey: string) => `exec-${workflowKey}-1`,
);

let workflowReviewDrafts: Record<string, Record<string, string>> = {};

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  })),
  usePathname: vi.fn(() => "/decisions/recommendations/create_hero_product_1"),
  useSearchParams: vi.fn(),
}));

const mockStateListeners = new Set<() => void>();

function notifyMockStateListeners() {
  mockStateListeners.forEach((listener) => listener());
}

vi.mock("../components/demo-state", () => ({
  DemoStateProvider: ({ children }: { children: ReactNode }) => children,
  useDemoState: () => {
    const [, setTick] = useState(0);

    useEffect(() => {
      const listener = () => setTick((tick) => tick + 1);
      mockStateListeners.add(listener);
      return () => {
        mockStateListeners.delete(listener);
      };
    }, []);

    return {
      feedback: null,
      mode: "mock" as const,
      mutableState: {
        rejectedRecommendationIds: [],
        approvedRecommendationIds: [],
        workflowInputs: {},
        workflowReviewDrafts,
        executionRecords: {},
        executionProgress: {},
        decisionsView: "recommendations" as const,
        analyticsMetric: "net-revenue",
        analyticsRange: "30d" as const,
        settingsDraft: {},
      },
      recommendationContext: null,
      requestSignIn: vi.fn(),
      resetMockState: vi.fn(),
      setRecommendationContext: vi.fn(),
      startExecution: mockStartExecution,
      updateMutableState: (
        updater:
          | ((current: {
              workflowReviewDrafts: Record<string, Record<string, string>>;
            }) => {
              workflowReviewDrafts: Record<string, Record<string, string>>;
            })
          | {
              workflowReviewDrafts: Record<string, Record<string, string>>;
            },
      ) => {
        const current = { workflowReviewDrafts };
        const resolved =
          typeof updater === "function" ? updater(current) : updater;
        workflowReviewDrafts = resolved.workflowReviewDrafts;
        notifyMockStateListeners();
      },
    };
  },
}));

function renderHeroReview() {
  return render(
    <RecommendationReview workflowKey={CREATE_HERO_PRODUCT_WORKFLOW_KEY} />,
  );
}

function getFileInputs(container: HTMLElement): HTMLInputElement[] {
  return Array.from(
    container.querySelectorAll<HTMLInputElement>('input[type="file"]'),
  );
}

function getMainImagesInput(): HTMLInputElement {
  return screen.getByLabelText(/Ảnh sản phẩm/) as HTMLInputElement;
}

function getSupportingFileInput(): HTMLInputElement {
  return screen.getByLabelText(
    /Tệp hỗ trợ \(nếu danh mục yêu cầu\)/,
  ) as HTMLInputElement;
}

beforeEach(() => {
  workflowReviewDrafts = {};
  mockStateListeners.clear();
  push.mockClear();
  mockStartExecution.mockClear();
  vi.mocked(useRouter).mockReturnValue({
    back: vi.fn(),
    forward: vi.fn(),
    prefetch: vi.fn(),
    push,
    refresh: vi.fn(),
    replace: vi.fn(),
  });
  // Deterministic image decode in jsdom, mirroring the @juli/ui suite.
  vi.stubGlobal(
    "createImageBitmap",
    vi.fn(async () => ({ close: vi.fn() }) as unknown as ImageBitmap),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("create_hero_product_1 upload exception — reachable from the review route", () => {
  it("renders both uploads at rest on the plan-review card, inside the needs-you section", () => {
    const { container } = renderHeroReview();

    // The route lands on the plan-review spine, not the five-stage review.
    expect(screen.getByTestId("plan-review-card")).toBeInTheDocument();
    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();

    // Both uploads present at rest — no expansion needed to find them.
    expect(getFileInputs(container)).toHaveLength(2);
    const needsYou = screen.getByTestId("plan-needs-you");
    expect(getFileInputs(needsYou)).toHaveLength(2);
  });

  it("places the needs-you section between the Decision section and the approve action", () => {
    renderHeroReview();

    const decision = screen.getByTestId("plan-decision");
    const needsYou = screen.getByTestId("plan-needs-you");
    const approveButton = screen.getByRole("button", { name: "Phê duyệt" });

    // Document order: Decision → needs-you → Phê duyệt. The section reads as
    // the thing standing between the seller and approval, never a footnote
    // after the action.
    expect(
      decision.compareDocumentPosition(needsYou) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      needsYou.compareDocumentPosition(approveButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("keeps both fields image-only and marks only main_images required", () => {
    renderHeroReview();

    const mainImages = getMainImagesInput();
    const supportingFile = getSupportingFileInput();

    // Item 20: image-only on BOTH fields — a PDF certificate must be
    // photographed. The allowlist is deliberate and must not widen.
    expect(mainImages).toHaveAttribute("accept", IMAGE_ONLY_ACCEPT);
    expect(supportingFile).toHaveAttribute("accept", IMAGE_ONLY_ACCEPT);

    expect(mainImages).toBeRequired();
    expect(supportingFile).not.toBeRequired();
  });

  it("proposes nothing for either upload — no value, no suggestion badge, no placeholder imagery", () => {
    renderHeroReview();

    const needsYou = screen.getByTestId("plan-needs-you");

    for (const input of getFileInputs(needsYou)) {
      expect(input.value).toBe("");
      expect(input).not.toHaveAttribute("placeholder");
    }
    // Juli pre-commits every other field; here it proposes nothing, so the
    // suggestion badge must not appear.
    expect(within(needsYou).queryByText("Gợi ý bởi Juli")).toBeNull();
    expect(within(needsYou).queryByRole("img")).toBeNull();
  });

  it("explains why Juli cannot propose here and what happens next — never a bare empty form", () => {
    renderHeroReview();

    const plan = getCreateHeroProductPlanReview();
    const needsYou = screen.getByTestId("plan-needs-you");

    expect(needsYou).toHaveTextContent(plan.needsYou!.title);
    expect(needsYou).toHaveTextContent(plan.needsYou!.explanation);
    expect(needsYou).toHaveTextContent(plan.needsYou!.approvalBlockedText);
  });

  it("keeps the needs-you copy free of system vocabulary and of any security-gate claim", () => {
    renderHeroReview();

    const surfaces = [
      screen.getByTestId("plan-needs-you").textContent ?? "",
      screen.getByTestId("plan-review-card").textContent ?? "",
    ];

    // REVIEW_UI_BANNED_PATTERNS includes the false-security set (virus,
    // antivirus, malware, "an toàn") — asserted explicitly below so a future
    // trim of the shared list cannot silently drop the claim.
    const securityClaimPatterns = [
      /\bvirus\b/i,
      /antivirus/i,
      /malware/i,
      /\ban toàn\b/i,
    ];

    for (const text of surfaces) {
      for (const pattern of REVIEW_UI_BANNED_PATTERNS) {
        expect(text).not.toMatch(pattern);
      }
      for (const pattern of securityClaimPatterns) {
        expect(text).not.toMatch(pattern);
      }
    }
  });

  it("disables Phê duyệt while main_images is empty and never fires startExecution", async () => {
    const user = userEvent.setup();

    renderHeroReview();

    const approveButton = screen.getByRole("button", { name: "Phê duyệt" });
    expect(approveButton).toBeDisabled();
    expect(approveButton).toHaveAccessibleDescription(
      getCreateHeroProductPlanReview().needsYou!.approvalBlockedText,
    );

    await user.click(approveButton);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mockStartExecution).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("unblocks approval on main_images alone — an empty supporting_file does not block", async () => {
    const user = userEvent.setup();

    renderHeroReview();

    selectUploadFile(getMainImagesInput(), makeValidPngFile("serum.png"));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Phê duyệt" })).toBeEnabled();
    });
    // The optional field is still empty; the blocking line is gone.
    expect(getSupportingFileInput().value).toBe("");
    expect(screen.queryByTestId("plan-approve-blocked")).toBeNull();

    await confirmApproveThroughGate(user);

    expect(mockStartExecution).toHaveBeenCalledTimes(1);
    expect(mockStartExecution).toHaveBeenCalledWith(
      CREATE_HERO_PRODUCT_WORKFLOW_KEY,
    );
    expect(push).toHaveBeenCalledWith(
      `/decisions/in-progress/exec-${CREATE_HERO_PRODUCT_WORKFLOW_KEY}-1`,
    );
  });

  it("stays blocked when the picked file fails the image check", async () => {
    renderHeroReview();

    // PDF bytes under a .pdf name — the upload control rejects it, so the
    // required field stays unsatisfied and approval stays blocked.
    const notAnImage = new File(
      [new Uint8Array([0x25, 0x50, 0x44, 0x46])],
      "certificate.pdf",
      { type: "application/pdf" },
    );
    selectUploadFile(getMainImagesInput(), notAnImage);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: "Phê duyệt" })).toBeDisabled();
    expect(screen.getByTestId("plan-approve-blocked")).toBeInTheDocument();
  });
});
