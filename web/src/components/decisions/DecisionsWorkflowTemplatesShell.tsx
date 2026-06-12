"use client";

import { useCallback, useEffect, useState } from "react";

import type { ValidatedWorkflowId } from "@/lib/mock-data/operations/schemas";
import {
  loadWorkflowTemplatesSession,
  saveWorkflowTemplatesSession,
  updateTemplateControlValue,
  WORKFLOW_TEMPLATE_DEFINITIONS,
  type WorkflowTemplateSession,
} from "@/lib/decisions/workflow-templates";

import { WorkflowTemplateGroup } from "./WorkflowTemplateGroup";

export function DecisionsWorkflowTemplatesShell() {
  const [session, setSession] = useState<WorkflowTemplateSession | null>(null);

  useEffect(() => {
    setSession(loadWorkflowTemplatesSession());
  }, []);

  const handleControlChange = useCallback(
    (workflowId: ValidatedWorkflowId, controlId: string, value: number | boolean) => {
      setSession((current) => {
        if (!current) {
          return current;
        }

        const next = updateTemplateControlValue(current, workflowId, controlId, value);
        saveWorkflowTemplatesSession(next);
        return next;
      });
    },
    [],
  );

  if (!session) {
    return (
      <div className="space-y-3" data-testid="decisions-templates-shell" aria-busy="true">
        <div className="skeleton h-16 w-full" />
        <div className="skeleton h-32 w-full" />
        <div className="skeleton h-32 w-full" />
      </div>
    );
  }

  return (
    <section className="space-y-4" data-testid="decisions-templates-shell">
      <div
        className="rounded-xl border px-4 py-3"
        style={{ borderColor: "var(--border)", background: "var(--card)" }}
        data-testid="decisions-templates-advanced-notice"
      >
        <p className="text-xs font-medium uppercase tracking-wide" style={{ color: "var(--muted-foreground)" }}>
          Cài đặt nâng cao
        </p>
        <p className="mt-1 text-sm" style={{ color: "var(--muted-foreground)" }}>
          Điều chỉnh ngưỡng và quy tắc tự động hóa cho từng quy trình. Các thay đổi chỉ lưu
          trong phiên hiện tại — không ảnh hưởng đến đề xuất ở tab Đề xuất.
        </p>
      </div>

      <div className="space-y-3">
        {WORKFLOW_TEMPLATE_DEFINITIONS.map((definition) => (
          <WorkflowTemplateGroup
            key={definition.workflowId}
            definition={definition}
            values={session[definition.workflowId]}
            onControlChange={handleControlChange}
          />
        ))}
      </div>
    </section>
  );
}
