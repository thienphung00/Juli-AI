"use client";

import { useId } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMemo, useEffect, useState } from "react";

import { useDemoState } from "./demo-state";
import { InProgressPanel } from "./in-progress-panel";
import { RecommendationsPanel } from "./recommendations-panel";
import { recommendationFixtures } from "../lib/recommendations";
import { readReplayDecision } from "../lib/replay-decision";
import { OPTIMIZE_PRODUCT_WORKFLOW_KEY } from "../lib/reviews";
import { REPLAY_SCENARIO_RUN_ID } from "../lib/run-surface/replay-scenario";

interface RecommendationsViewProps {
  initialLoadState?: "ready" | "error";
}

export function RecommendationsView({
  initialLoadState = "ready",
}: RecommendationsViewProps = {}) {
  const { mutableState, updateMutableState } = useDemoState();
  const router = useRouter();
  const searchParams = useSearchParams();
  const recommendationsPanelId = useId();
  const inProgressPanelId = useId();
  const statRowId = useId();

  // Get tab from URL query param, default to "recommendations"
  const urlTab = searchParams.get("tab");
  const activeView =
    urlTab === "in-progress" ? "in-progress" : "recommendations";

  // Sync mutableState with URL on mount
  useEffect(() => {
    if (mutableState.decisionsView !== activeView) {
      updateMutableState((current) => ({ ...current, decisionsView: activeView }));
    }
  }, [activeView, mutableState.decisionsView, updateMutableState]);

  // Issue #1836: same replay-decided-card exclusion `recommendations-panel.tsx`
  // applies to the list itself -- the stat row must never claim a count
  // that includes a card the list right below it no longer shows. See that
  // file's own docstring for why this is state+effect rather than a direct
  // render-time read (SSR/hydration parity, react-hooks/set-state-in-effect).
  const [replayDecidedWorkflowKey, setReplayDecidedWorkflowKey] = useState<
    string | null
  >(null);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const decision = readReplayDecision();
      setReplayDecidedWorkflowKey(
        decision?.runId === REPLAY_SCENARIO_RUN_ID
          ? OPTIMIZE_PRODUCT_WORKFLOW_KEY
          : null,
      );
    }, 0);

    return () => window.clearTimeout(timer);
  }, [mutableState]);

  // Calculate open recommendations count
  const openRecommendationsCount = useMemo(
    () =>
      recommendationFixtures.filter(
        (fixture) =>
          !mutableState.rejectedRecommendationIds.includes(
            fixture.workflowKey,
          ) &&
          !mutableState.approvedRecommendationIds.includes(fixture.workflowKey) &&
          fixture.workflowKey !== replayDecidedWorkflowKey,
      ).length,
    [
      mutableState.rejectedRecommendationIds,
      mutableState.approvedRecommendationIds,
      replayDecidedWorkflowKey,
    ],
  );

  // Calculate in-progress executions count
  const inProgressCount = useMemo(
    () => Object.values(mutableState.executionRecords).length,
    [mutableState.executionRecords],
  );

  const handleSelectView = (view: "recommendations" | "in-progress") => {
    const params = new URLSearchParams(searchParams);
    params.set("tab", view);
    router.replace(`/decisions?${params.toString()}`);
    updateMutableState((current) => ({ ...current, decisionsView: view }));
  };

  return (
    <section aria-labelledby="decisions-title" className="demo-decisions">
      <p className="demo-kicker">Quyết định</p>
      <h1 className="demo-title" id="decisions-title">
        Việc cần bạn quyết định
      </h1>
      <p className="demo-intro">
        Đây là đề xuất Juli tìm thấy cho shop của bạn, dựa trên dữ liệu bán
        hàng gần nhất — bạn xem, chỉnh, rồi quyết định phê duyệt hay không.
      </p>

      {/* Stat row - read-only stats under header */}
      <div
        aria-label="Tóm tắt quyết định"
        className="demo-decisions__stat-row"
        id={statRowId}
        role="region"
      >
        <div className="demo-decisions__stat">
          <span className="demo-decisions__stat-value">
            {openRecommendationsCount}
          </span>
          <span className="demo-decisions__stat-label">Đề xuất mở</span>
        </div>
        <div className="demo-decisions__stat">
          <span className="demo-decisions__stat-value">{inProgressCount}</span>
          <span className="demo-decisions__stat-label">Đang thực hiện</span>
        </div>
      </div>

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
        <InProgressPanel
          active={activeView === "in-progress"}
          panelId={inProgressPanelId}
        />
      </div>
    </section>
  );
}
