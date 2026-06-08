/**
 * Issue #168 — Leakage integration tests + UX instrumentation (P1.7-5)
 */
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeakageCopilotPanel } from "@/components/workflows/leakage";
import { LeakageWorkflowPanel } from "@/components/workflows/leakage/LeakageWorkflowPanel";
import * as leakageWorkflowData from "@/lib/mock-data/leakage-workflow";
import { loadLeakageWorkflowTask } from "@/lib/mock-data/leakage-workflow";
import type { LeakageWorkflowTask } from "@/lib/mock-data/leakage-workflow/schemas";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { getWorkflowTasks } from "@/lib/seller-workflows";
import { TASK_DISMISS_REASONS } from "@/lib/task-executor/dismiss-reasons";
import { clearTaskExecutorSession, loadTaskExecutorSession } from "@/lib/task-executor";
import { clearLeakageWorkflowSession } from "@/lib/workflows/leakage";
import {
  assertLeakageEvidenceHasNoRawPii,
  type LeakageUxEventPayload,
} from "@/lib/workflows/leakage";
import {
  dismissTaskWithReason,
  expectDismissBlockedWithoutReason,
} from "./helpers/dismiss-task";

const leakagePersona = loadPersona("leakage");
const leakageTasks = getWorkflowTasks(leakagePersona, "leakage");

const FORBIDDEN_ANALYTICS_KEYS = [
  "buyer_id",
  "phone",
  "email",
  "shop_name",
  "title",
  "body",
];

function collectLeakageAnalyticsEvents(): {
  events: LeakageUxEventPayload[];
  cleanup: () => void;
} {
  const events: LeakageUxEventPayload[] = [];
  const handler = (event: Event) => {
    const detail = (event as CustomEvent<LeakageUxEventPayload>).detail;
    if (detail?.workflow === "leakage" || detail?.event?.startsWith("leakage_")) {
      events.push(detail);
    }
    if (detail?.event === "task_dismissed_with_reason") {
      events.push(detail);
    }
  };
  window.addEventListener("juli:analytics", handler);
  return {
    events,
    cleanup: () => window.removeEventListener("juli:analytics", handler),
  };
}

beforeEach(() => {
  sessionStorage.clear();
  clearTaskExecutorSession();
  for (const task of leakageTasks) {
    clearLeakageWorkflowSession(task.id);
  }
});

async function traverseWorkflowToSuccess(
  user: ReturnType<typeof userEvent.setup>,
) {
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

  await waitFor(
    () => {
      expect(screen.getByTestId("leakage-step-success")).toBeInTheDocument();
    },
    { timeout: 8_000 },
  );

  await user.click(screen.getByTestId("leakage-workflow-complete"));
}

async function completeLeakageHappyPath(taskType: string) {
  jest.useFakeTimers();
  const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
  const task = leakageTasks.find((item) => item.type === taskType)!;

  render(<LeakageCopilotPanel persona={leakagePersona} tasks={[task]} />);

  await user.click(screen.getByTestId("task-approve"));
  await waitFor(() => {
    expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
  });

  await traverseWorkflowToSuccess(user);
  await jest.advanceTimersByTimeAsync(5_000);

  await waitFor(() => {
    expect(screen.queryByTestId("leakage-workflow")).not.toBeInTheDocument();
    expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();
  });

  expect(loadTaskExecutorSession().records[task.id]?.disposition).toBe("approved");

  jest.useRealTimers();
}

describe("Issue #168: happy-path integration per leakage task type", () => {
  it.each([
    "return_spike",
    "buyer_cancellation_cluster",
    "refund_cluster",
    "return_window_policy",
  ] as const)("approve → all steps → success → queue empty for %s", async (taskType) => {
    await completeLeakageHappyPath(taskType);
  });
});

describe("Issue #168: evidence PII guard", () => {
  it("throws when forbidden PII keys are present in evidence bundle", () => {
    const task = loadLeakageWorkflowTask("task_leak_001")!;
    const badBundle = {
      ...task.evidence_bundle,
      phone: "+84912345678",
    } as typeof task.evidence_bundle & { phone: string };

    expect(() => assertLeakageEvidenceHasNoRawPii(badBundle)).toThrow(
      /forbidden PII keys/i,
    );
  });

  it("blocks evidence step advance when bundle has unmasked buyer_id", async () => {
    const user = userEvent.setup();
    const baseTask = loadLeakageWorkflowTask("task_leak_001")!;
    const badTask: LeakageWorkflowTask = {
      ...baseTask,
      evidence_bundle: {
        ...baseTask.evidence_bundle,
        orders: baseTask.evidence_bundle.orders.map((order, index) =>
          index === 0
            ? { ...order, buyer_id: "buyer_raw_unmasked_12345" }
            : order,
        ),
      },
    };

    jest.spyOn(leakageWorkflowData, "loadLeakageWorkflowTask").mockImplementation((taskId) => {
      if (taskId === "task_leak_001") return badTask;
      return loadLeakageWorkflowTask(taskId);
    });

    render(
      <LeakageWorkflowPanel
        taskId="task_leak_001"
        persona={leakagePersona}
        onClose={jest.fn()}
      />,
    );

    await user.click(screen.getByTestId("leakage-next"));
    await waitFor(() => {
      expect(screen.getByTestId("leakage-pii-guard-blocked")).toBeInTheDocument();
    });

    expect(screen.getByTestId("leakage-next")).toBeDisabled();
    expect(screen.queryByTestId("leakage-evidence-confirm")).not.toBeInTheDocument();

    jest.restoreAllMocks();
  });
});

describe("Issue #168: dismiss-with-reason", () => {
  it("blocks dismiss submit until a reason is selected", async () => {
    const user = userEvent.setup();
    const task = leakageTasks.find((item) => item.type === "return_spike")!;

    render(<LeakageCopilotPanel persona={leakagePersona} tasks={[task]} />);

    await expectDismissBlockedWithoutReason(user);
  });

  it.each(TASK_DISMISS_REASONS)(
    "dismiss with reason %s removes task from queue",
    async (reason) => {
      const user = userEvent.setup();
      const task = leakageTasks.find((item) => item.type === "refund_cluster")!;

      render(<LeakageCopilotPanel persona={leakagePersona} tasks={[task]} />);

      await dismissTaskWithReason(user, reason, {
        note: reason === "other" ? "Không áp dụng" : undefined,
      });

      await waitFor(() => {
        expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();
      });

      const record = loadTaskExecutorSession().records[task.id];
      expect(record?.disposition).toBe("dismissed");
      expect(record?.dismissReason).toBe(reason);
    },
  );
});

describe("Issue #168: leakage UX instrumentation", () => {
  it("emits workflow lifecycle and step events through happy path", async () => {
    jest.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    const task = leakageTasks.find((item) => item.type === "return_spike")!;
    const { events, cleanup } = collectLeakageAnalyticsEvents();

    render(<LeakageCopilotPanel persona={leakagePersona} tasks={[task]} />);

    await user.click(screen.getByTestId("task-approve"));
    await waitFor(() => {
      expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    });

    expect(events.some((e) => e.event === "leakage_workflow_started")).toBe(true);

    await traverseWorkflowToSuccess(user);
    await jest.advanceTimersByTimeAsync(5_000);

    const started = events.find((e) => e.event === "leakage_workflow_started")!;
    expect(started).toMatchObject({
      workflow: "leakage",
      task_type: "return_spike",
      persona_id: "leakage",
    });
    expect(started.session_id).toBeTruthy();

    const stepEvents = events.filter((e) => e.event === "leakage_step_completed");
    expect(stepEvents.length).toBeGreaterThanOrEqual(5);
    expect(stepEvents.map((e) => e.step)).toEqual(
      expect.arrayContaining([
        "detail",
        "evidence",
        "root_cause",
        "recommended_action",
        "execution",
      ]),
    );

    expect(events.some((e) => e.event === "leakage_workflow_completed")).toBe(true);

    for (const event of events) {
      for (const key of FORBIDDEN_ANALYTICS_KEYS) {
        expect(event).not.toHaveProperty(key);
      }
    }

    cleanup();
    jest.useRealTimers();
  });

  it("emits task_dismissed_with_reason when leakage task is dismissed", async () => {
    const user = userEvent.setup();
    const task = leakageTasks.find((item) => item.type === "return_window_policy")!;
    const { events, cleanup } = collectLeakageAnalyticsEvents();

    render(<LeakageCopilotPanel persona={leakagePersona} tasks={[task]} />);

    await dismissTaskWithReason(user, "false_positive");

    await waitFor(() => {
      expect(
        events.some((e) => e.event === "task_dismissed_with_reason"),
      ).toBe(true);
    });

    const dismissed = events.find((e) => e.event === "task_dismissed_with_reason")!;
    expect(dismissed).toMatchObject({
      workflow: "leakage",
      task_type: "return_window_policy",
      persona_id: "leakage",
      dismiss_reason: "false_positive",
    });

    cleanup();
  });
});
