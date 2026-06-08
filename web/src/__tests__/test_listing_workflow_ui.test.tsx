/**
 * Issue #155 — E2E listing workflow UI (P1.6-2)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskQueue } from "@/components/tasks/TaskQueue";
import { api } from "@/lib/api-client";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { filterOpportunities } from "@/lib/workflows/new-seller/listing";
import { loadOpportunities } from "@/lib/mock-data/listing-workflow";
import { clearTaskExecutorSession } from "@/lib/task-executor";

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

beforeEach(() => {
  jest.clearAllMocks();
  clearTaskExecutorSession();
  sessionStorage.clear();
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
  it("reaches draft review with generated draft from rules engine", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);

    await user.click(screen.getByTestId("listing-path-a"));
    await waitFor(() => {
      expect(screen.getByTestId("listing-step-product_form")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("listing-next"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-step-distributor_pick")).toBeInTheDocument();
    });

    const distributorButton = screen.getByTestId(
      "listing-distributor-a1000001-0001-4000-8000-000000000001",
    );
    await user.click(distributorButton);
    await user.click(screen.getByTestId("listing-next"));

    await waitFor(() => {
      expect(screen.getByTestId("listing-draft-review")).toBeInTheDocument();
    });

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

describe("Issue #155: UI-only mode", () => {
  it("does not call backend APIs during workflow", async () => {
    const user = userEvent.setup();
    await approveListProducts(user);
    await user.click(screen.getByTestId("listing-path-a"));

    expect(api.products.list).not.toHaveBeenCalled();
    expect(api.shops.list).not.toHaveBeenCalled();
  });
});
