/**
 * Issue #196 — Decision detail flow step graph + approve routing (ADR-028 P1.8-9)
 */
import {
  DECISION_DETAIL_STEP_LABELS,
  DECISION_DETAIL_STEPS,
  getNextStep,
  getPreviousStep,
  getStepIndex,
  isFirstStep,
  isLastStep,
  type DecisionDetailStep,
} from "@/lib/decisions/detail-steps";

describe("Issue #196: decision detail step graph", () => {
  it("defines five ordered steps with Vietnamese labels", () => {
    expect(DECISION_DETAIL_STEPS).toEqual([
      "why",
      "analytics",
      "inputs",
      "preview",
      "approve",
    ]);
    expect(DECISION_DETAIL_STEP_LABELS.why).toBe("Tại sao");
    expect(DECISION_DETAIL_STEP_LABELS.analytics).toBe("Phân tích");
    expect(DECISION_DETAIL_STEP_LABELS.inputs).toBe("Thông tin của bạn");
    expect(DECISION_DETAIL_STEP_LABELS.preview).toBe("Xem trước");
    expect(DECISION_DETAIL_STEP_LABELS.approve).toBe("Phê duyệt");
  });

  it("navigates forward through the full step graph", () => {
    let step: DecisionDetailStep = "why";
    const visited: DecisionDetailStep[] = [step];

    while (!isLastStep(step)) {
      const next = getNextStep(step);
      expect(next).not.toBeNull();
      step = next!;
      visited.push(step);
    }

    expect(visited).toEqual(DECISION_DETAIL_STEPS);
    expect(getNextStep("approve")).toBeNull();
  });

  it("navigates backward through the full step graph", () => {
    let step: DecisionDetailStep = "approve";
    const visited: DecisionDetailStep[] = [step];

    while (!isFirstStep(step)) {
      const previous = getPreviousStep(step);
      expect(previous).not.toBeNull();
      step = previous!;
      visited.push(step);
    }

    expect(visited).toEqual([...DECISION_DETAIL_STEPS].reverse());
    expect(getPreviousStep("why")).toBeNull();
  });

  it("reports first and last step boundaries", () => {
    expect(isFirstStep("why")).toBe(true);
    expect(isLastStep("why")).toBe(false);
    expect(isFirstStep("approve")).toBe(false);
    expect(isLastStep("approve")).toBe(true);
    expect(getStepIndex("inputs")).toBe(2);
  });
});
