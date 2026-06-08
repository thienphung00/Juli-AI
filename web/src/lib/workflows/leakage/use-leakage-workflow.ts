"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { loadLeakageWorkflowTask } from "@/lib/mock-data/leakage-workflow";
import type { LeakageWorkflowTask } from "@/lib/mock-data/leakage-workflow/schemas";
import { checkLeakageEvidencePii } from "./pii-guard";
import {
  clearLeakageWorkflowSession,
  loadLeakageWorkflowSession,
  saveLeakageWorkflowSession,
} from "./session-store";
import {
  advanceLeakageStep,
  canAdvanceLeakage,
  canGoBackLeakage,
  createInitialLeakageWorkflowState,
  goBackLeakageStep,
  markEvidenceReviewed,
  skipLeakageWorkflow,
  type LeakageWorkflowSessionState,
} from "./state-machine";

function resolveInitialState(
  taskId: string,
  piiGuardPassed: boolean,
): LeakageWorkflowSessionState {
  const saved = loadLeakageWorkflowSession(taskId);
  if (saved) return saved.state;
  return createInitialLeakageWorkflowState(taskId, piiGuardPassed);
}

export function useLeakageWorkflow(options: { taskId: string }) {
  const { taskId } = options;

  const task = useMemo(
    (): LeakageWorkflowTask | undefined => loadLeakageWorkflowTask(taskId),
    [taskId],
  );

  const piiGuardPassed = useMemo(() => {
    if (!task) return false;
    return checkLeakageEvidencePii(task.evidence_bundle);
  }, [task]);

  const [state, setState] = useState<LeakageWorkflowSessionState>(() =>
    resolveInitialState(taskId, piiGuardPassed),
  );

  useEffect(() => {
    setState(resolveInitialState(taskId, piiGuardPassed));
  }, [taskId, piiGuardPassed]);

  useEffect(() => {
    if (!taskId) return;
    saveLeakageWorkflowSession({ version: 1, taskId, state });
  }, [taskId, state]);

  const reset = useCallback(() => {
    clearLeakageWorkflowSession(taskId);
    setState(createInitialLeakageWorkflowState(taskId, piiGuardPassed));
  }, [taskId, piiGuardPassed]);

  const reviewEvidence = useCallback(() => {
    setState((prev) => markEvidenceReviewed(prev));
  }, []);

  const goNext = useCallback(() => {
    setState((prev) => advanceLeakageStep(prev));
  }, []);

  const goBack = useCallback(() => {
    setState((prev) => goBackLeakageStep(prev));
  }, []);

  const skip = useCallback(() => {
    setState((prev) => skipLeakageWorkflow(prev));
  }, []);

  const canAdvance = canAdvanceLeakage(state);
  const canGoBack = canGoBackLeakage(state);

  return {
    task,
    state,
    piiGuardPassed,
    reset,
    reviewEvidence,
    goNext,
    goBack,
    skip,
    canAdvance,
    canGoBack,
  };
}

export type LeakageWorkflowController = ReturnType<typeof useLeakageWorkflow>;
