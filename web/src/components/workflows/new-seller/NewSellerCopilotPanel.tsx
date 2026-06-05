"use client";

import { TaskQueue } from "@/components/tasks";
import type { MockTask, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { MilestoneProgress } from "./MilestoneProgress";

export function NewSellerCopilotPanel({
  persona,
  tasks,
}: {
  persona: SellerPersona;
  tasks: MockTask[];
}) {
  return (
    <section className="space-y-4" data-testid="new-seller-copilot-panel">
      <div className="card p-4" data-testid="new-seller-checklist-header">
        <h2 className="text-base font-bold" style={{ color: "var(--foreground)" }}>
          Checklist Người Bán Mới
        </h2>
        <p className="text-muted mt-1 text-sm">
          Hoàn thành từng bước để đạt đơn hàng có lãi đầu tiên và xây nền tảng tăng trưởng.
        </p>
      </div>

      <MilestoneProgress profile={persona.profile} />

      <TaskQueue tasks={tasks} personaId={persona.profile.id} />
    </section>
  );
}
