"use client";

import { RecommendationCard } from "@juli/ui";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { recommendationFixtures } from "../lib/recommendations";
import { isReviewExecutableWorkflow } from "../lib/reviews";
import { useDemoState } from "./demo-state";

const APPROVE_DISABLED_REASON =
  "Phê duyệt: luồng xem trước và điền thông tin trước khi thực thi chưa có trong Demo này — sẽ ra mắt ở bản cập nhật tiếp theo.";

interface RecommendationsPanelProps {
  initialLoadState?: "ready" | "error";
  panelId: string;
}

export function RecommendationsPanel({
  initialLoadState = "ready",
  panelId,
}: RecommendationsPanelProps) {
  const router = useRouter();
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
          ) &&
          !mutableState.approvedRecommendationIds.includes(
            fixture.workflowKey,
          ),
      ),
    [
      mutableState.approvedRecommendationIds,
      mutableState.rejectedRecommendationIds,
    ],
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

  const handleApprove = (workflowKey: string) => {
    router.push(`/decisions/recommendations/${workflowKey}`);
  };

  return (
    <div
      ref={recommendationsPanelRef}
      aria-label="Đề xuất"
      id={panelId}
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
          <Link className="demo-placeholder__recovery" href="/analytics">
            Mở Phân tích
          </Link>
        </section>
      ) : (
        <ul className="demo-decisions__list">
          {visibleFixtures.map((fixture) => {
            const isHighlighted = fixture.workflowKey === highlightKey;
            const approveEnabled = isReviewExecutableWorkflow(
              fixture.workflowKey,
            );

            return (
              <li key={fixture.workflowKey}>
                <RecommendationCard
                  ref={isHighlighted ? highlightedCardRef : undefined}
                  approveDisabledReason={
                    approveEnabled ? undefined : APPROVE_DISABLED_REASON
                  }
                  capabilityLabel={fixture.capabilityLabel}
                  confidenceLabel={fixture.confidenceLabel}
                  confidenceLevel={fixture.confidenceLevel}
                  eligibility={fixture.eligibility}
                  evidence={fixture.evidence}
                  expectedImpactLabel={fixture.expectedImpactLabel}
                  isHighlighted={isHighlighted}
                  isPriority={fixture.isPriority}
                  knownLimits={fixture.knownLimits}
                  onApprove={
                    approveEnabled
                      ? () => handleApprove(fixture.workflowKey)
                      : undefined
                  }
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
  );
}
