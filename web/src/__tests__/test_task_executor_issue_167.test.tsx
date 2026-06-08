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

describe("Issue #167: approve opens LeakageWorkflowPanel", () => {
  it("opens leakage workflow when return_spike is approved", async () => {
    const user = userEvent.setup();
    render(
      <LeakageCopilotPanel persona={leakagePersona} tasks={[returnSpikeTask]} />,
    );

    await user.click(screen.getByTestId("task-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    });
    expect(screen.getByTestId("leakage-step-detail")).toBeInTheDocument();
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

  it.each(TASK_DISMISS_REASONS)("accepts dismiss reason %s", async (reason) => {
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
  });
});
