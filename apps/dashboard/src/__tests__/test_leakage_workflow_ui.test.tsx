/**
 * Issue #166 — LeakageWorkflowPanel modal UI (P1.7-3)
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import fs from "fs";
import path from "path";
import { LeakageWorkflowPanel } from "@/components/workflows/leakage/LeakageWorkflowPanel";
import { loadPersona } from "@/lib/mock-data/seller-personas";
import { loadLeakageWorkflowTask } from "@/lib/mock-data/leakage-workflow";
import { clearLeakageWorkflowSession } from "@/lib/workflows/leakage";

const RETURN_SPIKE_TASK_ID = "task_leak_001";
const persona = loadPersona("leakage");

beforeEach(() => {
  sessionStorage.clear();
  clearLeakageWorkflowSession(RETURN_SPIKE_TASK_ID);
  clearLeakageWorkflowSession("task_leak_002");
  clearLeakageWorkflowSession("task_leak_003");
  clearLeakageWorkflowSession("task_leak_004");
});

describe("Issue #166: LeakageWorkflowPanel portal modal", () => {
  it("mounts in a portal modal with step navigation controls", async () => {
    render(
      <LeakageWorkflowPanel taskId={RETURN_SPIKE_TASK_ID} onClose={jest.fn()} />,
    );

    expect(screen.getByTestId("leakage-workflow")).toBeInTheDocument();
    expect(screen.getByTestId("leakage-workflow")).toHaveClass("z-[100]");
    expect(screen.getByTestId("leakage-step-indicator")).toBeInTheDocument();
    expect(screen.getByTestId("leakage-close")).toBeInTheDocument();
    expect(screen.getByTestId("leakage-next")).toBeInTheDocument();
  });

  it("renders detail step for return_spike fixture", () => {
    const task = loadLeakageWorkflowTask(RETURN_SPIKE_TASK_ID)!;
    render(
      <LeakageWorkflowPanel taskId={RETURN_SPIKE_TASK_ID} onClose={jest.fn()} />,
    );

    expect(screen.getByTestId("leakage-step-detail")).toBeInTheDocument();
    expect(screen.getByTestId("leakage-detail-summary")).toHaveTextContent(
      task.detail.summary_vi,
    );
    expect(screen.getByTestId("leakage-detail-chart-0")).toHaveTextContent(
      "Tỷ lệ trả hàng 7 ngày",
    );
  });
});

describe("Issue #166: evidence step PII guard", () => {
  it("renders masked buyer IDs on evidence step", async () => {
    const user = userEvent.setup();
    render(
      <LeakageWorkflowPanel
        taskId={RETURN_SPIKE_TASK_ID}
        persona={persona}
        onClose={jest.fn()}
      />,
    );

    await user.click(screen.getByTestId("leakage-next"));

    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-evidence")).toBeInTheDocument();
    });

    const evidence = screen.getByTestId("leakage-evidence-step");
    expect(within(evidence).getAllByText(/buyer_\*\*\*/).length).toBeGreaterThan(0);
    expect(screen.getByTestId("leakage-evidence-confirm")).toBeInTheDocument();
  });

  it("blocks advance until evidence is reviewed", async () => {
    const user = userEvent.setup();
    render(
      <LeakageWorkflowPanel taskId={RETURN_SPIKE_TASK_ID} onClose={jest.fn()} />,
    );

    await user.click(screen.getByTestId("leakage-next"));
    await waitFor(() => {
      expect(screen.getByTestId("leakage-step-evidence")).toBeInTheDocument();
    });

    expect(screen.getByTestId("leakage-next")).toBeDisabled();
    await user.click(screen.getByTestId("leakage-evidence-confirm"));
    expect(screen.getByTestId("leakage-next")).toBeEnabled();
  });
});

describe("Issue #166: all four task types render fixture-driven steps", () => {
  it("renders detail content for task_leak_001", () => {
    const task = loadLeakageWorkflowTask("task_leak_001")!;
    render(<LeakageWorkflowPanel taskId="task_leak_001" onClose={jest.fn()} />);
    expect(screen.getByTestId("leakage-detail-summary")).toHaveTextContent(
      task.detail.summary_vi,
    );
    clearLeakageWorkflowSession("task_leak_001");
  });

  it("renders detail content for task_leak_002", () => {
    const task = loadLeakageWorkflowTask("task_leak_002")!;
    render(<LeakageWorkflowPanel taskId="task_leak_002" onClose={jest.fn()} />);
    expect(screen.getByTestId("leakage-detail-summary")).toHaveTextContent(
      task.detail.summary_vi,
    );
    clearLeakageWorkflowSession("task_leak_002");
  });

  it("renders detail content for task_leak_003", () => {
    const task = loadLeakageWorkflowTask("task_leak_003")!;
    render(<LeakageWorkflowPanel taskId="task_leak_003" onClose={jest.fn()} />);
    expect(screen.getByTestId("leakage-detail-summary")).toHaveTextContent(
      task.detail.summary_vi,
    );
    clearLeakageWorkflowSession("task_leak_003");
  });

  it("renders detail content for task_leak_004", () => {
    const task = loadLeakageWorkflowTask("task_leak_004")!;
    render(<LeakageWorkflowPanel taskId="task_leak_004" onClose={jest.fn()} />);
    expect(screen.getByTestId("leakage-detail-summary")).toHaveTextContent(
      task.detail.summary_vi,
    );
    clearLeakageWorkflowSession("task_leak_004");
  });

  async function traverseToSuccess(taskId: string, actionType: string) {
    const user = userEvent.setup();
    const task = loadLeakageWorkflowTask(taskId)!;
    const totalDurationMs = task.execution_plan.steps.reduce(
      (sum, step) => sum + (step.mock_duration_ms ?? 0),
      0,
    );

    render(
      <LeakageWorkflowPanel taskId={taskId} persona={persona} onClose={jest.fn()} />,
    );

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

    expect(screen.getByTestId(`leakage-execution-mock-${actionType}`)).toBeInTheDocument();
    expect(screen.getByTestId("leakage-execution-stepper")).toBeInTheDocument();

    await waitFor(
      () => {
        expect(screen.getByTestId("leakage-step-success")).toBeInTheDocument();
      },
      { timeout: totalDurationMs + 500 },
    );

    expect(screen.getByTestId("leakage-success-headline")).toHaveTextContent(
      task.success.headline_vi,
    );
    expect(screen.getByTestId("leakage-success-metrics")).toBeInTheDocument();
    clearLeakageWorkflowSession(taskId);
  }

  it("displays success headline and metrics from fixture payload", async () => {
    await traverseToSuccess("task_leak_004", "shop_settings");
  });

  it("shows action-type execution mock for task_leak_001", async () => {
    await traverseToSuccess("task_leak_001", "listing_update");
  });

  it("shows action-type execution mock for task_leak_002", async () => {
    await traverseToSuccess("task_leak_002", "investigation_package");
  });

  it("shows action-type execution mock for task_leak_003", async () => {
    await traverseToSuccess("task_leak_003", "monitoring");
  });

  it("shows action-type execution mock for task_leak_004", async () => {
    await traverseToSuccess("task_leak_004", "shop_settings");
  });
});

describe("Issue #166: module exports", () => {
  it("exports LeakageWorkflowPanel from leakage workflow index", () => {
    const indexPath = path.join(
      process.cwd(),
      "src/components/workflows/leakage/index.ts",
    );
    const content = fs.readFileSync(indexPath, "utf8");
    expect(content).toContain("LeakageWorkflowPanel");
  });

  it("documents LeakageWorkflowPanel in web MODULE.md", () => {
    const modulePath = path.join(process.cwd(), "MODULE.md");
    const content = fs.readFileSync(modulePath, "utf8");
    expect(content).toContain("LeakageWorkflowPanel");
  });
});
