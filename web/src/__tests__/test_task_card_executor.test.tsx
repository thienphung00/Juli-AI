/**
 * Issue #117 — Shared task card + no-op executor (P1-5)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskCard } from "@/components/tasks/TaskCard";
import { TaskQueue } from "@/components/tasks/TaskQueue";
import { api } from "@/lib/api-client";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import {
  TASK_EXECUTOR_SESSION_KEY,
  clearTaskExecutorSession,
  createEmptySession,
  filterActiveTasks,
  setTaskDisposition,
} from "@/lib/task-executor";
import { dismissTaskWithReason } from "./helpers/dismiss-task";

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

const sampleTasks = loadPersona("new").tasks.slice(0, 2);

beforeEach(() => {
  jest.clearAllMocks();
  clearTaskExecutorSession();
  sessionStorage.clear();
});

describe("Issue #117: TaskCard", () => {
  it("renders title, body, severity, CTA, and optional GMV impact", () => {
    const task = sampleTasks[0];
    render(
      <TaskCard
        task={task}
        personaId="new"
        onApprove={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );

    expect(screen.getByTestId("task-title")).toHaveTextContent(task.title);
    expect(screen.getByTestId("task-body")).toHaveTextContent(task.body);
    expect(screen.getByTestId("task-severity")).toHaveTextContent("Ưu tiên cao");
    expect(screen.getByTestId("task-approve")).toHaveTextContent(task.cta_label);
    expect(screen.getByTestId("task-gmv-impact")).toHaveTextContent("₫");
  });

  it("omits GMV impact when estimated_impact_vnd is null", () => {
    const task = { ...sampleTasks[0], estimated_impact_vnd: null };
    render(
      <TaskCard
        task={task}
        personaId="new"
        onApprove={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );
    expect(screen.queryByTestId("task-gmv-impact")).not.toBeInTheDocument();
  });
});

describe("Issue #117: TaskQueue no-op executor", () => {
  it("shows demo-mode copy that Phase 1 does not execute on TikTok", () => {
    render(<TaskQueue tasks={sampleTasks} personaId="new" />);
    expect(screen.getByTestId("task-demo-notice")).toHaveTextContent("Chế độ demo");
    expect(screen.getByTestId("task-demo-notice")).toHaveTextContent(
      "chưa thực thi",
    );
  });

  it("visual confirmation on approve", async () => {
    const user = userEvent.setup();
    render(<TaskQueue tasks={sampleTasks} personaId="new" />);

    await user.click(screen.getAllByTestId("task-approve")[0]);

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toBeInTheDocument();
    });
    expect(screen.getByTestId("task-feedback-approved")).toHaveTextContent(
      "chưa thực thi trên TikTok",
    );
  });

  it("visual confirmation on dismiss", async () => {
    const user = userEvent.setup();
    render(<TaskQueue tasks={sampleTasks} personaId="new" />);

    await dismissTaskWithReason(user, "not_relevant");

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-dismissed")).toBeInTheDocument();
    });
  });

  it("approve then dismiss on separate tasks updates queue correctly", async () => {
    const user = userEvent.setup();
    const tasks = sampleTasks;
    render(<TaskQueue tasks={tasks} personaId="new" />);

    const list = screen.getByTestId("task-queue-list");
    expect(within(list).getAllByTestId("task-card")).toHaveLength(2);

    const firstApprove = within(list).getAllByTestId("task-approve")[0];
    await user.click(firstApprove);

    await waitFor(() => {
      expect(within(list).getAllByTestId("task-card")).toHaveLength(1);
    });

    await dismissTaskWithReason(user, "false_positive");

    await waitFor(() => {
      expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();
    });
  });

  it("session persistence: dismissals survive remount within session", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <TaskQueue tasks={sampleTasks} personaId="new" />,
    );

    await dismissTaskWithReason(user, "already_handled");

    await waitFor(() => {
      expect(screen.getAllByTestId("task-card")).toHaveLength(1);
    });

    unmount();
    render(<TaskQueue tasks={sampleTasks} personaId="new" />);

    expect(screen.getAllByTestId("task-card")).toHaveLength(1);
    const stored = sessionStorage.getItem(TASK_EXECUTOR_SESSION_KEY);
    expect(stored).toContain(sampleTasks[0].id);
  });

  it("no API calls on approve or dismiss", async () => {
    const user = userEvent.setup();
    render(<TaskQueue tasks={sampleTasks} personaId="new" />);

    await user.click(screen.getAllByTestId("task-approve")[0]);
    await dismissTaskWithReason(user, "not_relevant");

    expect(api.shops.list).not.toHaveBeenCalled();
    expect(api.shops.me).not.toHaveBeenCalled();
    expect(api.orders.list).not.toHaveBeenCalled();
    expect(api.recommendations.list).not.toHaveBeenCalled();
  });
});

describe("Issue #117: task executor queue (unit)", () => {
  it("filterActiveTasks excludes approved and dismissed tasks", () => {
    const session = createEmptySession();
    const [first, second] = sampleTasks;
    const withApprove = setTaskDisposition(
      session,
      first.id,
      "approved",
      "2026-06-05T00:00:00.000Z",
    );
    const withDismiss = setTaskDisposition(
      withApprove,
      second.id,
      "dismissed",
      "2026-06-05T00:00:01.000Z",
    );
    expect(filterActiveTasks(sampleTasks, withDismiss)).toHaveLength(0);
  });
});
