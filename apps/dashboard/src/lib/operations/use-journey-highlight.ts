"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";

import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";

import { parseDecisionsHighlight } from "./journey-loop";

const HIGHLIGHT_DURATION_MS = 2000;

function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export function useJourneyHighlight(
  workflowIds: readonly ValidatedWorkflowId[],
): ValidatedWorkflowId | null {
  const searchParams = useSearchParams();
  const [highlightedWorkflowId, setHighlightedWorkflowId] =
    useState<ValidatedWorkflowId | null>(null);

  useEffect(() => {
    const parsed = parseDecisionsHighlight(searchParams.get("highlight"));
    if (!parsed || !workflowIds.includes(parsed)) {
      setHighlightedWorkflowId(null);
      return;
    }

    setHighlightedWorkflowId(parsed);

    const card = document.querySelector<HTMLElement>(`[data-workflow-id="${parsed}"]`);
    card?.scrollIntoView({
      behavior: prefersReducedMotion() ? "auto" : "smooth",
      block: "center",
    });

    const timer = window.setTimeout(() => {
      setHighlightedWorkflowId(null);
    }, HIGHLIGHT_DURATION_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [searchParams, workflowIds]);

  return highlightedWorkflowId;
}
