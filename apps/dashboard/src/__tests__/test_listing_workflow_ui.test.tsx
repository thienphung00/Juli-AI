/**
 * Issue #155 — E2E listing workflow UI (P1.6-2)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fs from "fs";
import path from "path";
import { TaskQueue } from "@/components/tasks/TaskQueue";
import { api } from "@/lib/api-client";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { filterOpportunities } from "@/lib/workflows/new-seller/listing";
import { loadOpportunities } from "@/lib/mock-data/listing-workflow";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import {
  BASELINE_ACTIVE_LISTING_COUNT,
  clearShopProgress,
  loadShopProgress,
} from "@/lib/workflows/new-seller/shop-progress";
import { NewSellerCopilotPanel } from "@/components/workflows/new-seller/NewSellerCopilotPanel";

jest.mock("@/lib/api-client", () => ({
  api: {
    auth: { sendOtp: jest.fn(), verifyOtp: jest.fn() },
    shops: { list: jest.fn(), me: jest.fn() },
    orders: { list: jest.fn(), confirmShipment: jest.fn() },
    products: { list: jest.fn() },
    inventory: { list: jest.fn() },
    livestreams: { list: jest.fn() },
    creators: { list: jest.fn() },
    alerts: { history: jest.fn(), upsertConfig: jest.fn() },
    recommendations: { list: jest.fn() },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
      this.name = "ApiError";
    }
  },
}));

const persona = loadPersona("new");
const listProductsTask = persona.tasks.find((task) => task.type === "list_products")!;
const shopSetupTask = persona.tasks.find((task) => task.type === "shop_setup")!;

const PATH_B_FILTER_CONSTRAINTS = {
  category: "Mỹ phẩm",
  maxCapitalVnd: 20_000_000,
  dropshipOnly: true,
};

const EXPECTED_PATH_B_OPPORTUNITY_IDS = [
  "b2000001-0001-4000-8000-000000000001",
];

async function completePathAToDraftReview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("listing-path-a"));
  await waitFor(() => {
    expect(screen.getByTestId("listing-step-product_form")).toBeInTheDocument();
  });

  await user.click(screen.getByTestId("listing-next"));

  await waitFor(() => {
    expect(screen.getByTestId("listing-step-distributor_pick")).toBeInTheDocument();
  });

  await user.click(
    screen.getByTestId("listing-distributor-a1000001-0001-4000-8000-000000000001"),
  );
  await user.click(screen.getByTestId("listing-next"));

  await waitFor(() => {
    expect(screen.getByTestId("listing-draft-review")).toBeInTheDocument();
  });
}

async function completePathBToDraftReview(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByTestId("listing-path-b"));
  await waitFor(() => {
    expect(screen.getByTestId("listing-step-constraints")).toBeInTheDocument();
  });

  await user.click(screen.getByTestId("listing-next"));
  await waitFor(() => {
    expect(screen.getByTestId("listing-step-opportunity_browse")).toBeInTheDocument();
  });

  await user.click(
    screen.getByTestId(`listing-opportunity-card-${EXPECTED_PATH_B_OPPORTUNITY_IDS[0]}`),
  );
  await user.click(screen.getByTestId("listing-next"));

  await waitFor(() => {
    expect(screen.getByTestId("listing-step-distributor_pick")).toBeInTheDocument();
  });

  await user.click(
    screen.getByTestId("listing-distributor-a1000001-0001-4000-8000-000000000001"),
  );
  await user.click(screen.getByTestId("listing-next"));
  await waitFor(() => {
    expect(screen.getByTestId("listing-draft-review")).toBeInTheDocument();
  });
}

beforeEach(() => {
  jest.clearAllMocks();
  clearTaskExecutorSession();
  clearShopProgress("new");
  sessionStorage.clear();

  global.URL.createObjectURL = jest.fn(() => "blob:mock-url");
  global.URL.revokeObjectURL = jest.fn();
  HTMLAnchorElement.prototype.click = jest.fn();
});

async function approveListProducts(user: ReturnType<typeof userEvent.setup>) {
  render(<TaskQueue tasks={[listProductsTask]} personaId="new" />);
  await user.click(screen.getByTestId("task-approve"));
  await waitFor(() => {
    expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
  });
}

describe("Issue #155: listing workflow entry", () => {
  it("opens listing workflow when list_products is approved", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);
    expect(screen.getByTestId("listing-step-path_selection")).toBeInTheDocument();
    expect(screen.getByTestId("listing-workflow")).toHaveClass("z-[100]");
    expect(screen.getByTestId("task-feedback-approved")).toHaveTextContent(
      "quy trình đăng sản phẩm",
    );
  });

  it("keeps Phase 1 no-op feedback for non-list_products tasks", async () => {
    const user = userEvent.setup();
    render(<TaskQueue tasks={[shopSetupTask]} personaId="new" />);

    await user.click(screen.getByTestId("task-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toHaveTextContent(
        "chưa thực thi trên TikTok",
      );
    });
    expect(screen.queryByTestId("listing-workflow")).not.toBeInTheDocument();
  });
});

describe("Issue #155: Path A listing workflow", () => {
  it("enables Tiếp theo immediately after Path A selection with visible inputs", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);

    await user.click(screen.getByTestId("listing-path-a"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-product_form")).toBeInTheDocument();
    });

    expect(screen.getByTestId("listing-product-name")).toBeVisible();
    expect(screen.getByTestId("listing-next")).toBeEnabled();
  });

  it("reaches draft review with generated draft from rules engine", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);
    await completePathAToDraftReview(user);

    const review = screen.getByTestId("listing-draft-review");
    expect(within(review).getByText("Serum Vitamin C 20ml")).toBeInTheDocument();
    expect(within(review).getByTestId("listing-draft-status")).toHaveTextContent(
      "ready_for_export",
    );
    expect(within(review).getByTestId("listing-compliance-status")).toHaveTextContent(
      "approved",
    );
  });

  it("preserves session data when navigating back from distributor pick", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);

    await user.click(screen.getByTestId("listing-path-a"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-product-name")).toBeInTheDocument();
    });

    const nameInput = screen.getByTestId("listing-product-name");
    await user.clear(nameInput);
    await user.type(nameInput, "Kem dưỡng ẩm đêm");

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-distributor_pick")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-back"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-product_form")).toBeInTheDocument();
    });

    expect(screen.getByTestId("listing-product-name")).toHaveValue("Kem dưỡng ẩm đêm");
  });
});

describe("Issue #155: Path B opportunity filter", () => {
  it("returns deterministic card set for fixed constraints", () => {
    const filtered = filterOpportunities(
      loadOpportunities(),
      PATH_B_FILTER_CONSTRAINTS,
    );
    expect(filtered.map((item) => item.opportunity_id)).toEqual(
      EXPECTED_PATH_B_OPPORTUNITY_IDS,
    );
  });

  it("shows filtered opportunities in the browse step", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);

    await user.click(screen.getByTestId("listing-path-b"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-constraints")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-opportunity_browse")).toBeInTheDocument();
    });

    for (const id of EXPECTED_PATH_B_OPPORTUNITY_IDS) {
      expect(
        screen.getByTestId(`listing-opportunity-card-${id}`),
      ).toBeInTheDocument();
    }

    expect(screen.queryByTestId("listing-opportunity-card-b2000002-0002-4000-8000-000000000002")).not.toBeInTheDocument();
  });
});

describe("Issue #156: listing export execute step", () => {
  it("Path A E2E export succeeds with Seller Center upload success message", async () => {
    const user = userEvent.setup();
    const analyticsEvents: CustomEvent[] = [];
    const onAnalytics = (event: Event) => {
      analyticsEvents.push(event as CustomEvent);
    };
    window.addEventListener("juli:analytics", onAnalytics);

    await approveListProducts(user);
    await completePathAToDraftReview(user);

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-export-execute")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-export-download"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-export-success")).toBeInTheDocument();
    });

    expect(screen.getByTestId("listing-export-success")).toHaveTextContent(
      "Seller Center",
    );
    expect(global.URL.createObjectURL).toHaveBeenCalled();

    const exportEvent = analyticsEvents.find(
      (event) => event.detail?.event === "export_completed",
    );
    expect(exportEvent?.detail).toMatchObject({
      event: "export_completed",
      task_type: "list_products",
      format: "json",
    });

    window.removeEventListener("juli:analytics", onAnalytics);
  });

  it("Path B E2E — complete Path B and export succeeds", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);
    await completePathBToDraftReview(user);

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-export-execute")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-export-format-csv"));
    await user.click(screen.getByTestId("listing-export-download"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-export-success")).toBeInTheDocument();
    });
  });
});

describe("Issue #155: architecture docs", () => {
  it("map.md documents deployed listing workflow UI module row", () => {
    const mapPath = path.join(process.cwd(), "..", "..", "docs/architecture/map.md");
    const content = fs.readFileSync(mapPath, "utf-8");
    expect(content).toContain("workflows/new-seller/listing");
    expect(content).toContain("ListingWorkflowPanel");
  });
});

describe("Issue #157: shop progress tracking", () => {
  it("increments mock active listing count after successful export", async () => {
    const user = userEvent.setup();
    expect(loadShopProgress("new").activeListingCount).toBe(
      BASELINE_ACTIVE_LISTING_COUNT,
    );

    await approveListProducts(user);
    await completePathAToDraftReview(user);

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-export-execute")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-export-download"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-export-success")).toBeInTheDocument();
    });

    expect(loadShopProgress("new").activeListingCount).toBe(
      BASELINE_ACTIVE_LISTING_COUNT + 1,
    );
  });

  it("widget state transitions NoDistributor → DistributorKnown → DraftGenerated → Published-stub", async () => {
    const user = userEvent.setup();

    render(<NewSellerCopilotPanel persona={persona} tasks={[listProductsTask]} />);

    await waitFor(() => {
      expect(screen.getByTestId("listing-progress-widget")).toHaveAttribute(
        "data-widget-state",
        "no_distributor",
      );
    });

    await user.click(screen.getByTestId("task-approve"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-workflow")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-path-a"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-product_form")).toBeInTheDocument();
    });

    expect(screen.getByTestId("listing-progress-widget")).toHaveAttribute(
      "data-widget-state",
      "no_distributor",
    );

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-distributor_pick")).toBeInTheDocument();
    });

    await user.click(
      screen.getByTestId("listing-distributor-a1000001-0001-4000-8000-000000000001"),
    );

    await waitFor(() => {
      expect(screen.getByTestId("listing-progress-widget")).toHaveAttribute(
        "data-widget-state",
        "distributor_known",
      );
    });

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-draft-review")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(screen.getByTestId("listing-progress-widget")).toHaveAttribute(
        "data-widget-state",
        "draft_generated",
      );
    });

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-export-execute")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-export-download"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-progress-widget")).toHaveAttribute(
        "data-widget-state",
        "published_stub",
      );
    });
  });

  it("updates listing milestone progress bar after export", async () => {
    const user = userEvent.setup();

    render(<NewSellerCopilotPanel persona={persona} tasks={[listProductsTask]} />);

    await waitFor(() => {
      expect(screen.getByTestId("listing-milestone-percent")).toHaveTextContent("30%");
    });

    await user.click(screen.getByTestId("task-approve"));
    await completePathAToDraftReview(user);

    await user.click(screen.getByTestId("listing-next"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-export-execute")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-export-download"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-milestone-percent")).toHaveTextContent("40%");
    });
  });

  it("emits readiness_score_bucket on export_completed analytics", async () => {
    const user = userEvent.setup();
    const analyticsEvents: CustomEvent[] = [];
    const onAnalytics = (event: Event) => {
      analyticsEvents.push(event as CustomEvent);
    };
    window.addEventListener("juli:analytics", onAnalytics);

    await approveListProducts(user);
    await completePathAToDraftReview(user);

    await user.click(screen.getByTestId("listing-next"));
    await user.click(screen.getByTestId("listing-export-download"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-export-success")).toBeInTheDocument();
    });

    const exportEvent = analyticsEvents.find(
      (event) => event.detail?.event === "export_completed",
    );
    expect(exportEvent?.detail).toMatchObject({
      event: "export_completed",
      readiness_score_bucket: expect.stringMatching(/^(low|medium|high)$/),
    });
    expect(typeof exportEvent?.detail.readiness_score).toBe("number");

    window.removeEventListener("juli:analytics", onAnalytics);
  });
});

describe("Issue #155: UI-only mode", () => {
  it("does not call backend APIs during workflow", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);
    await user.click(screen.getByTestId("listing-path-a"));

    expect(api.products.list).not.toHaveBeenCalled();
    expect(api.shops.list).not.toHaveBeenCalled();
  });
});
