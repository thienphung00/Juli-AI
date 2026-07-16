"use client";

import { useId } from "react";

import { useDemoState } from "./demo-state";
import { InProgressPanel } from "./in-progress-panel";
import { RecommendationsPanel } from "./recommendations-panel";

interface RecommendationsViewProps {
  initialLoadState?: "ready" | "error";
}

export function RecommendationsView({
  initialLoadState = "ready",
}: RecommendationsViewProps = {}) {
  const { mutableState, updateMutableState } = useDemoState();
  const recommendationsPanelId = useId();
  const inProgressPanelId = useId();
  const activeView = mutableState.decisionsView;

  const handleSelectView = (view: "recommendations" | "in-progress") => {
    updateMutableState((current) => ({ ...current, decisionsView: view }));
  };

  return (
    <section aria-labelledby="decisions-title" className="demo-decisions">
      <p className="demo-kicker">Quyết định</p>
      <h1 className="demo-title" id="decisions-title">
        Việc cần bạn quyết định
      </h1>
      <p className="demo-intro">
        Xem các đề xuất Juli phát hiện được, mở rộng để hiểu lý do, và giữ
        quyền quyết định cuối cùng ở bạn.
      </p>

      <div
        aria-label="Loại quyết định"
        className="demo-decisions__tabs"
        role="group"
      >
        <button
          aria-controls={recommendationsPanelId}
          aria-pressed={activeView === "recommendations"}
          className="demo-decisions__tab"
          onClick={() => handleSelectView("recommendations")}
          type="button"
        >
          Đề xuất
        </button>
        <button
          aria-controls={inProgressPanelId}
          aria-pressed={activeView === "in-progress"}
          className="demo-decisions__tab"
          onClick={() => handleSelectView("in-progress")}
          type="button"
        >
          Đang thực hiện
        </button>
      </div>

      <div hidden={activeView !== "recommendations"}>
        <RecommendationsPanel
          initialLoadState={initialLoadState}
          panelId={recommendationsPanelId}
        />
      </div>

      <div hidden={activeView !== "in-progress"}>
        <InProgressPanel panelId={inProgressPanelId} />
      </div>
    </section>
  );
}
