/**
 * Issue #122 — UX instrumentation (P1-7)
 */
import { readFileSync } from "fs";
import path from "path";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TaskCard } from "@/components/tasks/TaskCard";
import { TaskQueue } from "@/components/tasks/TaskQueue";
import { NewSellerCopilotPanel } from "@/components/workflows/new-seller/NewSellerCopilotPanel";
import { LeakageCopilotPanel } from "@/components/workflows/leakage/LeakageCopilotPanel";
import { GrowthCopilotPanel } from "@/components/workflows/growth/GrowthCopilotPanel";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import type { TaskUxEventPayload } from "@/lib/ux-analytics";
import { UX_SESSION_STORAGE_KEY, clearUxSessionId } from "@/lib/ux-analytics";
import { clearTaskExecutorSession } from "@/lib/task-executor";
import { dismissTaskWithReason } from "./helpers/dismiss-task";

function collectAnalyticsEvents(): TaskUxEventPayload[] {
  const events: TaskUxEventPayload[] = [];
  const handler = (e: Event) => {
    events.push((e as CustomEvent<TaskUxEventPayload>).detail);
  };
  window.addEventListener("juli:analytics", handler);
  return events;
}

function removeAnalyticsListener(
  events: TaskUxEventPayload[],
  handler: (e: Event) => void,
) {
  window.removeEventListener("juli:analytics", handler);
}

const FORBIDDEN_PAYLOAD_KEYS = [
  "buyer_id",
  "phone",
  "email",
  "shop_name",
  "title",
  "body",
];

beforeEach(() => {
  sessionStorage.clear();
  clearTaskExecutorSession();
  clearUxSessionId();
});

describe("Issue #122: task UX analytics", () => {
  it("emits task_clicked with workflow, task_type, persona_id, session_id", async () => {
    const user = userEvent.setup();
    const persona = loadPersona("new");
    const task = persona.tasks[0];
    const events: TaskUxEventPayload[] = [];
    const handler = (e: Event) => {
      events.push((e as CustomEvent<TaskUxEventPayload>).detail);
    };
    window.addEventListener("juli:analytics", handler);

    render(
      <TaskCard
        task={task}
        personaId={persona.profile.id}
        onApprove={jest.fn()}
        onDismiss={jest.fn()}
      />,
    );

    await user.click(screen.getByTestId("task-title"));

    expect(events).toHaveLength(1);
    expect(events[0]).toMatchObject({
      event: "task_clicked",
      workflow: task.workflow,
      task_type: task.type,
      persona_id: persona.profile.id,
    });
    expect(events[0].session_id).toBeTruthy();
    expect(events[0].timestamp).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    for (const key of FORBIDDEN_PAYLOAD_KEYS) {
      expect(events[0]).not.toHaveProperty(key);
    }

    window.removeEventListener("juli:analytics", handler);
  });

  it("emits task_approved and task_dismissed from TaskQueue", async () => {
    const user = userEvent.setup();
    const persona = loadPersona("new");
    const tasks = persona.tasks.slice(0, 2);
    const events: TaskUxEventPayload[] = [];
    const handler = (e: Event) => {
      events.push((e as CustomEvent<TaskUxEventPayload>).detail);
    };
    window.addEventListener("juli:analytics", handler);

    render(<TaskQueue tasks={tasks} personaId={persona.profile.id} />);

    await user.click(screen.getAllByTestId("task-approve")[0]);
    await dismissTaskWithReason(user, "false_positive");

    await waitFor(() => {
      expect(events.filter((e) => e.event === "task_approved")).toHaveLength(1);
      expect(events.filter((e) => e.event === "task_dismissed")).toHaveLength(1);
    });

    const approved = events.find((e) => e.event === "task_approved")!;
    const dismissed = events.find((e) => e.event === "task_dismissed")!;

    expect(approved).toMatchObject({
      workflow: tasks[0].workflow,
      task_type: tasks[0].type,
      persona_id: "new",
    });
    expect(dismissed).toMatchObject({
      workflow: tasks[1].workflow,
      task_type: tasks[1].type,
      persona_id: "new",
      dismiss_reason: "false_positive",
    });
    expect(approved.session_id).toBe(dismissed.session_id);
    expect(sessionStorage.getItem(UX_SESSION_STORAGE_KEY)).toBe(approved.session_id);

    window.removeEventListener("juli:analytics", handler);
  });

  it("analytics failures do not break approve or dismiss", async () => {
    const user = userEvent.setup();
    const persona = loadPersona("growth");
    const tasks = persona.tasks.filter((t) => t.workflow === "growth").slice(0, 1);
    const dispatchSpy = jest
      .spyOn(window, "dispatchEvent")
      .mockImplementation(() => {
        throw new Error("analytics sink unavailable");
      });

    render(<TaskQueue tasks={tasks} personaId={persona.profile.id} />);

    await user.click(screen.getByTestId("task-approve"));

    await waitFor(() => {
      expect(screen.getByTestId("task-feedback-approved")).toBeInTheDocument();
    });
    expect(screen.getByTestId("task-queue-empty")).toBeInTheDocument();

    dispatchSpy.mockRestore();
  });

  it("wires instrumentation into all three workflow panels", async () => {
    const user = userEvent.setup();
    const events: TaskUxEventPayload[] = [];
    const handler = (e: Event) => {
      events.push((e as CustomEvent<TaskUxEventPayload>).detail);
    };
    window.addEventListener("juli:analytics", handler);

    const newPersona = loadPersona("new");
    const leakagePersona = loadPersona("leakage");
    const growthPersona = loadPersona("growth");

    const { unmount: unmountNew } = render(
      <NewSellerCopilotPanel
        persona={newPersona}
        tasks={newPersona.tasks.filter((t) => t.workflow === "new_seller")}
      />,
    );
    await user.click(screen.getAllByTestId("task-approve")[0]);
    unmountNew();

    const { unmount: unmountLeakage } = render(
      <LeakageCopilotPanel
        persona={leakagePersona}
        tasks={leakagePersona.tasks.filter((t) => t.workflow === "leakage")}
      />,
    );
    await dismissTaskWithReason(user, "not_relevant");
    unmountLeakage();

    const { unmount: unmountGrowth } = render(
      <GrowthCopilotPanel
        persona={growthPersona}
        tasks={growthPersona.tasks.filter((t) => t.workflow === "growth")}
      />,
    );
    await user.click(screen.getAllByTestId("task-approve")[0]);
    unmountGrowth();

    const workflows = new Set(events.map((e) => e.workflow));
    expect(workflows).toEqual(
      new Set(["new_seller", "leakage", "growth"]),
    );
    expect(events.some((e) => e.event === "task_approved")).toBe(true);
    expect(events.some((e) => e.event === "task_dismissed")).toBe(true);

    window.removeEventListener("juli:analytics", handler);
  });
});

describe("Issue #122: engagement instrumentation", () => {
  it("defines task_approved UX event for engagement tracking", () => {
    const typesPath = path.join(process.cwd(), "src/lib/ux-analytics/types.ts");
    const types = readFileSync(typesPath, "utf-8");

    expect(types).toContain("task_approved");
    expect(types).toContain("task_dismissed");
  });
});
