import { render, screen, waitFor } from "@testing-library/react";
import { LivestreamsPage } from "@/components/LivestreamsPage";
import { api } from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    livestreams: {
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
  usePathname: () => "/livestreams",
}));

const mockLivestreams = [
  {
    id: "ls1",
    title: "Flash sale cuối tuần",
    started_at: "2026-05-25T14:00:00Z",
    ended_at: "2026-05-25T17:00:00Z",
    duration_minutes: 180,
    viewers_peak: 1200,
    viewers_avg: 800,
    gmv: 15_000_000,
    orders_count: 45,
    performance_grade: 85,
  },
  {
    id: "ls2",
    title: "Giới thiệu BST mới",
    started_at: "2026-05-24T10:00:00Z",
    ended_at: "2026-05-24T12:00:00Z",
    duration_minutes: 120,
    viewers_peak: 500,
    viewers_avg: 300,
    gmv: 5_000_000,
    orders_count: 12,
    performance_grade: 42,
  },
  {
    id: "ls3",
    title: "Livestream test",
    started_at: "2026-05-23T08:00:00Z",
    ended_at: "2026-05-23T08:30:00Z",
    duration_minutes: 30,
    viewers_peak: 50,
    viewers_avg: 20,
    gmv: 500_000,
    orders_count: 2,
    performance_grade: 15,
  },
];

describe("AC3: Livestreams page lists sessions with metrics and performance grade", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("renders livestream sessions list", async () => {
    (api.livestreams.list as jest.Mock).mockResolvedValue({
      sessions: mockLivestreams,
      total: 3,
    });

    render(<LivestreamsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("livestreams-list")).toBeInTheDocument();
    });

    const cards = screen.getAllByTestId("livestream-card");
    expect(cards).toHaveLength(3);
  });

  it("displays session titles", async () => {
    (api.livestreams.list as jest.Mock).mockResolvedValue({
      sessions: mockLivestreams,
      total: 3,
    });

    render(<LivestreamsPage />);

    await waitFor(() => {
      expect(screen.getByText("Flash sale cuối tuần")).toBeInTheDocument();
      expect(screen.getByText("Giới thiệu BST mới")).toBeInTheDocument();
    });
  });

  it("shows metrics summary (viewers, GMV, orders)", async () => {
    (api.livestreams.list as jest.Mock).mockResolvedValue({
      sessions: mockLivestreams,
      total: 3,
    });

    render(<LivestreamsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("livestreams-list")).toBeInTheDocument();
    });

    expect(screen.getByText(/1\.200/)).toBeInTheDocument();
    expect(screen.getByText(/15\.000\.000/)).toBeInTheDocument();
  });

  it("displays 0-100 performance grade for each session", async () => {
    (api.livestreams.list as jest.Mock).mockResolvedValue({
      sessions: mockLivestreams,
      total: 3,
    });

    render(<LivestreamsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("livestreams-list")).toBeInTheDocument();
    });

    const grades = screen.getAllByTestId("performance-grade");
    expect(grades).toHaveLength(3);
    expect(grades[0]).toHaveTextContent("85");
    expect(grades[1]).toHaveTextContent("42");
    expect(grades[2]).toHaveTextContent("15");
  });

  it("applies color coding to grades (green >= 70, yellow >= 40, red < 40)", async () => {
    (api.livestreams.list as jest.Mock).mockResolvedValue({
      sessions: mockLivestreams,
      total: 3,
    });

    render(<LivestreamsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("livestreams-list")).toBeInTheDocument();
    });

    const grades = screen.getAllByTestId("performance-grade");
    expect(grades[0].className).toMatch(/green/);
    expect(grades[1].className).toMatch(/yellow/);
    expect(grades[2].className).toMatch(/red/);
  });

  it("renders empty state when no livestream sessions", async () => {
    (api.livestreams.list as jest.Mock).mockResolvedValue({
      sessions: [],
      total: 0,
    });

    render(<LivestreamsPage />);

    await waitFor(() => {
      expect(screen.getByTestId("livestreams-empty")).toBeInTheDocument();
    });
  });
});
