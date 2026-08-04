"use client";

import { useMemo } from "react";
import Link from "next/link";

import { useDemoState } from "./demo-state";
import { recommendationFixtures } from "../lib/recommendations";

interface HomeActivityTrackerProps {
  initialLoadState?: "ready" | "loading" | "error";
}

export function HomeActivityTracker({
  initialLoadState = "ready",
}: HomeActivityTrackerProps = {}) {
  const { mutableState } = useDemoState();

  // Calculate completed count
  const completedCount = useMemo(
    () =>
      Object.values(mutableState.executionRecords).filter(
        (record) => record.lifecycleStatus === "completed",
      ).length,
    [mutableState.executionRecords],
  );

  // Calculate executing + needs_input count
  const runningCount = useMemo(
    () =>
      Object.values(mutableState.executionRecords).filter(
        (record) =>
          record.lifecycleStatus === "executing" ||
          record.lifecycleStatus === "needs_input",
      ).length,
    [mutableState.executionRecords],
  );

  // Calculate open recommendations count
  const openRecommendationsCount = useMemo(
    () =>
      recommendationFixtures.filter(
        (fixture) =>
          !mutableState.rejectedRecommendationIds.includes(
            fixture.workflowKey,
          ) &&
          !mutableState.approvedRecommendationIds.includes(fixture.workflowKey),
      ).length,
    [
      mutableState.rejectedRecommendationIds,
      mutableState.approvedRecommendationIds,
    ],
  );

  const hasActivity =
    completedCount > 0 || runningCount > 0 || openRecommendationsCount > 0;

  if (initialLoadState === "loading") {
    return (
      <div
        className="demo-activity-tracker__skeleton"
        role="status"
        aria-label="Đang tải hoạt động"
      >
        <div className="demo-activity-tracker__skeleton-tile" />
        <div className="demo-activity-tracker__skeleton-tile" />
        <div className="demo-activity-tracker__skeleton-tile" />
      </div>
    );
  }

  if (initialLoadState === "error") {
    return (
      <div
        className="demo-activity-tracker__error"
        role="status"
        aria-label="Lỗi tải hoạt động"
      >
        <p>Không thể tải hoạt động tóm tắt.</p>
        <button
          className="demo-decisions__retry"
          type="button"
          onClick={() => window.location.reload()}
        >
          Thử lại
        </button>
      </div>
    );
  }

  if (!hasActivity) {
    return (
      <div className="demo-activity-tracker__empty">
        <p>Bạn chưa có hoạt động nào. Khám phá các đề xuất để bắt đầu.</p>
      </div>
    );
  }

  return (
    <div className="demo-activity-tracker">
      <Link
        href="/decisions?tab=in-progress"
        className="demo-activity-tracker__tile"
      >
        <span className="demo-activity-tracker__value">{completedCount}</span>
        <span className="demo-activity-tracker__label">Hoàn tất</span>
      </Link>

      <Link
        href="/decisions?tab=in-progress"
        className="demo-activity-tracker__tile"
      >
        <span className="demo-activity-tracker__value">{runningCount}</span>
        <span className="demo-activity-tracker__label">Đang thực hiện</span>
      </Link>

      <Link
        href="/decisions?tab=recommendations"
        className="demo-activity-tracker__tile"
      >
        <span className="demo-activity-tracker__value">
          {openRecommendationsCount}
        </span>
        <span className="demo-activity-tracker__label">
          Đề xuất cần xem xét
        </span>
      </Link>
    </div>
  );
}
