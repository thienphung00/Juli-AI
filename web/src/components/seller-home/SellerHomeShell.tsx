"use client";

import { NewSellerCopilotPanel } from "@/components/workflows/new-seller";
import { TaskQueue } from "@/components/tasks";
import { useDemoPersona } from "@/lib/demo-persona-context";
import { formatVND } from "@/lib/format";
import {
  getWorkflowTasks,
  resolveSellerWorkflow,
} from "@/lib/seller-workflows";

export function SellerHomeShell() {
  const { persona, isReady } = useDemoPersona();

  if (!isReady) {
    return (
      <div className="flex justify-center py-12">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-primary-500 border-t-transparent" />
      </div>
    );
  }

  const workflow = resolveSellerWorkflow(persona);
  const tasks = getWorkflowTasks(persona, workflow.workflowId);

  return (
    <div className="space-y-4" data-testid="seller-home-shell">
      <nav
        aria-label="Luồng công việc đang hoạt động"
        className="card p-4"
        data-testid="workflow-breadcrumb"
      >
        <p className="text-muted text-xs font-medium uppercase tracking-wide">
          Luồng đang hoạt động
        </p>
        <p
          className="mt-1 text-base font-bold"
          style={{ color: "var(--foreground)" }}
          data-testid="workflow-stage"
          data-stage={workflow.stage}
        >
          {workflow.label}
        </p>
        <p className="text-muted mt-1 text-sm">{workflow.description}</p>
      </nav>

      <section className="card p-4" data-testid="seller-shop-summary">
        <h2 className="text-muted text-sm font-medium">Cửa hàng demo</h2>
        <p className="mt-1 text-sm font-semibold">{persona.profile.shop_name}</p>
        <p className="text-muted mt-1 text-sm" data-testid="seller-gmv-30d">
          GMV 30 ngày: {formatVND(persona.profile.gmv_30d_vnd)}
        </p>
      </section>

      {workflow.workflowId === "new_seller" ? (
        <NewSellerCopilotPanel persona={persona} tasks={tasks} />
      ) : (
        <TaskQueue tasks={tasks} />
      )}
    </div>
  );
}
