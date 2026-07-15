"use client";

import { RecommendationCard } from "@juli/ui";
import { useSearchParams } from "next/navigation";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { recommendationFixtures } from "../lib/recommendations";
import { useDemoState } from "./demo-state";

const APPROVE_DISABLED_REASON =
  "Phê duyệt: luồng xem trước và điền thông tin trước khi thực thi chưa có trong Demo này — sẽ ra mắt ở bản cập nhật tiếp theo.";

interface RecommendationsViewProps {
  initialLoadState?: "ready" | "error";
}

export function RecommendationsView({
  initialLoadState = "ready",
}: RecommendationsViewProps = {}) {
  const searchParams = useSearchParams();
  const highlightKey = searchParams.get("highlight");
  const {
    mutableState,
    setRecommendationContext,
    updateMutableState,
  } = useDemoState();
  const highlightedCardRef = useRef<HTMLElement | null>(null);
  const recommendationsPanelRef = useRef<HTMLDivElement | null>(null);
  const [loadState, setLoadState] = useState(initialLoadState);
  const [statusMessage, setStatusMessage] = useState("");

  const visibleFixtures = useMemo(
    () =>
      recommendationFixtures.filter(
        (fixture) =>
          !mutableState.rejectedRecommendationIds.includes(
            fixture.workflowKey,
          ),
      ),
    [mutableState.rejectedRecommendationIds],
  );

  const activeFixture =
    visibleFixtures.find((fixture) => fixture.workflowKey === highlightKey) ??
    visibleFixtures[0] ??
    null;

  useEffect(() => {
    setRecommendationContext(
      activeFixture
        ? {
            evidence: activeFixture.evidence,
            risks: activeFixture.risks,
            title: activeFixture.title,
            workflowKey: activeFixture.workflowKey,
          }
        : null,
    );

    return () => setRecommendationContext(null);
  }, [activeFixture, setRecommendationContext]);

  useEffect(() => {
    if (!highlightKey) {
      return;
    }

    const node = highlightedCardRef.current;

    if (!node) {
      return;
    }

    const prefersReducedMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    node.scrollIntoView({
      behavior: prefersReducedMotion ? "auto" : "smooth",
      block: "center",
    });
    node.focus();
  }, [highlightKey]);

  const recommendationsPanelId = useId();
  const inProgressPanelId = useId();
  const activeView = mutableState.decisionsView;

  const handleSelectView = (view: "recommendations" | "in-progress") => {
    updateMutableState((current) => ({ ...current, decisionsView: view }));
  };

  const handleReject = (workflowKey: string) => {
    const rejectedFixture = recommendationFixtures.find(
      (fixture) => fixture.workflowKey === workflowKey,
    );

    updateMutableState((current) => ({
      ...current,
      rejectedRecommendationIds: [
        ...current.rejectedRecommendationIds,
        workflowKey,
      ],
    }));
    setStatusMessage(
      rejectedFixture
        ? `Đã từ chối đề xuất ${rejectedFixture.title}.`
        : "Đã từ chối đề xuất.",
    );
    window.setTimeout(() => recommendationsPanelRef.current?.focus(), 0);
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

      <div
        ref={recommendationsPanelRef}
        aria-label="Đề xuất"
        hidden={activeView !== "recommendations"}
        id={recommendationsPanelId}
        tabIndex={-1}
      >
        <p aria-live="polite" className="demo-decisions__status" role="status">
          {statusMessage}
        </p>
        {loadState === "error" ? (
          <section
            aria-label="Lỗi tải đề xuất"
            className="demo-decisions__empty"
            role="alert"
          >
            <p className="demo-kicker">Chưa thể tải nội dung</p>
            <h2>Không thể tải đề xuất mẫu</h2>
            <p>Dữ liệu mẫu chưa sẵn sàng. Bạn có thể thử lại ngay.</p>
            <button
              className="demo-decisions__retry"
              onClick={() => setLoadState("ready")}
              type="button"
            >
              Thử lại
            </button>
          </section>
        ) : visibleFixtures.length === 0 ? (
          <section
            aria-label="Đề xuất"
            className="demo-decisions__empty"
            role="status"
          >
            <p className="demo-kicker">Chưa có dữ liệu</p>
            <h2>Không có đề xuất nào cần xem xét</h2>
            <p>
              Hiện chưa có tín hiệu nào cần bạn xem xét. Mở Phân tích để hiểu
              thêm về shop, hoặc dùng Làm mới Demo để xem lại toàn bộ đề xuất
              mẫu.
            </p>
            <a className="demo-placeholder__recovery" href="/analytics">
              Mở Phân tích
            </a>
          </section>
        ) : (
          <ul className="demo-decisions__list">
            {visibleFixtures.map((fixture) => {
              const isHighlighted = fixture.workflowKey === highlightKey;

              return (
                <li key={fixture.workflowKey}>
                  <RecommendationCard
                    ref={isHighlighted ? highlightedCardRef : undefined}
                    approveDisabledReason={APPROVE_DISABLED_REASON}
                    capabilityLabel={fixture.capabilityLabel}
                    confidenceLabel={fixture.confidenceLabel}
                    confidenceLevel={fixture.confidenceLevel}
                    eligibility={fixture.eligibility}
                    evidence={fixture.evidence}
                    expectedImpactLabel={fixture.expectedImpactLabel}
                    isHighlighted={isHighlighted}
                    isPriority={fixture.isPriority}
                    knownLimits={fixture.knownLimits}
                    onReject={() => handleReject(fixture.workflowKey)}
                    reasoning={fixture.reasoning}
                    risks={fixture.risks}
                    signal={fixture.signal}
                    title={fixture.title}
                    workflowKey={fixture.workflowKey}
                  />
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div
        aria-label="Đang thực hiện"
        hidden={activeView !== "in-progress"}
        id={inProgressPanelId}
      >
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
    </section>
  );
}
