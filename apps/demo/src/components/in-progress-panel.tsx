"use client";

import { useDemoState } from "./demo-state";

interface InProgressPanelProps {
  panelId: string;
}

export function InProgressPanel({ panelId }: InProgressPanelProps) {
  const { mutableState } = useDemoState();
  const executionRecords = Object.values(mutableState.executionRecords);

  if (executionRecords.length === 0) {
    return (
      <div aria-label="Đang thực hiện" id={panelId}>
        <section
          aria-label="Đang thực hiện"
          className="demo-placeholder"
          role="status"
        >
          <p className="demo-kicker">Sắp ra mắt</p>
          <h2>Đang thực hiện</h2>
          <p>
            Công việc đã phê duyệt sẽ xuất hiện ở đây trong một bản cập nhật
            tiếp theo.
          </p>
        </section>
      </div>
    );
  }

  return (
    <div aria-label="Đang thực hiện" id={panelId}>
      <ul className="demo-decisions__list">
        {executionRecords.map((record) => (
          <li key={record.executionId}>
            <article data-execution-id={record.executionId}>
              <h3>{record.workflowKey}</h3>
              <p>{record.lifecycleStatus}</p>
            </article>
          </li>
        ))}
      </ul>
    </div>
  );
}
