/**
 * Issue #167 — Executor integration: leakage workflow + global skip-with-reason (P1.7-4)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeakageCopilotPanel } from "@/components/workflows/leakage";
import { TaskQueue } from "@/components/tasks/TaskQueue";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { clearTaskExecutorSession, loadTaskExecutorSession } from "@/lib/task-executor";
import { TASK_DISMISS_REASONS } from "@/lib/task-executor/dismiss-reasons";
import { getWorkflowTasks } from "@/lib/seller-workflows";
import {
  dismissTaskWithReason,
  expectDismissBlockedWithoutReason,
} from "./helpers/dismiss-task";

const leakagePersona = loadPersona("leakage");
const leakageTasks = getWorkflowTasks(leakagePersona, "leakage");
const returnSpikeTask = leakageTasks.find((t) => t.type === "return_spike")!;
const newPersona = loadPersona("new");
const shopSetupTask =
  newPersona.tasks.find((t) => t.type !== "list_products") ?? newPersona.tasks[0]!;

beforeEach(() => {
  sessionStorage.clear();
  clearTaskExecutorSession();
});

async function approveLeakageTaskAndExpectWorkflow(taskType: string) {
  const user = userEvent.setup();
  const task = leakageTasks.find((item) => item.type === taskType)!;
  render(<LeakageCopilotPanel persona={leakagePersona} tasks={[task]} />);

  await user.click(screen.getByTestId("task-approve"));

  await waitFor(() => {
    expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
  });
  expect(screen.getByTestId("leakage-step-detail")).toBeInTheDocument();
}

describe("Issue #167: approve opens LeakageWorkflowPanel", () => {
  it("opens leakage workflow when return_spike is approved", async () => {
    await approveLeakageTaskAndExpectWorkflow("return_spike");
  });

  it.each([
    "buyer_cancellation_cluster",
    "refund_cluster",
    "return_window_policy",
  ] as const)("opens leakage workflow when %s is approved", async (taskType) => {
    await approveLeakageTaskAndExpectWorkflow(taskType);
  });

  it("keeps no-op feedback for non-leakage executable task types", async () => {
    const user = userEvent.setup();
    render(<TaskQueue tasks={[shopSetupTask]} personaId="new" />);

    await user.click(screen.getByTestId("task-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toHaveTextContent(
        "chưa thực thi trên TikTok",
      );
    });
    expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
  });
});

describe("Issue #167: global skip-with-reason", () => {
  it("blocks dismiss submit until a reason is selected", async () => {
    const user = userEvent.setup();
    render(
      <LeakageCopilotPanel persona={leakagePersona} tasks={[returnSpikeTask]} />,
    );

    await expectDismissBlockedWithoutReason(user);
  });

  it("dismiss with false_positive removes task from active list and records reason", async () => {
    const user = userEvent.setup();
    render(
      <LeakageCopilotPanel persona={leakagePersona} tasks={[returnSpikeTask]} />,
    );

    await dismissTaskWithReason(user, "false_positive");

    await waitFor(() => {
      expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();
    });

    const session = loadTaskExecutorSession();
    const record = session.records[returnSpikeTask.id];
    expect(record?.disposition).toBe("dismissed");
    expect(record?.dismissReason).toBe("false_positive");
  });

  it("uses global dismiss modal from New Seller TaskQueue", async () => {
    const user = userEvent.setup();
    render(<TaskQueue tasks={newPersona.tasks.slice(0, 1)} personaId="new" />);

    await user.click(screen.getByTestId("task-more-menu"));
    await user.click(screen.getByTestId("task-dismiss"));
    await waitFor(() => {
      expect(screen.getByTestId("task-dismiss-modal")).toBeInTheDocument();
    });
  });

  it("accepts dismiss reason false_positive", async () => {
    const user = userEvent.setup();
    const tasks = leakageTasks.slice(0, 1);
    render(<LeakageCopilotPanel persona={leakagePersona} tasks={tasks} />);

    await dismissTaskWithReason(user, "false_positive");

    expect(loadTaskExecutorSession().records[tasks[0]!.id]?.dismissReason).toBe(
      "false_positive",
    );
  });

  it.each(["already_handled", "not_relevant", "other"] as const)(
    "accepts dismiss reason %s",
    async (reason) => {
      const user = userEvent.setup();
      const tasks = leakageTasks.slice(0, 1);
      render(<LeakageCopilotPanel persona={leakagePersona} tasks={tasks} />);

      await dismissTaskWithReason(user, reason, {
        note: reason === "other" ? "Không áp dụng cho shop nhỏ" : undefined,
      });

      const session = loadTaskExecutorSession();
      expect(session.records[tasks[0]!.id]?.dismissReason).toBe(reason);
      if (reason === "other") {
        expect(session.records[tasks[0]!.id]?.dismissNote).toBe(
          "Không áp dụng cho shop nhỏ",
        );
      }
    },
  );
});

describe("Issue #167: workflow completion", () => {
  it("workflow completion closes modal and keeps task out of active queue", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });

    render(
      <LeakageCopilotPanel persona={leakagePersona} tasks={[returnSpikeTask]} />,
    );

    await user.click(screen.getByTestId("task-approve"));
    await waitFor(() => {
      expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("leakage-next"));
    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-evidence")).toBeInTheDocument();
    });
    await user.click(screen.getByTestId("leakage-evidence-confirm"));
    await user.click(screen.getByTestId("leakage-next"));
    await user.click(screen.getByTestId("leakage-next"));
    await user.click(screen.getByTestId("leakage-next"));

    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-execution")).toBeInTheDocument();
    });

    await jest.advanceTimersByTimeAsync(5_000);

    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-success")).toBeInTheDocument();
    });

    await user.click(screen.getByTestId("leakage-workflow-complete"));

    await waitFor(() => {
      expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
    });
    expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();

    const session = loadTaskExecutorSession();
    expect(session.records[returnSpikeTask.id]?.disposition).toBe("approved");

    jest.useRealTimers();
  });
});
