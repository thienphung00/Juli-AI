import { render, screen, waitFor } from "@testing-library/react";
import { CreatorsPage } from "@/components/CreatorsPage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    creators: {
      list: jest.fn(),
    },
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg: string) {
      super(msg);
      this.status = status;
    }
  },
}));

jest.mock("next/navigation", () => ({
  usePathname: () => "/creators",
}));

const mockCreators = [
  {
    id: "c1",
    name: "Nguyễn Văn A",
    avatar_url: "https://example.com/avatar1.jpg",
    total_gmv: 50_000_000,
    commission_paid: 5_000_000,
    commission_rate: 0.1,
    efficiency_score: 92,
    sessions_count: 15,
  },
  {
    id: "c2",
    name: "Trần Thị B",
    avatar_url: "https://example.com/avatar2.jpg",
    total_gmv: 30_000_000,
    commission_paid: 6_000_000,
    commission_rate: 0.2,
    efficiency_score: 65,
    sessions_count: 8,
  },
  {
    id: "c3",
    name: "Lê Văn C",
    avatar_url: null,
    total_gmv: 5_000_000,
    commission_paid: 1_500_000,
    commission_rate: 0.3,
    efficiency_score: 35,
    sessions_count: 3,
  },
];

describe("AC4: Creators page shows GMV attribution and commission efficiency", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders creator scorecards", async () => {
    (api.creators.list as jest.Mock).mockResolvedValue({
      creators: mockCreators,
      total: 3,
    });

    render(<CreatorsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("creators-list")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("creator-card");
    expect(cards).toHaveLength(3);
  });

  it("displays per-creator GMV attribution formatted as VND", async () => {
    (api.creators.list as jest.Mock).mockResolvedValue({
      creators: mockCreators,
      total: 3,
    });

    render(<CreatorsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("creators-list")).toBeInTheDocument();
    });

    expect(screen.getByText(/50\.000\.000/)).toBeInTheDocument();
    expect(screen.getByText(/30\.000\.000/)).toBeInTheDocument();
  });

  it("shows commission efficiency score per creator", async () => {
    (api.creators.list as jest.Mock).mockResolvedValue({
      creators: mockCreators,
      total: 3,
    });

    render(<CreatorsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("creators-list")).toBeInTheDocument();
    });

    const scores = screen.getAllByTestId("efficiency-score");
    expect(scores).toHaveLength(3);
    expect(scores[0]).toHaveTextContent("92");
    expect(scores[1]).toHaveTextContent("65");
    expect(scores[2]).toHaveTextContent("35");
  });

  it("displays commission rate as percentage", async () => {
    (api.creators.list as jest.Mock).mockResolvedValue({
      creators: mockCreators,
      total: 3,
    });

    render(<CreatorsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("creators-list")).toBeInTheDocument();
    });

    expect(screen.getByText(/10%/)).toBeInTheDocument();
    expect(screen.getByText(/20%/)).toBeInTheDocument();
    expect(screen.getByText(/30%/)).toBeInTheDocument();
  });

  it("shows session count per creator", async () => {
    (api.creators.list as jest.Mock).mockResolvedValue({
      creators: mockCreators,
      total: 3,
    });

    render(<CreatorsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("creators-list")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("creator-card");
    expect(cards[0]).toHaveTextContent("15");
    expect(cards[1]).toHaveTextContent("8");
  });

  it("renders empty state when no creators", async () => {
    (api.creators.list as jest.Mock).mockResolvedValue({
      creators: [],
      total: 0,
    });

    render(<CreatorsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("creators-empty")).toBeInTheDocument();
    });
  });
});
