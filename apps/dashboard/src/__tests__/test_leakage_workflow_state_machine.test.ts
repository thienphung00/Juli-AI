/**
 * Issue #165 — Leakage workflow state machine + session persistence (P1.7-2)
 */
import fs from "fs";
import path from "path";
import { loadLeakageWorkflowTask } from "@/lib/mock-data/leakage-workflow";
import {
  advanceLeakageStep,
  canAdvanceLeakage,
  canGoBackLeakage,
  createInitialLeakageWorkflowState,
  goBackLeakageStep,
  LEAKAGE_WORKFLOW_STEPS,
  markEvidenceReviewed,
  type LeakageWorkflowSessionState,
} from "@/lib/workflows/leakage/state-machine";
import {
  clearLeakageWorkflowSession,
  loadLeakageWorkflowSession,
  saveLeakageWorkflowSession,
} from "@/lib/workflows/leakage/session-store";
import { checkLeakageEvidencePii } from "@/lib/workflows/leakage/pii-guard";

const TASK_ID = "task_leak_001";
const LEAKAGE_WORKFLOW_DIR = path.join(
  process.cwd(),
  "src/lib/workflows/leakage",
);

function validStateForFullTraversal(): LeakageWorkflowSessionState {
  const task = loadLeakageWorkflowTask(TASK_ID);
  expect(task).toBeDefined();

  const piiPassed = checkLeakageEvidencePii(task!.evidence_bundle);
  expect(piiPassed).toBe(true);

  let state = createInitialLeakageWorkflowState(TASK_ID, piiPassed);
  state = markEvidenceReviewed(state);
  return state;
}

beforeEach(() => {
  sessionStorage.clear();
  clearLeakageWorkflowSession(TASK_ID);
});

describe("Issue #165: useLeakageWorkflow fixture loading", () => {
  it("loads leakage workflow task fixture by task ID", () => {
    const task = loadLeakageWorkflowTask(TASK_ID);
    expect(task).toBeDefined();
    expect(task!.id).toBe(TASK_ID);
    expect(task!.type).toBe("return_spike");
  });
});

describe("Issue #165: leakage workflow step graph", () => {
  it("defines the full forward step order", () => {
    expect(LEAKAGE_WORKFLOW_STEPS).toEqual([
      "detail",
      "evidence",
      "root_cause",
      "recommended_action",
      "execution",
      "success",
    ]);
  });

  it("advances through the full step graph with valid state", () => {
    let state = validStateForFullTraversal();

    for (let i = 0; i < LEAKAGE_WORKFLOW_STEPS.length - 1; i += 1) {
      expect(state.step).toBe(LEAKAGE_WORKFLOW_STEPS[i]);
      expect(canAdvanceLeakage(state)).toBe(true);
      state = advanceLeakageStep(state);
    }

    expect(state.step).toBe("success");
    expect(state.workflowStatus).toBe("completed");
    expect(canAdvanceLeakage(state)).toBe(false);
  });

  it("maps workflow_status on each step transition", () => {
    const task = loadLeakageWorkflowTask(TASK_ID)!;
    const piiPassed = checkLeakageEvidencePii(task.evidence_bundle);

    let state = createInitialLeakageWorkflowState(TASK_ID, piiPassed);
    expect(state.workflowStatus).toBe("new");

    state = advanceLeakageStep(state);
    expect(state.step).toBe("evidence");
    expect(state.workflowStatus).toBe("in_review");

    state = markEvidenceReviewed(state);
    state = advanceLeakageStep(state);
    expect(state.step).toBe("root_cause");
    expect(state.workflowStatus).toBe("evidence_reviewed");

    state = advanceLeakageStep(state);
    expect(state.step).toBe("recommended_action");
    expect(state.workflowStatus).toBe("ready_to_execute");

    state = advanceLeakageStep(state);
    expect(state.step).toBe("execution");
    expect(state.workflowStatus).toBe("executing");

    state = advanceLeakageStep(state);
    expect(state.step).toBe("success");
    expect(state.workflowStatus).toBe("completed");
  });
});

describe("Issue #165: canAdvance guards", () => {
  it("returns false on evidence step until evidence is reviewed", () => {
    const task = loadLeakageWorkflowTask(TASK_ID)!;
    const piiPassed = checkLeakageEvidencePii(task.evidence_bundle);

    let state = createInitialLeakageWorkflowState(TASK_ID, piiPassed);
    state = advanceLeakageStep(state);
    expect(state.step).toBe("evidence");

    expect(canAdvanceLeakage(state)).toBe(false);

    state = markEvidenceReviewed(state);
    expect(canAdvanceLeakage(state)).toBe(true);
  });

  it("returns false on evidence step when PII guard fails", () => {
    let state = createInitialLeakageWorkflowState(TASK_ID, false);
    state = advanceLeakageStep(state);
    state = markEvidenceReviewed(state);

    expect(state.step).toBe("evidence");
    expect(canAdvanceLeakage(state)).toBe(false);
  });
});

describe("Issue #165: session resume", () => {
  it("persists state across refresh and restores step and payload after reload", () => {
    const task = loadLeakageWorkflowTask(TASK_ID)!;
    const piiPassed = checkLeakageEvidencePii(task.evidence_bundle);

    let state = createInitialLeakageWorkflowState(TASK_ID, piiPassed);
    state = advanceLeakageStep(state);
    state = markEvidenceReviewed(state);
    state = advanceLeakageStep(state);

    saveLeakageWorkflowSession({ version: 1, taskId: TASK_ID, state });

    const reloaded = loadLeakageWorkflowSession(TASK_ID);
    expect(reloaded).not.toBeNull();
    expect(reloaded!.state.step).toBe("root_cause");
    expect(reloaded!.state.evidenceReviewed).toBe(true);
    expect(reloaded!.state.piiGuardPassed).toBe(true);
    expect(reloaded!.state.workflowStatus).toBe("evidence_reviewed");
  });
});

describe("Issue #165: scope boundaries", () => {
  it("has no TikTok API or Postgres imports in leakage workflow module", () => {
    const entryPath = path.join(LEAKAGE_WORKFLOW_DIR, "index.ts");
    const source = fs.readFileSync(entryPath, "utf8");

    expect(source).not.toMatch(/tiktok/i);
    expect(source).not.toMatch(/postgres|supabase/i);
    expect(source).not.toMatch(/fetch\s*\(/);
  });
});

describe("Issue #165: backward navigation", () => {
  it("allows going back without losing reviewed evidence", () => {
    let state = validStateForFullTraversal();
    state = advanceLeakageStep(state);
    state = advanceLeakageStep(state);
    expect(state.step).toBe("root_cause");

    expect(canGoBackLeakage(state)).toBe(true);
    state = goBackLeakageStep(state);
    expect(state.step).toBe("evidence");
    expect(state.evidenceReviewed).toBe(true);
  });
});
