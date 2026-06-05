"use client";

import type { MockTask, SellerPersona } from "@/lib/mock-data/seller-personas/schemas";
import { useTaskExecutor } from "@/lib/task-executor/use-task-executor";
import { rankGrowthTasks } from "@/lib/workflows/growth/rank-tasks";
import { DemoModeNotice } from "@/components/tasks/DemoModeNotice";
import { TaskCard } from "@/components/tasks/TaskCard";
import { TaskFeedbackBanner } from "@/components/tasks/TaskFeedbackBanner";
import { AdPerformanceSummary } from "./AdPerformanceSummary";

export function GrowthCopilotPanel({
  persona,
  tasks,
}: {
  persona: SellerPersona;
  tasks: MockTask[];
}) {
  const rankedTasks = rankGrowthTasks(tasks);
  const { activeTasks, feedback, clearFeedback, approveTask, dismissTask } =
    useTaskExecutor(rankedTasks, { personaId: persona.profile.id });

  const activeRanked = rankGrowthTasks(activeTasks);

  return (
    <section className="space-y-4" data-testid="growth-copilot-panel">
      <header>
        <h2 className="text-sm font-semibold">Copilot Tăng Trưởng</h2>
        <p className="text-muted mt-1 text-xs">
          Gợi ý scale/cut được xếp hạng theo cơ hội tác động doanh thu
        </p>
      </header>

      <AdPerformanceSummary persona={persona} />

      <DemoModeNotice />

      {feedback && (
        <TaskFeedbackBanner feedback={feedback} onDismiss={clearFeedback} />
      )}

      {activeRanked.length === 0 ? (
        <p
          className="rounded-xl border px-4 py-6 text-center text-sm"
          style={{ borderColor: "var(--border)", color: "var(--muted-foreground)" }}
          data-testid="task-queue-empty"
        >
          Không còn nhiệm vụ đang chờ xử lý trong phiên này.
        </p>
      ) : (
        <ul className="space-y-3" data-testid="growth-task-list">
          {activeRanked.map((task) => (
            <li key={task.id}>
              <TaskCard
                task={task}
                personaId={persona.profile.id}
                onApprove={approveTask}
                onDismiss={dismissTask}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
